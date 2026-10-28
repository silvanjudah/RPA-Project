"""Tests for the local web interface (Flask test client, no network)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from rpa_jobs import webapp
from rpa_jobs.config import load_config
from rpa_jobs.models import JobPosting
from rpa_jobs.pipeline import RunResult


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    config = load_config()
    config["output"]["directory"] = str(tmp_path)
    config["crawl"]["delay_seconds"] = 0
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture()
def app(config_path: Path, monkeypatch):
    monkeypatch.setattr(webapp, "_current", None)
    application = webapp.create_app(config_path)
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def sample_result(output: Path) -> RunResult:
    job = JobPosting(
        portal="hasjob",
        title="Backend Engineer",
        company="Acme",
        location="Bangalore",
        location_country="India",
        work_mode="On-site",
        employment_type="Full-time",
        posted_date="2026-10-24",
        apply_url="https://hasjob.co/acme/backend",
        source_url="https://hasjob.co/acme/backend",
    )
    return RunResult(
        portal="hasjob",
        portal_label="Hasjob (India, live Atom feed)",
        jobs=[job],
        discovered=1,
        successful=1,
        started_at="2026-10-24T10:00:00+00:00",
        finished_at="2026-10-24T10:00:01+00:00",
        duration_seconds=0.01,
        output_path=output,
        countries=["India"],
        keywords=[],
    )


class StubBot:
    """Stand-in for JobBot: records the call, writes a small report file."""

    last_config: dict | None = None

    def __init__(self, config, *, logger=None, progress=None, append=False, output=None):
        self.config = config
        self.logger = logger
        self.progress = progress
        self.output = Path(output) if output else Path(config["output"]["directory"]) / "stub.xlsx"
        StubBot.last_config = config

    def run(self) -> RunResult:
        if self.logger:
            self.logger.info("[INIT] Target portal: Stub")
        if self.progress:
            self.progress(1, 1, "Backend Engineer")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_bytes(b"PK\x03\x04stub workbook")
        return sample_result(self.output)


def test_index_renders_run_form(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Run configuration" in body
    assert "Country filter" in body
    assert "India" in body
    assert "Report library" in body


def test_unknown_portal_is_rejected(client):
    response = client.post("/api/run", json={"portal": "no-such-board"})
    assert response.status_code == 400
    assert "Unknown portal" in response.get_json()["error"]


def test_invalid_limit_is_rejected(client):
    response = client.post("/api/run", json={"portal": "hasjob", "limit": 0})
    assert response.status_code == 400
    assert "between 1 and 500" in response.get_json()["error"]


def test_build_config_applies_filters_and_filename(tmp_path):
    base = load_config()
    base["output"]["directory"] = str(tmp_path)

    config, output = webapp.build_config(
        base,
        {
            "portal": "himalayas",
            "limit": 25,
            "countries": "India, none",
            "keywords": "python, django",
            "match": "all",
            "fetch_details": False,
            "delay": "0",
        },
    )

    assert config["portal"] == "himalayas"
    assert config["crawl"]["max_items"] == 25
    assert config["crawl"]["fetch_details"] is False
    assert config["filters"]["countries"] == []  # "none" clears the filter
    assert config["filters"]["keywords"] == ["python", "django"]
    assert config["filters"]["match"] == "all"
    assert output is None

    _, output = webapp.build_config(
        base,
        {"portal": "hasjob", "append": True, "filename": "../../evil name.xlsx"},
    )
    assert output is not None
    assert output.parent == tmp_path
    assert output.name == "evil_name.xlsx"

    _, output = webapp.build_config(base, {"portal": "hasjob", "append": True})
    assert output is not None
    assert output.name == webapp.DEFAULT_APPEND_FILENAME


def test_run_reports_progress_result_and_download(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JobBot", StubBot)
    reports_dir = tmp_path

    response = client.post(
        "/api/run",
        json={"portal": "hasjob", "limit": 5, "countries": "India"},
    )
    assert response.status_code == 202
    run_id = response.get_json()["id"]

    deadline = time.time() + 5
    payload = {}
    while time.time() < deadline:
        payload = client.get("/api/status").get_json()
        if payload["status"] != "running":
            break
        time.sleep(0.02)

    assert payload["status"] == "finished", payload
    assert payload["id"] == run_id
    assert payload["completed"] == 1
    result = payload["result"]
    assert result["total_rows"] == 1
    assert result["jobs"][0]["title"] == "Backend Engineer"
    assert result["sources"] == {"hasjob": 1}
    assert result["download_url"].startswith("/reports/")
    assert any("Target portal" in entry["message"] for entry in payload["logs"])
    assert payload["reports"], "finished run should be listed"

    download = client.get(result["download_url"])
    assert download.status_code == 200
    assert download.data.startswith(b"PK")

    # A second start while one is running is refused.
    monkeypatch.setattr(webapp, "_current", webapp.RunState(id="busy", status="running"))
    busy = client.post("/api/run", json={"portal": "hasjob"})
    assert busy.status_code == 409


def test_download_rejects_unknown_and_non_report_paths(client, tmp_path):
    assert client.get("/reports/missing.xlsx").status_code == 404
    assert client.get("/reports/notes.txt").status_code == 404
    (tmp_path / "job_vacancies_hasjob_20260101_000000.xlsx").write_bytes(b"PK\x03\x04")
    ok = client.get("/reports/job_vacancies_hasjob_20260101_000000.xlsx")
    assert ok.status_code == 200


def test_status_is_idle_before_any_run(client):
    payload = client.get("/api/status").get_json()
    assert payload["status"] == "idle"
    assert payload["logs"] == []
    assert payload["reports"] == []
