"""Adapter for the Arbeitnow job-board API (live, no key required).

API docs: https://www.arbeitnow.com/api/job-board-api
Returns 300 newest listings per page with full descriptions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..extractors import clean_text, html_to_text, normalise_employment_type, parse_date
from ..models import JobPosting
from .base import BasePortal, BusinessError


class ArbeitnowPortal(BasePortal):
    name = "arbeitnow"
    label = "Arbeitnow (live API)"

    def discover(self, limit: int) -> list[JobPosting]:
        max_pages = max(1, int(self.settings.get("max_pages", 3)))
        jobs: list[JobPosting] = []
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            if len(jobs) >= limit:
                break
            url = self.base_url if page == 1 else f"{self.base_url}?page={page}"
            try:
                payload = json.loads(self.http.get(url))
            except json.JSONDecodeError as exc:
                raise BusinessError(f"Arbeitnow returned invalid JSON: {exc}") from exc

            items = payload.get("data") if isinstance(payload, dict) else None
            if not items:
                if page == 1:
                    raise BusinessError("Arbeitnow returned no vacancies.")
                break

            for item in items:
                if len(jobs) >= limit:
                    break
                job = self._to_job(item)
                if not job.title or job.source_url in seen:
                    continue
                seen.add(job.source_url)
                jobs.append(job)

            next_link = ((payload.get("links") or {}).get("next")) if isinstance(payload, dict) else None
            if not next_link:
                break

        return jobs[:limit]

    def _to_job(self, item: dict) -> JobPosting:
        created = item.get("created_at")
        posted = ""
        if created:
            try:
                posted = parse_date(
                    datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
                )
            except (TypeError, ValueError, OSError):
                posted = ""

        job_types = item.get("job_types") or []
        employment = normalise_employment_type(*job_types)
        tags = [clean_text(tag) for tag in (item.get("tags") or []) if clean_text(tag)]

        job = JobPosting(
            portal=self.name,
            title=clean_text(item.get("title")),
            company=clean_text(item.get("company_name")),
            location=clean_text(item.get("location")),
            employment_type=employment,
            posted_date=posted,
            category=", ".join(tags),
            description=html_to_text(item.get("description")),
            apply_url=str(item.get("url") or ""),
            source_url=str(item.get("url") or ""),
        )
        if item.get("remote"):
            job.work_mode = "Remote"
        return job
