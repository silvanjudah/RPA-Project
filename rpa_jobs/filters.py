"""Keyword and location filters shared by portals and the pipeline.

Filtering jobs before enrichment keeps India-only runs cheap: the location is
already known from the listing, so only matching vacancies need a detail page.
"""

from __future__ import annotations

import re
from typing import Any

# Cities and states used when a feed says "Bangalore" instead of "India".
# Matched with word boundaries against the *location* field only, so an
# American "Indiana" or "Indianapolis" does not slip through.
COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "india": (
        "bengaluru",
        "bangalore",
        "mumbai",
        "navi mumbai",
        "new delhi",
        "delhi",
        "gurgaon",
        "gurugram",
        "noida",
        "greater noida",
        "faridabad",
        "ghaziabad",
        "hyderabad",
        "secunderabad",
        "pune",
        "chennai",
        "kolkata",
        "calcutta",
        "ahmedabad",
        "jaipur",
        "kochi",
        "cochin",
        "coimbatore",
        "indore",
        "chandigarh",
        "mohali",
        "thiruvananthapuram",
        "trivandrum",
        "mysore",
        "mysuru",
        "nagpur",
        "surat",
        "vadodara",
        "bhubaneswar",
        "visakhapatnam",
        "vizag",
        "dehradun",
        "panaji",
        "lucknow",
        "kanpur",
        "nashik",
        "madurai",
        "tiruchirappalli",
        "trichy",
        "salem",
        "vijayawada",
        "warangal",
        "guwahati",
        "patna",
        "ranchi",
        "bhopal",
        "raipur",
        "jodhpur",
        "udaipur",
        "agra",
        "meerut",
        "rajkot",
        "srinagar",
        "jammu",
        "amritsar",
        "ludhiana",
        "jalandhar",
        "gwalior",
        "jabalpur",
        "kolhapur",
        "aurangabad",
        "solapur",
        "hubli",
        "mangalore",
        "belgaum",
        "tirupati",
        "nellore",
        "guntur",
        "kakinada",
        "kerala",
        "telangana",
        "karnataka",
        "maharashtra",
        "tamil nadu",
        "andhra pradesh",
        "uttar pradesh",
        "haryana",
        "punjab",
        "rajasthan",
        "gujarat",
        "west bengal",
        "odisha",
        "assam",
        "uttarakhand",
        "madhya pradesh",
        "chhattisgarh",
        "jharkhand",
        "bihar",
        "goa",
    ),
}


def _has_word(needle: str, haystack: str) -> bool:
    return bool(re.search(rf"\b{re.escape(needle)}\b", haystack, re.I))


def matches_keywords(job: Any, keywords: list[str], match_all: bool = False) -> bool:
    if not keywords:
        return True
    haystack = " ".join(
        part
        for part in (
            getattr(job, "title", ""),
            getattr(job, "company", ""),
            getattr(job, "location", ""),
            getattr(job, "category", ""),
            getattr(job, "work_mode", ""),
            getattr(job, "employment_type", ""),
            getattr(job, "salary", ""),
            getattr(job, "description", ""),
            " ".join(getattr(job, "skills", []) or []),
        )
        if part
    ).casefold()
    checks = (keyword.casefold() in haystack for keyword in keywords)
    return all(checks) if match_all else any(checks)


def matches_countries(job: Any, countries: list[str]) -> bool:
    """True when the vacancy's location is inside one of ``countries``."""
    if not countries:
        return True
    location = " ".join(
        part
        for part in (getattr(job, "location", ""), getattr(job, "location_country", ""))
        if part
    )
    if not location.strip():
        return False
    for country in countries:
        if _has_word(country, location):
            return True
        for alias in COUNTRY_ALIASES.get(country.casefold(), ()):
            if _has_word(alias, location):
                return True
    return False


def job_matches(job: Any, filters: dict) -> bool:
    """Apply keyword and country filters together (AND semantics)."""
    keywords = [str(word) for word in (filters.get("keywords") or []) if str(word).strip()]
    countries = [str(name) for name in (filters.get("countries") or []) if str(name).strip()]
    match_all = str(filters.get("match", "any")).lower() == "all"
    return matches_keywords(job, keywords, match_all) and matches_countries(job, countries)
