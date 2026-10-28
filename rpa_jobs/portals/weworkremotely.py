"""Adapter for We Work Remotely RSS feeds.

RSS is the sanctioned, low-impact way to consume WWR listings: each item has
the company in the title ("Company: Role"), region, category, full HTML
description and publication date.

Feeds: https://weworkremotely.com/categories/remote-programming-jobs.rss
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..extractors import clean_text, html_to_text, parse_date
from ..filters import matches_countries
from ..models import JobPosting
from .base import BasePortal, BusinessError

DEFAULT_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
]


class WeWorkRemotelyPortal(BasePortal):
    name = "weworkremotely"
    label = "We Work Remotely (live RSS)"

    def discover(self, limit: int) -> list[JobPosting]:
        feeds = self.settings.get("feeds") or DEFAULT_FEEDS
        countries = self.country_filter()
        per_feed: list[list[JobPosting]] = []
        seen: set[str] = set()
        errors: list[str] = []

        for feed_url in feeds:
            try:
                xml_text = self.http.get(feed_url)
                root = ET.fromstring(xml_text)
            except (ET.ParseError, OSError, ValueError) as exc:
                errors.append(f"{feed_url}: {exc}")
                continue

            channel = root.find("channel")
            if channel is None:
                errors.append(f"{feed_url}: no <channel> element")
                continue

            feed_jobs: list[JobPosting] = []
            for item in channel.findall("item"):
                job = self._to_job(item)
                if not job.title or not job.source_url or job.source_url in seen:
                    continue
                # Filter the whole feed before trimming to the run limit; the
                # India item can otherwise sit below the cut-off.
                if countries and not matches_countries(job, countries):
                    continue
                seen.add(job.source_url)
                feed_jobs.append(job)
            if feed_jobs:
                # Newest first; some feeds pin old evergreen posts.
                feed_jobs.sort(key=lambda job: job.posted_date or "0000-00-00", reverse=True)
                per_feed.append(feed_jobs)

        if not per_feed:
            detail = "; ".join(errors) if errors else "feeds contained no items"
            raise BusinessError(f"We Work Remotely feed could not be read ({detail}).")

        # Interleave feeds so multiple categories are represented.
        jobs: list[JobPosting] = []
        while len(jobs) < limit and any(per_feed):
            for feed_jobs in per_feed:
                if feed_jobs and len(jobs) < limit:
                    jobs.append(feed_jobs.pop(0))
        return jobs

    def _to_job(self, item: ET.Element) -> JobPosting:
        raw_title = self._text(item, "title")
        company, title = self._split_title(raw_title)
        region = self._text(item, "region")
        category = self._text(item, "category")
        description = html_to_text(self._text(item, "description"))
        link = self._text(item, "link")

        return JobPosting(
            portal=self.name,
            title=title,
            company=company,
            location=region,
            work_mode="Remote",
            posted_date=parse_date(self._text(item, "pubDate")),
            category=category,
            description=description,
            apply_url=link,
            source_url=link,
        )

    @staticmethod
    def _text(item: ET.Element, tag: str) -> str:
        node = item.find(tag)
        return clean_text(node.text if node is not None else "")

    @staticmethod
    def _split_title(raw_title: str) -> tuple[str, str]:
        """WWR titles look like ``Company: Job title``."""
        if ": " in raw_title:
            company, title = raw_title.split(": ", 1)
            return clean_text(company), clean_text(title)
        return "", clean_text(raw_title)
