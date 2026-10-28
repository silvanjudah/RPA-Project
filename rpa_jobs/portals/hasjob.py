"""Adapter for Hasjob's Atom feed (India-focused startup jobs).

Hasjob (https://hasjob.co) is an Indian job board run by Zerodha. The public
Atom feed is explicitly crawlable (robots.txt only blocks edit/admin paths) and
contains company, location, full HTML description and publication dates.

Feed: https://hasjob.co/feed
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..extractors import (
    clean_text,
    detect_employment_type,
    detect_work_mode,
    html_to_text,
    parse_date,
)
from ..models import JobPosting
from .base import BasePortal, BusinessError

ATOM = {"a": "http://www.w3.org/2005/Atom"}


class HasjobPortal(BasePortal):
    name = "hasjob"
    label = "Hasjob (India, live Atom feed)"

    def discover(self, limit: int) -> list[JobPosting]:
        url = self.base_url or "https://hasjob.co/feed"
        try:
            root = ET.fromstring(self.http.get(url))
        except (ET.ParseError, OSError, ValueError) as exc:
            raise BusinessError(f"Hasjob feed could not be read: {exc}") from exc

        jobs: list[JobPosting] = []
        seen: set[str] = set()
        for entry in root.findall("a:entry", ATOM):
            if len(jobs) >= limit:
                break
            job = self._to_job(entry)
            if not job.title or not job.source_url or job.source_url in seen:
                continue
            seen.add(job.source_url)
            jobs.append(job)

        if not jobs:
            raise BusinessError("Hasjob feed contained no vacancies.")
        return jobs

    def _to_job(self, entry: ET.Element) -> JobPosting:
        raw_title = clean_text(self._text(entry, "a:title"))
        location = clean_text(self._text(entry, "a:location"))
        content = self._text(entry, "a:content")
        link_node = entry.find("a:link", ATOM)
        link = str(link_node.get("href") or "") if link_node is not None else ""
        identifier = clean_text(self._text(entry, "a:id")) or link

        soup = BeautifulSoup(content, "html.parser")
        company = ""
        strong_link = soup.select_one("strong a") or soup.select_one("p a")
        if strong_link is not None:
            company = clean_text(strong_link.get_text(" ", strip=True))
        if not company:
            company = self._company_from_url(identifier)

        description = html_to_text(content)
        title = self._strip_location_suffix(raw_title, location)
        work_mode = detect_work_mode(location, description[:400])

        return JobPosting(
            portal=self.name,
            title=title,
            company=company,
            location=location,
            location_country="India",
            work_mode=work_mode,
            employment_type=detect_employment_type(description[:600]),
            posted_date=parse_date(
                self._text(entry, "a:published") or self._text(entry, "a:updated")
            ),
            description=description,
            apply_url=link,
            source_url=link,
        )

    @staticmethod
    def _text(entry: ET.Element, path: str) -> str:
        return entry.findtext(path, default="", namespaces=ATOM)

    @staticmethod
    def _strip_location_suffix(title: str, location: str) -> str:
        """Turn ``Role — Chennai`` into ``Role`` when the tail is the location."""
        if not location or " — " not in title:
            return title
        parts = [part.strip() for part in title.split(" — ")]
        if parts and parts[-1].casefold() == location.casefold():
            parts.pop()
        return " — ".join(part for part in parts if part) or title

    @staticmethod
    def _company_from_url(identifier: str) -> str:
        """Fallback: ``hasjob.co/acme.com/xyz`` -> ``acme.com``."""
        parsed = urlparse(identifier)
        segments = [part for part in parsed.path.split("/") if part]
        if segments:
            return segments[0].replace("www.", "")
        return ""
