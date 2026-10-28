"""Adapter for Shine.com's public India job search.

Shine is an India-only board; the listing is server-rendered Next.js markup.
The search path carries the query (``/job-search/<query>-jobs-in-india``) and
supports ``-2``, ``-3``… page suffixes. robots.txt allows the search pages and
only blocks account, API and similar-job paths.

Search: https://www.shine.com/job-search/software-jobs-in-india
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

CARD_SELECTOR = 'article[itemprop="itemListElement"]'
_META_ITEM = re.compile(r"result-card_meta-item")


class ShinePortal(BasePortal):
    name = "shine"
    label = "Shine (India search)"

    def discover(self, limit: int) -> list[JobPosting]:
        keywords = [
            clean_text(word)
            for word in (self.settings.get("filters") or {}).get("keywords") or []
            if clean_text(word)
        ]
        query = self._slug(" ".join(keywords) or str(self.settings.get("default_query") or "software"))
        template = str(
            self.settings.get("search_url")
            or "https://www.shine.com/job-search/{query}-jobs-in-india"
        )
        max_pages = max(1, int(self.settings.get("max_pages", 2)))
        countries = self.country_filter()

        jobs: list[JobPosting] = []
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            if len(jobs) >= limit:
                break
            url = template.format(query=query)
            if page > 1:
                url = f"{url}-{page}"

            soup = self.soup(self.http.get(url))
            cards = soup.select(CARD_SELECTOR)
            if not cards:
                if page == 1:
                    raise BusinessError("Shine returned no job cards (markup change or block).")
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
            raise BusinessError("Shine returned no matching India vacancies.")
        return jobs[:limit]

    # ------------------------------------------------------------------ helpers
    def _to_job(self, card) -> JobPosting:
        link_node = card.select_one('h3[itemprop="name"] a') or card.find("a", href=True)
        title = self.text(link_node)
        href = self.link_from(link_node)

        meta_url = card.find("meta", attrs={"itemprop": "url"})
        source_url = self.text(meta_url.get("content") if meta_url else "") or self.url(href)

        location = self._meta_text(card, "result-card-icon-pin")
        salary = self._meta_text(card, "result-card-icon-rupee")
        experience = self._meta_text(card, "result-card-icon-briefcase")
        posted = parse_posted_date(self.text(card.select_one('[class*="result-card_posted"]')))

        description = experience and f"Experience: {experience}" or ""
        return JobPosting(
            portal=self.name,
            title=title,
            company=self.text(card.select_one('[class*="result-card_company"]')),
            location=location,
            # Shine's search is scoped to India; some cards only carry city names.
            location_country="India",
            work_mode=detect_work_mode(title, location, description),
            employment_type=detect_employment_type(title, description),
            salary=salary,
            posted_date=posted,
            description=description,
            apply_url=source_url,
            source_url=source_url,
        )

    def _meta_text(self, card, icon_id: str) -> str:
        icon = card.select_one(f'use[href="#{icon_id}"]')
        if icon is None:
            return ""
        parent = icon.find_parent("span", class_=_META_ITEM)
        if parent is None:
            parent = icon.find_parent(class_=_META_ITEM)
        return self.text(parent)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        return slug or "software"
