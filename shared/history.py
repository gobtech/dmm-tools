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

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notes_artist
            ON notes(artist, timestamp);

        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            artist_source TEXT DEFAULT 'manual',
            artists TEXT DEFAULT '[]',
            mode TEXT DEFAULT 'snapshot',
            radio_region TEXT DEFAULT 'latam',
            radio_time_range TEXT DEFAULT '7d',
            include_radio INTEGER DEFAULT 1,
            include_dsp INTEGER DEFAULT 1,
            include_press INTEGER DEFAULT 1,
            cron_expression TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_at TEXT,
            last_run_status TEXT
        );

        CREATE TABLE IF NOT EXISTS schedule_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            total_artists INTEGER DEFAULT 0,
            artists_with_data INTEGER DEFAULT 0,
            artists_failed INTEGER DEFAULT 0,
            duration_seconds REAL,
            details TEXT DEFAULT '{}',
            error TEXT,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id)
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_runs
            ON schedule_runs(schedule_id, started_at);

        CREATE TABLE IF NOT EXISTS artist_google_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist_name TEXT NOT NULL,
            artist_name_normalized TEXT NOT NULL,
            doc_url TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            bookmark_index INTEGER DEFAULT NULL,
            insertion_confirmed INTEGER DEFAULT 0,
            linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_appended_at TIMESTAMP DEFAULT NULL,
            last_append_status TEXT DEFAULT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_artist_docs_normalized
            ON artist_google_docs(artist_name_normalized);
    """)

    # Migration: add auto_append_gdocs column to schedules if missing
    try:
        conn.execute("SELECT auto_append_gdocs FROM schedules LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE schedules ADD COLUMN auto_append_gdocs INTEGER DEFAULT 0")

    # Migration: add undo tracking columns to artist_google_docs
    for col, default in [
        ('last_insert_start', 'NULL'),
        ('last_insert_end', 'NULL'),
        ('last_insert_doc_id', 'NULL'),
        ('last_insert_at', 'NULL'),
    ]:
        try:
            conn.execute(f"SELECT {col} FROM artist_google_docs LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE artist_google_docs ADD COLUMN {col} DEFAULT {default}")

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


# ── Campaign Notes ──

def add_note(artist, text):
    """Add a campaign note for an artist."""
    init_db()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO notes (artist, timestamp, text) VALUES (?, ?, ?)",
        (artist.strip(), datetime.utcnow().isoformat(), text.strip()),
    )
    conn.commit()
    conn.close()


def get_notes(artist):
    """Get all notes for an artist, newest first."""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, timestamp, text FROM notes WHERE artist = ? ORDER BY timestamp DESC",
        (artist.strip(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_note(note_id):
    """Delete a note by ID."""
    init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()


# ── Schedules ──

def get_all_schedules():
    init_db()
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM schedules ORDER BY name").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['artists'] = json.loads(d['artists'])
        d['enabled'] = bool(d['enabled'])
        d['include_radio'] = bool(d['include_radio'])
        d['include_dsp'] = bool(d['include_dsp'])
        d['include_press'] = bool(d['include_press'])
        d['auto_append_gdocs'] = bool(d.get('auto_append_gdocs', 0))
        result.append(d)
    return result


def get_schedule(schedule_id):
    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d['artists'] = json.loads(d['artists'])
    d['enabled'] = bool(d['enabled'])
    d['include_radio'] = bool(d['include_radio'])
    d['include_dsp'] = bool(d['include_dsp'])
    d['include_press'] = bool(d['include_press'])
    d['auto_append_gdocs'] = bool(d.get('auto_append_gdocs', 0))
    return d


def save_schedule(data):
    init_db()
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    cur = conn.execute("""
        INSERT INTO schedules (name, artist_source, artists, mode,
            radio_region, radio_time_range, include_radio, include_dsp, include_press,
            cron_expression, enabled, auto_append_gdocs, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get('name', 'Untitled'),
        data.get('artist_source', 'manual'),
        json.dumps(data.get('artists', [])),
        data.get('mode', 'snapshot'),
        data.get('radio_region', 'latam'),
        data.get('radio_time_range', '7d'),
        int(data.get('include_radio', True)),
        int(data.get('include_dsp', True)),
        int(data.get('include_press', True)),
        data['cron_expression'],
        int(data.get('enabled', True)),
        int(data.get('auto_append_gdocs', False)),
        now, now,
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_schedule(schedule_id, data):
    init_db()
    allowed = {
        'name', 'artist_source', 'artists', 'mode',
        'radio_region', 'radio_time_range',
        'include_radio', 'include_dsp', 'include_press',
        'cron_expression', 'enabled', 'auto_append_gdocs',
    }
    sets = []
    vals = []
    for k, v in data.items():
        if k not in allowed:
            continue
        if k == 'artists':
            v = json.dumps(v)
        elif k in ('include_radio', 'include_dsp', 'include_press', 'enabled', 'auto_append_gdocs'):
            v = int(v)
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return
    sets.append("updated_at = ?")
    vals.append(datetime.utcnow().isoformat())
    vals.append(schedule_id)
    conn = _get_conn()
    conn.execute(f"UPDATE schedules SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def delete_schedule(schedule_id):
    init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,))
    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def save_schedule_run(schedule_id, total_artists):
    init_db()
    conn = _get_conn()
    cur = conn.execute("""
        INSERT INTO schedule_runs (schedule_id, started_at, total_artists)
        VALUES (?, ?, ?)
    """, (schedule_id, datetime.utcnow().isoformat(), total_artists))
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def update_schedule_run(run_id, **kwargs):
    init_db()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k == 'details':
            v = json.dumps(v)
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return
    vals.append(run_id)
    conn = _get_conn()
    conn.execute(f"UPDATE schedule_runs SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def get_schedule_runs(schedule_id=None, limit=50):
    init_db()
    conn = _get_conn()
    if schedule_id:
        rows = conn.execute(
            "SELECT * FROM schedule_runs WHERE schedule_id = ? ORDER BY started_at DESC LIMIT ?",
            (schedule_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM schedule_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['details'] = json.loads(d['details'])
        result.append(d)
    return result


def mark_stale_runs():
    init_db()
    conn = _get_conn()
    conn.execute(
        "UPDATE schedule_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
        (datetime.utcnow().isoformat(),),
    )
    conn.commit()
    conn.close()


def update_schedule_last_run(schedule_id, status):
    init_db()
    conn = _get_conn()
    conn.execute(
        "UPDATE schedules SET last_run_at = ?, last_run_status = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), status, schedule_id),
    )
    conn.commit()
    conn.close()


# ── Google Docs Mapping ──

def _normalize_artist(name):
    """Normalize artist name for matching: lowercase, strip accents and non-alnum."""
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', name.lower().strip())
    return ''.join(c for c in nfkd if not unicodedata.combining(c) and (c.isalnum() or c == ' ')).strip()


def _extract_doc_id(url):
    """Extract Google Doc ID from a URL like https://docs.google.com/document/d/{ID}/..."""
    import re
    m = re.search(r'/document/d/([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else None


def get_artist_doc(artist_name):
    """Get the linked Google Doc for an artist, or None."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM artist_google_docs WHERE artist_name_normalized = ?",
        (_normalize_artist(artist_name),),
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d['insertion_confirmed'] = bool(d['insertion_confirmed'])
        return d
    return None


def save_artist_doc(artist_name, doc_url, doc_id=None):
    """Link a Google Doc to an artist. Insert or update."""
    init_db()
    if doc_id is None:
        doc_id = _extract_doc_id(doc_url)
    if not doc_id:
        raise ValueError(f"Could not extract doc ID from URL: {doc_url}")

    normalized = _normalize_artist(artist_name)
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM artist_google_docs WHERE artist_name_normalized = ?",
        (normalized,),
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE artist_google_docs
            SET doc_url = ?, doc_id = ?, artist_name = ?,
                bookmark_index = NULL, insertion_confirmed = 0,
                linked_at = CURRENT_TIMESTAMP
            WHERE artist_name_normalized = ?
        """, (doc_url, doc_id, artist_name.strip(), normalized))
    else:
        conn.execute("""
            INSERT INTO artist_google_docs
                (artist_name, artist_name_normalized, doc_url, doc_id)
            VALUES (?, ?, ?, ?)
        """, (artist_name.strip(), normalized, doc_url, doc_id))

    conn.commit()
    conn.close()


def update_artist_doc_bookmark(artist_name, bookmark_index):
    """Store the insertion point index for an artist's doc."""
    init_db()
    conn = _get_conn()
    conn.execute(
        "UPDATE artist_google_docs SET bookmark_index = ? WHERE artist_name_normalized = ?",
        (bookmark_index, _normalize_artist(artist_name)),
    )
    conn.commit()
    conn.close()


def confirm_artist_doc_insertion(artist_name):
    """Set insertion_confirmed = 1 for an artist's doc."""
    init_db()
    conn = _get_conn()
    conn.execute(
        "UPDATE artist_google_docs SET insertion_confirmed = 1 WHERE artist_name_normalized = ?",
        (_normalize_artist(artist_name),),
    )
    conn.commit()
    conn.close()


def update_artist_doc_append_status(artist_name, status):
    """Update last_appended_at and last_append_status."""
    init_db()
    conn = _get_conn()
    conn.execute("""
        UPDATE artist_google_docs
        SET last_appended_at = ?, last_append_status = ?
        WHERE artist_name_normalized = ?
    """, (datetime.utcnow().isoformat(), status, _normalize_artist(artist_name)))
    conn.commit()
    conn.close()


def get_all_artist_docs():
    """Return all linked artist-doc mappings."""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM artist_google_docs ORDER BY artist_name"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['insertion_confirmed'] = bool(d['insertion_confirmed'])
        result.append(d)
    return result


def delete_artist_doc(artist_name):
    """Remove an artist's Google Doc mapping."""
    init_db()
    conn = _get_conn()
    conn.execute(
        "DELETE FROM artist_google_docs WHERE artist_name_normalized = ?",
        (_normalize_artist(artist_name),),
    )
    conn.commit()
    conn.close()


def save_artist_doc_undo(artist_name, doc_id, insert_start, insert_end):
    """Store the range of the last append for undo support. Expires after 24h."""
    init_db()
    conn = _get_conn()
    conn.execute("""
        UPDATE artist_google_docs
        SET last_insert_start = ?, last_insert_end = ?,
            last_insert_doc_id = ?, last_insert_at = ?
        WHERE artist_name_normalized = ?
    """, (insert_start, insert_end, doc_id,
          datetime.utcnow().isoformat(), _normalize_artist(artist_name)))
    conn.commit()
    conn.close()


def get_artist_doc_undo(artist_name):
    """Get undo data for an artist's last append, or None if expired/absent."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT last_insert_start, last_insert_end, last_insert_doc_id, last_insert_at "
        "FROM artist_google_docs WHERE artist_name_normalized = ?",
        (_normalize_artist(artist_name),),
    ).fetchone()
    conn.close()
    if not row or not row['last_insert_start']:
        return None
    # Check 24h expiry
    try:
        inserted = datetime.fromisoformat(row['last_insert_at'])
        if (datetime.utcnow() - inserted).total_seconds() > 86400:
            return None
    except (ValueError, TypeError):
        return None
    return {
        'start': row['last_insert_start'],
        'end': row['last_insert_end'],
        'doc_id': row['last_insert_doc_id'],
        'inserted_at': row['last_insert_at'],
    }


def clear_artist_doc_undo(artist_name):
    """Clear undo data after a successful undo."""
    init_db()
    conn = _get_conn()
    conn.execute("""
        UPDATE artist_google_docs
        SET last_insert_start = NULL, last_insert_end = NULL,
            last_insert_doc_id = NULL, last_insert_at = NULL
        WHERE artist_name_normalized = ?
    """, (_normalize_artist(artist_name),))
    conn.commit()
    conn.close()
