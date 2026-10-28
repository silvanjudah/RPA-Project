"""Adapter for Internshala's public India jobs listing.

Internshala is India-only by design. The ``/jobs/`` listing is server-rendered
and robots.txt allows it (detail pages under ``/job/details/`` are disallowed,
so the bot never opens them). Cards carry title, company, city, salary,
experience, skills and a relative posting date.

Listing: https://internshala.com/jobs/
"""

from __future__ import annotations

import re

from ..extractors import (
    clean_text,
    detect_employment_type,
    detect_work_mode,
    parse_posted_date,
)
from ..filters import matches_countries
from ..models import JobPosting
from .base import BasePortal, BusinessError

CARD_SELECTOR = ".individual_internship"


class InternshalaPortal(BasePortal):
    name = "internshala"
    label = "Internshala (India jobs)"

    def discover(self, limit: int) -> list[JobPosting]:
        base = self.base_url or "https://internshala.com/jobs/"
        max_pages = max(1, int(self.settings.get("max_pages", 2)))
        countries = self.country_filter()

        jobs: list[JobPosting] = []
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            if len(jobs) >= limit:
                break
            url = base if page == 1 else f"{base.rstrip('/')}/page-{page}/"

            soup = self.soup(self.http.get(url))
            cards = soup.select(CARD_SELECTOR)
            if not cards:
                if page == 1:
                    raise BusinessError("Internshala returned no job cards (markup change or block).")
                break

            for card in cards:
                if len(jobs) >= limit:
                    break
                job = self._to_job(card)
                if not job.title or not job.source_url or job.source_url in seen:
                    continue
                if countries and not matches_countries(job, countries):
                    continue
                seen.add(job.source_url)
                jobs.append(job)

        if not jobs:
            raise BusinessError("Internshala returned no matching India vacancies.")
        return jobs[:limit]

    # ------------------------------------------------------------------ helpers
    def _to_job(self, card) -> JobPosting:
        link_node = card.select_one("a.job-title-href") or card.select_one("a[href]")
        title = self.text(link_node)
        href = self.link_from(link_node) or str(card.get("data-href") or "")
        source_url = self.url(href)

        location = self.text(card.select_one(".locations"))
        location = clean_text(location.replace(" ,", ",").replace(", ,", ","))

        description = self.text(card.select_one(".about_job .text"))
        salary = self._salary(card)
        experience = self._experience(card)
        skills = [
            self.text(node)
            for node in card.select(".job_skill")
            if self.text(node)
        ]

        detail_text = self.text(card.select_one(".detail-row-2-container"))
        posted = parse_posted_date(detail_text)
        employment = self.text(card.select_one(".employment_type")) or str(
            card.get("employment_type") or ""
        )

        notes = []
        if experience:
            notes.append(f"Experience: {experience}")
        if description:
            notes.append(description)

        return JobPosting(
            portal=self.name,
            title=title,
            company=self.text(card.select_one(".company-name")),
            location=location,
            # Internshala only lists Indian roles.
            location_country="India",
            work_mode=detect_work_mode(title, location, description),
            employment_type=detect_employment_type(title, employment, detail_text, description),
            salary=salary,
            posted_date=posted,
            category=employment,
            skills=skills,
            description="\n".join(notes),
            apply_url=source_url,
            source_url=source_url,
        )

    def _salary(self, card) -> str:
        for row in card.select(".row-1-item"):
            text = self.text(row.select_one(".desktop") or row)
            if "₹" in text or "/year" in text.casefold():
                return clean_text(text.replace("/year", "").replace("/month", ""))
        return ""

    def _experience(self, card) -> str:
        for row in card.select(".row-1-item"):
            text = self.text(row)
            folded = text.casefold()
            # Salary rows also contain "/year"; skip them so the experience
            # field never repeats the pay range.
            if "₹" in text or "/year" in folded or "/month" in folded:
                continue
            if "experience" in folded or re.search(r"\b\d+\s*(?:\+\s*)?(?:year|yr)", folded):
                return text
        return ""
