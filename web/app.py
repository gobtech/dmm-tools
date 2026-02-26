#!/usr/bin/env python3
"""
DMM Tools — Web Frontend
Flask app serving a local UI for Radio Report, Press Pickup, and DSP Pickup.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

# Load .env (simple parser — no python-dotenv needed)
env_file = ROOT_DIR / '.env'
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            if '=' in line:
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)

from flask import Flask, request, jsonify, send_file, render_template, make_response

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------
jobs = {}  # { job_id: { status, log, result, output_path, error, ... } }

UPLOAD_DIR = Path(__file__).parent / 'uploads'
REPORT_DIR = ROOT_DIR / 'reports'
REPORT_DIR.mkdir(exist_ok=True)


def new_job():
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'status': 'running',
        'log': [],
        'result': None,
        'output_path': None,
        'error': None,
    }
    return job_id


def log_line(job_id, text):
    if job_id in jobs:
        jobs[job_id]['log'].append(text)


def finish_job(job_id, result=None, output_path=None, error=None):
    if job_id not in jobs:
        return
    jobs[job_id]['status'] = 'error' if error else 'done'
    jobs[job_id]['result'] = result
    jobs[job_id]['output_path'] = str(output_path) if output_path else None
    jobs[job_id]['error'] = error
    # Clean up uploads
    upload_dir = UPLOAD_DIR / job_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/api/status/<job_id>')
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({
        'status': job['status'],
        'log': job['log'],
        'result': job['result'],
        'error': job['error'],
        'has_file': job['output_path'] is not None,
        'proof_images': job.get('proof_images', []),
        'digest_html': job.get('digest_html', ''),
        'digest_text': job.get('digest_text', ''),
        'discovery_html': job.get('discovery_html', ''),
        'discovery_outlets': job.get('discovery_outlets', []),
        'pr_es_text': job.get('pr_es_text', ''),
        'pr_pt_text': job.get('pr_pt_text', ''),
        'pr_source_lang': job.get('pr_source_lang', ''),
        'pr_es_has_docx': bool(job.get('pr_es_docx_path')),
        'pr_pt_has_docx': bool(job.get('pr_pt_docx_path')),
    })


@app.route('/api/download/<job_id>')
def download(job_id):
    job = jobs.get(job_id)
    if not job or not job['output_path']:
        return jsonify({'error': 'No file available'}), 404
    p = Path(job['output_path'])
    if not p.exists():
        return jsonify({'error': 'File not found on disk'}), 404
    return send_file(str(p), as_attachment=True, download_name=p.name)


@app.route('/api/proof/<filename>')
def serve_proof(filename):
    """Serve a DSP proof image."""
    proof_dir = REPORT_DIR / 'dsp_proofs'
    p = proof_dir / filename
    if not p.exists() or '..' in filename:
        return jsonify({'error': 'Image not found'}), 404
    return send_file(str(p), mimetype='image/png')


@app.route('/api/proofs/zip')
def download_proofs_zip():
    """Download all proof images as a zip file."""
    import zipfile
    proof_dir = REPORT_DIR / 'dsp_proofs'
    if not proof_dir.exists():
        return jsonify({'error': 'No proof images available'}), 404
    images = sorted(proof_dir.glob('proof_*.png'))
    if not images:
        return jsonify({'error': 'No proof images available'}), 404
    zip_path = REPORT_DIR / 'dsp_proofs.zip'
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            zf.write(str(img), img.name)
    return send_file(str(zip_path), as_attachment=True, download_name='dsp_proofs.zip')


@app.route('/api/download/<job_id>/<filetype>')
def download_typed(job_id, filetype):
    """Download a specific output file type (txt, json, or docx) for jobs."""
    job = jobs.get(job_id)
    if not job or not job['output_path']:
        return jsonify({'error': 'No file available'}), 404
    base = Path(job['output_path'])
    if filetype == 'json':
        p = base.with_suffix('.json')
    elif filetype == 'docx':
        p = base.with_suffix('.docx')
    else:
        p = base
    if not p.exists():
        return jsonify({'error': 'File not found on disk'}), 404
    return send_file(str(p), as_attachment=True, download_name=p.name)


# ---------------------------------------------------------------------------
# Radio Report
# ---------------------------------------------------------------------------

@app.route('/api/radio/run', methods=['POST'])
def radio_run():
    artist = request.form.get('artist', '').strip()
    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400

    files = request.files.getlist('csvfiles')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'Please upload at least one CSV file.'}), 400

    job_id = new_job()

    # Save uploaded CSVs
    upload_dir = UPLOAD_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.filename:
            safe_name = f.filename.replace('..', '_').replace('/', '_')
            f.save(str(upload_dir / safe_name))

    safe_artist = artist.lower().replace(' ', '_')
    output_path = REPORT_DIR / f'{safe_artist}_radio.docx'

    def run():
        try:
            log_line(job_id, f'Starting radio report for {artist}...')
            cmd = [
                'node',
                str(ROOT_DIR / 'airplay-report' / 'generate_report.js'),
                '--artist', artist,
                '--input', str(upload_dir),
                '--output', str(output_path),
            ]
            log_line(job_id, f'Running: node generate_report.js --artist "{artist}"')
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(ROOT_DIR),
            )
            for line in proc.stdout:
                log_line(job_id, line.rstrip())
            proc.wait()
            if proc.returncode != 0:
                finish_job(job_id, error='Report generation failed. Check your CSV files.')
            elif output_path.exists():
                finish_job(job_id, result='Report generated successfully!', output_path=output_path)
            else:
                finish_job(job_id, error='Report file was not created. Check your CSV files have the right columns (Song, Station, 28D, Country).')
        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Radio Report — Soundcharts auto-fetch mode
# ---------------------------------------------------------------------------

@app.route('/api/radio/soundcharts', methods=['POST'])
def radio_soundcharts():
    data = request.get_json() or {}
    artist = data.get('artist', '').strip()
    region = data.get('region', 'latam').strip()  # 'latam' or 'all'
    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400

    job_id = new_job()

    safe_artist = artist.lower().replace(' ', '_')
    output_path = REPORT_DIR / f'{safe_artist}_radio.docx'

    def run():
        try:
            from shared.soundcharts import search_artist, fetch_airplay_data, airplay_to_csv, get_token

            token = get_token()
            if not token:
                finish_job(job_id, error='Soundcharts credentials not configured. Add SOUNDCHARTS_EMAIL and SOUNDCHARTS_PASSWORD to .env')
                return

            log_fn = lambda msg: log_line(job_id, msg)

            region_label = 'LATAM' if region == 'latam' else 'all countries'
            log_line(job_id, f'Searching Soundcharts for "{artist}" ({region_label})...')
            match = search_artist(artist, token=token)
            if not match:
                finish_job(job_id, error=f'Artist "{artist}" not found on Soundcharts.')
                return

            log_line(job_id, f'Found: {match["name"]} (UUID: {match["uuid"]})')
            log_line(job_id, f'Fetching airplay data ({region_label})...')

            airplay = fetch_airplay_data(match['uuid'], token, region=region if region != 'all' else None, log_fn=log_fn)
            if airplay is None:
                finish_job(job_id, error='Failed to fetch airplay data. Token may be expired.')
                return

            if not airplay:
                finish_job(job_id, error='No airplay data found for this artist.')
                return

            log_line(job_id, f'Total: {len(airplay)} station entries')

            # Write CSV for the report generator
            upload_dir = UPLOAD_DIR / job_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            csv_path = upload_dir / 'soundcharts_airplay.csv'
            airplay_to_csv(airplay, str(csv_path))
            log_line(job_id, f'Generated CSV with {len(airplay)} rows')

            # Run the existing Node.js report generator
            log_line(job_id, 'Generating Word document...')
            cmd = [
                'node',
                str(ROOT_DIR / 'airplay-report' / 'generate_report.js'),
                '--artist', artist,
                '--input', str(upload_dir),
                '--output', str(output_path),
                '--period', 'last 28 days',
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(ROOT_DIR),
            )
            for line in proc.stdout:
                log_line(job_id, line.rstrip())
            proc.wait()

            if proc.returncode != 0:
                finish_job(job_id, error='Report generation failed.')
            elif output_path.exists():
                finish_job(job_id, result='Report generated successfully!', output_path=output_path)
            else:
                finish_job(job_id, error='Report file was not created.')
        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Radio Report — Soundcharts two-step flow (fetch → pick songs → generate)
# ---------------------------------------------------------------------------

RANGE_MAP = {
    '7d':      ('weeklyPlaysCount',     'weekly_plays'),
    '7d_prev': ('lastWeeklyPlaysCount', 'prev_weekly_plays'),
    '28d':     ('monthlyPlaysCount',    'plays_28d'),
    '1y':      ('yearlyPlaysCount',     'yearly_plays'),
    'custom':  ('monthlyPlaysCount',    'plays_28d'),  # discovery still uses 28D sort
}

RANGE_LABELS = {
    '7d': '7D', '7d_prev': '7D-1', '28d': '28D', '1y': '1Y', 'custom': '28D ref',
}

RANGE_PERIOD_TITLES = {
    '7d': 'last 7 days', '7d_prev': 'previous 7 days', '28d': 'last 28 days', '1y': 'last year',
}


def format_custom_period(start_date, end_date):
    """Format custom date range as a human-readable period title, e.g. 'Feb 1 - Feb 15, 2026'."""
    from datetime import datetime
    try:
        s = datetime.strptime(start_date, '%Y-%m-%d')
        e = datetime.strptime(end_date, '%Y-%m-%d')
        if s.year == e.year:
            return f"{s.strftime('%b %-d')} - {e.strftime('%b %-d, %Y')}"
        return f"{s.strftime('%b %-d, %Y')} - {e.strftime('%b %-d, %Y')}"
    except (ValueError, TypeError):
        return f"{start_date} - {end_date}"


@app.route('/api/radio/soundcharts/fetch', methods=['POST'])
def radio_soundcharts_fetch():
    """Step 1: Fetch airplay data and return song summary for the picker."""
    data = request.get_json() or {}
    artist = data.get('artist', '').strip()
    region = data.get('region', 'latam').strip()
    time_range = data.get('time_range', '28d').strip()
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400
    if time_range == 'custom' and (not start_date or not end_date):
        return jsonify({'error': 'Please select both start and end dates.'}), 400

    sort_col, play_key = RANGE_MAP.get(time_range, RANGE_MAP['28d'])

    job_id = new_job()

    def run():
        try:
            from shared.soundcharts import search_artist, fetch_airplay_data, get_token

            token = get_token()
            if not token:
                finish_job(job_id, error='Soundcharts credentials not configured. Add SOUNDCHARTS_EMAIL and SOUNDCHARTS_PASSWORD to .env')
                return

            log_fn = lambda msg: log_line(job_id, msg)

            region_label = 'LATAM' if region == 'latam' else 'all countries'
            log_line(job_id, f'Searching Soundcharts for "{artist}" ({region_label})...')
            match = search_artist(artist, token=token)
            if not match:
                finish_job(job_id, error=f'Artist "{artist}" not found on Soundcharts.')
                return

            log_line(job_id, f'Found: {match["name"]} (UUID: {match["uuid"]})')
            log_line(job_id, f'Fetching airplay data ({region_label})...')

            airplay = fetch_airplay_data(match['uuid'], token, sort_by=sort_col, region=region if region != 'all' else None, log_fn=log_fn)
            if airplay is None:
                finish_job(job_id, error='Failed to fetch airplay data. Token may be expired.')
                return

            if not airplay:
                finish_job(job_id, error='No airplay data found for this artist.')
                return

            log_line(job_id, f'Total: {len(airplay)} station entries')

            # Cache the raw airplay data and chosen time range on the job
            jobs[job_id]['airplay_cache'] = airplay
            jobs[job_id]['time_range'] = time_range
            jobs[job_id]['region'] = region
            jobs[job_id]['start_date'] = start_date
            jobs[job_id]['end_date'] = end_date

            # Build song_uuid map (song_name → uuid) for custom range lookups
            song_uuids = {}
            for entry in airplay:
                name = entry.get('song', '')
                uid = entry.get('song_uuid', '')
                if name and uid and name not in song_uuids:
                    song_uuids[name] = uid
            jobs[job_id]['song_uuids'] = song_uuids

            # Aggregate unique songs with total plays + station count
            song_stats = {}
            for entry in airplay:
                name = entry['song']
                if not name:
                    continue
                if name not in song_stats:
                    song_stats[name] = {'song': name, 'total_plays': 0, 'station_count': 0}
                song_stats[name]['total_plays'] += entry[play_key]
                song_stats[name]['station_count'] += 1

            range_label = RANGE_LABELS.get(time_range, '28D')
            is_custom = time_range == 'custom'
            songs = sorted([s for s in song_stats.values() if s['total_plays'] > 0], key=lambda s: s['total_plays'], reverse=True)
            finish_job(job_id, result={'songs': songs, 'total_entries': len(airplay), 'range_label': range_label, 'is_custom': is_custom})

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/radio/soundcharts/generate', methods=['POST'])
def radio_soundcharts_generate():
    """Step 2: Filter cached airplay data to selected songs and generate report."""
    data = request.get_json() or {}
    fetch_job_id = data.get('fetch_job_id', '').strip()
    artist = data.get('artist', '').strip()
    selected_songs = data.get('selected_songs', [])
    time_range = data.get('time_range', '').strip()
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()

    if not fetch_job_id or fetch_job_id not in jobs or 'airplay_cache' not in jobs.get(fetch_job_id, {}):
        return jsonify({'error': 'Airplay data expired. Please fetch songs again.'}), 400
    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400
    if not selected_songs:
        return jsonify({'error': 'Please select at least one song.'}), 400

    # Use time_range from request, fall back to what was stored on the fetch job
    if not time_range:
        time_range = jobs[fetch_job_id].get('time_range', '28d')

    # For custom range, pull dates from request or fall back to fetch job cache
    if time_range == 'custom':
        if not start_date:
            start_date = jobs[fetch_job_id].get('start_date', '')
        if not end_date:
            end_date = jobs[fetch_job_id].get('end_date', '')
        if not start_date or not end_date:
            return jsonify({'error': 'Custom date range is missing. Please fetch songs again.'}), 400

    _, play_key = RANGE_MAP.get(time_range, RANGE_MAP['28d'])

    fetch_job = jobs[fetch_job_id]
    airplay = fetch_job['airplay_cache']
    # Use region from the original fetch job
    region = fetch_job.get('region', 'latam')
    selected_set = set(selected_songs)

    job_id = new_job()
    safe_artist = artist.lower().replace(' ', '_')
    output_path = REPORT_DIR / f'{safe_artist}_radio.docx'

    def run():
        try:
            from shared.soundcharts import airplay_to_csv

            if time_range == 'custom':
                # Custom range: fetch per-song data using SongBroadcastTopBroadcastPlayList
                from shared.soundcharts import fetch_song_custom_range, LATAM_CODES, get_token as _get_token

                token = _get_token()
                if not token:
                    finish_job(job_id, error='Soundcharts credentials not configured.')
                    return
                song_uuids = fetch_job.get('song_uuids', {})
                country_filter = LATAM_CODES if region == 'latam' else None

                log_fn = lambda msg: log_line(job_id, msg)
                filtered = []

                for song_name in selected_songs:
                    song_uuid = song_uuids.get(song_name)
                    if not song_uuid:
                        log_line(job_id, f'Warning: No UUID found for "{song_name}", skipping.')
                        continue

                    log_line(job_id, f'Fetching custom range data for "{song_name}" ({start_date} to {end_date})...')
                    items = fetch_song_custom_range(
                        song_uuid, token, start_date, end_date,
                        country_codes=country_filter, log_fn=log_fn,
                    )
                    if items is None:
                        finish_job(job_id, error='Failed to fetch custom range data. Token may be expired.')
                        return
                    log_line(job_id, f'  → {len(items)} stations, {sum(i["plays"] for i in items)} total plays')

                    for item in items:
                        filtered.append({
                            'song': song_name,
                            'station': item['station'],
                            'plays_28d': item['plays'],  # map to plays_28d for CSV compat
                            'country': item['country'],
                        })

                if not filtered:
                    finish_job(job_id, error='No airplay data found for the selected songs in this date range.')
                    return

                log_line(job_id, f'Total: {len(filtered)} station entries across {len(selected_songs)} song(s)')
            else:
                # Standard fixed range: filter from cached data
                filtered = [e for e in airplay if e['song'] in selected_set]
                if not filtered:
                    finish_job(job_id, error='No airplay data for the selected songs.')
                    return
                # Remap the chosen play field onto plays_28d for CSV compat
                for e in filtered:
                    e['plays_28d'] = e[play_key]
                log_line(job_id, f'Generating report for {len(selected_songs)} song(s) ({len(filtered)} station entries)...')

            # Write filtered CSV
            upload_dir = UPLOAD_DIR / job_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            csv_path = upload_dir / 'soundcharts_airplay.csv'
            airplay_to_csv(filtered, str(csv_path))
            log_line(job_id, f'Generated CSV with {len(filtered)} rows')

            # Run the existing Node.js report generator
            log_line(job_id, 'Generating Word document...')
            if time_range == 'custom':
                period_title = format_custom_period(start_date, end_date)
            else:
                period_title = RANGE_PERIOD_TITLES.get(time_range, 'last 28 days')
            cmd = [
                'node',
                str(ROOT_DIR / 'airplay-report' / 'generate_report.js'),
                '--artist', artist,
                '--input', str(upload_dir),
                '--output', str(output_path),
                '--period', period_title,
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(ROOT_DIR),
            )
            for line in proc.stdout:
                log_line(job_id, line.rstrip())
            proc.wait()

            if proc.returncode != 0:
                finish_job(job_id, error='Report generation failed.')
            elif output_path.exists():
                finish_job(job_id, result='Report generated successfully!', output_path=output_path)
            else:
                finish_job(job_id, error='Report file was not created.')
        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Press Pickup
# ---------------------------------------------------------------------------

@app.route('/api/press/run', methods=['POST'])
def press_run():
    data = request.get_json(silent=True) or {}
    artist = data.get('artist', '').strip()
    days = data.get('days', 28)

    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 28

    job_id = new_job()
    safe_artist = artist.lower().replace(' ', '_')
    output_path = REPORT_DIR / f'{safe_artist}_press.txt'

    def run():
        try:
            from importlib import import_module
            # Capture stdout from the press pickup module
            buf = io.StringIO()
            log_line(job_id, f'Searching for press coverage of {artist} (last {days} days)...')

            # Import and run
            spec_path = ROOT_DIR / 'press-pickup' / 'press_pickup.py'
            import importlib.util
            spec = importlib.util.spec_from_file_location('press_pickup', str(spec_path))
            mod = importlib.util.module_from_spec(spec)

            # Redirect stdout to capture progress
            old_stdout = sys.stdout
            sys.stdout = buf

            try:
                spec.loader.exec_module(mod)
                country_results = mod.run_press_pickup(artist, days, str(output_path))
            finally:
                sys.stdout = old_stdout

            # Send captured output to log
            for line in buf.getvalue().splitlines():
                log_line(job_id, line)

            # Build result text
            if not country_results:
                finish_job(job_id, result='No press coverage found for this artist in the selected time range.',
                           output_path=output_path if output_path.exists() else None)
                return

            # Read the generated report
            result_text = output_path.read_text(encoding='utf-8') if output_path.exists() else ''
            total = sum(len(v) for v in country_results.values())
            log_line(job_id, f'Found {total} results across {len(country_results)} countries.')
            finish_job(job_id, result=result_text, output_path=output_path if output_path.exists() else None)

        except SystemExit:
            finish_job(job_id, error='Press pickup failed unexpectedly.')
        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# DSP Pickup
# ---------------------------------------------------------------------------

@app.route('/api/dsp/run', methods=['POST'])
def dsp_run():
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'artist')  # artist | week | all
    artist = data.get('artist', '').strip()
    week = data.get('week', 'current').strip()
    spotify_only = data.get('spotify_only', False)

    if mode == 'artist' and not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400

    job_id = new_job()

    def run():
        try:
            from shared.database import load_playlist_database, load_release_schedule

            log_line(job_id, 'Loading playlist database...')
            pl_path = os.environ.get('PLAYLIST_DB_PATH', str(ROOT_DIR / 'data' / 'playlist_database.csv'))
            playlists = load_playlist_database(pl_path)
            log_line(job_id, f'  Loaded {len(playlists)} playlists')

            if spotify_only:
                playlists = [p for p in playlists if p['platform'] == 'Spotify']
                log_line(job_id, f'  Filtered to {len(playlists)} Spotify playlists')

            schedule_url = os.environ.get(
                'RELEASE_SCHEDULE_URL',
                'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
            )
            log_line(job_id, 'Loading release schedule...')
            releases = load_release_schedule(schedule_url)
            log_line(job_id, f'  Loaded {len(releases)} releases')

            # Filter releases
            if mode == 'artist':
                search_lower = artist.lower()
                releases = [r for r in releases if search_lower in r['artist'].lower() or r['artist'].lower() in search_lower]
                log_line(job_id, f'  Filtered to {len(releases)} releases for {artist}')
                safe_name = artist.lower().replace(' ', '_')
            elif mode == 'week':
                spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
                import importlib.util
                spec = importlib.util.spec_from_file_location('dsp_pickup_mod', str(spec_path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                releases = mod.filter_releases_by_week(releases, week or 'current')
                log_line(job_id, f'  Filtered to {len(releases)} releases for week of {week}')
                safe_name = f'week_{week}'
            else:
                safe_name = 'all_releases'

            if not releases:
                finish_job(job_id, result='No releases found matching your criteria.')
                return

            output_path = REPORT_DIR / f'{safe_name}_dsp.txt'

            # Clear previous proof images
            proof_dir = REPORT_DIR / 'dsp_proofs'
            if proof_dir.exists():
                shutil.rmtree(proof_dir, ignore_errors=True)

            # Capture stdout
            buf = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = buf

            try:
                spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
                import importlib.util
                spec = importlib.util.spec_from_file_location('dsp_pickup_run', str(spec_path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                results = mod.run_dsp_pickup(releases, playlists, str(output_path))
            finally:
                sys.stdout = old_stdout

            # Feed captured output into log
            for line in buf.getvalue().splitlines():
                log_line(job_id, line)

            # Read the generated report
            result_text = output_path.read_text(encoding='utf-8') if output_path.exists() else ''
            json_path = output_path.with_suffix('.json')

            total_matches = sum(
                len(matches)
                for artist_releases in results.values()
                for matches in artist_releases.values()
            ) if results else 0

            if total_matches:
                log_line(job_id, f'Found {total_matches} playlist placements!')
            else:
                log_line(job_id, 'No matches found in checked playlists.')

            # Collect proof image paths — just list all PNGs in the proof dir
            proof_images = []
            proof_dir = REPORT_DIR / 'dsp_proofs'
            if proof_dir.exists():
                proof_images = sorted([f.name for f in proof_dir.glob('proof_*.png')])

            jobs[job_id]['proof_images'] = proof_images

            finish_job(job_id, result=result_text, output_path=output_path if output_path.exists() else None)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Release Calendar
# ---------------------------------------------------------------------------

@app.route('/playlists')
def playlists_page():
    return render_template('playlists.html')


@app.route('/api/playlists')
def api_playlists():
    """Return playlist database as JSON."""
    from shared.database import load_playlist_database

    pl_path = os.environ.get(
        'PLAYLIST_DB_PATH',
        str(ROOT_DIR / 'data' / 'playlist_database.csv')
    )
    playlists = load_playlist_database(pl_path)

    # Also read raw CSV for "Last Updated" column (not in parsed output)
    import csv as csv_mod
    updated_map = {}
    try:
        with open(pl_path, encoding='utf-8-sig') as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                name = row.get('Playlist Name', '').strip()
                if name:
                    updated_map[name] = row.get('Last Updated', '').strip()
    except Exception:
        pass

    result = []
    for p in playlists:
        result.append({
            'name': p.get('name', ''),
            'platform': p.get('platform', ''),
            'country': p.get('country', ''),
            'followers': p.get('followers', ''),
            'updated': updated_map.get(p.get('name', ''), ''),
            'mood': p.get('mood', ''),
            'link': p.get('link', ''),
        })
    return jsonify(result)


@app.route('/api/playlists/add', methods=['POST'])
def api_playlists_add():
    """Add a new playlist to the CSV database."""
    import csv as csv_mod

    data = request.get_json(silent=True) or {}
    link = data.get('link', '').strip()
    name = data.get('name', '').strip()
    country = data.get('country', '').strip()
    followers = data.get('followers', '').strip()
    mood = data.get('mood', '').strip()
    updated = data.get('updated', '').strip()

    if not link:
        return jsonify({'error': 'Playlist link is required.'}), 400
    if not name:
        return jsonify({'error': 'Playlist name is required.'}), 400

    # Auto-detect platform from URL
    link_lower = link.lower()
    if 'spotify.com' in link_lower:
        platform = 'Spotify'
    elif 'music.apple.com' in link_lower:
        platform = 'Apple Music'
    elif 'deezer.com' in link_lower:
        platform = 'Deezer'
    elif 'music.amazon' in link_lower:
        platform = 'Amazon Music'
    elif 'claromusica.com' in link_lower:
        platform = 'Claro Música'
    elif 'music.youtube.com' in link_lower:
        platform = 'YouTube Music'
    else:
        return jsonify({'error': 'Could not detect platform from URL. Supported: Spotify, Apple Music, Deezer, Amazon Music, Claro Música, YouTube Music.'}), 400

    pl_path = os.environ.get(
        'PLAYLIST_DB_PATH',
        str(ROOT_DIR / 'data' / 'playlist_database.csv')
    )

    # Check for duplicates (by link)
    try:
        with open(pl_path, encoding='utf-8-sig') as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                if row.get('Link', '').strip() == link:
                    return jsonify({'error': 'This playlist is already in the database.'}), 409
    except Exception:
        pass

    # Append to CSV
    row = {
        'Playlist Name': name,
        'Country': country,
        'Followers': followers,
        'Last Updated': updated or 'Each week',
        'Link': link,
        'Mood': mood,
        'Platform': platform,
    }
    fieldnames = ['Playlist Name', 'Country', 'Followers', 'Last Updated', 'Link', 'Mood', 'Platform']

    try:
        # Ensure file ends with a newline before appending
        with open(pl_path, 'rb') as f:
            f.seek(0, 2)  # end of file
            if f.tell() > 0:
                f.seek(-1, 2)
                if f.read(1) not in (b'\n', b'\r'):
                    with open(pl_path, 'a', encoding='utf-8') as fa:
                        fa.write('\n')
        with open(pl_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writerow(row)
    except Exception as e:
        return jsonify({'error': f'Failed to write to database: {e}'}), 500

    return jsonify({
        'success': True,
        'playlist': {
            'name': name,
            'platform': platform,
            'country': country,
            'followers': followers,
            'updated': updated or 'Each week',
            'mood': mood,
            'link': link,
        },
    })


@app.route('/api/playlists/delete', methods=['POST'])
def api_playlists_delete():
    """Remove a playlist from the CSV database by link."""
    import csv as csv_mod

    data = request.get_json(silent=True) or {}
    link = data.get('link', '').strip()
    if not link:
        return jsonify({'error': 'Playlist link is required.'}), 400

    pl_path = os.environ.get(
        'PLAYLIST_DB_PATH',
        str(ROOT_DIR / 'data' / 'playlist_database.csv')
    )

    # Read all rows, filter out the one to delete
    rows = []
    fieldnames = None
    found = False
    try:
        with open(pl_path, encoding='utf-8-sig') as f:
            reader = csv_mod.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row.get('Link', '').strip() == link:
                    found = True
                    continue
                rows.append(row)
    except Exception as e:
        return jsonify({'error': f'Failed to read database: {e}'}), 500

    if not found:
        return jsonify({'error': 'Playlist not found in database.'}), 404

    # Rewrite CSV without the deleted row
    try:
        with open(pl_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        return jsonify({'error': f'Failed to write database: {e}'}), 500

    return jsonify({'success': True})


@app.route('/calendar')
def calendar():
    resp = make_response(render_template('calendar.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/licensing')
def licensing():
    return render_template('licensing.html')


@app.route('/api/releases')
def api_releases():
    """Return release schedule as JSON with computed phase per release."""
    from datetime import datetime, timedelta
    from shared.database import load_release_schedule

    schedule_url = os.environ.get(
        'RELEASE_SCHEDULE_URL',
        'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
    )
    releases = load_release_schedule(schedule_url)
    today = datetime.now()
    year = today.year

    result = []
    for r in releases:
        # Parse date
        parsed = None
        date_str = r.get('date', '').strip()
        if date_str:
            for fmt in ('%b %d', '%B %d'):
                try:
                    parsed = datetime.strptime(f'{date_str} {year}', f'{fmt} %Y')
                    break
                except ValueError:
                    continue

        # Compute phase
        phase = 'unknown'
        if parsed:
            delta = (parsed - today).days
            if delta > 14:
                phase = 'pre-pitch'
            elif delta > 7:
                phase = 'radio-press'
            elif delta >= -7:
                phase = 'release-week'
            elif delta >= -14:
                phase = 'post-release'
            else:
                phase = 'reporting'

        result.append({
            'artist': r['artist'],
            'title': r['title'],
            'date': date_str,
            'parsed_date': parsed.strftime('%Y-%m-%d') if parsed else '',
            'format': r.get('format', ''),
            'label': r.get('label', ''),
            'priority': r.get('priority', ''),
            'week_block': r.get('week_block', 0),
            'phase': phase,
            'spotify_uri': r.get('spotify_uri', ''),
        })

    return jsonify(result)


# ---------------------------------------------------------------------------
# Report Compiler
# ---------------------------------------------------------------------------

@app.route('/api/report/compile', methods=['POST'])
def report_compile():
    data = request.get_json(silent=True) or {}
    artist = data.get('artist', '').strip()
    days = data.get('days', 28)
    radio_region = data.get('radio_region', 'latam')
    radio_time_range = data.get('radio_time_range', '28d')
    efforts_text = data.get('efforts_text', '')
    include_radio = data.get('include_radio', True)
    include_dsp = data.get('include_dsp', True)
    include_press = data.get('include_press', True)

    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400

    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 28

    job_id = new_job()
    safe_artist = artist.lower().replace(' ', '_')
    output_path = REPORT_DIR / f'{safe_artist}_full_report.docx'

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'report-compiler' / 'compile_report.py'
            spec = importlib.util.spec_from_file_location('compile_report', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result = mod.compile_report(
                artist=artist,
                days=days,
                radio_region=radio_region,
                radio_time_range=radio_time_range,
                efforts_text=efforts_text,
                output_path=str(output_path),
                log_fn=lambda msg: log_line(job_id, msg),
                include_radio=include_radio,
                include_dsp=include_dsp,
                include_press=include_press,
            )

            # Summary for result
            sections = []
            if result.get('radio_data'):
                sections.append(f"Radio: {len(result['radio_data'])} entries")
            if result.get('dsp_data'):
                total_dsp = sum(len(m) for r in result['dsp_data'].values() for m in r.values())
                sections.append(f"DSP: {total_dsp} placements")
            if result.get('press_data'):
                total_press = sum(len(v) for v in result['press_data'].values())
                sections.append(f"Press: {total_press} results")

            summary = ' | '.join(sections) if sections else 'Report generated (no data found in selected sections)'

            # Collect proof images
            proof_dir = REPORT_DIR / 'dsp_proofs'
            if proof_dir.exists():
                jobs[job_id]['proof_images'] = sorted([f.name for f in proof_dir.glob('proof_*.png')])

            finish_job(job_id, result=summary, output_path=output_path)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Outlet Discovery
# ---------------------------------------------------------------------------

@app.route('/api/discovery/search', methods=['POST'])
def discovery_search():
    data = request.get_json(silent=True) or {}
    genre = data.get('genre', 'general music')
    countries = data.get('countries', ['All LATAM'])
    custom_query = data.get('custom_query', '')
    use_llm = data.get('use_llm', True)

    if not countries:
        countries = ['All LATAM']

    job_id = new_job()

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'discovery' / 'discover_outlets.py'
            spec = importlib.util.spec_from_file_location('discover_outlets', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result = mod.discover_outlets(
                genre=genre,
                countries=countries,
                custom_query=custom_query,
                use_llm=use_llm,
                log_fn=lambda msg: log_line(job_id, msg),
            )

            summary = f"Searched {result['total_searched']} results → {result['already_in_db']} already in DB → {result['new_count']} new outlets"
            jobs[job_id]['discovery_html'] = result.get('html', '')
            jobs[job_id]['discovery_outlets'] = result.get('outlets', [])
            jobs[job_id]['discovery_csv'] = result.get('csv_rows', [])

            finish_job(job_id, result=summary)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/discovery/csv/<job_id>')
def discovery_csv(job_id):
    """Download discovered outlets as CSV (Notion-importable format)."""
    import csv as csv_mod
    import io as io_mod

    job = jobs.get(job_id)
    if not job or not job.get('discovery_csv'):
        return jsonify({'error': 'No discovery data available'}), 404

    rows = job['discovery_csv']
    if not rows:
        return jsonify({'error': 'No new outlets found'}), 404

    output = io_mod.StringIO()
    fieldnames = ['NAME OF MEDIA', 'Territory', 'DESCRIPTION & SM', 'WEBSITE', 'TYPE', 'REACH']
    writer = csv_mod.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=new_outlets.csv'},
    )


# ---------------------------------------------------------------------------
# Weekly Digest
# ---------------------------------------------------------------------------

@app.route('/api/digest/generate', methods=['POST'])
def digest_generate():
    data = request.get_json(silent=True) or {}
    artist = data.get('artist', '').strip()
    days = data.get('days', 7)
    radio_region = data.get('radio_region', 'latam')
    radio_time_range = data.get('radio_time_range', '7d')
    next_steps = data.get('next_steps', '')
    sender_name = data.get('sender_name', '')
    contact_name = data.get('contact_name', '')
    include_radio = data.get('include_radio', True)
    include_dsp = data.get('include_dsp', True)
    include_press = data.get('include_press', True)

    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400

    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 7

    job_id = new_job()

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'digest-generator' / 'generate_digest.py'
            spec = importlib.util.spec_from_file_location('generate_digest', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result = mod.generate_digest(
                artist=artist,
                days=days,
                radio_region=radio_region,
                radio_time_range=radio_time_range,
                next_steps=next_steps,
                sender_name=sender_name,
                contact_name=contact_name,
                include_radio=include_radio,
                include_dsp=include_dsp,
                include_press=include_press,
                log_fn=lambda msg: log_line(job_id, msg),
            )

            summary = []
            if result['radio_count']:
                summary.append(f"Radio: {result['radio_count']}")
            if result['dsp_count']:
                summary.append(f"DSP: {result['dsp_count']}")
            if result['press_count']:
                summary.append(f"Press: {result['press_count']}")

            jobs[job_id]['digest_html'] = result['html']
            jobs[job_id]['digest_text'] = result['text']

            summary_str = ' | '.join(summary) if summary else 'No activity found for this period'
            finish_job(job_id, result=summary_str)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Proposal Generator
# ---------------------------------------------------------------------------

@app.route('/api/proposal/data')
def proposal_data():
    """Return radio stations, pricing, and DSP strategies for the proposal form."""
    import csv as csv_mod

    # Radio targets
    radio_path = ROOT_DIR / 'data' / 'radio_targets.csv'
    stations = []
    if radio_path.exists():
        with open(radio_path, encoding='utf-8-sig') as f:
            for row in csv_mod.DictReader(f):
                stations.append({
                    'station': row.get('Station', ''),
                    'country': row.get('Country', ''),
                    'genre': row.get('Genre', ''),
                    'format': row.get('Format', ''),
                    'price': row.get('Price USD', ''),
                    'notes': row.get('Notes', ''),
                })

    # Pricing
    pricing_path = ROOT_DIR / 'data' / 'pricing.json'
    pricing = {}
    if pricing_path.exists():
        with open(pricing_path, encoding='utf-8') as f:
            pricing = json.load(f)

    # DSP strategies
    dsp_path = ROOT_DIR / 'data' / 'dsp_strategy.json'
    dsp = {}
    if dsp_path.exists():
        with open(dsp_path, encoding='utf-8') as f:
            dsp = json.load(f)

    return jsonify({
        'stations': stations,
        'pricing': pricing,
        'dsp': dsp,
    })


@app.route('/api/proposal/generate', methods=['POST'])
def proposal_generate():
    data = request.get_json(silent=True) or {}
    artist = data.get('artist', '').strip()

    if not artist:
        return jsonify({'error': 'Please enter an artist name.'}), 400

    genre = data.get('genre', 'general')
    campaign_duration = data.get('campaign_duration', 3)
    try:
        campaign_duration = int(campaign_duration)
    except (TypeError, ValueError):
        campaign_duration = 3

    collaborators = data.get('collaborators', '')
    goal_strategy = data.get('goal_strategy', '')
    digital_marketing = data.get('digital_marketing', '')
    countries = data.get('countries', None)
    radio_stations = data.get('radio_stations', None)
    influencer_tier = data.get('influencer_tier', 'mid')
    dj_markets = data.get('dj_markets', None)
    digital_package = data.get('digital_package', 'standard')

    # Parse timeline
    timeline = []
    raw_timeline = data.get('timeline', [])
    if isinstance(raw_timeline, list):
        for entry in raw_timeline:
            if isinstance(entry, dict) and entry.get('title'):
                timeline.append({
                    'title': entry.get('title', ''),
                    'date': entry.get('date', ''),
                    'format': entry.get('format', ''),
                })

    import re as re_mod
    safe_artist = re_mod.sub(r'[^\w\-]', '_', artist.lower())
    output_path = REPORT_DIR / f'{safe_artist}_proposal.docx'

    job_id = new_job()

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'proposal-generator' / 'generate_proposal.py'
            spec = importlib.util.spec_from_file_location('generate_proposal', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result = mod.generate_proposal(
                artist=artist,
                genre=genre,
                timeline=timeline,
                collaborators=collaborators,
                campaign_duration=campaign_duration,
                goal_strategy=goal_strategy,
                digital_marketing=digital_marketing,
                countries=countries,
                radio_stations=radio_stations,
                influencer_tier=influencer_tier,
                dj_markets=dj_markets,
                digital_package=digital_package,
                output_path=str(output_path),
                log_fn=lambda msg: log_line(job_id, msg),
            )

            summary = (
                f"Proposal generated — "
                f"{result['press_count']} press targets, "
                f"{result['radio_count']} radio stations, "
                f"{result['dsp_platforms']} DSP platforms"
            )
            finish_job(job_id, result=summary, output_path=output_path)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Press Release Translator
# ---------------------------------------------------------------------------

@app.route('/api/pr/translate', methods=['POST'])
def pr_translate():
    # Handle both JSON (pasted text) and multipart/form-data (file upload)
    text = ''
    docx_path = ''
    target_es = True
    target_pt = True
    notes = ''

    use_ai = False

    if request.content_type and 'multipart/form-data' in request.content_type:
        text = request.form.get('text', '').strip()
        target_es = request.form.get('target_es', 'true') == 'true'
        target_pt = request.form.get('target_pt', 'true') == 'true'
        use_ai = request.form.get('use_ai', 'false') == 'true'
        notes = request.form.get('notes', '')

        # Handle file upload
        uploaded = request.files.get('file')
        if uploaded and uploaded.filename:
            job_id = str(uuid.uuid4())
            upload_path = UPLOAD_DIR / job_id
            upload_path.mkdir(parents=True, exist_ok=True)
            file_path = upload_path / uploaded.filename
            uploaded.save(str(file_path))
            docx_path = str(file_path)
    else:
        data = request.get_json(silent=True) or {}
        text = data.get('text', '').strip()
        target_es = data.get('target_es', True)
        target_pt = data.get('target_pt', True)
        use_ai = data.get('use_ai', False)
        notes = data.get('notes', '')

    if not text and not docx_path:
        return jsonify({'error': 'Please paste the PR text or upload a .docx file.'}), 400

    if not target_es and not target_pt:
        return jsonify({'error': 'Please select at least one target language.'}), 400

    job_id = new_job()

    # Output directory for translated .docx files
    pr_output_dir = str(REPORT_DIR / 'pr_translations')

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'pr-generator' / 'generate_pr.py'
            spec = importlib.util.spec_from_file_location('generate_pr', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result = mod.translate_pr(
                text=text,
                docx_path=docx_path,
                target_es=target_es,
                target_pt=target_pt,
                use_ai=use_ai,
                notes=notes,
                output_dir=pr_output_dir,
                log_fn=lambda msg: log_line(job_id, msg),
            )

            jobs[job_id]['pr_es_text'] = result['es_text']
            jobs[job_id]['pr_pt_text'] = result['pt_text']
            jobs[job_id]['pr_source_lang'] = result['source_lang']
            jobs[job_id]['pr_es_docx_path'] = result.get('es_docx_path', '')
            jobs[job_id]['pr_pt_docx_path'] = result.get('pt_docx_path', '')

            langs = []
            if result['es_text']:
                langs.append('Spanish')
            if result['pt_text']:
                langs.append('Portuguese')

            engine_label = 'Gemini Flash' if result.get('engine') == 'gemini' else 'Google Translate'
            finish_job(
                job_id,
                result=f"Translated from {result['source_lang']} \u2192 {' + '.join(langs)} (via {engine_label})",
            )

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/pr/download/<job_id>')
def pr_download(job_id):
    """Download a translated PR .docx file."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    lang = request.args.get('lang', 'es')
    key = f'pr_{lang}_docx_path'
    path_str = job.get(key, '')
    if not path_str:
        return jsonify({'error': 'No .docx file available for this language.'}), 404
    p = Path(path_str)
    if not p.exists():
        return jsonify({'error': 'File not found on disk.'}), 404
    return send_file(str(p), as_attachment=True, download_name=p.name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Open browser after short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')

    threading.Thread(target=open_browser, daemon=True).start()

    print('=' * 50)
    print('  DMM Tools — Web UI')
    print('  http://localhost:5000')
    print('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
