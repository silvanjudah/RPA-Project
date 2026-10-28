"""Unit tests for the pure text-extraction helpers."""

from __future__ import annotations

import pytest

from rpa_jobs.extractors import (
    clean_text,
    derive_fields,
    detect_employment_type,
    detect_work_mode,
    extract_salary,
    extract_skills,
    format_salary,
    html_to_text,
    normalise_employment_type,
    parse_date,
    repair_mojibake,
    truncate,
)

VOCABULARY = [
    {"label": "Python", "patterns": ["python"]},
    {"label": "Django", "patterns": ["django"]},
    {"label": "PostgreSQL", "patterns": ["postgresql", "postgres"]},
    {"label": "REST API", "patterns": ["rest api", "restful", "rest"]},
    {"label": "React", "patterns": ["react"]},
    {"label": "AWS", "patterns": ["aws", "amazon web services"]},
]


def test_clean_text_collapses_whitespace_and_nbsp():
    assert clean_text("  Senior\u00a0Python \n\t Developer ") == "Senior Python Developer"
    assert clean_text(None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2021-04-08", "2021-04-08"),
        ("2026-10-23T22:37:12.242849+00:00", "2026-10-23"),
        ("23 October 2026", "2026-10-23"),
        ("Posted: 2021-04-08", "2021-04-08"),
        ("April 8, 2021", "2021-04-08"),
        ("2021-04-08T10:00:00Z", "2021-04-08"),
        ("not-a-date", ""),
        ("", ""),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Senior Python Developer - Remote", "Remote"),
        ("Work from home, UK", "Remote"),
        ("Hybrid role in London", "Hybrid"),
        ("On-site role in Berlin", "On-site"),
        ("Senior Python Developer", "Unspecified"),
    ],
)
def test_detect_work_mode(text, expected):
    assert detect_work_mode(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Full-time permanent role", "Full-time"),
        ("Part time, 3 days a week", "Part-time"),
        ("6 month contract (outside IR35)", "Contract"),
        ("Paid internship", "Internship"),
        ("Temporary cover", "Temporary"),
        ("", ""),
    ],
)
def test_detect_employment_type(text, expected):
    assert detect_employment_type(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Salary: $120,000 - $150,000 per year", "$120,000 - $150,000 per year"),
        ("We pay £60k - £75k", "£60k - £75k"),
        ("Compensation of USD 90,000", "USD 90,000"),
        ("Starting at €45.000 per annum", "€45.000 per annum"),
        ("Python 3 and AWS", ""),
        ("", ""),
    ],
)
def test_extract_salary(text, expected):
    assert extract_salary(text) == expected


def test_extract_salary_does_not_match_year_or_small_numbers():
    assert extract_salary("Founded in 2024 with 12 people") == ""
    assert extract_salary("A $500 home-office stipend and $40 monthly internet") == ""


def test_extract_salary_accepts_hourly_rates():
    assert extract_salary("Rate: $50 per hour") == "$50 per hour"


def test_detect_employment_type_ignores_free_text_false_positives():
    assert detect_employment_type("Präsentationen intern und vor Ort") == ""
    assert detect_employment_type("salary depends on employment contract type") == ""
    assert detect_employment_type("6 month contract (outside IR35)") == "Contract"


def test_normalise_structured_employment_labels():
    assert normalise_employment_type("Full Time") == "Full-time"
    assert normalise_employment_type("contract") == "Contract"
    assert normalise_employment_type("internship") == "Internship"
    assert normalise_employment_type("mid", "professional / experienced") == ""


def test_extract_skills_uses_word_boundaries_and_labels():
    text = "Python, Django and PostgreSQL. RESTful APIs. We build reactive UIs, not SPAs."
    skills = extract_skills(text, vocabulary=VOCABULARY)
    assert skills == ["Python", "Django", "PostgreSQL", "REST API"]
    assert "React" not in skills


def test_extract_skills_handles_simple_string_vocabulary():
    assert extract_skills("AWS and python", vocabulary=["Python", "AWS"]) == ["Python", "AWS"]


def test_derive_fields_fills_missing_values():
    derived = derive_fields(
        title="Senior Python Developer",
        company="Acme",
        location="Remote (UK)",
        description="Full-time role. Salary $90,000 - $110,000 per year. Django, AWS.",
        category="",
        work_mode="Unspecified",
        employment_type="",
        salary="",
        posted_date="2024-05-01",
        skills=[],
        vocabulary=VOCABULARY,
        description_limit=80,
    )
    assert derived["work_mode"] == "Remote"
    assert derived["employment_type"] == "Full-time"
    assert derived["salary"] == "$90,000 - $110,000 per year"
    assert derived["skills"] == ["Python", "Django", "AWS"]
    assert len(derived["description"]) <= 80


def test_derive_fields_caps_skill_list():
    derived = derive_fields(
        title="Python Django AWS Docker Engineer",
        company="Acme",
        location="Remote",
        description="Python Django AWS Docker Kubernetes React",
        category="",
        work_mode="",
        employment_type="",
        salary="",
        posted_date="",
        skills=[],
        vocabulary=VOCABULARY,
        skills_limit=2,
    )
    assert len(derived["skills"]) == 2


def test_parse_date_rfc_2822():
    assert parse_date("Mon, 05 Oct 2026 07:31:29 +0000") == "2026-10-05"


def test_html_to_text_handles_double_escaped_markup():
    assert html_to_text("&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;") == "Hello & welcome"
    assert html_to_text("<div><p>Hello <b>world</b></p></div>") == "Hello world"
    assert html_to_text("AccountantÂ&nbsp;Salary") == "Accountant Salary"
    assert html_to_text(None) == ""


def test_format_salary_builds_readable_ranges():
    assert format_salary(84000, 97000, "USD", "yearly") == "$84,000 - $97,000 per year"
    assert format_salary(50, 60, "EUR", "hourly") == "€50 - €60 per hour"
    assert format_salary(0, 0) == ""
    assert format_salary(90000, None, "GBP") == "£90,000"


def test_repair_mojibake_recovers_utf8_read_as_cp1252():
    assert repair_mojibake("Weâ€™ve been – here") == "We’ve been – here"
    assert repair_mojibake("Sothebyâ€™s") == "Sotheby’s"
    assert repair_mojibake("CafÃ©") == "Café"


def test_repair_mojibake_keeps_valid_text_and_handles_mixed_runs():
    assert repair_mojibake("already fine – café") == "already fine – café"
    assert repair_mojibake("Don’t â€“ stop") == "Don’t – stop"
    assert repair_mojibake(None) == ""


def test_clean_text_repairs_mojibake_and_nbsp():
    assert clean_text("Management AccountantÂ\u00a0Salary") == "Management Accountant Salary"


def test_derive_fields_never_overrides_portal_values():
    derived = derive_fields(
        title="Engineer",
        company="Acme",
        location="Berlin",
        description="Remote possible",
        category="",
        work_mode="On-site",
        employment_type="Contract",
        salary="€70,000",
        posted_date="2024-01-02",
        skills=["Go"],
        vocabulary=VOCABULARY,
    )
    assert derived["work_mode"] == "On-site"
    assert derived["employment_type"] == "Contract"
    assert derived["salary"] == "€70,000"
    assert derived["skills"] == ["Go"]


def test_truncate_respects_limit():
    assert truncate("abcdefghij", 5) == "abcd…"
    assert truncate("short", 50) == "short"
