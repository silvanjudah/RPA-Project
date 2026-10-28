"""Aggregate several live portals into a single discovery stream.

The pipeline still sees one portal; this adapter fans out to each configured
source, interleaves the results (newest from each, round-robin) and routes
per-job detail enrichment back to the adapter that produced the row.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import JobPosting
from .base import BasePortal, BusinessError

DEFAULT_SOURCES = [
    "hasjob",
    "shine",
    "internshala",
    "ycombinator",
    "himalayas",
    "python-jobs",
    "remoteok",
    "workingnomads",
]


class AggregatePortal(BasePortal):
    name = "all"
    label = "All live job sources"

    def __init__(
        self,
        settings: dict,
        http,
        logger: logging.Logger | None = None,
        registry: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(settings, http, logger)
        self.registry = registry or {}
        self.source_names = [
            name for name in (settings.get("sources") or DEFAULT_SOURCES) if name != self.name
        ]
        self.label = "All live sources: " + ", ".join(self.source_names)
        self._adapters: dict[str, BasePortal] = {}

    # ------------------------------------------------------------------ discovery
    def discover(self, limit: int) -> list[JobPosting]:
        sources = [name for name in self.source_names if name in self.registry]
        if not sources:
            raise BusinessError(
                "No live sources configured. Add portal blocks under 'portals' in config.json."
            )

        base, extra = divmod(limit, len(sources))
        queues: list[list[JobPosting]] = []
        failures: list[str] = []

        for index, name in enumerate(sources):
            # Small buffer so round-robin trimming still fills the quota when a
            # source returns fewer rows than its budget.
            budget = base + (1 if index < extra else 0) + 3
            try:
                adapter = self._make_adapter(name)
                jobs = adapter.discover(budget)
            except Exception as exc:  # noqa: BLE001 - one dead feed must not stop the run
                failures.append(f"{name}: {exc}")
                self.log.warning("Source '%s' failed: %s", name, exc)
                continue
            self.log.info("Source '%s' returned %d listings", name, len(jobs))
            if jobs:
                queues.append(jobs)

        if not queues:
            raise BusinessError("All live sources failed: " + "; ".join(failures))

        merged: list[JobPosting] = []
        while len(merged) < limit:
            progressed = False
            for queue in queues:
                if queue and len(merged) < limit:
                    merged.append(queue.pop(0))
                    progressed = True
            if not progressed:
                break
        return merged

    def enrich(self, job: JobPosting) -> JobPosting:
        adapter = self._adapters.get(job.portal)
        if adapter is None:
            return job
        return adapter.enrich(job)

    # --------------------------------------------------------------------- helpers
    def _make_adapter(self, name: str) -> BasePortal:
        from . import create_portal

        if name not in self._adapters:
            settings = dict(self.registry[name])
            filters = self.settings.get("filters") or {}
            if filters.get("countries") and not settings.get("countries"):
                settings["countries"] = list(filters["countries"])
            self._adapters[name] = create_portal(name, settings, self.http, self.log)
        return self._adapters[name]
