"""Tests for keyword and country filtering."""

from __future__ import annotations

from rpa_jobs.filters import job_matches, matches_countries, matches_keywords
from rpa_jobs.models import JobPosting


def job(**kwargs) -> JobPosting:
    kwargs.setdefault("title", "Role")
    return JobPosting(portal="test", **kwargs)


def test_india_matches_country_and_city_names():
    assert matches_countries(job(location="India"), ["India"])
    assert matches_countries(job(location="Bengaluru, Karnataka"), ["India"])
    assert matches_countries(job(location="HSR Layout, Bangalore"), ["India"])
    assert matches_countries(job(location="Remote (Pune)"), ["India"])


def test_indiana_is_not_india():
    assert not matches_countries(job(location="Indiana, USA"), ["India"])
    assert not matches_countries(job(location="Indianapolis, IN"), ["India"])


def test_explicit_country_field_wins_for_anywhere_jobs():
    assert matches_countries(job(location="Anywhere", location_country="India"), ["India"])
    assert not matches_countries(job(location="Anywhere in the World"), ["India"])


def test_empty_location_does_not_match():
    assert not matches_countries(job(location=""), ["India"])


def test_no_country_filter_accepts_everything():
    assert matches_countries(job(location="Berlin"), [])
    assert matches_countries(job(), [])


def test_keywords_any_and_all():
    posting = job(
        title="Backend Engineer",
        company="Acme",
        location="Bangalore, India",
        description="Django and PostgreSQL",
        skills=["Python"],
    )
    assert matches_keywords(posting, ["python"])
    assert matches_keywords(posting, ["python", "django"])
    assert not matches_keywords(posting, ["python", "rust"], match_all=True)


def test_job_matches_combines_keyword_and_country():
    filters = {"keywords": ["python"], "countries": ["India"], "match": "any"}
    assert job_matches(
        job(title="Python Developer", location="Chennai, India"), filters
    )
    assert not job_matches(
        job(title="Python Developer", location="London, UK"), filters
    )
    assert not job_matches(
        job(title="Sales Manager", location="Chennai, India"), filters
    )
