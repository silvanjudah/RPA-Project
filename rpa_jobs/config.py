"""Configuration loading with sane defaults and deep merge support."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"

DEFAULT_SKILLS = [
    {"label": "Python", "patterns": ["python"]},
    {"label": "Django", "patterns": ["django"]},
    {"label": "Flask", "patterns": ["flask"]},
    {"label": "FastAPI", "patterns": ["fastapi", "fast api"]},
    {"label": "SQL", "patterns": ["sql"]},
    {"label": "AWS", "patterns": ["aws", "amazon web services"]},
    {"label": "Docker", "patterns": ["docker"]},
    {"label": "Kubernetes", "patterns": ["kubernetes", "k8s"]},
    {"label": "React", "patterns": ["react"]},
    {"label": "Machine Learning", "patterns": ["machine learning"]},
]

DEFAULTS: dict[str, Any] = {
    "portal": "all",
    "crawl": {
        "max_items": 50,
        "fetch_details": True,
        "delay_seconds": 0.4,
        "timeout_seconds": 20,
        "retries": 3,
        "backoff_seconds": 1.2,
        "respect_robots": True,
        "user_agent": "RPAJobBot/1.0 (personal job-search automation)",
    },
    "filters": {
        "keywords": [],
        "countries": ["India"],
        "match": "any",
    },
    "output": {
        "directory": "output",
        "filename_prefix": "job_vacancies",
        "description_limit": 1200,
        "skills_limit": 12,
    },
    "skills": DEFAULT_SKILLS,
    "portals": {},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` on top of ``base`` (returns a new dict)."""
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load JSON config, layered over :data:`DEFAULTS`.

    A missing path falls back to ``config/config.json`` and, if that is absent
    too, to the built-in defaults.
    """
    candidate = Path(path) if path else DEFAULT_CONFIG_PATH
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()

    file_config: dict[str, Any] = {}
    if candidate.exists():
        with candidate.open("r", encoding="utf-8") as handle:
            try:
                file_config = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in config file {candidate}: {exc}") from exc
        if not isinstance(file_config, dict):
            raise ValueError(f"Config root must be a JSON object: {candidate}")
    elif path:
        raise FileNotFoundError(f"Config file not found: {candidate}")

    config = _deep_merge(DEFAULTS, file_config)
    _normalise_paths(config)
    return config


def _normalise_paths(config: dict[str, Any]) -> None:
    """Resolve relative output paths against the project root."""
    out = config.setdefault("output", {})
    directory = Path(out.get("directory", "output"))
    if not directory.is_absolute():
        out["directory"] = str((PROJECT_ROOT / directory).resolve())
    else:
        out["directory"] = str(directory)


def portal_settings(config: dict[str, Any], portal_name: str | None = None) -> dict[str, Any]:
    """Return the settings block for a portal (empty dict when unknown)."""
    name = portal_name or config.get("portal", "")
    return (config.get("portals") or {}).get(name) or {}


def output_path(config: dict[str, Any], filename: str | None = None) -> Path:
    """Build the default output path for a fresh report."""
    from datetime import datetime

    out = config.get("output", {})
    directory = Path(out.get("directory", "output"))
    if filename:
        return directory / filename
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = out.get("filename_prefix", "job_vacancies")
    portal = config.get("portal", "portal")
    return directory / f"{prefix}_{portal}_{stamp}.xlsx"
