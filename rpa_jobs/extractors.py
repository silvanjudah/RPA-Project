"""Text normalisation and field extraction helpers.

Everything here is pure (no I/O) so it can be unit-tested offline. The portal
adapters supply raw strings; these helpers turn them into report-ready values.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Iterable

from bs4 import BeautifulSoup

_WHITESPACE_RE = re.compile(r"\s+")
_LABEL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z /]{1,24}\s*[:\-]\s*")

# Mojibake left behind when UTF-8 bytes are decoded as cp1252/latin-1, e.g.
# "itâ€™s" (U+2019), "CafÃ©" (U+00E9) or "Â " (U+00A0). Some feeds ship text
# that is already broken like this, so we repair it before reporting.
_MOJIBAKE_CONTINUATION = (
    "\u0080-\u00bf"
    "\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192"
    "\u02c6\u02dc\u2013\u2014\u2018\u2019\u201a\u201c\u201d\u201e"
    "\u2020\u2021\u2022\u2026\u2030\u2039\u203a\u20ac\u2122"
)
_MOJIBAKE_RE = re.compile(
    rf"(?:[\u00c2-\u00f4][{_MOJIBAKE_CONTINUATION}]{{1,3}})+"
)


def _decode_mojibake(chunk: str) -> str:
    for codec in ("cp1252", "latin-1"):
        try:
            return chunk.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return chunk


def repair_mojibake(value: Any) -> str:
    """Undo UTF-8-as-cp1252 double encoding, keeping valid text untouched."""
    if value is None:
        return ""
    text = str(value)
    if not _MOJIBAKE_RE.search(text):
        return text
    repaired = _decode_mojibake(text)
    if repaired != text:
        return repaired
    return _MOJIBAKE_RE.sub(lambda match: _decode_mojibake(match.group(0)), text)

_WORK_MODE_PATTERNS = (
    ("Hybrid", re.compile(r"\b(hybrid|partially remote|remote[- ]friendly)\b", re.I)),
    (
        "Remote",
        re.compile(
            r"\b(remote|work\s+from\s+home|wfh|telecommut\w*|telework|fully\s+distributed)\b",
            re.I,
        ),
    ),
    ("On-site", re.compile(r"\b(on[- ]?site|in[- ]office|office[- ]based|work\s+from\s+office)\b", re.I)),
)

_EMPLOYMENT_PATTERNS = (
    ("Internship", re.compile(r"\b(internship|intern\s+(?:position|role|program(?:me)?)|traineeship)\b", re.I)),
    ("Part-time", re.compile(r"\bpart[-\s]?time\b", re.I)),
    (
        "Contract",
        re.compile(
            r"\bcontractor\b|\bfreelance\b|\bb2b\b|\bcontract\s+(?:role|position|job|opportunity)\b"
            r"|\b\d+[-\s]?(?:month|months|week|weeks|year|years)\s+contract\b",
            re.I,
        ),
    ),
    ("Temporary", re.compile(r"\b(temporary|fixed[-\s]?term|seasonal)\b", re.I)),
    ("Full-time", re.compile(r"\bfull[-\s]?time\b|\bpermanent\b", re.I)),
)

_STRUCTURED_EMPLOYMENT = (
    (re.compile(r"full[-\s]?time|permanent", re.I), "Full-time"),
    (re.compile(r"part[-\s]?time", re.I), "Part-time"),
    (re.compile(r"\bcontract(?:or)?\b|\bfreelance\b|\bb2b\b", re.I), "Contract"),
    (re.compile(r"\bintern(?:ship)?\b", re.I), "Internship"),
    (re.compile(r"temporary|fixed[-\s]?term|seasonal", re.I), "Temporary"),
)

_AMOUNT = r"\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?\s?[kK]?"
_SALARY_RE = re.compile(
    rf"(?P<currency>[$£€₹]|USD|EUR|GBP|INR)\s?(?P<first>{_AMOUNT})"
    rf"(?:\s*(?:-|–|—|to)\s*(?P<currency2>[$£€₹])?\s?(?P<second>{_AMOUNT}))?"
    rf"(?:\s*(?:per|/|a)\s*(?P<period>year|annum|month|hour|hr|week|day))?",
    re.I,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)
_DATE_TOKEN_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})")


def clean_text(value: Any) -> str:
    """Repair encoding artefacts, collapse whitespace and drop nbsp."""
    if value is None:
        return ""
    text = repair_mojibake(value).replace("\xa0", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def strip_label(value: Any, *labels: str) -> str:
    """Remove a leading label such as ``Location:`` from a field value."""
    text = clean_text(value)
    for label in labels:
        text = re.sub(rf"^\s*{re.escape(label)}\s*[:\-]\s*", "", text, flags=re.I)
    if labels:
        return text
    return _LABEL_RE.sub("", text)


def truncate(value: str, limit: int, suffix: str = "…") -> str:
    text = clean_text(value)
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def html_to_text(raw: Any) -> str:
    """Decode (possibly double-escaped) HTML from APIs and RSS into plain text."""
    if raw is None:
        return ""
    text = repair_mojibake(unescape(str(raw)))
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return clean_text(text)


def format_salary(
    minimum: Any = None,
    maximum: Any = None,
    currency: str = "",
    period: str = "",
) -> str:
    """Build a readable salary range from structured API values."""
    def amount(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if number <= 0:
            return ""
        return f"{number:,.0f}"

    low, high = amount(minimum), amount(maximum)
    if not low and not high:
        return ""
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency.upper(), "")
    prefix = symbol or (currency.upper() + " " if currency else "")
    if low and high:
        core = f"{prefix}{low} - {prefix}{high}"
    else:
        core = f"{prefix}{low or high}"
    if period:
        label = {
            "yearly": "year",
            "monthly": "month",
            "weekly": "week",
            "daily": "day",
            "hourly": "hour",
        }.get(period.lower(), period.lower())
        core += f" per {label}"
    return core


def parse_date(raw: Any) -> str:
    """Return an ISO ``YYYY-MM-DD`` date or an empty string.

    Handles ISO datetimes (python.org uses them in ``<time datetime=...>``),
    ``2021-04-08`` and human formats such as ``23 October 2026``.
    """
    text = clean_text(raw)
    if not text:
        return ""
    text = re.sub(r"^(posted|published|date)\s*[:\-]?\s*", "", text, flags=re.I).strip()
    if not text:
        return ""

    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date().isoformat()
    except ValueError:
        pass

    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass

    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    match = _DATE_TOKEN_RE.search(text)
    if match and match.group(1) != text:
        return parse_date(match.group(1))
    return ""


_RELATIVE_DATE_RE = re.compile(
    r"\b(?:(\d+)\s*\+?\s*(minute|hour|day|week|month|year)s?\s+ago"
    r"|(today|yesterday)|just\s+now)\b",
    re.I,
)
_RELATIVE_UNITS = {
    "minute": "minutes",
    "hour": "hours",
    "day": "days",
    "week": "weeks",
    "month": "months",
    "year": "years",
}


def parse_posted_date(raw: Any, today: date | None = None) -> str:
    """Parse absolute or relative listing dates (``4 days ago``).

    Listing pages often show ``Posted 3 days ago`` instead of a timestamp.
    The absolute parser runs first so real dates are never approximated; only
    then does the relative branch convert the text against ``today`` (UTC by
    default, injectable for deterministic tests).
    """
    absolute = parse_date(raw)
    if absolute:
        return absolute

    text = clean_text(raw)
    match = _RELATIVE_DATE_RE.search(text)
    if not match:
        return ""

    base = today or datetime.now(timezone.utc).date()
    if match.group(3):
        offset = 1 if match.group(3).casefold() == "yesterday" else 0
        return (base - timedelta(days=offset)).isoformat()
    if not match.group(1):
        return base.isoformat()

    amount = int(match.group(1))
    unit = _RELATIVE_UNITS[match.group(2).casefold()]
    if unit in ("months", "years"):
        # Calendar months are uneven; 30/365 days is the listing-site convention.
        days = amount * (30 if unit == "months" else 365)
        return (base - timedelta(days=days)).isoformat()
    return (base - timedelta(**{unit: amount})).isoformat()


def detect_work_mode(*values: Any) -> str:
    """Classify the work arrangement from title/location/description text."""
    text = " ".join(clean_text(value) for value in values if value)
    if not text:
        return "Unspecified"
    for label, pattern in _WORK_MODE_PATTERNS:
        if pattern.search(text):
            return label
    return "Unspecified"


def detect_employment_type(*values: Any) -> str:
    text = " ".join(clean_text(value) for value in values if value)
    if not text:
        return ""
    for label, pattern in _EMPLOYMENT_PATTERNS:
        if pattern.search(text):
            return label
    return ""


def normalise_employment_type(*values: Any) -> str:
    """Map structured API labels (``["Full Time"]``) to canonical values.

    Distinct from :func:`detect_employment_type` because API labels are short
    tokens where a bare "contract" is meaningful, while free-text descriptions
    often contain "contract type" or German "intern" (internally).
    """
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        for pattern, label in _STRUCTURED_EMPLOYMENT:
            if pattern.search(text):
                return label
    return ""


def _amount_magnitude(token: str) -> int:
    digits = re.sub(r"[^\d]", "", token)
    if not digits:
        return 0
    value = int(digits)
    if re.search(r"\d\s?[kK]\b", token) or token.strip().lower().endswith("k"):
        value *= 1000
    return value


def _looks_like_amount(token: str) -> bool:
    return bool(re.search(r"\d", token))


def extract_salary(*values: Any) -> str:
    """Find the first credible salary expression in the supplied text.

    Without an explicit period (year/month/hour), small amounts are rejected:
    a "$500 home-office stipend" is not a salary, while "$50 per hour" is.
    """
    text = " ".join(clean_text(value) for value in values if value)
    if not text:
        return ""
    for match in _SALARY_RE.finditer(text):
        first = match.group("first")
        if not _looks_like_amount(first):
            continue
        period = match.group("period")
        magnitudes = [_amount_magnitude(first)]
        if match.group("second"):
            magnitudes.append(_amount_magnitude(match.group("second")))
        if not period and max(magnitudes) < 1000:
            continue
        snippet = clean_text(match.group(0))
        if len(snippet) > 60:
            snippet = snippet[:60].rstrip()
        return snippet
    return ""


def normalise_vocabulary(vocabulary: Iterable[Any]) -> list[tuple[str, list[str]]]:
    """Accept either ``["Python"]`` or ``[{"label": ..., "patterns": [...]}]``."""
    entries: list[tuple[str, list[str]]] = []
    for item in vocabulary or []:
        if isinstance(item, str):
            entries.append((item, [item]))
        elif isinstance(item, dict) and item.get("label"):
            patterns = item.get("patterns") or [item["label"]]
            entries.append((str(item["label"]), [str(p) for p in patterns]))
    return entries


def extract_skills(*values: Any, vocabulary: Iterable[Any] | None = None) -> list[str]:
    """Match a configurable skill vocabulary against free text (word bounded)."""
    text = " ".join(clean_text(value) for value in values if value)
    if not text:
        return []
    found: list[str] = []
    for label, patterns in normalise_vocabulary(vocabulary or []):
        for pattern in patterns:
            regex = re.compile(
                rf"(?<![\w+#]){re.escape(pattern)}(?![\w+#])",
                re.I,
            )
            if regex.search(text):
                found.append(label)
                break
    return found


def derive_fields(
    *,
    title: str,
    company: str,
    location: str,
    description: str,
    category: str,
    work_mode: str,
    employment_type: str,
    salary: str,
    posted_date: str,
    skills: list[str],
    vocabulary: Iterable[Any] | None,
    description_limit: int = 1200,
    skills_limit: int = 0,
) -> dict[str, Any]:
    """Enrich a raw posting with detected fields, never overwriting portal data."""
    blob = " ".join(part for part in (title, company, category, location, description) if part)
    resolved_date = parse_date(posted_date)
    detected_skills = skills or extract_skills(
        title, category, description, vocabulary=vocabulary
    )
    if skills_limit and len(detected_skills) > skills_limit:
        detected_skills = detected_skills[:skills_limit]
    return {
        "work_mode": work_mode if work_mode and work_mode != "Unspecified" else detect_work_mode(
            title, location, description
        ),
        "employment_type": employment_type or detect_employment_type(blob),
        "salary": salary or extract_salary(description, title),
        "posted_date": resolved_date or posted_date,
        "skills": detected_skills,
        "description": truncate(description, description_limit),
    }
