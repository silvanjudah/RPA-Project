"""Adapter for the Jobicy public jobs API (live, no key required).

Docs: https://jobi.cy/apidocs - listings are remote-only, newest first,
published within the last 7 days. Public responses include the Jobicy listing
URL; Jobicy asks for clear source credit, which the Excel report provides.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from ..extractors import clean_text, format_salary, html_to_text, normalise_employment_type, parse_date
from ..models import JobPosting
from .base import BasePortal, BusinessError


class JobicyPortal(BasePortal):
    name = "jobicy"
    label = "Jobicy (live API)"

    def discover(self, limit: int) -> list[JobPosting]:
        base = self.base_url or "https://jobicy.com/api/jobs"
        max_pages = max(1, int(self.settings.get("max_pages", 2)))
        count = min(max(limit, 1), 200)
        url = f"{base}?count={count}"

        jobs: list[JobPosting] = []
        seen: set[str] = set()

        for _page in range(max_pages):
            try:
                payload = json.loads(self.http.get(url))
            except json.JSONDecodeError as exc:
                raise BusinessError(f"Jobicy returned invalid JSON: {exc}") from exc

            if not isinstance(payload, dict) or payload.get("success") is False:
                raise BusinessError(f"Jobicy API error: {payload!r}")

            for item in payload.get("jobs") or []:
                if len(jobs) >= limit:
                    break
                job = self._to_job(item)
                if not job.title or job.source_url in seen:
                    continue
                seen.add(job.source_url)
                jobs.append(job)

            cursor = payload.get("nextCursor")
            if len(jobs) >= limit or not cursor:
                break
            url = f"{base}?count={count}&cursor={quote(str(cursor))}"

        return jobs[:limit]

    def _to_job(self, item: dict) -> JobPosting:
        industries = [clean_text(value) for value in (item.get("jobIndustry") or []) if clean_text(value)]
        job_types = item.get("jobType") or []
        salary = format_salary(
            item.get("salaryMin"),
            item.get("salaryMax"),
            str(item.get("salaryCurrency") or ""),
            str(item.get("salaryPeriod") or ""),
        )

        return JobPosting(
            portal=self.name,
            title=clean_text(item.get("jobTitle")),
            company=clean_text(item.get("companyName")),
            location=clean_text(item.get("jobGeo")),
            work_mode="Remote",
            employment_type=normalise_employment_type(*job_types),
            salary=salary,
            posted_date=parse_date(item.get("pubDate")),
            category=", ".join(industries),
            description=html_to_text(item.get("jobDescription")),
            apply_url=str(item.get("url") or ""),
            source_url=str(item.get("url") or ""),
        )
