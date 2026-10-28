"""Data model for a single job vacancy transaction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def normalise(value: str | None) -> str:
    """Case-folded, whitespace-collapsed text used for comparisons."""
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class JobPosting:
    """One vacancy extracted from a portal.

    ``job_id`` is deterministic, so re-running the bot against a static board
    produces the same identifiers and duplicate rows can be filtered.
    """

    portal: str
    title: str
    company: str = ""
    location: str = ""
    location_country: str = ""
    work_mode: str = "Unspecified"
    employment_type: str = ""
    salary: str = ""
    posted_date: str = ""
    category: str = ""
    skills: list[str] = field(default_factory=list)
    description: str = ""
    apply_url: str = ""
    source_url: str = ""
    scraped_at: str = field(default_factory=utc_now)

    @property
    def job_id(self) -> str:
        basis = self.source_url or f"{self.title}|{self.company}|{self.location}"
        digest = hashlib.sha1(f"{self.portal}::{basis}".encode("utf-8")).hexdigest()
        return digest[:10].upper()

    @property
    def dedupe_key(self) -> str:
        """Content-based key, catches the same job listed under two URLs."""
        return "|".join(
            (
                normalise(self.title),
                normalise(self.company),
                normalise(self.location),
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "work_mode": self.work_mode,
            "employment_type": self.employment_type,
            "salary": self.salary,
            "posted_date": self.posted_date,
            "category": self.category,
            "skills": self.skills,
            "description": self.description,
            "apply_url": self.apply_url,
            "source_url": self.source_url,
            "portal": self.portal,
            "scraped_at": self.scraped_at,
        }


@dataclass
class LogRecord:
    """Structured transaction log line, mirrored to Excel and the console."""

    timestamp: str
    level: str
    status: str
    step: str
    message: str
    job_id: str = ""
    title: str = ""
    attempt: int = 0
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "status": self.status,
            "step": self.step,
            "message": self.message,
            "job_id": self.job_id,
            "title": self.title,
            "attempt": self.attempt,
            "duration_ms": self.duration_ms,
        }
