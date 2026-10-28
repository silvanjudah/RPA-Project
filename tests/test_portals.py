"""Offline adapter tests using saved portal HTML fixtures."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from rpa_jobs.config import load_config
from rpa_jobs.portals import BusinessError, PythonJobsPortal

FIXTURES = Path(__file__).parent / "fixtures"
PYTHON_BASE = "https://www.python.org/jobs/"


class StubHttp:
    """Tiny HttpClient stand-in: no sockets, deterministic failures."""

    def __init__(self, pages: dict[str, str], fail_times: dict[str, int] | None = None,
                 always_fail: set[str] | None = None) -> None:
        self.pages = pages
        self.fail_times = dict(fail_times or {})
        self.always_fail = always_fail or set()
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        if url in self.always_fail:
            raise RuntimeError(f"simulated permanent failure: {url}")
        if self.fail_times.get(url, 0) > 0:
            self.fail_times[url] -= 1
            raise RuntimeError(f"simulated transient failure: {url}")
        if url not in self.pages:
            raise AssertionError(f"Unexpected URL fetched: {url}")
        return self.pages[url]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def python_settings(**overrides) -> dict:
    settings = copy.deepcopy(load_config()["portals"]["python-jobs"])
    settings["base_url"] = PYTHON_BASE
    settings["max_pages"] = 1
    settings.update(overrides)
    return settings


# --------------------------------------------------------------------------- python.org
def test_python_jobs_discovers_rich_listing_fields():
    portal = PythonJobsPortal(
        python_settings(),
        StubHttp({PYTHON_BASE: fixture("python_jobs_list.html")}),
    )
    jobs = portal.discover(limit=2)

    assert [job.title for job in jobs] == ["AI Engineer", "Senior Python Engineer"]
    first = jobs[0]
    assert first.company == "webbyfox consultancy"
    assert first.location == "London, UK"
    assert first.posted_date == "2026-10-23"
    assert first.category == "Developer / Engineer"
    assert first.source_url == "https://www.python.org/jobs/8184/"


def test_python_jobs_enriches_description_and_external_apply_link():
    detail_url = "https://www.python.org/jobs/8184/"
    stub = StubHttp(
        {
            PYTHON_BASE: fixture("python_jobs_list.html"),
            detail_url: fixture("python_job_detail.html"),
        }
    )
    portal = PythonJobsPortal(python_settings(), stub)
    job = portal.enrich(portal.discover(limit=1)[0])

    assert "RAG architectures" in job.description
    assert job.apply_url == "https://www.webbyfox.co.uk/careers/ai-engineer/"


def test_python_jobs_raises_when_listing_is_empty():
    portal = PythonJobsPortal(
        python_settings(),
        StubHttp({PYTHON_BASE: "<html><body><ol></ol></body></html>"}),
    )
    with pytest.raises(BusinessError):
        portal.discover(limit=5)


def test_python_jobs_stops_paginating_when_next_page_is_missing():
    from rpa_jobs.http_client import FetchError

    class PaginatedStub(StubHttp):
        def get(self, url: str) -> str:
            self.calls.append(url)
            if url.endswith("?page=2"):
                raise FetchError(f"HTTP 404 for {url}", permanent=True)
            return super().get(url)

    stub = PaginatedStub({PYTHON_BASE: fixture("python_jobs_list.html")})
    portal = PythonJobsPortal(python_settings(max_pages=3), stub)

    jobs = portal.discover(limit=10)

    assert len(jobs) == 2
    assert stub.calls[-1].endswith("?page=2")


def test_python_jobs_country_filter_keeps_matching_locations_only():
    settings = python_settings(countries=["India"])
    jobs = PythonJobsPortal(settings, StubHttp({PYTHON_BASE: fixture("python_jobs_list.html")})).discover(5)
    assert jobs == []

    settings = python_settings(countries=["UK"])
    jobs = PythonJobsPortal(settings, StubHttp({PYTHON_BASE: fixture("python_jobs_list.html")})).discover(5)
    assert len(jobs) == 2
