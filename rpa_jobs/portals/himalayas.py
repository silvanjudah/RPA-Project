"""Adapter for the Himalayas public jobs API (remote roles worldwide).

API: https://himalayas.app/jobs/api?limit=20&cursor=...

Each record lists ``locationRestrictions`` (e.g. ``["India"]``), which lets an
India-only run page deeper and keep just the eligible vacancies. The API already
returns the full description, so no detail request is needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from ..extractors import (
    clean_text,
    format_salary,
    html_to_text,
    normalise_employment_type,
    parse_date,
)
from ..filters import matches_countries
from ..models import JobPosting
from .base import BasePortal, BusinessError


class HimalayasPortal(BasePortal):
    name = "himalayas"
    label = "Himalayas (live remote API)"

    def discover(self, limit: int) -> list[JobPosting]:
        base = self.base_url or "https://himalayas.app/jobs/api"
        page_size = max(1, min(int(self.settings.get("page_size", 20)), 20))
        max_pages = max(1, int(self.settings.get("max_pages", 20)))
        countries = self.country_filter()

        jobs: list[JobPosting] = []
        seen: set[str] = set()
        url = f"{base}?limit={page_size}"

        for _page in range(max_pages):
            if len(jobs) >= limit:
                break
            try:
                payload = json.loads(self.http.get(url))
            except json.JSONDecodeError as exc:
                raise BusinessError(f"Himalayas returned invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise BusinessError("Himalayas returned an unexpected response shape.")

            items = payload.get("jobs") or []
            if not items:
                break

            for item in items:
                if len(jobs) >= limit:
                    break
                job = self._to_job(item)
                if not job.title or not job.source_url or job.source_url in seen:
                    continue
                if countries and not matches_countries(job, countries):
                    continue
                seen.add(job.source_url)
                jobs.append(job)

            cursor = payload.get("nextCursor")
            if not cursor:
                break
            url = f"{base}?limit={page_size}&cursor={quote(str(cursor))}"

        if not jobs:
            raise BusinessError("Himalayas returned no matching vacancies.")
        return jobs[:limit]

    def _to_job(self, item: dict) -> JobPosting:
        restrictions = [
            clean_text(name) for name in (item.get("locationRestrictions") or []) if clean_text(name)
        ]
        location = ", ".join(restrictions) or "Remote"
        location_country = (
            "India"
            if any(name.casefold() == "india" for name in restrictions)
            else ""
        )

        categories = item.get("parentCategories") or item.get("categories") or []
        category = ", ".join(
            clean_text(str(value)).replace("-", " ")
            for value in categories
            if clean_text(str(value))
        )

        posted = ""
        if item.get("pubDate"):
            try:
                posted = parse_date(
                    datetime.fromtimestamp(int(item["pubDate"]), tz=timezone.utc).isoformat()
                )
            except (TypeError, ValueError, OSError):
                posted = ""

        source_url = str(item.get("guid") or item.get("applicationLink") or "")
        apply_url = str(item.get("applicationLink") or source_url)

        return JobPosting(
            portal=self.name,
            title=clean_text(item.get("title")),
            company=clean_text(item.get("companyName")),
            location=location,
            location_country=location_country,
            work_mode="Remote",
            employment_type=normalise_employment_type(item.get("employmentType")),
            salary=format_salary(
                item.get("minSalary"),
                item.get("maxSalary"),
                str(item.get("currency") or ""),
                str(item.get("salaryPeriod") or ""),
            ),
            posted_date=posted,
            category=category,
            description=html_to_text(item.get("description")),
            apply_url=apply_url,
            source_url=source_url,
        )
