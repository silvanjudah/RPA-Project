"""Portal adapter contract.

Adding a new job board means subclassing :class:`BasePortal`, pointing the JSON
selector map at the new markup and registering the class — the pipeline, Excel
report and logging stay untouched. This is the bot's "Object Repository".
"""

from __future__ import annotations

import abc
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..extractors import clean_text, parse_date, strip_label
from ..models import JobPosting


class BusinessError(Exception):
    """Data problem (empty page, missing title) - retrying will not help."""


class BasePortal(abc.ABC):
    name: str = ""
    label: str = ""

    def __init__(self, settings: dict, http, logger: logging.Logger | None = None) -> None:
        self.settings = settings or {}
        self.http = http
        self.log = logger or logging.getLogger("rpa.jobs.portal")
        self.base_url = str(self.settings.get("base_url", "")).strip()
        self.selectors = self.settings.get("selectors") or {}

    # ------------------------------------------------------------------ helpers
    def url(self, path: str) -> str:
        return urljoin(self.base_url, path)

    def selector(self, key: str, default: str) -> str:
        return self.selectors.get(key) or default

    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def country_filter(self) -> list[str]:
        """Countries requested by the run; empty means "no location filter".

        The pipeline copies ``filters`` into the portal settings, and the
        aggregate adapter also propagates ``filters.countries`` to each source,
        so either location can carry the value.
        """
        values = (
            self.settings.get("countries")
            or (self.settings.get("filters") or {}).get("countries")
            or []
        )
        return [clean_text(value) for value in values if clean_text(value)]

    @staticmethod
    def text(node: Tag | str | None, default: str = "") -> str:
        if node is None:
            return default
        if isinstance(node, str):
            return clean_text(node) or default
        return clean_text(node.get_text(" ", strip=True)) or default

    @staticmethod
    def strip_label(value: str, *labels: str) -> str:
        return strip_label(value, *labels)

    @staticmethod
    def date_from(node: Tag | None) -> str:
        if node is None:
            return ""
        raw = node.get("datetime") or node.get_text(" ", strip=True)
        return parse_date(raw)

    @staticmethod
    def link_from(node: Tag | None) -> str:
        if node is None:
            return ""
        href = node.get("href")
        return str(href).strip() if href else ""

    # ----------------------------------------------------------------- contract
    @abc.abstractmethod
    def discover(self, limit: int) -> list[JobPosting]:
        """Return list-page postings (core fields, no detail text)."""

    def enrich(self, job: JobPosting) -> JobPosting:
        """Optionally open the detail page and fill description/salary data."""
        return job

    # ----------------------------------------------------------------- metadata
    @classmethod
    def describe(cls) -> str:
        return f"{cls.name}: {cls.label}"
