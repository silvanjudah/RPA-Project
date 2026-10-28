"""Bot orchestration: discover -> per-item transaction -> Excel report.

The flow intentionally mirrors UiPath's REFramework:

    INIT -> GET TRANSACTION DATA -> PROCESS TRANSACTION (with retries) -> END

Each vacancy is a transaction with a status (Successful / BusinessException /
SystemException) and every step is written to the run log that ships inside
the workbook.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import output_path as default_output_path
from .config import portal_settings
from .extractors import clean_text, derive_fields
from .filters import job_matches, matches_countries, matches_keywords
from .http_client import FetchError, HttpClient
from .models import JobPosting, LogRecord, utc_now
from .portals import BusinessError, create_portal

LOGGER = logging.getLogger("rpa.jobs.bot")

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class RunResult:
    portal: str
    portal_label: str
    jobs: list[JobPosting] = field(default_factory=list)
    records: list[LogRecord] = field(default_factory=list)
    discovered: int = 0
    successful: int = 0
    skipped: int = 0
    filtered: int = 0
    filtered_location: int = 0
    failed: int = 0
    carried_over: int = 0
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    output_path: Path | None = None
    keywords: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class JobBot:
    """Unattended robot that turns portal listings into an Excel report."""

    def __init__(
        self,
        config: dict,
        *,
        http: HttpClient | None = None,
        logger: logging.Logger | None = None,
        progress: ProgressCallback | None = None,
        append: bool = False,
        output: str | Path | None = None,
    ) -> None:
        self.config = config
        self.log = logger or LOGGER
        self.progress = progress
        self.append = append
        self.output = Path(output) if output else None
        self.records: list[LogRecord] = []
        self._http = http
        self._portal = None
        self._total = 0
        self._index = 0

    # ------------------------------------------------------------------ entry
    def run(self) -> RunResult:
        started = time.perf_counter()
        started_at = utc_now()
        portal_name = str(self.config.get("portal", ""))
        settings = portal_settings(self.config, portal_name)
        if not settings:
            raise BusinessError(
                f"No selector configuration for portal '{portal_name}'. "
                "Add a 'portals' block to config/config.json."
            )

        filters = self.config.get("filters") or {}
        keywords = [
            clean_text(keyword)
            for keyword in (filters.get("keywords") or [])
            if clean_text(keyword)
        ]
        countries = [
            clean_text(country)
            for country in (filters.get("countries") or [])
            if clean_text(country)
        ]
        match_all = str(filters.get("match", "any")).lower() == "all"

        settings = dict(settings)
        settings["filters"] = filters

        self._record("INFO", "Init", "Bot initialising", step="INIT")
        portal = create_portal(
            portal_name,
            settings,
            self._client(),
            self.log,
            self.config.get("portals") or {},
        )
        self._portal = portal
        self._record(
            "INFO",
            "Init",
            f"Target portal: {portal.label} ({portal.base_url})",
            step="INIT",
        )
        if keywords:
            self._record(
                "INFO",
                "Init",
                f"Keyword filter ({'all' if match_all else 'any'}): {', '.join(keywords)}",
                step="FILTER",
            )
        if countries:
            self._record(
                "INFO",
                "Init",
                f"Location filter: {', '.join(countries)} only",
                step="FILTER",
            )

        crawl = self.config.get("crawl", {})
        limit = max(1, int(crawl.get("max_items", 50)))
        fetch_details = bool(crawl.get("fetch_details", True))

        # Filters remove most rows, so collect a deeper pool than the report
        # limit; otherwise the filter would only ever see the newest few rows.
        if countries:
            fetch_limit = min(300, max(limit, limit * 8))
        elif keywords:
            fetch_limit = min(200, max(limit, limit * 5))
        else:
            fetch_limit = limit
        drafts = self._discover(portal, fetch_limit, crawl)
        drafts = self._unique_drafts(drafts)
        discovered_total = len(drafts)
        self._record("INFO", "Init", f"{len(drafts)} unique vacancies discovered", step="GET DATA")

        filtered_location = 0
        if countries:
            matched = [draft for draft in drafts if matches_countries(draft, countries)]
            filtered_location = len(drafts) - len(matched)
            drafts = matched
            if filtered_location:
                self._record(
                    "INFO",
                    "Skipped",
                    (
                        f"{filtered_location} vacancies outside {', '.join(countries)} "
                        "skipped before enrichment"
                    ),
                    step="FILTER",
                )

        jobs: list[JobPosting] = []
        seen_signatures: dict[str, str] = {}
        skipped_duplicates = 0
        filtered_out = 0
        failed_transactions = 0
        self._total = len(drafts)

        for index, draft in enumerate(drafts, start=1):
            self._index = index
            if self.progress:
                try:
                    self.progress(index, self._total, draft.title)
                except Exception:  # noqa: BLE001 - UI callbacks must never kill the run
                    self.log.debug("Progress callback failed", exc_info=True)

            job, status, _attempts = self._process(portal, draft, fetch_details, crawl)
            if job is None:
                failed_transactions += 1
                continue

            if not job_matches(job, filters):
                filtered_out += 1
                reason = []
                if keywords and not matches_keywords(job, keywords, match_all):
                    reason.append(f"no keyword match for {', '.join(keywords)}")
                if countries and not matches_countries(job, countries):
                    reason.append(f"outside {', '.join(countries)}")
                self._record(
                    "INFO",
                    "Skipped",
                    "Filtered out: " + ("; ".join(reason) or "did not match the run filters"),
                    step="FILTER",
                    job=job,
                )
                continue

            signature = job.dedupe_key
            if signature in seen_signatures:
                skipped_duplicates += 1
                self._record(
                    "WARN",
                    "Skipped",
                    f"Duplicate of {seen_signatures[signature]} - not added twice",
                    step="DEDUPLICATE",
                    job=job,
                )
                continue

            seen_signatures[signature] = job.job_id
            jobs.append(job)
            self._record(
                "INFO",
                "Successful",
                f"Captured: {job.title} @ {job.company or 'unknown company'}",
                step="PROCESS",
                job=job,
            )

        jobs.sort(key=_sort_key, reverse=True)
        jobs = jobs[:limit]
        result = RunResult(
            portal=portal.name,
            portal_label=portal.label,
            jobs=jobs,
            records=self.records,
            discovered=discovered_total,
            successful=len(jobs),
            skipped=skipped_duplicates,
            filtered=filtered_out,
            filtered_location=filtered_location,
            failed=failed_transactions,
            started_at=started_at,
            keywords=keywords,
            countries=countries,
        )

        destination = self.output or default_output_path(self.config)
        result.carried_over = self._merge_previous(result, destination)
        result.output_path = destination
        result.finished_at = utc_now()
        result.duration_seconds = round(time.perf_counter() - started, 2)

        from .report import write_report  # local import keeps module graph acyclic

        self._record(
            "INFO",
            "Successful",
            f"Writing Excel report to {destination}",
            step="REPORT",
        )
        write_report(result, self.config)
        self._record("INFO", "Successful", "Report written successfully", step="END")
        return result

    # -------------------------------------------------------------- internals
    def _client(self) -> HttpClient:
        if self._http is not None:
            return self._http
        crawl = self.config.get("crawl", {})
        self._http = HttpClient(
            user_agent=crawl.get("user_agent", "RPAJobBot/1.0"),
            timeout=float(crawl.get("timeout_seconds", 20)),
            retries=int(crawl.get("retries", 3)),
            backoff=float(crawl.get("backoff_seconds", 1.2)),
            delay=float(crawl.get("delay_seconds", 0.4)),
            respect_robots=bool(crawl.get("respect_robots", True)),
        )
        return self._http

    def _discover(self, portal, limit: int, crawl: dict) -> list[JobPosting]:
        attempts = max(1, int(crawl.get("retries", 3)))
        backoff = float(crawl.get("backoff_seconds", 1.2))
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                jobs = portal.discover(limit)
            except BusinessError:
                raise
            except Exception as exc:  # noqa: BLE001 - network/parse failures
                last_error = exc
                duration = int((time.perf_counter() - started) * 1000)
                self._record(
                    "WARN",
                    "SystemException",
                    f"Discovery attempt {attempt}/{attempts} failed: {exc}",
                    step="GET DATA",
                    attempt=attempt,
                    duration_ms=duration,
                )
                if attempt < attempts:
                    time.sleep(backoff * (2 ** (attempt - 1)))
                continue

            if not jobs:
                raise BusinessError("Portal returned no vacancies.")
            duration = int((time.perf_counter() - started) * 1000)
            self._record(
                "INFO",
                "Successful",
                f"Discovery succeeded with {len(jobs)} listings",
                step="GET DATA",
                attempt=attempt,
                duration_ms=duration,
            )
            return jobs[:limit]

        raise FetchError(f"Could not retrieve the job listing after {attempts} attempts: {last_error}")

    def _process(
        self,
        portal,
        draft: JobPosting,
        fetch_details: bool,
        crawl: dict,
    ) -> tuple[JobPosting | None, str, int]:
        attempts = max(1, int(crawl.get("retries", 3)))
        backoff = float(crawl.get("backoff_seconds", 1.2))

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                job = portal.enrich(draft) if fetch_details else draft
                if not job.title.strip():
                    raise BusinessError("Vacancy has no title.")
                if not job.apply_url:
                    job.apply_url = job.source_url
                self._apply_derived(job)
                duration = int((time.perf_counter() - started) * 1000)
                self._record(
                    "INFO",
                    "Successful",
                    f"Details extracted in {duration} ms",
                    step="PROCESS",
                    job=job,
                    attempt=attempt,
                    duration_ms=duration,
                )
                return job, "Successful", attempt
            except BusinessError as exc:
                duration = int((time.perf_counter() - started) * 1000)
                self._record(
                    "WARN",
                    "BusinessException",
                    f"Skipped vacancy: {exc}",
                    step="PROCESS",
                    job=draft,
                    attempt=attempt,
                    duration_ms=duration,
                )
                return None, "BusinessException", attempt
            except Exception as exc:  # noqa: BLE001 - retryable system failure
                duration = int((time.perf_counter() - started) * 1000)
                final = attempt >= attempts
                self._record(
                    "ERROR" if final else "WARN",
                    "SystemException",
                    (
                        f"Failed after {attempts} attempts: {exc}"
                        if final
                        else f"Attempt {attempt}/{attempts} failed: {exc} - retrying"
                    ),
                    step="PROCESS",
                    job=draft,
                    attempt=attempt,
                    duration_ms=duration,
                )
                if final:
                    return None, "SystemException", attempt
                time.sleep(backoff * (2 ** (attempt - 1)))

        return None, "SystemException", attempts

    def _apply_derived(self, job: JobPosting) -> None:
        output_cfg = self.config.get("output", {})
        derived = derive_fields(
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
            category=job.category,
            work_mode=job.work_mode,
            employment_type=job.employment_type,
            salary=job.salary,
            posted_date=job.posted_date,
            skills=job.skills,
            vocabulary=self.config.get("skills", []),
            description_limit=int(output_cfg.get("description_limit", 1200)),
            skills_limit=int(output_cfg.get("skills_limit", 12)),
        )
        job.work_mode = derived["work_mode"]
        job.employment_type = derived["employment_type"]
        job.salary = derived["salary"]
        job.posted_date = derived["posted_date"]
        job.skills = derived["skills"]
        job.description = derived["description"]
        job.location = job.location or "Not specified"
        job.scraped_at = utc_now()

    def _merge_previous(self, result: RunResult, destination: Path) -> int:
        """Append mode: keep rows from an earlier run and skip repeats."""
        if not self.append or not destination.exists():
            return 0

        from .report import read_existing_jobs

        try:
            existing = read_existing_jobs(destination)
        except Exception as exc:  # noqa: BLE001 - corrupt workbook should not kill the run
            self._record("WARN", "SystemException", f"Could not read existing report: {exc}", step="REPORT")
            return 0

        known_ids = {job.job_id for job in existing}
        known_signatures = {job.dedupe_key for job in existing}
        new_jobs = [
            job
            for job in result.jobs
            if job.job_id not in known_ids and job.dedupe_key not in known_signatures
        ]
        carried = len(existing)
        result.jobs = sorted(existing + new_jobs, key=_sort_key, reverse=True)
        result.successful = len(new_jobs)
        if carried:
            self._record(
                "INFO",
                "Successful",
                f"Append mode: {carried} existing vacancies kept, {len(new_jobs)} new rows added",
                step="REPORT",
            )
        return carried

    def _record(
        self,
        level: str,
        status: str,
        message: str,
        *,
        step: str = "",
        job: JobPosting | None = None,
        attempt: int = 0,
        duration_ms: int = 0,
    ) -> None:
        record = LogRecord(
            timestamp=utc_now(),
            level=level,
            status=status,
            step=step,
            message=message,
            job_id=job.job_id if job else "",
            title=job.title if job else "",
            attempt=attempt,
            duration_ms=duration_ms,
        )
        self.records.append(record)
        log_method = {
            "DEBUG": self.log.debug,
            "INFO": self.log.info,
            "WARN": self.log.warning,
            "ERROR": self.log.error,
        }.get(level, self.log.info)
        prefix = f"[{step}]" if step else ""
        log_method("%s %s", prefix, message)

    @staticmethod
    def _unique_drafts(drafts: list[JobPosting]) -> list[JobPosting]:
        seen: set[str] = set()
        unique: list[JobPosting] = []
        for draft in drafts:
            key = draft.source_url or draft.dedupe_key
            if key in seen:
                continue
            seen.add(key)
            unique.append(draft)
        return unique


def _sort_key(job: JobPosting) -> tuple[str, str]:
    return (job.posted_date or "0000-00-00", job.title.casefold())
