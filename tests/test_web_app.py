"""Tests for web/app.py and the batch frontend contract."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web.app as web_app


class _NoopThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return None


class TestFormatCustomPeriod:
    def test_same_year(self):
        result = web_app.format_custom_period("2026-02-01", "2026-02-15")
        assert "Feb" in result
        assert "2026" in result
        # Should only show year once
        assert result.count("2026") == 1

    def test_cross_year(self):
        result = web_app.format_custom_period("2025-12-15", "2026-01-15")
        assert "2025" in result
        assert "2026" in result

    def test_invalid_date(self):
        result = web_app.format_custom_period("not-a-date", "also-not")
        assert "not-a-date" in result
        assert "also-not" in result

    def test_same_day(self):
        result = web_app.format_custom_period("2026-03-01", "2026-03-01")
        assert "Mar" in result


class TestBatchEndpoints:
    def test_radio_batch_respects_selected_artists(self, monkeypatch):
        monkeypatch.setattr(web_app.threading, "Thread", _NoopThread)
        web_app.jobs.clear()

        with web_app.app.test_client() as client:
            resp = client.post(
                "/api/radio/soundcharts/batch",
                json={
                    "mode": "week",
                    "week": "2026-03-01",
                    "region": "latam",
                    "time_range": "28d",
                    "artists": ["Shakira", "Karol G"],
                },
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["artist_jobs"] == [
            {"artist": "Shakira", "index": 0},
            {"artist": "Karol G", "index": 1},
        ]
        assert [entry["artist"] for entry in web_app.jobs[data["batch_id"]]["artist_statuses"]] == [
            "Shakira",
            "Karol G",
        ]

    def test_press_batch_respects_selected_artists(self, monkeypatch):
        monkeypatch.setattr(web_app.threading, "Thread", _NoopThread)
        web_app.jobs.clear()

        with web_app.app.test_client() as client:
            resp = client.post(
                "/api/press/run",
                json={
                    "mode": "week",
                    "week": "2026-03-01",
                    "days": 28,
                    "artists": ["Nathy Peluso", "Danna"],
                },
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["artist_jobs"] == [
            {"artist": "Nathy Peluso", "index": 0},
            {"artist": "Danna", "index": 1},
        ]
        assert [entry["artist"] for entry in web_app.jobs[data["batch_id"]]["artist_statuses"]] == [
            "Nathy Peluso",
            "Danna",
        ]


class TestJobStatusEndpoint:
    def test_status_exposes_phase_text_and_opt_in_progress(self):
        web_app.jobs.clear()
        job_id = web_app.new_job()
        web_app.log_line(job_id, "Scanning feeds...")
        web_app.jobs[job_id]["progress"] = 42
        web_app.jobs[job_id]["determinate_progress"] = True

        with web_app.app.test_client() as client:
            resp = client.get(f"/api/status/{job_id}")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_step"] == "Scanning feeds..."
        assert data["progress"] == 42
        assert data["determinate_progress"] is True


class TestBatchFrontendContract:
    def test_batch_flows_normalize_batch_id_in_app_js(self):
        js = (Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "app.js").read_text()

        assert js.count("const runId = data.batch_id || data.job_id;") >= 4
        assert "const startedJobId = data?.batch_id || data?.job_id;" in js
        assert re.search(r"pollJob\(runId, logEl, progressEl, resultEl", js)
        assert "/api/download/${runId}" in js

    def test_active_job_drawer_uses_backend_done_error_statuses(self):
        js = (Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "app.js").read_text()

        assert "if (data.status === 'done')" in js
        assert "if (data.status === 'error')" in js
        assert "if (data.status === 'completed')" not in js
        assert "if (data.status === 'failed')" not in js

    def test_active_job_drawer_defaults_to_indeterminate_progress(self):
        js = (Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "app.js").read_text()

        assert 'data?.determinate_progress !== true' in js
        assert 'job-item-progress is-indeterminate' in js
        assert 'status.classList.toggle(\'is-live\'' in js
        assert "return getLatestJobLogLine(data.log) || 'Working...';" in js
