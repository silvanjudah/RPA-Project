"""Adapter for Y Combinator's India startup-jobs page.

``https://www.ycombinator.com/jobs/location/india`` is a public, server-rendered
list of roles at YC companies that hire in India. Cards include company, title,
salary, role family and the locations string (for example ``IN`` or
``Bengaluru, KA, IN / Remote``). robots.txt only blocks account/verify paths,
so the listing is safe to read.

Listing: https://www.ycombinator.com/jobs/location/india
"""

from __future__ import annotations

import re

from ..extractors import (
    clean_text,
    detect_employment_type,
    detect_work_mode,
    parse_posted_date,
)
from ..filters import COUNTRY_ALIASES, matches_countries
from ..models import JobPosting
from .base import BasePortal, BusinessError

CARD_SELECTOR = "li.my-2"
_INDIA_TOKEN = re.compile(r"\b(?:india|IN)\b")


class YCombinatorPortal(BasePortal):
    name = "ycombinator"
    label = "Y Combinator startups hiring in India"

    def discover(self, limit: int) -> list[JobPosting]:
        base = self.base_url or "https://www.ycombinator.com/jobs/location/india"
        countries = self.country_filter()

        soup = self.soup(self.http.get(base))
        cards = [
            card
            for card in soup.select(CARD_SELECTOR)
            if card.select_one('a[href*="/companies/"][href*="/jobs/"]')
        ]
        if not cards:
            raise BusinessError("Y Combinator returned no India job cards (markup change).")

        jobs: list[JobPosting] = []
        seen: set[str] = set()
        for card in cards:
            if len(jobs) >= limit:
                break
            job = self._to_job(card)
            if not job.title or not job.source_url or job.source_url in seen:
                continue
            if not self._india_eligible(job.location):
                continue
            if countries and not matches_countries(job, countries):
                continue
            seen.add(job.source_url)
            jobs.append(job)

        if not jobs:
            raise BusinessError("Y Combinator returned no India-eligible vacancies.")
        return jobs[:limit]

    # ------------------------------------------------------------------ helpers
    def _to_job(self, card) -> JobPosting:
        link = card.select_one('a[href*="/companies/"][href*="/jobs/"]')
        href = self.link_from(link)
        source_url = self.url(href)

        company_link = card.select_one('a[href^="/companies/"] span.block.font-bold')
        company = self.text(company_link)
        company = re.sub(r"\s*\([A-Z]\d{2}\)\s*$", "", company).strip()

        meta = card.select_one("div.flex.flex-wrap.items-center")
        parts = [self.text(node) for node in meta.find_all("div", recursive=False)] if meta else []
        parts = [part for part in parts if part and part != "•"]

        employment = next((part for part in parts if detect_employment_type(part)), "")
        salary = next(
            (part for part in parts if part.startswith(("$", "₹", "€", "£"))),
            "",
        )
        location = parts[-1] if parts else ""
        category = parts[1] if len(parts) > 1 and parts[1] != salary else ""

        posted = parse_posted_date(self.text(card.select_one("span.text-gray-400")))

        return JobPosting(
            portal=self.name,
            title=self.text(link),
            company=company,
            location=location,
            location_country="India" if self._india_eligible(location) else "",
            work_mode=detect_work_mode(location, self.text(link)),
            employment_type=employment or detect_employment_type(self.text(link)),
            salary=salary,
            posted_date=posted,
            category=category,
            description=f"{category} role at {company}" if category else "",
            apply_url=source_url,
            source_url=source_url,
        )

    @staticmethod
    def _india_eligible(location: str) -> bool:
        """True for ``IN``, ``India``, or a city-only Indian location."""
        if not location:
            return False
        if _INDIA_TOKEN.search(location):
            return True
        folded = location.casefold()
        return any(
            re.search(rf"\b{re.escape(alias)}\b", folded)
            for alias in COUNTRY_ALIASES.get("india", ())
        )
