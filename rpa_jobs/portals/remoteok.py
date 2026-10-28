"""Adapter for Remote OK's public JSON feed.

The feed returns the 100 newest remote jobs. Remote OK's API terms require a
link back to the listing and source credit - both are preserved in the
report's Apply/Source URL and Portal columns.

Docs: https://remoteok.com/api
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..extractors import clean_text, format_salary, html_to_text, parse_date
from ..filters import matches_countries
from ..models import JobPosting
from .base import BasePortal, BusinessError


class RemoteOkPortal(BasePortal):
    name = "remoteok"
    label = "Remote OK (live API)"

    def discover(self, limit: int) -> list[JobPosting]:
        try:
            payload = json.loads(self.http.get(self.base_url or "https://remoteok.com/api"))
        except json.JSONDecodeError as exc:
            raise BusinessError(f"Remote OK returned invalid JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise BusinessError("Remote OK returned an unexpected response shape.")

        # The feed is only ~100 rows, so scan all of it and keep the matching
        # country before trimming: a location filter must not miss an India
        # listing that sits at position 60.
        countries = self.country_filter()
        jobs: list[JobPosting] = []
        for item in payload:
            if not isinstance(item, dict) or "legal" in item:
                continue
            job = self._to_job(item)
            if not job.title:
                continue
            if countries and not matches_countries(job, countries):
                continue
            jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs

    def _to_job(self, item: dict) -> JobPosting:
        posted = parse_date(item.get("date"))
        if not posted and item.get("epoch"):
            try:
                posted = parse_date(
                    datetime.fromtimestamp(int(item["epoch"]), tz=timezone.utc).isoformat()
                )
            except (TypeError, ValueError, OSError):
                posted = ""

        tags = [clean_text(tag) for tag in (item.get("tags") or []) if clean_text(tag)]
        source_url = str(item.get("url") or "")
        apply_url = str(item.get("apply_url") or source_url)

        return JobPosting(
            portal=self.name,
            title=clean_text(item.get("position")),
            company=html_to_text(item.get("company")),
            location=clean_text(item.get("location")),
            work_mode="Remote",
            salary=format_salary(item.get("salary_min"), item.get("salary_max"), "USD"),
            posted_date=posted,
            category=", ".join(tags),
            description=html_to_text(item.get("description")),
            apply_url=apply_url,
            source_url=source_url,
        )
