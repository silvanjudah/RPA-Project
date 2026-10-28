"""Adapter for the Working Nomads public jobs API.

API: https://www.workingnomads.com/api/exposed_jobs/

The feed returns every open remote job (a few dozen rows) with the full HTML
description, the company, a comma-separated list of eligible countries in
``location`` and an ISO publication date. Because the feed is worldwide, the
country filter is applied to the whole feed before the run limit is applied.
"""

from __future__ import annotations

import json

from ..extractors import clean_text, html_to_text, parse_date
from ..filters import matches_countries
from ..models import JobPosting
from .base import BasePortal, BusinessError


class WorkingNomadsPortal(BasePortal):
    name = "workingnomads"
    label = "Working Nomads (live API)"

    def discover(self, limit: int) -> list[JobPosting]:
        try:
            payload = json.loads(
                self.http.get(
                    self.base_url or "https://www.workingnomads.com/api/exposed_jobs/"
                )
            )
        except json.JSONDecodeError as exc:
            raise BusinessError(f"Working Nomads returned invalid JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise BusinessError("Working Nomads returned an unexpected response shape.")

        countries = self.country_filter()
        jobs: list[JobPosting] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            job = self._to_job(item)
            if not job.title or not job.source_url:
                continue
            if countries and not matches_countries(job, countries):
                continue
            jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs

    def _to_job(self, item: dict) -> JobPosting:
        tags = item.get("tags") or ""
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]
        source_url = str(item.get("url") or "")

        return JobPosting(
            portal=self.name,
            title=clean_text(item.get("title")),
            company=clean_text(item.get("company_name")),
            location=clean_text(item.get("location")),
            work_mode="Remote",
            posted_date=parse_date(item.get("pub_date")),
            category=clean_text(item.get("category_name")),
            skills=[clean_text(tag) for tag in tags if clean_text(tag)],
            description=html_to_text(item.get("description")),
            apply_url=source_url,
            source_url=source_url,
        )
