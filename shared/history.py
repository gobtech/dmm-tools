"""
Historical data storage for Artist Dashboard.
Uses SQLite to store snapshots of radio/press/DSP data over time.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'history.db'


def _get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            source TEXT DEFAULT 'manual',

            radio_total INTEGER DEFAULT 0,
            radio_countries INTEGER DEFAULT 0,
            radio_stations INTEGER DEFAULT 0,
            press_total INTEGER DEFAULT 0,
            press_countries INTEGER DEFAULT 0,
            press_db_hits INTEGER DEFAULT 0,
            dsp_total INTEGER DEFAULT 0,
            dsp_platforms INTEGER DEFAULT 0,

            radio_by_country TEXT DEFAULT '{}',
            press_by_country TEXT DEFAULT '{}',
            dsp_by_platform TEXT DEFAULT '{}',

            radio_top TEXT DEFAULT '[]',
            press_top TEXT DEFAULT '[]',
            dsp_top TEXT DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_artist
            ON snapshots(artist, timestamp);
    """)
    conn.commit()
    conn.close()


def save_snapshot(artist, radio_data=None, press_data=None, dsp_data=None,
                  play_key='weekly_plays', source='tool'):
    """Save a data snapshot for an artist."""
    init_db()

    # ── Process radio ──
    radio_total = 0
    radio_countries = {}
    radio_stations = set()
    radio_top = []

    if radio_data:
        for entry in radio_data:
            country = entry.get('country', 'UNKNOWN')
            station = entry.get('station', '')
            plays = entry.get(play_key, 0) or 0
            if not plays:
                continue
            radio_total += plays
            radio_countries[country] = radio_countries.get(country, 0) + plays
            radio_stations.add(station)
            radio_top.append({
                'station': station,
                'country': country,
                'song': entry.get('song', ''),
                'plays': plays,
            })
        radio_top.sort(key=lambda x: -x['plays'])
        radio_top = radio_top[:20]

    # ── Process press ──
    press_total = 0
    press_countries = {}
    press_db_hits = 0
    press_top = []

    if press_data:
        for country, entries in press_data.items():
            press_countries[country] = len(entries)
            press_total += len(entries)
            for e in entries:
                if e.get('in_database'):
                    press_db_hits += 1
                press_top.append({
                    'name': e.get('media_name', ''),
                    'country': country,
                    'title': e.get('title', ''),
                    'url': e.get('url', ''),
                    'in_db': bool(e.get('in_database')),
                })
        press_top = press_top[:20]

    # ── Process DSP ──
    dsp_total = 0
    dsp_platforms = {}
    dsp_top = []

    if dsp_data:
        for release_dict in dsp_data.values():
            for matches in release_dict.values():
                for m in matches:
                    platform = m.get('platform', '?')
                    dsp_platforms[platform] = dsp_platforms.get(platform, 0) + 1
                    dsp_total += 1
                    dsp_top.append({
                        'playlist': m.get('playlist_name', ''),
                        'platform': platform,
                        'followers': m.get('playlist_followers', ''),
                        'position': m.get('position', '?'),
                        'track': m.get('playlist_track', ''),
                    })
        dsp_top = dsp_top[:20]

    conn = _get_conn()
    conn.execute("""
        INSERT INTO snapshots (
            artist, timestamp, source,
            radio_total, radio_countries, radio_stations,
            press_total, press_countries, press_db_hits,
            dsp_total, dsp_platforms,
            radio_by_country, press_by_country, dsp_by_platform,
            radio_top, press_top, dsp_top
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        artist.strip(),
        datetime.utcnow().isoformat(),
        source,
        radio_total,
        len(radio_countries),
        len(radio_stations),
        press_total,
        len(press_countries),
        press_db_hits,
        dsp_total,
        len(dsp_platforms),
        json.dumps(radio_countries),
        json.dumps(press_countries),
        json.dumps(dsp_platforms),
        json.dumps(radio_top),
        json.dumps(press_top),
        json.dumps(dsp_top),
    ))
    conn.commit()
    conn.close()


def get_artists():
    """List all artists that have at least one snapshot."""
    init_db()
    conn = _get_conn()
    rows = conn.execute("""
        SELECT artist, COUNT(*) as snapshots,
               MAX(timestamp) as latest,
               MIN(timestamp) as first
        FROM snapshots
        GROUP BY artist
        ORDER BY latest DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_artist_history(artist, days=180):
    """Get all snapshots for an artist within the last N days."""
    init_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM snapshots
        WHERE artist = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    """, (artist.strip(), cutoff)).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        for key in ('radio_by_country', 'press_by_country', 'dsp_by_platform',
                     'radio_top', 'press_top', 'dsp_top'):
            d[key] = json.loads(d[key])
        results.append(d)
    return results


def get_latest_snapshot(artist):
    """Get the most recent snapshot for an artist."""
    init_db()
    conn = _get_conn()
    row = conn.execute("""
        SELECT * FROM snapshots
        WHERE artist = ?
        ORDER BY timestamp DESC
        LIMIT 1
    """, (artist.strip(),)).fetchone()
    conn.close()

    if not row:
        return None
    d = dict(row)
    for key in ('radio_by_country', 'press_by_country', 'dsp_by_platform',
                 'radio_top', 'press_top', 'dsp_top'):
        d[key] = json.loads(d[key])
    return d
