"""Offline tests for the live-feed adapters (saved API/RSS fixtures)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rpa_jobs.portals import BusinessError, create_portal
from rpa_jobs.portals.aggregate import AggregatePortal
from rpa_jobs.portals.arbeitnow import ArbeitnowPortal
from rpa_jobs.portals.hasjob import HasjobPortal
from rpa_jobs.portals.himalayas import HimalayasPortal
from rpa_jobs.portals.jobicy import JobicyPortal
from rpa_jobs.portals.remoteok import RemoteOkPortal
from rpa_jobs.portals.weworkremotely import WeWorkRemotelyPortal
from rpa_jobs.portals.workingnomads import WorkingNomadsPortal

from .test_portals import StubHttp

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
JOBICY_URL = "https://jobicy.com/api/jobs"
REMOTEOK_URL = "https://remoteok.com/api"
WWR_FEED = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
HASJOB_FEED = "https://hasjob.co/feed"
HIMALAYAS_URL = "https://himalayas.app/jobs/api"
WORKINGNOMADS_URL = "https://www.workingnomads.com/api/exposed_jobs/"


# --------------------------------------------------------------------------- Arbeitnow
def test_arbeitnow_maps_api_fields():
    portal = ArbeitnowPortal(
        {"base_url": ARBEITNOW_URL},
        StubHttp({ARBEITNOW_URL: fixture("arbeitnow.json")}),
    )
    jobs = portal.discover(limit=2)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.title == "Senior Digital Creative Design – for dm-drogerie markt"
    assert first.company == "wongdoody"
    assert first.location == "Berlin, DE"
    assert first.work_mode == "Unspecified"
    assert first.apply_url.startswith("https://www.arbeitnow.com/jobs/")
    assert first.source_url == first.apply_url
    assert "<p>" not in first.description
    expected_date = datetime.fromtimestamp(1792810524, tz=timezone.utc).date().isoformat()
    assert first.posted_date == expected_date


def test_arbeitnow_marks_remote_flag():
    payload = json.loads(fixture("arbeitnow.json"))
    payload["data"][0]["remote"] = True
    portal = ArbeitnowPortal(
        {"base_url": ARBEITNOW_URL},
        StubHttp({ARBEITNOW_URL: json.dumps(payload)}),
    )
    assert portal.discover(limit=1)[0].work_mode == "Remote"


def test_arbeitnow_rejects_invalid_json():
    portal = ArbeitnowPortal({"base_url": ARBEITNOW_URL}, StubHttp({ARBEITNOW_URL: "not json"}))
    with pytest.raises(BusinessError):
        portal.discover(limit=1)


# --------------------------------------------------------------------------- Jobicy
def test_jobicy_maps_fields_and_structured_salary():
    portal = JobicyPortal(
        {"base_url": JOBICY_URL},
        StubHttp({f"{JOBICY_URL}?count=2": fixture("jobicy.json")}),
    )
    jobs = portal.discover(limit=2)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.title == "Billing Operations Lead"
    assert first.company == "Instacart"
    assert first.location == "USA"
    assert first.work_mode == "Remote"
    assert first.employment_type == "Full-time"
    assert first.salary == "$84,000 - $97,000 per year"
    assert first.category == "Finance & Accounting"
    assert first.posted_date == "2026-10-23"
    assert first.apply_url.startswith("https://jobicy.com/jobs/")
    assert "<p>" not in first.description


# --------------------------------------------------------------------------- Remote OK
def test_remoteok_skips_legal_notice_and_unescapes_company():
    portal = RemoteOkPortal(
        {"base_url": REMOTEOK_URL},
        StubHttp({REMOTEOK_URL: fixture("remoteok.json")}),
    )
    jobs = portal.discover(limit=2)

    assert len(jobs) == 2
    first, second = jobs
    assert first.company == "Aisles & Abroad"
    assert first.title == "Travel Support Specialist"
    assert first.work_mode == "Remote"
    assert first.location == "Seattle, Washington"
    assert first.posted_date == "2026-10-23"
    assert second.company == "Lemon.io"
    assert second.salary == "$50,000 - $150,000"


def test_remoteok_rejects_unexpected_payload():
    portal = RemoteOkPortal({"base_url": REMOTEOK_URL}, StubHttp({REMOTEOK_URL: "{}"}))
    with pytest.raises(BusinessError):
        portal.discover(limit=1)


def test_remoteok_filters_country_before_trimming_limit():
    payload = [
        {"legal": "terms"},
        *[
            {
                "position": f"US Role {index}",
                "company": "Acme",
                "location": "New York, USA",
                "url": f"https://remoteok.com/remote-jobs/us-{index}",
            }
            for index in range(5)
        ],
        {
            "position": "Backend Engineer",
            "company": "Indian Startup",
            "location": "India",
            "url": "https://remoteok.com/remote-jobs/india-role",
        },
    ]
    portal = RemoteOkPortal(
        {"base_url": REMOTEOK_URL, "countries": ["India"]},
        StubHttp({REMOTEOK_URL: json.dumps(payload)}),
    )

    jobs = portal.discover(limit=1)

    assert [job.title for job in jobs] == ["Backend Engineer"]
    assert jobs[0].location == "India"


# --------------------------------------------------------------------------- WWR
def test_weworkremotely_parses_rss_and_splits_company():
    portal = WeWorkRemotelyPortal(
        {"feeds": [WWR_FEED]},
        StubHttp({WWR_FEED: fixture("weworkremotely.xml")}),
    )
    jobs = portal.discover(limit=3)

    assert len(jobs) == 3
    first = jobs[0]
    assert first.company == "Aquifer"
    assert first.title == "Development Manager"
    assert first.location == "Anywhere in the World"
    assert first.work_mode == "Remote"
    assert first.posted_date == "2026-10-23"
    assert first.category == "DevOps and Sysadmin"
    assert first.apply_url.startswith("https://weworkremotely.com/remote-jobs/")
    assert "<p>" not in first.description

    wrike = next(job for job in jobs if job.company == "Wrike")
    assert wrike.posted_date == "2026-10-05"
    assert wrike.category == "Full-Stack Programming"


def test_weworkremotely_raises_when_feed_invalid():
    portal = WeWorkRemotelyPortal(
        {"feeds": [WWR_FEED]},
        StubHttp({WWR_FEED: "<rss><channel></channel></rss>"}),
    )
    with pytest.raises(BusinessError):
        portal.discover(limit=1)


def test_weworkremotely_filters_country_before_trimming_limit():
    rss = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Acme: US Engineer</title>
    <region>USA Only</region>
    <category>Programming</category>
    <link>https://weworkremotely.com/remote-jobs/acme-us</link>
    <description><![CDATA[<p>New York</p>]]></description>
    <pubDate>Fri, 23 Oct 2026 10:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Zeta: Platform Engineer</title>
    <region>India</region>
    <category>Programming</category>
    <link>https://weworkremotely.com/remote-jobs/zeta-india</link>
    <description><![CDATA[<p>Bangalore</p>]]></description>
    <pubDate>Thu, 22 Oct 2026 10:00:00 +0000</pubDate>
  </item>
</channel></rss>"""
    portal = WeWorkRemotelyPortal(
        {"feeds": [WWR_FEED], "countries": ["India"]},
        StubHttp({WWR_FEED: rss}),
    )

    jobs = portal.discover(limit=1)

    assert [job.title for job in jobs] == ["Platform Engineer"]
    assert jobs[0].location == "India"


# --------------------------------------------------------------------------- Working Nomads
def test_workingnomads_filters_country_and_maps_fields():
    portal = WorkingNomadsPortal(
        {"base_url": WORKINGNOMADS_URL, "countries": ["India"]},
        StubHttp({WORKINGNOMADS_URL: fixture("workingnomads.json")}),
    )
    jobs = portal.discover(limit=10)

    # The US-only row is dropped; the multi-country row and "Anywhere in India" stay.
    assert len(jobs) == 2
    first = jobs[0]
    assert first.title == "AI Trainer"
    assert first.company == "iMerit Technology"
    assert first.work_mode == "Remote"
    assert first.category == "Administration"
    assert "quality" in first.skills
    assert first.posted_date == "2026-10-14"
    assert first.apply_url.startswith("https://www.workingnomads.com/")

    local = next(job for job in jobs if job.company == "TELUS Digital")
    assert local.location == "Anywhere in India"
    assert local.posted_date


def test_workingnomads_returns_global_jobs_without_country_filter():
    portal = WorkingNomadsPortal(
        {"base_url": WORKINGNOMADS_URL},
        StubHttp({WORKINGNOMADS_URL: fixture("workingnomads.json")}),
    )
    jobs = portal.discover(limit=10)
    assert len(jobs) == 3


# --------------------------------------------------------------------------- Hasjob
def test_hasjob_maps_atom_entries_and_marks_india():
    portal = HasjobPortal(
        {"base_url": HASJOB_FEED},
        StubHttp({HASJOB_FEED: fixture("hasjob.xml")}),
    )
    jobs = portal.discover(limit=3)

    assert len(jobs) == 3
    first = jobs[0]
    assert first.title == "Forward Deployed Engineer — Freshers welcome"
    assert first.company == "Actionboard"
    assert first.location == "Chennai"
    assert first.location_country == "India"
    assert first.work_mode == "On-site"
    assert first.employment_type == "Full-time"
    assert first.posted_date == "2026-10-23"
    assert first.apply_url == "https://hasjob.co/myactionboard.com/ccvh3"
    assert "Work from office" in first.description


def test_hasjob_rejects_invalid_feed():
    portal = HasjobPortal({"base_url": HASJOB_FEED}, StubHttp({HASJOB_FEED: "<feed>"}))
    with pytest.raises(BusinessError):
        portal.discover(limit=1)


# --------------------------------------------------------------------------- Himalayas
def test_himalayas_filters_india_and_maps_fields():
    url = f"{HIMALAYAS_URL}?limit=20"
    portal = HimalayasPortal(
        {"base_url": HIMALAYAS_URL, "countries": ["India"]},
        StubHttp({url: fixture("himalayas.json")}),
    )
    jobs = portal.discover(limit=5)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Cloud Finance Functional"
    assert job.company == "Inoapps"
    assert job.location == "India"
    assert job.location_country == "India"
    assert job.work_mode == "Remote"
    assert job.posted_date  # epoch converted to ISO date
    assert job.apply_url.startswith("https://himalayas.app/")


def test_himalayas_returns_global_jobs_without_country_filter():
    url = f"{HIMALAYAS_URL}?limit=20"
    portal = HimalayasPortal(
        {"base_url": HIMALAYAS_URL},
        StubHttp({url: fixture("himalayas.json")}),
    )
    jobs = portal.discover(limit=5)

    assert len(jobs) == 2
    assert {job.location_country for job in jobs} == {"India", ""}


# --------------------------------------------------------------------------- aggregate
def _aggregate_registry() -> dict:
    return {
        "all": {"sources": ["arbeitnow", "jobicy"]},
        "arbeitnow": {"base_url": ARBEITNOW_URL, "max_pages": 1},
        "jobicy": {"base_url": JOBICY_URL, "max_pages": 1},
    }


def test_aggregate_interleaves_sources():
    stub = StubHttp(
        {
            ARBEITNOW_URL: fixture("arbeitnow.json"),
            f"{JOBICY_URL}?count=5": fixture("jobicy.json"),
        }
    )
    portal = create_portal("all", _aggregate_registry()["all"], stub, None, _aggregate_registry())
    jobs = portal.discover(limit=4)

    assert len(jobs) == 4
    assert [job.portal for job in jobs] == ["arbeitnow", "jobicy", "arbeitnow", "jobicy"]
    assert portal.label.startswith("All live sources")


def test_aggregate_raises_when_every_source_fails():
    registry = {"all": {"sources": ["arbeitnow"]}, "arbeitnow": {"base_url": ARBEITNOW_URL}}
    portal = create_portal("all", registry["all"], StubHttp({}), None, registry)
    with pytest.raises(BusinessError):
        portal.discover(limit=2)


def test_aggregate_is_registered():
    portal = create_portal("all", {"sources": []}, StubHttp({}))
    assert isinstance(portal, AggregatePortal)
