"""Tests for shared/history.py — SQLite CRUD operations."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared.history as history


# ── init_db ──

class TestInitDb:
    def test_creates_tables(self, tmp_history_db):
        history.init_db()
        conn = sqlite3.connect(str(tmp_history_db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "snapshots" in tables
        assert "notes" in tables

    def test_idempotent(self, tmp_history_db):
        history.init_db()
        history.init_db()  # Should not raise


# ── save_snapshot ──

class TestSaveSnapshot:
    def test_minimal_snapshot(self, tmp_history_db):
        history.save_snapshot("Test Artist")
        snap = history.get_latest_snapshot("Test Artist")
        assert snap is not None
        assert snap["artist"] == "Test Artist"
        assert snap["radio_total"] == 0
        assert snap["press_total"] == 0
        assert snap["dsp_total"] == 0

    def test_with_radio_data(self, tmp_history_db):
        radio = [
            {"country": "MEXICO", "station": "Radio Uno", "song": "Hit Song", "weekly_plays": 10},
            {"country": "MEXICO", "station": "Radio Dos", "song": "Hit Song", "weekly_plays": 5},
            {"country": "ARGENTINA", "station": "Radio Tres", "song": "Hit Song", "weekly_plays": 3},
        ]
        history.save_snapshot("Radio Artist", radio_data=radio)
        snap = history.get_latest_snapshot("Radio Artist")
        assert snap["radio_total"] == 18
        assert snap["radio_countries"] == 2
        assert snap["radio_stations"] == 3

    def test_with_press_data(self, tmp_history_db):
        press = {
            "MEXICO": [
                {"media_name": "Outlet A", "url": "https://a.com", "in_database": True, "title": "T"},
                {"media_name": "Outlet B", "url": "https://b.com", "in_database": False, "title": "T2"},
            ],
            "ARGENTINA": [
                {"media_name": "Outlet C", "url": "https://c.com", "in_database": True, "title": "T3"},
            ],
        }
        history.save_snapshot("Press Artist", press_data=press)
        snap = history.get_latest_snapshot("Press Artist")
        assert snap["press_total"] == 3
        assert snap["press_countries"] == 2
        assert snap["press_db_hits"] == 2

    def test_aggregation_correctness(self, tmp_history_db):
        dsp = {
            "release1": {
                "track1": [
                    {"platform": "Spotify", "playlist_name": "PL1", "playlist_followers": "1000", "position": 1, "playlist_track": "T"},
                    {"platform": "Deezer", "playlist_name": "PL2", "playlist_followers": "500", "position": 2, "playlist_track": "T"},
                ],
            },
        }
        history.save_snapshot("DSP Artist", dsp_data=dsp)
        snap = history.get_latest_snapshot("DSP Artist")
        assert snap["dsp_total"] == 2
        assert snap["dsp_platforms"] == 2


# ── get_artists ──

class TestGetArtists:
    def test_multiple_artists(self, tmp_history_db):
        history.save_snapshot("Artist A")
        history.save_snapshot("Artist B")
        artists = history.get_artists()
        names = [a["artist"] for a in artists]
        assert "Artist A" in names
        assert "Artist B" in names

    def test_empty_db(self, tmp_history_db):
        assert history.get_artists() == []


# ── get_artist_history ──

class TestGetArtistHistory:
    def test_returns_snapshots(self, tmp_history_db):
        history.save_snapshot("Hist Artist")
        history.save_snapshot("Hist Artist")
        result = history.get_artist_history("Hist Artist")
        assert len(result) == 2

    def test_json_fields_parsed(self, tmp_history_db):
        history.save_snapshot("JSON Artist")
        result = history.get_artist_history("JSON Artist")
        assert isinstance(result[0]["radio_by_country"], dict)
        assert isinstance(result[0]["radio_top"], list)


# ── get_latest_snapshot ──

class TestGetLatestSnapshot:
    def test_returns_newest(self, tmp_history_db):
        radio1 = [{"country": "MX", "station": "S1", "song": "Song", "weekly_plays": 1}]
        radio2 = [{"country": "MX", "station": "S1", "song": "Song", "weekly_plays": 99}]
        history.save_snapshot("Latest Artist", radio_data=radio1)
        history.save_snapshot("Latest Artist", radio_data=radio2)
        snap = history.get_latest_snapshot("Latest Artist")
        assert snap["radio_total"] == 99

    def test_unknown_artist_returns_none(self, tmp_history_db):
        assert history.get_latest_snapshot("Nonexistent Artist") is None


# ── Notes CRUD ──

class TestNotes:
    def test_add_and_get(self, tmp_history_db):
        history.add_note("Note Artist", "First note")
        notes = history.get_notes("Note Artist")
        assert len(notes) == 1
        assert notes[0]["text"] == "First note"

    def test_newest_first_ordering(self, tmp_history_db):
        history.add_note("Order Artist", "First")
        history.add_note("Order Artist", "Second")
        notes = history.get_notes("Order Artist")
        assert notes[0]["text"] == "Second"
        assert notes[1]["text"] == "First"

    def test_delete_note(self, tmp_history_db):
        history.add_note("Del Artist", "To delete")
        notes = history.get_notes("Del Artist")
        history.delete_note(notes[0]["id"])
        assert history.get_notes("Del Artist") == []
