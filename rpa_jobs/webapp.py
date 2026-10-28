"""Local web interface for the job vacancy bot.

A small Flask app that wraps the same :class:`~rpa_jobs.pipeline.JobBot` used by
the CLI and the desktop UI: the form builds the run configuration, the bot runs
in a background thread, and the browser polls for progress, log lines and the
finished Excel report.

The server is meant for local use only (default bind: ``127.0.0.1``). There is
no authentication, so do not expose it to an untrusted network.
"""

from __future__ import annotations

import copy
import logging
import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from . import __version__
from .config import load_config
from .pipeline import JobBot, RunResult
from .portals import PORTALS
from .portals.aggregate import DEFAULT_SOURCES

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_LOG_LINES = 500
MAX_PREVIEW_ROWS = 200
DEFAULT_APPEND_FILENAME = "web_jobs.xlsx"


@dataclass
class RunState:
    """Mutable state of the current (or last) web-triggered run."""

    id: str
    status: str = "running"  # running | finished | failed
    phase: str = "starting"
    started_at: str = ""
    finished_at: str = ""
    total: int = 0
    completed: int = 0
    current: str = ""
    logs: list[dict[str, str]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "completed": self.completed,
            "current": self.current,
            "logs": list(self.logs),
            "result": self.result,
            "error": self.error,
        }


class _RunLogHandler(logging.Handler):
    """Copy bot log records into the run state polled by the browser."""

    def __init__(self, state: RunState) -> None:
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - logging must never break the run
            message = str(record.msg)
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": record.levelname,
            "message": message,
        }
        with _lock:
            self.state.logs.append(entry)
            if len(self.state.logs) > MAX_LOG_LINES:
                del self.state.logs[: len(self.state.logs) - MAX_LOG_LINES]


# --------------------------------------------------------------------------- state
_lock = threading.Lock()
_current: RunState | None = None


def create_app(config_path: str | Path | None = None) -> Flask:
    """Build the Flask application (factory keeps tests isolated)."""
    app = Flask(
        __name__,
        template_folder=str(WEB_DIR / "templates"),
        static_folder=str(WEB_DIR / "static"),
    )
    app.json.sort_keys = False

    def current_config() -> dict:
        return load_config(config_path)

    # ----------------------------------------------------------------- pages
    @app.get("/")
    def index():
        config = current_config()
        defaults = {
            "portal": config.get("portal", "all"),
            "limit": int((config.get("crawl") or {}).get("max_items", 50)),
            "countries": ", ".join((config.get("filters") or {}).get("countries") or []),
            "keywords": ", ".join((config.get("filters") or {}).get("keywords") or []),
            "match": (config.get("filters") or {}).get("match", "any"),
            "fetch_details": bool((config.get("crawl") or {}).get("fetch_details", True)),
            "delay": float((config.get("crawl") or {}).get("delay_seconds", 0.4)),
        }
        portal_labels = {name: cls.label for name, cls in PORTALS.items()}
        sources = list((config.get("portals") or {}).get("all", {}).get("sources") or DEFAULT_SOURCES)
        return render_template(
            "index.html",
            version=__version__,
            portals=sorted(PORTALS),
            portal_labels=portal_labels,
            sources=sources,
            defaults=defaults,
        )

    # ------------------------------------------------------------------- API
    @app.get("/api/status")
    def status():
        directory = _output_directory(current_config())
        with _lock:
            state = _current
            payload = state.snapshot() if state else _idle_payload()
        payload["reports"] = _list_reports(directory)
        return jsonify(payload)

    @app.get("/api/reports")
    def reports():
        return jsonify({"reports": _list_reports(_output_directory(current_config()))})

    @app.post("/api/run")
    def start_run():
        payload = request.get_json(silent=True) or {}
        try:
            config, output = build_config(current_config(), payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        state = RunState(id=uuid.uuid4().hex[:12], started_at=_timestamp())
        with _lock:
            global _current
            if _current is not None and _current.status == "running":
                return jsonify({"error": "A run is already in progress."}), 409
            _current = state

        thread = threading.Thread(
            target=_execute,
            args=(config, state, bool(payload.get("append")), output),
            name=f"job-bot-{state.id}",
            daemon=True,
        )
        thread.start()
        return jsonify(state.snapshot()), 202

    @app.get("/reports/<path:filename>")
    def download(filename: str):
        directory = _output_directory(current_config())
        safe = Path(filename).name
        if safe != filename or not safe.lower().endswith(".xlsx"):
            abort(404)
        target = directory / safe
        if not target.is_file():
            abort(404)
        return send_from_directory(directory, safe, as_attachment=True)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "version": __version__})

    return app


# ------------------------------------------------------------------ run helpers
def build_config(base: dict, payload: dict) -> tuple[dict, Path | None]:
    """Apply the web form values to a loaded config.

    Returns ``(config, output_path)``; raises :class:`ValueError` for anything
    a user can fix in the form (unknown portal, bad limit, bad delay).
    """
    portal = str(payload.get("portal") or base.get("portal") or "all").strip()
    if portal not in PORTALS:
        raise ValueError(f"Unknown portal '{portal}'.")

    config = copy.deepcopy(base)
    config["portal"] = portal

    crawl = config.setdefault("crawl", {})
    try:
        limit = int(payload.get("limit", crawl.get("max_items", 50)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Maximum vacancies must be a whole number.") from exc
    if not 1 <= limit <= 500:
        raise ValueError("Maximum vacancies must be between 1 and 500.")
    crawl["max_items"] = limit
    crawl["fetch_details"] = bool(payload.get("fetch_details", True))

    delay_raw = payload.get("delay")
    if delay_raw not in (None, ""):
        try:
            delay = float(delay_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Delay must be a number.") from exc
        if not 0 <= delay <= 30:
            raise ValueError("Delay must be between 0 and 30 seconds.")
        crawl["delay_seconds"] = delay

    filters = config.setdefault("filters", {})
    countries = _split(payload.get("countries"))
    if any(value.lower() in {"none", "any", "all", "worldwide"} for value in countries):
        countries = []
    filters["countries"] = countries
    filters["keywords"] = _split(payload.get("keywords"))
    filters["match"] = "all" if str(payload.get("match", "any")).lower() == "all" else "any"

    append = bool(payload.get("append"))
    filename = str(payload.get("filename") or "").strip()
    if append and not filename:
        filename = DEFAULT_APPEND_FILENAME

    output = None
    if filename:
        directory = _output_directory(config)
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / _safe_filename(filename)
    return config, output


def _execute(
    config: dict,
    state: RunState,
    append: bool,
    output: Path | None,
) -> None:
    """Run the bot in the worker thread and publish the outcome."""
    logger = logging.getLogger(f"rpa.jobs.web.{state.id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = _RunLogHandler(state)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
    logger.addHandler(console)

    def progress(index: int, total: int, title: str) -> None:
        with _lock:
            state.phase = "processing"
            state.completed = index
            state.total = total or state.total
            state.current = title

    try:
        state.phase = "discovering"
        bot = JobBot(
            config,
            logger=logger,
            progress=progress,
            append=append,
            output=output,
        )
        result = bot.run()
        with _lock:
            state.result = serialize_result(result)
            state.status = "finished"
            state.phase = "finished"
            state.total = state.total or state.result["total_rows"]
            state.completed = state.total
            state.current = ""
            state.finished_at = _timestamp()
    except Exception as exc:  # noqa: BLE001 - surfaced to the browser
        logger.error("Run failed: %s", exc, exc_info=True)
        with _lock:
            state.status = "failed"
            state.phase = "failed"
            state.error = str(exc) or exc.__class__.__name__
            state.finished_at = _timestamp()
    finally:
        logger.removeHandler(handler)
        logger.removeHandler(console)


def serialize_result(result: RunResult) -> dict[str, Any]:
    """JSON-friendly view of a finished :class:`RunResult`."""
    output = result.output_path
    name = output.name if output else ""
    sources = Counter(job.portal for job in result.jobs)
    jobs = [
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "work_mode": job.work_mode,
            "employment_type": job.employment_type,
            "salary": job.salary,
            "posted_date": job.posted_date,
            "category": job.category,
            "portal": job.portal,
            "apply_url": job.apply_url or job.source_url,
        }
        for job in result.jobs[:MAX_PREVIEW_ROWS]
    ]
    return {
        "portal": result.portal,
        "portal_label": result.portal_label,
        "countries": list(result.countries),
        "keywords": list(result.keywords),
        "discovered": result.discovered,
        "successful": result.successful,
        "skipped": result.skipped,
        "filtered": result.filtered,
        "filtered_location": result.filtered_location,
        "failed": result.failed,
        "carried_over": result.carried_over,
        "total_rows": len(result.jobs),
        "duration_seconds": result.duration_seconds,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "output": name,
        "download_url": f"/reports/{quote(name)}" if name else "",
        "sources": dict(sources.most_common()),
        "jobs": jobs,
        "preview_truncated": len(result.jobs) > MAX_PREVIEW_ROWS,
    }


# --------------------------------------------------------------------- helpers
def _idle_payload() -> dict[str, Any]:
    return {
        "id": "",
        "status": "idle",
        "phase": "idle",
        "started_at": "",
        "finished_at": "",
        "total": 0,
        "completed": 0,
        "current": "",
        "logs": [],
        "result": None,
        "error": "",
    }


def _output_directory(config: dict) -> Path:
    directory = Path((config.get("output") or {}).get("directory", "output"))
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    return directory.resolve()


def _list_reports(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    files = sorted(
        directory.glob("*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:12]
    reports = []
    for path in files:
        stat = path.stat()
        reports.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "download_url": f"/reports/{quote(path.name)}",
            }
        )
    return reports


def _safe_filename(raw: str) -> str:
    name = Path(raw.replace("\\", "/")).name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "report.xlsx"
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    return name


def _split(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = str(value or "").replace(";", ",").split(",")
    return [item.strip() for item in raw_items if item.strip()]


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
