#!/usr/bin/env python3
"""
DMM Tools — Web Frontend
Flask app serving a local UI for Radio Report, Press Pickup, and DSP Pickup.
"""

import atexit
import contextlib
import importlib.util
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

from flask import Flask, request, jsonify, send_file, render_template, make_response, redirect, url_for, session

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dmm-tools-dev-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 30  # 30 days
app.config['SESSION_COOKIE_NAME'] = os.environ.get('DMM_SESSION_COOKIE_NAME', 'dmm_tools_session')


@app.template_filter('abbreviate')
def abbreviate_number(value):
    """Format large numbers: 1.7M, 245K, or 1,234 for smaller values."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return value
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}M'.replace('.0M', 'M')
    if n >= 10_000:
        return f'{n / 1_000:.1f}K'.replace('.0K', 'K')
    return f'{n:,.0f}'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ---------------------------------------------------------------------------
# Authentication — two-password model
#   DMM_TEAM_PASS  → shared password for the whole team (access all tools)
#   DMM_ADMIN_PASS → separate password for Settings page (API keys, config)
# ---------------------------------------------------------------------------
_TEAM_PASS = os.environ.get('DMM_TEAM_PASS', 'dmm2026')
_ADMIN_PASS = os.environ.get('DMM_ADMIN_PASS', 'dmmadmin2026')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == _TEAM_PASS:
            session.permanent = True
            session['authenticated'] = True
            resp = redirect(request.args.get('next') or url_for('index'))
            # Clear Flask's legacy default cookie name so old localhost sessions
            # don't keep shadowing the new dedicated DMM cookie.
            resp.delete_cookie('session')
            return resp
        return render_template('login.html', error='Wrong password.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    resp = redirect(url_for('login'))
    resp.delete_cookie('session')
    return resp

@app.route('/api/admin/auth', methods=['POST'])
def admin_auth():
    """Verify admin password to unlock Settings."""
    if not session.get('authenticated'):
        return jsonify({'error': 'Authentication required.'}), 401
    data = request.get_json(silent=True) or {}
    if data.get('password') == _ADMIN_PASS:
        session['is_admin'] = True
        return jsonify({'ok': True})
    return jsonify({'error': 'Wrong admin password.'}), 403

@app.before_request
def require_login():
    """Protect all routes except login, static files, and job status polls."""
    allowed = ('login', 'static')
    if request.endpoint and request.endpoint in allowed:
        return
    # Job status polls are safe to serve unauthenticated — job IDs are random
    # UUIDs and responses only contain job logs/results, no sensitive data.
    if request.endpoint in ('job_status', 'job_status_summary'):
        return
    if not session.get('authenticated'):
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        has_bad_cookie = bool(request.cookies.get(cookie_name))
        if request.path.startswith('/api/'):
            resp = jsonify({'error': 'Authentication required.'})
            resp.status_code = 401
            if has_bad_cookie:
                resp.delete_cookie(cookie_name, path='/')
            return resp
        resp = redirect(url_for('login', next=request.path))
        if has_bad_cookie:
            resp.delete_cookie(cookie_name, path='/')
        return resp
    # Settings API routes require admin auth
    if request.path.startswith('/api/settings/') or request.path == '/api/backup':
        if not session.get('is_admin'):
            return jsonify({'error': 'Admin access required.'}), 403

# ---------------------------------------------------------------------------
# Structured file logging with rotation
# ---------------------------------------------------------------------------
import logging
from logging.handlers import RotatingFileHandler

_log_dir = ROOT_DIR / 'logs'
_log_dir.mkdir(exist_ok=True)
_file_handler = RotatingFileHandler(
    str(_log_dir / 'dmm_tools.log'),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
)
_file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
))
_file_handler.setLevel(logging.INFO)
app.logger.addHandler(_file_handler)
app.logger.setLevel(logging.INFO)
logger = app.logger

# ---------------------------------------------------------------------------
# Credential sanitizer — redacts sensitive values from log output
# ---------------------------------------------------------------------------
_SENSITIVE_ENV_KEYS = [
    'SOUNDCHARTS_PASSWORD', 'SOUNDCHARTS_EMAIL',
    'SERPER_API_KEY', 'TAVILY_API_KEY',
    'GROQ_API_KEY', 'GEMINI_API_KEY',
    'GITHUB_PAT',
]
_REDACT_PATTERNS = []  # list of (value, replacement) tuples

def _build_redact_patterns():
    """Build redaction patterns from current env values. Call after env is loaded."""
    _REDACT_PATTERNS.clear()
    for key in _SENSITIVE_ENV_KEYS:
        val = os.environ.get(key, '')
        if val and len(val) >= 6:
            _REDACT_PATTERNS.append((val, f'[REDACTED:{key[-8:]}]'))

def sanitize_log(text):
    """Remove any credential values from log text."""
    for secret, replacement in _REDACT_PATTERNS:
        if secret in text:
            text = text.replace(secret, replacement)
    return text

_build_redact_patterns()

# ---------------------------------------------------------------------------
# Thread-safe stdout capture
# ---------------------------------------------------------------------------
from shared.capture import capture_stdout, install_proxy
install_proxy()


# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------
jobs = {}  # { job_id: { status, log, result, output_path, error, ... } }

UPLOAD_DIR = Path(__file__).parent / 'uploads'
REPORT_DIR = ROOT_DIR / 'reports'
REPORT_DIR.mkdir(exist_ok=True)


def _check_internet(timeout=3):
    """Quick connectivity check (HEAD to Google)."""
    import requests as _req
    try:
        _req.head('https://www.google.com', timeout=timeout)
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# APScheduler — background cron scheduler
# ---------------------------------------------------------------------------
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler(daemon=True)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


def _register_scheduler_job(schedule_id, cron_expression):
    """Register (or re-register) a cron job in APScheduler for a schedule."""
    job_name = f'schedule_{schedule_id}'
    if scheduler.get_job(job_name):
        scheduler.remove_job(job_name)
    trigger = CronTrigger.from_crontab(cron_expression)
    scheduler.add_job(
        _execute_schedule, trigger,
        args=[schedule_id],
        id=job_name,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )


def _execute_schedule(schedule_id, job_id=None):
    """Run a scheduled digest/snapshot job. Called by APScheduler or manual trigger."""
    from shared.history import (get_schedule, save_schedule_run, update_schedule_run,
                                update_schedule_last_run)
    from shared.database import load_release_schedule

    schedule = get_schedule(schedule_id)
    if not schedule:
        return

    auto_append = schedule.get('auto_append_gdocs', False)

    # Resolve artist list
    artist_source = schedule['artist_source']
    if artist_source == 'manual':
        artists = list(schedule['artists'])
    else:
        from shared.history import get_artists
        data_names = [a['artist'] for a in get_artists()]
        schedule_names = []
        try:
            releases = load_release_schedule(RELEASE_SCHEDULE_URL)
            schedule_names = sorted({r['artist'] for r in releases})
        except Exception:
            pass

        if artist_source == 'all_with_data':
            artists = data_names
        elif artist_source == 'all_schedule':
            artists = schedule_names
        else:  # 'all'
            seen = set()
            artists = []
            for n in data_names + schedule_names:
                if n not in seen:
                    seen.add(n)
                    artists.append(n)

    if not artists:
        if job_id:
            finish_job(job_id, result='No artists found for this schedule.')
        return

    if auto_append:
        from shared.history import get_artist_doc

    run_id = save_schedule_run(schedule_id, len(artists))

    try:
        spec_path = ROOT_DIR / 'digest-generator' / 'generate_digest.py'
        spec = importlib.util.spec_from_file_location('generate_digest_sched', str(spec_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        days_map = {'7d': 7, '28d': 28}
        days = days_map.get(schedule['radio_time_range'], 7)

        with_data = 0
        failed = 0
        appended = 0
        details = {}
        start_time = time.time()

        for i, artist in enumerate(artists, 1):
            if job_id:
                log_line(job_id, f"[{i}/{len(artists)}] Running {schedule['mode']} for {artist}...")
            try:
                result = mod.generate_digest(
                    artist=artist,
                    days=days,
                    radio_region=schedule['radio_region'],
                    radio_time_range=schedule['radio_time_range'],
                    next_steps='',
                    sender_name='',
                    contact_name='',
                    include_radio=schedule['include_radio'],
                    include_dsp=schedule['include_dsp'],
                    include_press=schedule['include_press'],
                    log_fn=lambda msg, _jid=job_id: log_line(_jid, f"  {msg}") if _jid else None,
                )
                entry = {
                    'radio_count': result.get('radio_count', 0),
                    'dsp_count': result.get('dsp_count', 0),
                    'press_count': result.get('press_count', 0),
                }
                has_activity = entry['radio_count'] or entry['dsp_count'] or entry['press_count']
                if has_activity:
                    with_data += 1
                details[artist] = entry
                if job_id:
                    counts = []
                    if entry['radio_count']: counts.append(f"Radio: {entry['radio_count']}")
                    if entry['dsp_count']: counts.append(f"DSP: {entry['dsp_count']}")
                    if entry['press_count']: counts.append(f"Press: {entry['press_count']}")
                    log_line(job_id, f"  => {artist}: {' | '.join(counts) if counts else 'No activity'}")

                # Auto-append to Google Doc
                if auto_append and has_activity:
                    doc = get_artist_doc(artist)
                    if doc:
                        ar = _batch_auto_append(
                            artist, doc['doc_id'],
                            radio_data=result.get('radio_data'),
                            dsp_data=result.get('dsp_data'),
                            press_data=result.get('press_data'),
                            radio_date_range=compute_radio_date_range(
                                schedule.get('radio_time_range', '7d')),
                        )
                        details[artist]['append'] = ar['status']
                        if ar['status'] == 'appended':
                            appended += 1
                            if job_id:
                                log_line(job_id, f"  \u2713 Appended to Google Doc: {ar['doc_title']}")
                        elif ar['status'] == 'skipped':
                            if job_id:
                                log_line(job_id, f"  \u26a0 Skipped: {ar['detail']}")
                        else:
                            if job_id:
                                log_line(job_id, f"  \u2717 Append failed: {ar['detail']}")
                        time.sleep(1)  # Rate limiting
                    elif job_id:
                        log_line(job_id, f"  — No Google Doc linked")

            except Exception as e:
                failed += 1
                details[artist] = {'error': str(e)}
                if job_id:
                    log_line(job_id, f"  => {artist}: Error — {e}")

        duration = round(time.time() - start_time, 1)
        status = 'error' if failed == len(artists) else ('partial' if failed else 'success')
        update_schedule_run(run_id,
                            finished_at=__import__('datetime').datetime.utcnow().isoformat(),
                            status=status,
                            artists_with_data=with_data,
                            artists_failed=failed,
                            duration_seconds=duration,
                            details=details)
        update_schedule_last_run(schedule_id, status)

        if job_id:
            summary = f"{len(artists)} artists: {with_data} with data, {failed} failed ({duration}s)"
            if auto_append and appended:
                summary += f", {appended} appended to Google Docs"
            finish_job(job_id, result=summary)

    except Exception as e:
        update_schedule_run(run_id,
                            finished_at=__import__('datetime').datetime.utcnow().isoformat(),
                            status='error',
                            error=str(e))
        update_schedule_last_run(schedule_id, 'error')
        if job_id:
            finish_job(job_id, error=str(e))


JOB_TIMEOUT_SECONDS = 600       # 10 minutes max per single job
BATCH_TIMEOUT_SECONDS = 7200    # 2 hours max for batch jobs
MAX_CONCURRENT_JOBS = 3
_job_semaphore = threading.Semaphore(MAX_CONCURRENT_JOBS)


def run_with_limit(job_id, fn):
    """Wrap a job function with concurrency limiting."""
    def wrapper():
        acquired = _job_semaphore.acquire(blocking=False)
        if not acquired:
            log_line(job_id, 'Queued — waiting for other jobs to finish...')
            _job_semaphore.acquire()
        try:
            fn()
        finally:
            _job_semaphore.release()
    return wrapper


MAX_ARTIST_NAME_LENGTH = 100


def combine_docx(paths, output_path):
    """Merge multiple .docx files into one with page breaks between them.

    Properly remaps image/hyperlink relationships so embedded images and links
    from sub-documents resolve correctly in the combined output.
    """
    import copy
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.part import Part as OpcPart
    from docx.opc.packuri import PackURI

    if not paths:
        return
    combined = Document(str(paths[0]))
    body = combined.element.body
    sect_pr = body.find(qn('w:sectPr'))

    # Track the next available image number to avoid filename collisions
    _img_counter = [0]
    for rel in combined.part.rels.values():
        if 'image' in rel.reltype:
            _img_counter[0] += 1

    for path in paths[1:]:
        # Page break between documents
        bp = OxmlElement('w:p')
        bpr = OxmlElement('w:r')
        bbr = OxmlElement('w:br')
        bbr.set(qn('w:type'), 'page')
        bpr.append(bbr)
        bp.append(bpr)
        if sect_pr is not None:
            sect_pr.addprevious(bp)
        else:
            body.append(bp)

        sub = Document(str(path))

        # Build a mapping from sub-doc rIds → new rIds in combined doc.
        # Only copy image and hyperlink relationships — document-level parts
        # (styles, settings, numbering, etc.) already exist from the base doc.
        rid_map = {}
        for rel in sub.part.rels.values():
            if rel.is_external:
                new_rid = combined.part.relate_to(
                    rel.target_ref, rel.reltype, is_external=True)
            elif 'image' in rel.reltype:
                # Copy image blob into a fresh part with a unique name
                _img_counter[0] += 1
                src = rel.target_part
                ext = src.partname.rsplit('.', 1)[-1] if '.' in src.partname else 'png'
                new_name = PackURI(f'/word/media/merged_{_img_counter[0]}.{ext}')
                new_part = OpcPart(new_name, src.content_type, src.blob,
                                   combined.part.package)
                new_rid = combined.part.relate_to(new_part, rel.reltype)
            else:
                continue  # skip document-level parts (styles, settings, etc.)
            rid_map[rel.rId] = new_rid

        # Clone body elements, remapping all rId references
        r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        rid_attrs = [f'{{{r_ns}}}embed', f'{{{r_ns}}}link', f'{{{r_ns}}}id']
        for element in sub.element.body:
            if element.tag == qn('w:sectPr'):
                continue
            clone = copy.deepcopy(element)
            for node in clone.iter():
                for attr_name in rid_attrs:
                    old_rid = node.get(attr_name)
                    if old_rid and old_rid in rid_map:
                        node.set(attr_name, rid_map[old_rid])
            if sect_pr is not None:
                sect_pr.addprevious(clone)
            else:
                body.append(clone)

    combined.save(str(output_path))


def validate_artist(name):
    """Return an error string if the artist name is invalid, else None."""
    if not name:
        return 'Please enter an artist name.'
    if len(name) > MAX_ARTIST_NAME_LENGTH:
        return f'Artist name is too long (max {MAX_ARTIST_NAME_LENGTH} characters).'
    return None


def _batch_auto_append(artist_name, doc_id, radio_data=None, dsp_data=None,
                       press_data=None, proof_image_paths=None, date_label=None,
                       radio_date_range=None):
    """Auto-append report data to a Google Doc. Used by batch endpoints.

    Returns dict: {status: 'appended'|'skipped'|'error', detail: str, doc_title: str}
    """
    from shared.google_docs import append_report_to_doc, get_document_title
    from shared.history import update_artist_doc_append_status, save_artist_doc_undo

    try:
        doc_title = get_document_title(doc_id)
    except Exception:
        doc_title = doc_id[:12] + '...'

    try:
        result = append_report_to_doc(
            doc_id=doc_id,
            dsp_data=dsp_data,
            radio_data=radio_data,
            press_data=press_data,
            artist_name=artist_name,
            date_label=date_label,
            proof_image_paths=proof_image_paths,
            radio_date_range=radio_date_range,
        )

        if result.get('skipped'):
            update_artist_doc_append_status(artist_name, 'skipped (duplicate)')
            return {'status': 'skipped', 'detail': result.get('reason', 'duplicate'),
                    'doc_title': doc_title}

        if result['success']:
            update_artist_doc_append_status(artist_name, 'success')
            # Save undo data
            if result.get('inserted_at') and result.get('insert_end'):
                save_artist_doc_undo(artist_name, doc_id,
                                     result['inserted_at'], result['insert_end'])
            return {'status': 'appended', 'detail': f'{result["characters_inserted"]} chars',
                    'doc_title': doc_title}

        update_artist_doc_append_status(artist_name, f'error: {result["error"]}')
        return {'status': 'error', 'detail': result['error'], 'doc_title': doc_title}

    except Exception as e:
        update_artist_doc_append_status(artist_name, f'error: {e}')
        return {'status': 'error', 'detail': str(e), 'doc_title': doc_title}


def new_job():
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'status': 'running',
        'log': [],
        'current_step': None,
        'progress': None,
        'determinate_progress': False,
        'result': None,
        'output_path': None,
        'error': None,
        'started_at': time.time(),
    }
    return job_id


def log_line(job_id, text):
    if job_id in jobs:
        jobs[job_id]['log'].append(text)
        if text:
            jobs[job_id]['current_step'] = text


def make_incremental_logger(job_id):
    """Create a line-buffered callback for capture_stdout."""
    buffer = []

    def on_write(text):
        if not text:
            return
        text = sanitize_log(text)
        # Handle multiple lines in one write
        lines = text.splitlines(keepends=True)
        for line in lines:
            if line.endswith('\n'):
                # Complete line
                complete = "".join(buffer) + line.rstrip('\n')
                log_line(job_id, complete)
                buffer.clear()
            else:
                buffer.append(line)
    return on_write


def finish_job(job_id, result=None, output_path=None, error=None):
    if job_id not in jobs:
        return
    if error:
        error = sanitize_log(str(error))
        elapsed = time.time() - jobs[job_id].get('started_at', 0)
        logger.error('Job %s FAILED (%.1fs): %s', job_id[:8], elapsed, error[:200])
    else:
        elapsed = time.time() - jobs[job_id].get('started_at', 0)
        logger.info('Job %s completed (%.1fs)', job_id[:8], elapsed)
    jobs[job_id]['status'] = 'error' if error else 'done'
    jobs[job_id]['result'] = result
    jobs[job_id]['output_path'] = str(output_path) if output_path else None
    jobs[job_id]['error'] = error
    jobs[job_id]['finished_at'] = time.time()
    # Clean up uploads
    upload_dir = UPLOAD_DIR / job_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)


JOB_EXPIRE_SECONDS = 3600        # remove finished single jobs after 1 hour
BATCH_EXPIRE_SECONDS = 14400     # remove finished batch jobs after 4 hours


def _reap_stale_jobs():
    """Mark timed-out jobs and clean up expired finished jobs."""
    now = time.time()
    to_delete = []
    for job_id, job in list(jobs.items()):
        started = job.get('started_at', now)
        if job['status'] == 'running':
            timeout = BATCH_TIMEOUT_SECONDS if job.get('batch') else JOB_TIMEOUT_SECONDS
            if now - started > timeout:
                mins = int(timeout // 60)
                job['status'] = 'error'
                job['error'] = f'This operation timed out after {mins} minutes. Please try again.'
                job['log'].append('Job timed out.')
        else:
            # Expire from when the job finished, not when it started
            finished_at = job.get('finished_at', started)
            expire = BATCH_EXPIRE_SECONDS if job.get('batch') else JOB_EXPIRE_SECONDS
            if now - finished_at > expire:
                to_delete.append(job_id)
    for job_id in to_delete:
        jobs.pop(job_id, None)


# Run stale job reaper every 30 seconds
scheduler.add_job(_reap_stale_jobs, 'interval', seconds=30, id='reap_stale_jobs',
                  replace_existing=True)


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
    # Incremental log: only return lines after the offset the client already has
    log_offset = request.args.get('log_offset', 0, type=int)
    full_log = job['log']
    log_slice = full_log[log_offset:] if log_offset > 0 else full_log
    resp_data = {
        'status': job['status'],
        'log': log_slice,
        'log_offset': len(full_log),
        'current_step': job.get('current_step'),
        'progress': job.get('progress'),
        'determinate_progress': bool(job.get('determinate_progress')),
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
        'batch_results': job.get('batch_results', {}),
        'artist_statuses': job.get('artist_statuses', []),
        'has_batch_zip': bool(job.get('batch_zip')),
        'has_batch_combined_docx': bool(job.get('batch_combined_docx')),
        'append_results': job.get('append_results', {}),
    }
    # Suppress empty optional fields to reduce payload
    for key in ('digest_html', 'digest_text', 'discovery_html', 'pr_es_text',
                'pr_pt_text', 'pr_source_lang'):
        if not resp_data[key]:
            del resp_data[key]
    for key in ('proof_images', 'discovery_outlets', 'artist_statuses'):
        if not resp_data[key]:
            del resp_data[key]
    for key in ('batch_results', 'append_results'):
        if not resp_data[key]:
            del resp_data[key]
    return jsonify(resp_data)


@app.route('/api/status/<job_id>/summary')
def job_status_summary(job_id):
    """Lightweight status for the jobs drawer — no log lines or result data."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({
        'status': job['status'],
        'current_step': job.get('current_step'),
        'progress': job.get('progress'),
        'determinate_progress': bool(job.get('determinate_progress')),
        'error': job['error'],
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


@app.route('/api/reports/<filename>')
def download_report(filename):
    """Serve a report file directly from reports/ directory."""
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    p = REPORT_DIR / filename
    if not p.exists():
        return jsonify({'error': 'File not found'}), 404
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
    """Download a specific output file type (txt, json, docx, or zip) for jobs."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'No file available'}), 404

    # Batch zip/combined don't need output_path
    if filetype == 'zip':
        zip_path = job.get('batch_zip')
        if zip_path and Path(zip_path).exists():
            return send_file(str(zip_path), as_attachment=True, download_name=Path(zip_path).name)
        return jsonify({'error': 'No zip file available'}), 404
    if filetype == 'combined':
        combined_path = job.get('batch_combined_docx')
        if combined_path and Path(combined_path).exists():
            return send_file(str(combined_path), as_attachment=True, download_name=Path(combined_path).name)
        return jsonify({'error': 'No combined file available'}), 404

    if not job.get('output_path'):
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
# Batch status & per-artist download endpoints
# ---------------------------------------------------------------------------

@app.route('/api/batch/<batch_id>')
def batch_status(batch_id):
    """Return per-artist statuses for a batch job (used by card dashboard)."""
    job = jobs.get(batch_id)
    if not job:
        return jsonify({'error': 'Batch not found'}), 404
    raw_statuses = job.get('artist_statuses', [])
    # Include output filenames for direct download URLs (survive server restarts)
    statuses = []
    for s in raw_statuses:
        entry = {k: v for k, v in s.items() if k != 'output_path'}
        out = s.get('output_path')
        if out:
            docx_path = Path(out).with_suffix('.docx')
            entry['output_name'] = docx_path.name if docx_path.exists() else None
        else:
            entry['output_name'] = None
        statuses.append(entry)
    zip_path = job.get('batch_zip')
    combined_path = job.get('batch_combined_docx')
    return jsonify({
        'status': job['status'],
        'error': job['error'],
        'artist_statuses': statuses,
        'has_batch_zip': bool(zip_path),
        'has_batch_combined_docx': bool(combined_path),
        'batch_zip_name': Path(zip_path).name if zip_path else None,
        'batch_combined_name': Path(combined_path).name if combined_path else None,
        'append_results': job.get('append_results', {}),
    })


@app.route('/api/batch/<batch_id>/download/<int:index>/<filetype>')
def batch_artist_download(batch_id, index, filetype):
    """Download a per-artist output file from a batch job."""
    job = jobs.get(batch_id)
    if not job:
        return jsonify({'error': 'Batch not found. Try re-running the batch.'}), 404
    statuses = job.get('artist_statuses', [])
    if index < 0 or index >= len(statuses):
        return jsonify({'error': 'Invalid artist index'}), 404
    astat = statuses[index]
    out = astat.get('output_path')
    if not out:
        return jsonify({'error': 'No file available for this artist'}), 404
    base = Path(out)
    if filetype == 'docx':
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
    err = validate_artist(artist)
    if err:
        return jsonify({'error': err}), 400

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

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
    return jsonify({'job_id': job_id})


# ---------------------------------------------------------------------------
# Radio Report — Soundcharts auto-fetch mode
# ---------------------------------------------------------------------------

@app.route('/api/radio/soundcharts', methods=['POST'])
def radio_soundcharts():
    data = request.get_json() or {}
    artist = (data.get('artist') or '').strip()
    region = data.get('region', 'latam').strip()  # 'latam' or 'all'
    err = validate_artist(artist)
    if err:
        return jsonify({'error': err}), 400

    job_id = new_job()

    safe_artist = artist.lower().replace(' ', '_')
    output_path = REPORT_DIR / f'{safe_artist}_radio.docx'

    def run():
        try:
            from shared.soundcharts import search_artist, fetch_airplay_data, airplay_to_csv, get_token

            token = get_token()
            if not token:
                finish_job(job_id, error='Soundcharts credentials not configured. Go to Settings to add them.')
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
                region_desc = 'LATAM' if region == 'latam' else 'any region'
                finish_job(job_id, error=f'No radio plays found for {match["name"]} in {region_desc}.')
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
                '--period', compute_radio_date_range('28d'),
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

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
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


def compute_radio_date_range(time_range, start_date=None, end_date=None):
    """Compute a human-readable date range string for any radio time range.

    Returns e.g. 'Mar 1 - Mar 8, 2026' for 7d, or the custom range for custom.
    """
    from datetime import datetime, timedelta
    today = datetime.now()
    if time_range == 'custom' and start_date and end_date:
        return format_custom_period(start_date, end_date)
    days_map = {'7d': 7, '7d_prev': 14, '28d': 28, '1y': 365}
    delta = days_map.get(time_range, 28)
    s = today - timedelta(days=delta)
    if time_range == '7d_prev':
        e = today - timedelta(days=7)
    else:
        e = today
    if s.year == e.year:
        return f"{s.strftime('%b %-d')} - {e.strftime('%b %-d, %Y')}"
    return f"{s.strftime('%b %-d, %Y')} - {e.strftime('%b %-d, %Y')}"


@app.route('/api/radio/soundcharts/fetch', methods=['POST'])
def radio_soundcharts_fetch():
    """Step 1: Fetch airplay data and return song summary for the picker."""
    data = request.get_json() or {}
    artist = (data.get('artist') or '').strip()
    region = data.get('region', 'latam').strip()
    time_range = data.get('time_range', '28d').strip()
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    err = validate_artist(artist)
    if err:
        return jsonify({'error': err}), 400
    if time_range == 'custom' and (not start_date or not end_date):
        return jsonify({'error': 'Please select both start and end dates.'}), 400

    sort_col, play_key = RANGE_MAP.get(time_range, RANGE_MAP['28d'])

    job_id = new_job()

    def run():
        try:
            from shared.soundcharts import search_artist, fetch_airplay_data, get_token

            token = get_token()
            if not token:
                finish_job(job_id, error='Soundcharts credentials not configured. Go to Settings to add them.')
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
                region_desc = 'LATAM' if region == 'latam' else 'any region'
                finish_job(job_id, error=f'No radio plays found for {match["name"]} in {region_desc}.')
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
            if not songs:
                region_desc = 'LATAM' if region == 'latam' else 'any region'
                finish_job(job_id, error=f'No radio plays found for {match["name"]} in {region_desc} during the selected time range.')
                return
            finish_job(job_id, result={'songs': songs, 'total_entries': len(airplay), 'range_label': range_label, 'is_custom': is_custom})

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/radio/soundcharts/generate', methods=['POST'])
def radio_soundcharts_generate():
    """Step 2: Filter cached airplay data to selected songs and generate report."""
    data = request.get_json() or {}
    fetch_job_id = data.get('fetch_job_id', '').strip()
    artist = (data.get('artist') or '').strip()
    selected_songs = data.get('selected_songs', [])
    time_range = data.get('time_range', '').strip()
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()

    if not fetch_job_id or fetch_job_id not in jobs or 'airplay_cache' not in jobs.get(fetch_job_id, {}):
        return jsonify({'error': 'Airplay data expired. Please fetch songs again.'}), 400
    err = validate_artist(artist)
    if err:
        return jsonify({'error': err}), 400
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
            period_title = compute_radio_date_range(time_range, start_date, end_date)
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

            # Store structured data for Google Docs append
            jobs[job_id]['artist'] = artist
            jobs[job_id]['radio_data'] = filtered
            jobs[job_id]['radio_date_range'] = compute_radio_date_range(
                time_range, start_date, end_date)

            if proc.returncode != 0:
                finish_job(job_id, error='Report generation failed.')
            elif output_path.exists():
                finish_job(job_id, result='Report generated successfully!', output_path=output_path)
            else:
                finish_job(job_id, error='Report file was not created.')
        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/radio/soundcharts/batch', methods=['POST'])
def radio_soundcharts_batch():
    """Batch mode: fetch + generate radio reports for multiple artists from release schedule."""
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'week')  # week | all
    week = (data.get('week') or 'current').strip()
    region = data.get('region', 'latam').strip()
    time_range = data.get('time_range', '28d').strip()
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    auto_append = data.get('auto_append', False)

    if time_range == 'custom' and (not start_date or not end_date):
        return jsonify({'error': 'Please select both start and end dates.'}), 400

    if mode == 'week' and week != 'current':
        from datetime import datetime as _dt
        try:
            _dt.strptime(week, '%Y-%m-%d')
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid week date. Use YYYY-MM-DD format or "current".'}), 400

    sort_col, play_key = RANGE_MAP.get(time_range, RANGE_MAP['28d'])

    # Load and filter releases if no specific artists provided
    artist_list = data.get('artists', [])
    if not artist_list:
        from shared.database import load_release_schedule
        schedule_url = os.environ.get(
            'RELEASE_SCHEDULE_URL',
            'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
        )
        try:
            releases = load_release_schedule(schedule_url)
        except Exception:
            return jsonify({'error': 'Could not load release schedule.'}), 500

        if mode == 'week':
            dsp_spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
            dsp_spec = importlib.util.spec_from_file_location('dsp_pickup_filter', str(dsp_spec_path))
            dsp_mod = importlib.util.module_from_spec(dsp_spec)
            dsp_mod.loader.exec_module(dsp_mod)
            releases = dsp_mod.filter_releases_by_week(releases, week)

        # Deduplicate artists
        seen = set()
        for r in releases:
            a = r['artist']
            if a and a not in seen:
                seen.add(a)
                artist_list.append(a)

    if not artist_list:
        return jsonify({'error': 'No releases found matching your criteria.'}), 400

    batch_id = new_job()
    jobs[batch_id]['batch'] = True
    jobs[batch_id]['artist_statuses'] = [
        {'artist': a, 'status': 'queued', 'result_count': 0, 'error': None, 'output_path': None}
        for a in artist_list
    ]
    if auto_append:
        jobs[batch_id]['append_results'] = {}
        jobs[batch_id]['batch_artist_data'] = {}

    def run():
        try:
            from shared.soundcharts import search_artist, fetch_airplay_data, get_token, airplay_to_csv

            if auto_append:
                from shared.history import get_artist_doc

            token = get_token()
            if not token:
                finish_job(batch_id, error='Soundcharts credentials not configured. Go to Settings to add them.')
                return

            statuses = jobs[batch_id]['artist_statuses']
            docx_paths = []

            for i, astat in enumerate(statuses):
                art = astat['artist']
                astat['status'] = 'running'

                try:
                    match = search_artist(art, token=token)
                    if not match:
                        astat['status'] = 'done'
                        astat['error'] = 'Not found on Soundcharts'
                        log_line(batch_id, f'  Not found on Soundcharts')
                        if auto_append:
                            jobs[batch_id]['append_results'][art] = {
                                'status': 'skipped', 'detail': 'Not found on Soundcharts', 'doc_title': None}
                        continue

                    airplay = fetch_airplay_data(match['uuid'], token, sort_by=sort_col,
                                                 region=region if region != 'all' else None)
                    if not airplay:
                        astat['status'] = 'done'
                        astat['error'] = 'No airplay data'
                        log_line(batch_id, f'  No radio plays found')
                        if auto_append:
                            jobs[batch_id]['append_results'][art] = {
                                'status': 'skipped', 'detail': 'No radio plays found', 'doc_title': None}
                        continue

                    for e in airplay:
                        e['plays_28d'] = e[play_key]

                    upload_dir = UPLOAD_DIR / f'{batch_id}_{i}'
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    csv_path = upload_dir / 'soundcharts_airplay.csv'
                    airplay_to_csv(airplay, str(csv_path))

                    safe_art = art.lower().replace(' ', '_')
                    output_path = REPORT_DIR / f'{safe_art}_radio.docx'

                    period_title = compute_radio_date_range(time_range, start_date, end_date)

                    cmd = [
                        'node',
                        str(ROOT_DIR / 'airplay-report' / 'generate_report.js'),
                        '--artist', art,
                        '--input', str(upload_dir),
                        '--output', str(output_path),
                        '--period', period_title,
                    ]
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, cwd=str(ROOT_DIR),
                    )
                    proc.wait()

                    if proc.returncode == 0 and output_path.exists():
                        docx_paths.append(output_path)
                        astat['status'] = 'done'
                        astat['result_count'] = len(airplay)
                        astat['output_path'] = str(output_path)

                        # Auto-append to Google Doc
                        if auto_append and airplay:
                            jobs[batch_id]['batch_artist_data'][art] = {'radio_data': airplay}
                            doc = get_artist_doc(art)
                            if doc:
                                ar = _batch_auto_append(art, doc['doc_id'], radio_data=airplay,
                                                        radio_date_range=compute_radio_date_range(time_range, start_date, end_date))
                                jobs[batch_id]['append_results'][art] = ar
                                if ar['status'] == 'appended':
                                    log_line(batch_id, f'  \u2713 Appended to Google Doc: {ar["doc_title"]}')
                                elif ar['status'] == 'skipped':
                                    log_line(batch_id, f'  \u26a0 Skipped: {ar["detail"]}')
                                else:
                                    log_line(batch_id, f'  \u2717 Append failed: {ar["detail"]}')
                                time.sleep(1)  # Rate limiting
                            else:
                                jobs[batch_id]['append_results'][art] = {
                                    'status': 'no_doc', 'detail': 'No Google Doc linked', 'doc_title': None}
                    else:
                        astat['status'] = 'done'
                        astat['error'] = 'Report generation failed'

                except Exception as e:
                    astat['status'] = 'error'
                    astat['error'] = str(e)

            # Create combined outputs
            safe_batch = f'batch_week_{week}' if mode == 'week' else 'batch_all'
            if docx_paths:
                import zipfile
                zip_path = REPORT_DIR / f'{safe_batch}_radio.zip'
                with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
                    for dp in docx_paths:
                        zf.write(str(dp), dp.name)
                jobs[batch_id]['batch_zip'] = str(zip_path)

                combined_docx = REPORT_DIR / f'{safe_batch}_radio.docx'
                try:
                    combine_docx(docx_paths, combined_docx)
                    jobs[batch_id]['batch_combined_docx'] = str(combined_docx)
                except Exception:
                    pass

            finish_job(batch_id, result='Batch complete.')

        except Exception as e:
            finish_job(batch_id, error=str(e))

    threading.Thread(target=run_with_limit(batch_id, run), daemon=True).start()
    return jsonify({
        'batch_id': batch_id,
        'artist_jobs': [{'artist': a, 'index': i} for i, a in enumerate(artist_list)]
    })


# ---------------------------------------------------------------------------
# Press Pickup
# ---------------------------------------------------------------------------

@app.route('/api/press/run', methods=['POST'])
def press_run():
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'artist')  # artist | week | all
    artist = (data.get('artist') or '').strip()
    week = (data.get('week') or 'current').strip()
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    days = data.get('days', 28)
    auto_append = data.get('auto_append', False)

    if mode == 'artist':
        err = validate_artist(artist)
        if err:
            return jsonify({'error': err}), 400

    if mode == 'week' and week != 'current':
        from datetime import datetime as _dt
        try:
            _dt.strptime(week, '%Y-%m-%d')
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid week date. Use YYYY-MM-DD format or "current".'}), 400

    # Custom date range or preset days
    if start_date and end_date:
        log_label = f'{start_date} to {end_date}'
    else:
        try:
            days = int(days)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid value for days. Please provide a number.'}), 400
        if days < 1:
            return jsonify({'error': 'Days must be at least 1.'}), 400
        start_date = None
        end_date = None
        log_label = f'last {days} days'

    # --- Single artist mode (unchanged) ---
    if mode == 'artist':
        job_id = new_job()

        def run():
            try:
                spec_path = ROOT_DIR / 'press-pickup' / 'press_pickup.py'
                spec = importlib.util.spec_from_file_location('press_pickup', str(spec_path))
                mod = importlib.util.module_from_spec(spec)
                with capture_stdout(on_write=make_incremental_logger(job_id)) as buf:
                    spec.loader.exec_module(mod)

                kwargs = {}
                if start_date and end_date:
                    kwargs['start_date'] = start_date
                    kwargs['end_date'] = end_date

                safe_artist = artist.lower().replace(' ', '_')
                output_path = REPORT_DIR / f'{safe_artist}_press.txt'
                log_line(job_id, f'Searching for press coverage of {artist} ({log_label})...')

                with capture_stdout(on_write=make_incremental_logger(job_id)) as buf:
                    country_results = mod.run_press_pickup(artist, days, str(output_path), **kwargs)

                total = sum(len(v) for v in country_results.values()) if country_results else 0
                result_text = output_path.read_text(encoding='utf-8') if output_path.exists() else ''

                # Store structured data for Google Docs append
                jobs[job_id]['artist'] = artist
                jobs[job_id]['press_data'] = country_results

                if not result_text.strip():
                    finish_job(job_id, result='No press coverage found for this artist in the selected time range.',
                               output_path=output_path if output_path.exists() else None)
                else:
                    log_line(job_id, f'Found {total} results.')
                    finish_job(job_id, result=result_text, output_path=output_path if output_path.exists() else None)

            except SystemExit:
                finish_job(job_id, error='Press pickup failed unexpectedly.')
            except Exception as e:
                finish_job(job_id, error=str(e))

        threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
        return jsonify({'job_id': job_id})

    # --- Batch mode (week / all) — per-artist card dashboard ---
    artist_list = data.get('artists', [])
    if not artist_list:
        from shared.database import load_release_schedule
        schedule_url = os.environ.get(
            'RELEASE_SCHEDULE_URL',
            'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
        )
        try:
            releases = load_release_schedule(schedule_url)
        except Exception:
            return jsonify({'error': 'Could not load release schedule.'}), 500

        if mode == 'week':
            dsp_spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
            dsp_spec = importlib.util.spec_from_file_location('dsp_pickup_filter', str(dsp_spec_path))
            dsp_mod = importlib.util.module_from_spec(dsp_spec)
            dsp_mod.loader.exec_module(dsp_mod)
            releases = dsp_mod.filter_releases_by_week(releases, week)

        # Deduplicate artists
        seen = set()
        for r in releases:
            a = r['artist']
            if a and a not in seen:
                seen.add(a)
                artist_list.append(a)

    if not artist_list:
        return jsonify({'error': 'No releases found matching your criteria.'}), 400

    batch_id = new_job()
    jobs[batch_id]['batch'] = True
    jobs[batch_id]['artist_statuses'] = [
        {'artist': a, 'status': 'queued', 'result_count': 0, 'error': None, 'output_path': None}
        for a in artist_list
    ]
    if auto_append:
        jobs[batch_id]['append_results'] = {}
        jobs[batch_id]['batch_artist_data'] = {}

    def orchestrate():
        try:
            spec_path = ROOT_DIR / 'press-pickup' / 'press_pickup.py'
            spec = importlib.util.spec_from_file_location('press_pickup', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            with capture_stdout(on_write=make_incremental_logger(batch_id)) as buf:
                spec.loader.exec_module(mod)

            if auto_append:
                from shared.history import get_artist_doc

            kwargs = {}
            if start_date and end_date:
                kwargs['start_date'] = start_date
                kwargs['end_date'] = end_date

            statuses = jobs[batch_id]['artist_statuses']
            docx_paths = []

            for i, astat in enumerate(statuses):
                art = astat['artist']
                astat['status'] = 'running'
                safe = art.lower().replace(' ', '_')
                out = REPORT_DIR / f'{safe}_press.txt'
                log_line(batch_id, f'[{i+1}/{len(statuses)}] Processing {art}...')

                try:
                    with capture_stdout(on_write=make_incremental_logger(batch_id)) as buf:
                        country_results = mod.run_press_pickup(art, days, str(out), **kwargs)
                    total = sum(len(v) for v in country_results.values()) if country_results else 0
                    astat['status'] = 'done'
                    astat['result_count'] = total
                    astat['output_path'] = str(out)
                    docx_out = out.with_suffix('.docx')
                    if docx_out.exists():
                        docx_paths.append(docx_out)

                    # Auto-append to Google Doc
                    if auto_append and country_results:
                        jobs[batch_id]['batch_artist_data'][art] = {'press_data': country_results}
                        doc = get_artist_doc(art)
                        if doc:
                            ar = _batch_auto_append(art, doc['doc_id'], press_data=country_results)
                            jobs[batch_id]['append_results'][art] = ar
                            if ar['status'] == 'appended':
                                log_line(batch_id, f'  \u2713 Appended to Google Doc: {ar["doc_title"]}')
                            elif ar['status'] == 'skipped':
                                log_line(batch_id, f'  \u26a0 Skipped: {ar["detail"]}')
                            else:
                                log_line(batch_id, f'  \u2717 Append failed: {ar["detail"]}')
                            time.sleep(1)  # Rate limiting
                        else:
                            jobs[batch_id]['append_results'][art] = {
                                'status': 'no_doc', 'detail': 'No Google Doc linked', 'doc_title': None}
                except Exception as e:
                    astat['status'] = 'error'
                    astat['error'] = str(e)

            # Generate combined outputs
            safe_batch = f'batch_week_{week}' if mode == 'week' else 'batch_all'
            if docx_paths:
                import zipfile
                zip_path = REPORT_DIR / f'{safe_batch}_press.zip'
                with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
                    for dp in docx_paths:
                        zf.write(str(dp), dp.name)
                jobs[batch_id]['batch_zip'] = str(zip_path)

                combined_docx = REPORT_DIR / f'{safe_batch}_press.docx'
                try:
                    combine_docx(docx_paths, combined_docx)
                    jobs[batch_id]['batch_combined_docx'] = str(combined_docx)
                except Exception:
                    pass

            finish_job(batch_id, result='Batch complete.')

        except Exception as e:
            finish_job(batch_id, error=str(e))

    threading.Thread(target=run_with_limit(batch_id, orchestrate), daemon=True).start()
    return jsonify({
        'batch_id': batch_id,
        'artist_jobs': [{'artist': a, 'index': i} for i, a in enumerate(artist_list)]
    })


# ---------------------------------------------------------------------------
# DSP Pickup
# ---------------------------------------------------------------------------

@app.route('/api/dsp/run', methods=['POST'])
def dsp_run():
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'artist')  # artist | week | all
    artist = (data.get('artist') or '').strip()
    week = data.get('week', 'current').strip()
    platforms = data.get('platforms', None)  # list of platform names, or None for all
    grouping = data.get('grouping', 'platform')
    auto_append = data.get('auto_append', False)

    VALID_PLATFORMS = {'Spotify', 'Apple Music', 'Deezer', 'Amazon Music', 'Claro Música', 'YouTube Music'}

    if mode == 'artist':
        err = validate_artist(artist)
        if err:
            return jsonify({'error': err}), 400

    if platforms is not None:
        if not isinstance(platforms, list) or len(platforms) == 0:
            return jsonify({'error': 'Please select at least one platform.'}), 400
        bad = [p for p in platforms if p not in VALID_PLATFORMS]
        if bad:
            return jsonify({'error': f'Unsupported platform(s): {", ".join(bad)}. Supported: {", ".join(sorted(VALID_PLATFORMS))}'}), 400

    if mode == 'week' and week != 'current':
        from datetime import datetime as _dt
        try:
            _dt.strptime(week, '%Y-%m-%d')
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid week date. Use YYYY-MM-DD format or "current".'}), 400

    job_id = new_job()

    def run():
        try:
            from shared.database import load_playlist_database, load_release_schedule

            log_line(job_id, 'Loading playlist database...')
            pl_path = os.environ.get('PLAYLIST_DB_PATH', str(ROOT_DIR / 'data' / 'playlist_database.csv'))
            playlists = load_playlist_database(pl_path)
            log_line(job_id, f'  Loaded {len(playlists)} playlists')

            if platforms and isinstance(platforms, list) and len(platforms) < 6:
                playlists = [p for p in playlists if p['platform'] in platforms]
                log_line(job_id, f'  Filtered to {len(playlists)} playlists ({", ".join(platforms)})')

            schedule_url = os.environ.get(
                'RELEASE_SCHEDULE_URL',
                'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
            )
            log_line(job_id, 'Loading release schedule...')
            try:
                releases = load_release_schedule(schedule_url)
                log_line(job_id, f'  Loaded {len(releases)} releases')
            except Exception as e:
                log_line(job_id, f'  Release schedule unavailable: {e}')
                releases = []

            # Filter releases
            if mode == 'artist':
                search_lower = artist.lower()
                releases = [r for r in releases if search_lower in r['artist'].lower() or r['artist'].lower() in search_lower]
                if not releases:
                    # No schedule entry — create a synthetic one for artist-only playlist matching
                    releases = [{'artist': artist, 'title': '', 'focus_track': '', 'date': '', 'type': ''}]
                    log_line(job_id, f'  No releases in schedule for {artist} — searching playlists by artist name')
                else:
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

            # Filter by selected artists if provided (from batch preview UI)
            selected_artists = data.get('artists', [])
            if selected_artists and mode != 'artist':
                selected_set = set(selected_artists)
                releases = [r for r in releases if r['artist'] in selected_set]
                log_line(job_id, f'  Selected {len(releases)} of {len(selected_set)} artists')

            if not releases:
                finish_job(job_id, result='No releases found matching your criteria.')
                return

            # Use job-scoped subdirectory so concurrent DSP jobs don't share proof images
            job_dir = REPORT_DIR / f'dsp_{job_id}'
            job_dir.mkdir(exist_ok=True)
            output_path = job_dir / f'{safe_name}_dsp.txt'

            with capture_stdout(on_write=make_incremental_logger(job_id)) as buf:
                spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
                import importlib.util
                spec = importlib.util.spec_from_file_location('dsp_pickup_run', str(spec_path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                results = mod.run_dsp_pickup(releases, playlists, str(output_path), grouping=grouping)

            # Read the generated report
            result_text = output_path.read_text(encoding='utf-8') if output_path.exists() else ''

            total_matches = sum(
                len(matches)
                for artist_releases in results.values()
                for matches in artist_releases.values()
            ) if results else 0

            if total_matches:
                log_line(job_id, f'Found {total_matches} playlist placements!')
            else:
                log_line(job_id, 'No matches found in checked playlists.')

            # Collect proof images from job-scoped proof dir
            proof_images = []
            proof_dir = job_dir / 'dsp_proofs'
            if proof_dir.exists():
                proof_images = sorted([f.name for f in proof_dir.glob('proof_*.png')])
                # Copy proofs to shared dir for the download endpoint
                shared_proof_dir = REPORT_DIR / 'dsp_proofs'
                shared_proof_dir.mkdir(exist_ok=True)
                for img in proof_dir.glob('proof_*.png'):
                    shutil.copy2(str(img), str(shared_proof_dir / img.name))

            jobs[job_id]['proof_images'] = proof_images
            jobs[job_id]['artist'] = artist
            jobs[job_id]['dsp_data'] = results

            # Auto-append to Google Docs (batch modes only)
            if auto_append and mode != 'artist' and results:
                from shared.history import get_artist_doc
                jobs[job_id]['append_results'] = {}
                jobs[job_id]['batch_artist_data'] = {}

                # Collect proof image paths per artist
                proof_dir_path = job_dir / 'dsp_proofs'
                all_proof_paths = sorted(str(p) for p in proof_dir_path.glob('proof_*.png')) if proof_dir_path.exists() else []

                for art, art_releases in results.items():
                    art_matches = sum(len(m) for m in art_releases.values())
                    if not art_matches:
                        jobs[job_id]['append_results'][art] = {
                            'status': 'skipped', 'detail': 'No playlist matches', 'doc_title': None}
                        continue

                    art_dsp_data = {art: art_releases}
                    jobs[job_id]['batch_artist_data'][art] = {'dsp_data': art_dsp_data}

                    doc = get_artist_doc(art)
                    if doc:
                        ar = _batch_auto_append(art, doc['doc_id'], dsp_data=art_dsp_data,
                                                proof_image_paths=all_proof_paths)
                        jobs[job_id]['append_results'][art] = ar
                        if ar['status'] == 'appended':
                            log_line(job_id, f'  \u2713 Appended to Google Doc: {ar["doc_title"]}')
                        elif ar['status'] == 'skipped':
                            log_line(job_id, f'  \u26a0 Skipped: {ar["detail"]}')
                        else:
                            log_line(job_id, f'  \u2717 Append failed: {ar["detail"]}')
                        time.sleep(1)  # Rate limiting
                    else:
                        jobs[job_id]['append_results'][art] = {
                            'status': 'no_doc', 'detail': 'No Google Doc linked', 'doc_title': None}

            finish_job(job_id, result=result_text, output_path=output_path if output_path.exists() else None)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
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

@app.route('/gangsigns')
def gangsigns():
    return render_template('gangsigns.html')



@app.route('/oracle')
def oracle():
    return render_template('oracle.html')


@app.route('/api/releases')
def api_releases():
    """Return release schedule as JSON with computed phase per release."""
    from datetime import datetime, timedelta
    from shared.database import load_release_schedule

    schedule_url = os.environ.get(
        'RELEASE_SCHEDULE_URL',
        'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
    )
    try:
        releases = load_release_schedule(schedule_url)
    except Exception as e:
        return jsonify({'error': f'Release schedule unavailable: {e}'}), 503
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


@app.route('/api/releases/preview', methods=['POST'])
def releases_preview():
    """Return filtered artist list for batch mode preview."""
    from datetime import datetime as _dt
    from shared.database import load_release_schedule

    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'week')
    week = (data.get('week') or 'current').strip()

    schedule_url = os.environ.get(
        'RELEASE_SCHEDULE_URL',
        'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
    )
    try:
        releases = load_release_schedule(schedule_url)
    except Exception:
        return jsonify({'error': 'Could not load release schedule.'}), 500

    if mode == 'week':
        spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
        spec = importlib.util.spec_from_file_location('dsp_pickup_preview', str(spec_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        releases = mod.filter_releases_by_week(releases, week)

    # Deduplicate artists, preserving order
    seen = set()
    artists = []
    for r in releases:
        a = r['artist']
        if a and a not in seen:
            seen.add(a)
            artists.append({'artist': a, 'title': r.get('title', ''), 'date': r.get('date', '')})

    return jsonify({'artists': artists, 'total': len(artists)})


# ---------------------------------------------------------------------------
# Report Compiler
# ---------------------------------------------------------------------------

@app.route('/api/report/compile', methods=['POST'])
def report_compile():
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'artist')  # artist | week | all
    artist = (data.get('artist') or '').strip()
    week = (data.get('week') or 'current').strip()
    auto_append = data.get('auto_append', False)
    press_days = data.get('press_days', data.get('days', 28))
    press_start_date = data.get('press_start_date')
    press_end_date = data.get('press_end_date')
    radio_region = data.get('radio_region', 'latam')
    radio_time_range = data.get('radio_time_range', '28d')
    radio_start_date = data.get('radio_start_date')
    radio_end_date = data.get('radio_end_date')
    efforts_text = data.get('efforts_text', '')
    include_radio = data.get('include_radio', True)
    include_dsp = data.get('include_dsp', True)
    include_press = data.get('include_press', True)

    if mode == 'artist':
        err = validate_artist(artist)
        if err:
            return jsonify({'error': err}), 400

    if mode == 'week' and week != 'current':
        from datetime import datetime as _dt
        try:
            _dt.strptime(week, '%Y-%m-%d')
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid week date. Use YYYY-MM-DD format or "current".'}), 400

    if not include_radio and not include_dsp and not include_press:
        return jsonify({'error': 'Please enable at least one section (Radio, Press, or DSP).'}), 400

    if press_start_date and press_end_date:
        pass  # custom date range, no days needed
    else:
        try:
            press_days = int(press_days)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid value for press days. Please provide a number.'}), 400
        if press_days < 1:
            return jsonify({'error': 'Press days must be at least 1.'}), 400

    # --- Single artist mode ---
    if mode == 'artist':
        job_id = new_job()
        safe_artist = artist.lower().replace(' ', '_')
        output_path = REPORT_DIR / f'{safe_artist}_full_report.docx'

        def run():
            try:
                spec_path = ROOT_DIR / 'report-compiler' / 'compile_report.py'
                spec = importlib.util.spec_from_file_location('compile_report', str(spec_path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                result = mod.compile_report(
                    artist=artist,
                    press_days=press_days,
                    press_start_date=press_start_date,
                    press_end_date=press_end_date,
                    radio_region=radio_region,
                    radio_time_range=radio_time_range,
                    radio_start_date=radio_start_date,
                    radio_end_date=radio_end_date,
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

                # Store structured data for Google Docs append
                jobs[job_id]['artist'] = artist
                jobs[job_id]['radio_data'] = result.get('radio_data')
                jobs[job_id]['press_data'] = result.get('press_data')
                jobs[job_id]['dsp_data'] = result.get('dsp_data')
                jobs[job_id]['radio_date_range'] = compute_radio_date_range(
                    radio_time_range, radio_start_date, radio_end_date)

                finish_job(job_id, result=summary, output_path=output_path)

            except Exception as e:
                finish_job(job_id, error=str(e))

        threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
        return jsonify({'job_id': job_id})

    # --- Batch mode (week / all) ---
    artist_list = data.get('artists', [])
    if not artist_list:
        from shared.database import load_release_schedule
        schedule_url = os.environ.get(
            'RELEASE_SCHEDULE_URL',
            'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
        )
        try:
            releases = load_release_schedule(schedule_url)
        except Exception:
            return jsonify({'error': 'Could not load release schedule.'}), 500

        if mode == 'week':
            dsp_spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
            dsp_spec = importlib.util.spec_from_file_location('dsp_pickup_filter', str(dsp_spec_path))
            dsp_mod = importlib.util.module_from_spec(dsp_spec)
            dsp_mod.loader.exec_module(dsp_mod)
            releases = dsp_mod.filter_releases_by_week(releases, week)

        seen = set()
        for r in releases:
            a = r['artist']
            if a and a not in seen:
                seen.add(a)
                artist_list.append(a)

    if not artist_list:
        return jsonify({'error': 'No releases found matching your criteria.'}), 400

    batch_id = new_job()
    jobs[batch_id]['batch'] = True
    jobs[batch_id]['artist_statuses'] = [
        {'artist': a, 'status': 'queued', 'result_count': 0, 'error': None, 'output_path': None}
        for a in artist_list
    ]
    if auto_append:
        jobs[batch_id]['append_results'] = {}

    radio_date_range = compute_radio_date_range(
        radio_time_range, radio_start_date, radio_end_date)

    def orchestrate():
        try:
            spec_path = ROOT_DIR / 'report-compiler' / 'compile_report.py'
            spec = importlib.util.spec_from_file_location('compile_report', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            if auto_append:
                from shared.history import get_artist_doc

            statuses = jobs[batch_id]['artist_statuses']
            docx_paths = []

            for i, astat in enumerate(statuses):
                art = astat['artist']
                astat['status'] = 'running'
                safe = art.lower().replace(' ', '_')
                out = REPORT_DIR / f'{safe}_full_report.docx'
                log_line(batch_id, f'[{i+1}/{len(statuses)}] Processing {art}...')

                try:
                    result = mod.compile_report(
                        artist=art,
                        press_days=press_days,
                        press_start_date=press_start_date,
                        press_end_date=press_end_date,
                        radio_region=radio_region,
                        radio_time_range=radio_time_range,
                        radio_start_date=radio_start_date,
                        radio_end_date=radio_end_date,
                        efforts_text='',
                        output_path=str(out),
                        log_fn=lambda msg, _bid=batch_id: log_line(_bid, msg),
                        include_radio=include_radio,
                        include_dsp=include_dsp,
                        include_press=include_press,
                    )

                    # Count results
                    total = 0
                    if result.get('radio_data'):
                        total += len(result['radio_data'])
                    if result.get('dsp_data'):
                        total += sum(len(m) for r in result['dsp_data'].values() for m in r.values())
                    if result.get('press_data'):
                        total += sum(len(v) for v in result['press_data'].values())

                    astat['status'] = 'done'
                    astat['result_count'] = total
                    astat['output_path'] = str(out)
                    if out.exists():
                        docx_paths.append(out)

                    # Auto-append to Google Doc
                    if auto_append:
                        # Collect proof image paths
                        proof_dir = REPORT_DIR / 'dsp_proofs'
                        proof_paths = sorted([str(f) for f in proof_dir.glob('proof_*.png')]) if proof_dir.exists() else []

                        doc = get_artist_doc(art)
                        if doc:
                            ar = _batch_auto_append(
                                art, doc['doc_id'],
                                radio_data=result.get('radio_data'),
                                dsp_data=result.get('dsp_data'),
                                press_data=result.get('press_data'),
                                proof_image_paths=proof_paths or None,
                                radio_date_range=radio_date_range,
                            )
                            jobs[batch_id]['append_results'][art] = ar
                            if ar['status'] == 'appended':
                                log_line(batch_id, f'  \u2713 Appended to Google Doc: {ar["doc_title"]}')
                            elif ar['status'] == 'skipped':
                                log_line(batch_id, f'  \u26a0 Skipped: {ar["detail"]}')
                            else:
                                log_line(batch_id, f'  \u2717 Append failed: {ar["detail"]}')
                            time.sleep(1)  # Rate limiting
                        else:
                            jobs[batch_id]['append_results'][art] = {
                                'status': 'no_doc', 'detail': 'No Google Doc linked', 'doc_title': None}

                except Exception as e:
                    astat['status'] = 'error'
                    astat['error'] = str(e)
                    log_line(batch_id, f'  Error: {e}')

            # Generate combined outputs
            safe_batch = f'batch_week_{week}' if mode == 'week' else 'batch_all'
            if docx_paths:
                import zipfile
                zip_path = REPORT_DIR / f'{safe_batch}_reports.zip'
                with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
                    for dp in docx_paths:
                        zf.write(str(dp), dp.name)
                jobs[batch_id]['batch_zip'] = str(zip_path)

                combined_docx = REPORT_DIR / f'{safe_batch}_reports.docx'
                try:
                    combine_docx(docx_paths, combined_docx)
                    jobs[batch_id]['batch_combined_docx'] = str(combined_docx)
                except Exception:
                    pass

            done = sum(1 for s in statuses if s['status'] == 'done')
            errs = sum(1 for s in statuses if s['status'] == 'error')
            summary = f'Batch complete: {done}/{len(statuses)} reports generated'
            if errs:
                summary += f' ({errs} failed)'
            finish_job(batch_id, result=summary)

        except Exception as e:
            finish_job(batch_id, error=str(e))

    threading.Thread(target=run_with_limit(batch_id, orchestrate), daemon=True).start()
    return jsonify({
        'batch_id': batch_id,
        'artist_jobs': [{'artist': a, 'index': i} for i, a in enumerate(artist_list)]
    })


# ---------------------------------------------------------------------------
# Outlet Discovery
# ---------------------------------------------------------------------------

@app.route('/api/discovery/search', methods=['POST'])
def discovery_search():
    data = request.get_json(silent=True) or {}
    genre = (data.get('genre') or 'general music').strip()
    countries = data.get('countries', ['All LATAM'])
    custom_query = data.get('custom_query', '')
    use_llm = data.get('use_llm', True)

    if not genre:
        genre = 'general music'
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

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
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
    artist = (data.get('artist') or '').strip()
    days = data.get('days', 7)
    radio_region = data.get('radio_region', 'latam')
    radio_time_range = data.get('radio_time_range', '7d')
    next_steps = data.get('next_steps', '')
    sender_name = data.get('sender_name', '')
    contact_name = data.get('contact_name', '')
    include_radio = data.get('include_radio', True)
    include_dsp = data.get('include_dsp', True)
    include_press = data.get('include_press', True)

    err = validate_artist(artist)
    if err:
        return jsonify({'error': err}), 400

    try:
        days = int(days)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid value for days. Please provide a number.'}), 400
    if days < 1:
        return jsonify({'error': 'Days must be at least 1.'}), 400

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

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/digest/batch', methods=['POST'])
def digest_batch():
    """Run digests for multiple artists sequentially."""
    data = request.get_json(silent=True) or {}
    artists = data.get('artists', [])
    mode = data.get('mode', 'digest')  # 'digest' or 'snapshot'
    radio_region = data.get('radio_region', 'latam')
    radio_time_range = data.get('radio_time_range', '7d')
    include_radio = data.get('include_radio', True)
    include_dsp = data.get('include_dsp', True)
    include_press = data.get('include_press', True)

    if not artists or not isinstance(artists, list):
        return jsonify({'error': 'Please select at least one artist.'}), 400

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for a in artists:
        name = a.strip()
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    artists = unique

    if not artists:
        return jsonify({'error': 'Please select at least one artist.'}), 400

    for a in artists:
        err = validate_artist(a)
        if err:
            return jsonify({'error': f'Invalid artist "{a}": {err}'}), 400

    daysMap = {'7d': 7, '28d': 28}
    days = daysMap.get(radio_time_range, 7)

    job_id = new_job()
    jobs[job_id]['batch'] = True
    jobs[job_id]['batch_results'] = {}

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'digest-generator' / 'generate_digest.py'
            spec = importlib.util.spec_from_file_location('generate_digest', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            total = len(artists)
            with_activity = 0

            for i, artist in enumerate(artists, 1):
                log_line(job_id, f"[{i}/{total}] Running digest for {artist}...")

                try:
                    result = mod.generate_digest(
                        artist=artist,
                        days=days,
                        radio_region=radio_region,
                        radio_time_range=radio_time_range,
                        next_steps='',
                        sender_name='',
                        contact_name='',
                        include_radio=include_radio,
                        include_dsp=include_dsp,
                        include_press=include_press,
                        log_fn=lambda msg, _jid=job_id: log_line(_jid, f"  {msg}"),
                    )

                    entry = {
                        'radio_count': result.get('radio_count', 0),
                        'dsp_count': result.get('dsp_count', 0),
                        'press_count': result.get('press_count', 0),
                    }

                    has_activity = (entry['radio_count'] or entry['dsp_count']
                                    or entry['press_count'])
                    if has_activity:
                        with_activity += 1

                    if mode == 'digest':
                        entry['html'] = result.get('html', '')
                        entry['text'] = result.get('text', '')

                    jobs[job_id]['batch_results'][artist] = entry

                    counts = []
                    if entry['radio_count']:
                        counts.append(f"Radio: {entry['radio_count']}")
                    if entry['dsp_count']:
                        counts.append(f"DSP: {entry['dsp_count']}")
                    if entry['press_count']:
                        counts.append(f"Press: {entry['press_count']}")
                    status_str = ' | '.join(counts) if counts else 'No activity'
                    log_line(job_id, f"  => {artist}: {status_str}")

                except Exception as e:
                    log_line(job_id, f"  => {artist}: Error — {e}")
                    jobs[job_id]['batch_results'][artist] = {
                        'radio_count': 0, 'dsp_count': 0, 'press_count': 0,
                        'error': str(e),
                    }

            no_data = total - with_activity
            summary = f"{total} artists processed: {with_activity} with activity"
            if no_data:
                summary += f", {no_data} no data"
            finish_job(job_id, result=summary)

        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
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
    artist = (data.get('artist') or '').strip()

    err = validate_artist(artist)
    if err:
        return jsonify({'error': err}), 400

    genre = (data.get('genre') or 'general').strip()
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

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
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
            if not uploaded.filename.lower().endswith('.docx'):
                return jsonify({'error': 'Please upload a .docx file. Other formats are not supported.'}), 400
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

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
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
# Artist Dashboard
# ---------------------------------------------------------------------------

RELEASE_SCHEDULE_URL = os.environ.get(
    'RELEASE_SCHEDULE_URL',
    'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
)


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@app.route('/compare')
def compare():
    return render_template('compare.html')


@app.route('/api/dashboard/artists')
def dashboard_artists():
    """List artists: those with snapshot data + those from release schedule."""
    from shared.history import get_artists
    from shared.database import load_release_schedule

    with_data = get_artists()
    # Normalize key: history DB uses 'artist', frontend expects 'name'
    for a in with_data:
        a['name'] = a.pop('artist')
    data_names = {a['name'] for a in with_data}

    # Get unique artist names from release schedule
    try:
        releases = load_release_schedule(RELEASE_SCHEDULE_URL)
        schedule_names = sorted({r['artist'] for r in releases} - data_names)
    except Exception:
        schedule_names = []

    return jsonify({
        'with_data': with_data,
        'from_schedule': schedule_names,
    })


@app.route('/api/dashboard/compare')
def dashboard_compare():
    """Get snapshot data for multiple artists (max 4) in one call."""
    from shared.history import get_artist_history
    names = request.args.get('artists', '')
    artists = [n.strip() for n in names.split(',') if n.strip()][:4]
    result = {}
    for name in artists:
        snapshots = get_artist_history(name, days=365)
        result[name] = {'artist': name, 'snapshots': snapshots}
    return jsonify(result)


@app.route('/api/dashboard/<path:artist>')
def dashboard_artist(artist):
    """Get historical snapshots for a specific artist."""
    from shared.history import get_artist_history
    snapshots = get_artist_history(artist.strip(), days=365)
    return jsonify({'artist': artist.strip(), 'snapshots': snapshots})


@app.route('/api/dashboard/collect', methods=['POST'])
def dashboard_collect():
    """Trigger a fresh data collection for an artist (reuses digest pipeline)."""
    data = request.get_json(silent=True) or {}
    artist = (data.get('artist') or '').strip()
    if not artist:
        return jsonify({'error': 'Artist name required'}), 400

    job_id = new_job()

    def run():
        try:
            import importlib.util
            spec_path = ROOT_DIR / 'digest-generator' / 'generate_digest.py'
            spec = importlib.util.spec_from_file_location('generate_digest_dash', str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            mod.generate_digest(
                artist=artist,
                days=7,
                radio_region='latam',
                radio_time_range='7d',
                next_steps='',
                sender_name='',
                contact_name='',
                include_radio=True,
                include_dsp=True,
                include_press=True,
                log_fn=lambda msg: log_line(job_id, msg),
            )
            finish_job(job_id, result='Snapshot collected')
        except Exception as e:
            finish_job(job_id, error=str(e))

    threading.Thread(target=run_with_limit(job_id, run), daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/dashboard/<path:artist>/notes')
def dashboard_notes(artist):
    """Get all campaign notes for an artist."""
    from shared.history import get_notes
    return jsonify({'notes': get_notes(artist.strip())})


@app.route('/api/dashboard/notes', methods=['POST'])
def dashboard_add_note():
    """Add a campaign note."""
    from shared.history import add_note
    data = request.get_json(silent=True) or {}
    artist = (data.get('artist') or '').strip()
    text = data.get('text', '').strip()
    if not artist or not text:
        return jsonify({'error': 'Artist and text required'}), 400
    add_note(artist, text)
    return jsonify({'ok': True})


@app.route('/api/dashboard/notes/<int:note_id>', methods=['DELETE'])
def dashboard_delete_note(note_id):
    """Delete a campaign note."""
    from shared.history import delete_note
    delete_note(note_id)
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Schedules API
# ---------------------------------------------------------------------------

@app.route('/api/schedules', methods=['GET'])
def list_schedules():
    from shared.history import get_all_schedules
    schedules = get_all_schedules()
    for s in schedules:
        job = scheduler.get_job(f"schedule_{s['id']}")
        s['next_run_time'] = job.next_run_time.isoformat() if job and job.next_run_time else None
    return jsonify(schedules)


@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    from shared.history import save_schedule
    data = request.get_json(silent=True) or {}
    if not data.get('name', '').strip():
        return jsonify({'error': 'Name is required'}), 400
    cron = data.get('cron_expression', '').strip()
    if not cron:
        return jsonify({'error': 'Cron expression is required'}), 400
    try:
        CronTrigger.from_crontab(cron)
    except Exception as e:
        return jsonify({'error': f'Invalid cron expression: {e}'}), 400
    if data.get('artist_source') == 'manual' and not data.get('artists'):
        return jsonify({'error': 'Please select at least one artist.'}), 400
    new_id = save_schedule(data)
    if data.get('enabled', True):
        _register_scheduler_job(new_id, cron)
    return jsonify({'id': new_id})


@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def edit_schedule(schedule_id):
    from shared.history import update_schedule, get_schedule
    data = request.get_json(silent=True) or {}
    cron = data.get('cron_expression', '').strip() if 'cron_expression' in data else None
    if cron:
        try:
            CronTrigger.from_crontab(cron)
        except Exception as e:
            return jsonify({'error': f'Invalid cron expression: {e}'}), 400
    update_schedule(schedule_id, data)
    sched = get_schedule(schedule_id)
    if not sched:
        return jsonify({'error': 'Schedule not found'}), 404
    job_name = f'schedule_{schedule_id}'
    if sched['enabled']:
        _register_scheduler_job(schedule_id, sched['cron_expression'])
    elif scheduler.get_job(job_name):
        scheduler.remove_job(job_name)
    return jsonify({'ok': True})


@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def remove_schedule(schedule_id):
    from shared.history import get_schedule, delete_schedule
    if not get_schedule(schedule_id):
        return jsonify({'error': 'Schedule not found'}), 404
    job_name = f'schedule_{schedule_id}'
    if scheduler.get_job(job_name):
        scheduler.remove_job(job_name)
    delete_schedule(schedule_id)
    return jsonify({'ok': True})


@app.route('/api/schedules/<int:schedule_id>/run', methods=['POST'])
def trigger_schedule(schedule_id):
    from shared.history import get_schedule
    sched = get_schedule(schedule_id)
    if not sched:
        return jsonify({'error': 'Schedule not found'}), 404
    job_id = new_job()
    threading.Thread(target=_execute_schedule, args=(schedule_id, job_id), daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/schedules/history')
def schedule_history():
    from shared.history import get_schedule_runs
    schedule_id = request.args.get('schedule_id', type=int)
    runs = get_schedule_runs(schedule_id=schedule_id)
    return jsonify(runs)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route('/api/health/internet')
def health_internet():
    return jsonify({'online': _check_internet()})


# ---------------------------------------------------------------------------
# Settings — API Credentials
# ---------------------------------------------------------------------------

CREDENTIAL_SERVICES = {
    'soundcharts': {
        'keys': ['SOUNDCHARTS_EMAIL', 'SOUNDCHARTS_PASSWORD'],
        'labels': {'SOUNDCHARTS_EMAIL': 'Email', 'SOUNDCHARTS_PASSWORD': 'Password'},
        'label': 'Soundcharts',
        'used_by': 'Radio Report, Full Report',
    },
    'serper': {
        'keys': ['SERPER_API_KEY'],
        'labels': {'SERPER_API_KEY': 'API Key'},
        'label': 'Serper.dev',
        'used_by': 'Press Pickup (Google SERP)',
    },
    'searxng': {
        'keys': ['SEARXNG_URL'],
        'labels': {'SEARXNG_URL': 'URL'},
        'defaults': {'SEARXNG_URL': 'http://localhost:8888'},
        'label': 'SearXNG (self-hosted)',
        'used_by': 'Press Pickup (Web Search)',
    },
    'groq': {
        'keys': ['GROQ_API_KEY'],
        'labels': {'GROQ_API_KEY': 'API Key'},
        'label': 'Groq',
        'used_by': 'Press Pickup, Digest, Discovery, Proposal',
    },
    'tavily': {
        'keys': ['TAVILY_API_KEY'],
        'labels': {'TAVILY_API_KEY': 'API Key'},
        'label': 'Tavily',
        'used_by': 'Press Pickup',
    },
    'gemini': {
        'keys': ['GEMINI_API_KEY'],
        'labels': {'GEMINI_API_KEY': 'API Key'},
        'label': 'Google Gemini',
        'used_by': 'PR Translator (AI mode)',
    },
    'gsheets': {
        'keys': ['GSHEETS_SERVICE_ACCOUNT'],
        'labels': {'GSHEETS_SERVICE_ACCOUNT': 'Service Account JSON'},
        'label': 'Google Sheets',
        'used_by': 'Social Metrics',
        'textarea': True,
        'file_backed': 'data/google_service_account.json',
    },
    'github': {
        'keys': ['GITHUB_PAT', 'GITHUB_REPO'],
        'labels': {'GITHUB_PAT': 'Personal Access Token', 'GITHUB_REPO': 'Repository'},
        'defaults': {'GITHUB_REPO': 'gobtech/DMM-Sheets'},
        'label': 'GitHub',
        'used_by': 'Social Metrics (on-demand update)',
    },
}


def _mask_value(val):
    """Return masked version of a credential value."""
    if not val:
        return None
    if len(val) <= 4:
        return '****'
    return '****' + val[-4:]


@app.route('/api/settings/credentials')
def get_credentials():
    services = []
    for sid, info in CREDENTIAL_SERVICES.items():
        fields = []
        for key in info['keys']:
            # File-backed credentials read from a file instead of env
            if info.get('file_backed'):
                fpath = ROOT_DIR / info['file_backed']
                val = '(file present)' if fpath.exists() and fpath.stat().st_size > 10 else ''
            else:
                default = info.get('defaults', {}).get(key, '')
                val = os.environ.get(key, default).strip()
            fields.append({
                'key': key,
                'label': info['labels'].get(key, key),
                'masked': _mask_value(val) if not info.get('file_backed') else ('Configured' if val else None),
                'configured': bool(val),
                'textarea': info.get('textarea', False),
            })
        services.append({
            'id': sid,
            'label': info['label'],
            'used_by': info['used_by'],
            'fields': fields,
        })
    return jsonify({'services': services})


@app.route('/api/settings/credentials/<service>/test', methods=['POST'])
def test_credential(service):
    if service not in CREDENTIAL_SERVICES:
        return jsonify({'ok': False, 'error': 'Unknown service.'}), 404
    import requests as req
    try:
        if service == 'soundcharts':
            email = os.environ.get('SOUNDCHARTS_EMAIL', '').strip()
            pw = os.environ.get('SOUNDCHARTS_PASSWORD', '').strip()
            if not email or not pw:
                return jsonify({'ok': False, 'error': 'Credentials not configured.'})
            resp = req.post('https://graphql.soundcharts.com/', json={
                'operationName': 'Login',
                'query': 'mutation Login($input: LoginInput!) { Login(input: $input) { token expiresAt } }',
                'variables': {'input': {'email': email, 'password': pw}},
            }, headers={'Content-Type': 'application/json'}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if 'errors' in data:
                return jsonify({'ok': False, 'error': data['errors'][0].get('message', 'Login failed')})
            if data.get('data', {}).get('Login', {}).get('token'):
                return jsonify({'ok': True, 'message': 'Logged in successfully.'})
            return jsonify({'ok': False, 'error': 'No token returned.'})

        elif service == 'serper':
            key = os.environ.get('SERPER_API_KEY', '').strip()
            if not key:
                return jsonify({'ok': False, 'error': 'API key not configured.'})
            resp = req.post('https://google.serper.dev/search',
                            headers={'X-API-KEY': key, 'Content-Type': 'application/json'},
                            json={'q': 'test', 'num': 1}, timeout=10)
            if resp.status_code == 402:
                return jsonify({'ok': False, 'error': 'Credits exhausted (402).'})
            resp.raise_for_status()
            return jsonify({'ok': True, 'message': 'Connected. Uses 1 credit per test.'})

        elif service == 'searxng':
            url = os.environ.get('SEARXNG_URL', 'http://localhost:8888').strip()
            resp = req.get(f'{url}/search',
                           params={'q': 'test', 'format': 'json'}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            count = len(data.get('results', []))
            return jsonify({'ok': True, 'message': f'Connected. Test returned {count} results.'})

        elif service == 'groq':
            key = os.environ.get('GROQ_API_KEY', '').strip()
            if not key:
                return jsonify({'ok': False, 'error': 'API key not configured.'})
            resp = req.post('https://api.groq.com/openai/v1/chat/completions',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'model': 'llama-3.3-70b-versatile',
                                  'messages': [{'role': 'user', 'content': 'hi'}],
                                  'max_tokens': 5}, timeout=15)
            resp.raise_for_status()
            return jsonify({'ok': True, 'message': 'Connected successfully.'})

        elif service == 'tavily':
            key = os.environ.get('TAVILY_API_KEY', '').strip()
            if not key:
                return jsonify({'ok': False, 'error': 'API key not configured.'})
            resp = req.post('https://api.tavily.com/search',
                            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                            json={'query': 'test', 'max_results': 1}, timeout=15)
            resp.raise_for_status()
            return jsonify({'ok': True, 'message': 'Connected successfully.'})

        elif service == 'gemini':
            key = os.environ.get('GEMINI_API_KEY', '').strip()
            if not key:
                return jsonify({'ok': False, 'error': 'API key not configured.'})
            resp = req.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}',
                headers={'Content-Type': 'application/json'},
                json={'contents': [{'parts': [{'text': 'hi'}]}],
                      'generationConfig': {'maxOutputTokens': 5}}, timeout=15)
            resp.raise_for_status()
            return jsonify({'ok': True, 'message': 'Connected successfully.'})

        elif service == 'gsheets':
            sa_path = ROOT_DIR / 'data' / 'google_service_account.json'
            if not sa_path.exists():
                return jsonify({'ok': False, 'error': 'Service account JSON not configured.'})
            import gspread
            from google.oauth2.service_account import Credentials
            scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
            creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
            gc = gspread.authorize(creds)
            # Just authenticate — no spreadsheet to open here
            return jsonify({'ok': True, 'message': f'Authenticated as {creds.service_account_email}'})

        elif service == 'github':
            pat = os.environ.get('GITHUB_PAT', '').strip()
            if not pat:
                return jsonify({'ok': False, 'error': 'Personal Access Token not configured.'})
            resp = req.get('https://api.github.com/user',
                           headers={'Authorization': f'token {pat}',
                                    'Accept': 'application/vnd.github.v3+json'},
                           timeout=10)
            resp.raise_for_status()
            username = resp.json().get('login', 'unknown')
            return jsonify({'ok': True, 'message': f'Connected as {username}'})

    except req.exceptions.Timeout:
        return jsonify({'ok': False, 'error': 'Connection timed out.'})
    except req.exceptions.ConnectionError:
        return jsonify({'ok': False, 'error': 'Could not connect to service.'})
    except req.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else '?'
        if code in (401, 403):
            return jsonify({'ok': False, 'error': f'Authentication failed ({code}).'})
        return jsonify({'ok': False, 'error': f'HTTP error {code}.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:200]})


@app.route('/api/settings/credentials/<service>', methods=['POST'])
def save_credential(service):
    if service not in CREDENTIAL_SERVICES:
        return jsonify({'error': 'Unknown service.'}), 404

    svc_info = CREDENTIAL_SERVICES[service]

    # File-backed credentials (e.g. gsheets service account JSON)
    if svc_info.get('file_backed'):
        data = request.get_json(force=True)
        content = data.get(svc_info['keys'][0], '').strip()
        if not content:
            return jsonify({'error': 'No content provided.'}), 400
        # Validate JSON
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict) or 'client_email' not in parsed:
                return jsonify({'error': 'Invalid service account JSON — missing client_email field.'}), 400
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid JSON format.'}), 400
        fpath = ROOT_DIR / svc_info['file_backed']
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, 'w') as f:
            json.dump(parsed, f, indent=2)
        os.chmod(str(fpath), 0o600)
        return jsonify({'ok': True, 'message': 'Service account saved.'})

    allowed_keys = set(svc_info['keys'])
    data = request.get_json(force=True)
    updates = {k: v for k, v in data.items() if k in allowed_keys and isinstance(v, str)}
    if not updates:
        return jsonify({'error': 'No valid fields to update.'}), 400

    # Read, update, and write .env atomically
    env_path = ROOT_DIR / '.env'
    lines = []
    if env_path.exists():
        with open(env_path) as f:
            lines = f.readlines()

    updated_keys = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        content = stripped[7:] if stripped.startswith('export ') else stripped
        if '=' in content:
            key = content.partition('=')[0].strip()
            if key in updates:
                lines[i] = f'export {key}="{updates[key]}"\n'
                updated_keys.add(key)

    for key, val in updates.items():
        if key not in updated_keys:
            lines.append(f'export {key}="{val}"\n')

    tmp_path = env_path.with_suffix('.env.tmp')
    with open(tmp_path, 'w') as f:
        f.writelines(lines)
    os.replace(str(tmp_path), str(env_path))

    # Update running process env + rebuild redact patterns
    for key, val in updates.items():
        os.environ[key] = val
    _build_redact_patterns()

    # Invalidate Soundcharts token cache if credentials changed
    if service == 'soundcharts':
        try:
            import shared.soundcharts as sc
            sc._cached_token = None
            sc._token_expires_at = 0
        except Exception:
            pass

    return jsonify({'ok': True, 'message': 'Credentials saved.'})


@app.route('/api/settings/data-sources')
def get_data_sources():
    result = {}

    # Press DB
    try:
        press_path = ROOT_DIR / 'data' / 'press_database.csv'
        enriched = ROOT_DIR / 'data' / 'press_database_enriched.csv'
        p = enriched if enriched.exists() else press_path
        import csv
        with open(p, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        result['press_db'] = {
            'total': len(rows),
            'with_url': sum(1 for r in rows if r.get('WEBSITE', r.get('website', '')).strip()),
            'updated': os.path.getmtime(p),
        }
    except Exception as e:
        result['press_db'] = {'error': str(e)[:100]}

    # Playlist DB
    try:
        pl_path = ROOT_DIR / 'data' / 'playlist_database.csv'
        import csv
        with open(pl_path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        result['playlists'] = {'total': len(rows), 'updated': os.path.getmtime(pl_path)}
    except Exception as e:
        result['playlists'] = {'error': str(e)[:100]}

    # Feed Registry
    try:
        feed_path = ROOT_DIR / 'data' / 'feed_registry.json'
        if feed_path.exists():
            with open(feed_path) as f:
                registry = json.load(f)
            outlets = registry.get('outlets', {})
            rss = sum(1 for o in outlets.values() if o.get('feed_url') and o.get('feed_type') == 'rss')
            wp = sum(1 for o in outlets.values() if o.get('wp_api_url'))
            result['feed_registry'] = {
                'scanned': len(outlets), 'rss': rss, 'wp': wp, 'none': len(outlets) - rss - wp,
                'generated': registry.get('generated'),
            }
        else:
            result['feed_registry'] = {'error': 'feed_registry.json not found'}
    except Exception as e:
        result['feed_registry'] = {'error': str(e)[:100]}

    # Social Handle Registry
    try:
        sh_path = ROOT_DIR / 'data' / 'social_handle_registry.json'
        if sh_path.exists():
            with open(sh_path) as f:
                sh = json.load(f)
            outlets = sh.get('outlets', {})
            with_any = sum(1 for o in outlets.values() if any(o.get(k) for k in ('instagram', 'facebook', 'twitter')))
            result['social_handles'] = {
                'scanned': len(outlets), 'with_handles': with_any,
                'generated': sh.get('generated'),
            }
        else:
            result['social_handles'] = {'error': 'social_handle_registry.json not found'}
    except Exception as e:
        result['social_handles'] = {'error': str(e)[:100]}

    # Release Schedule
    try:
        from shared.database import load_release_schedule
        releases = load_release_schedule(RELEASE_SCHEDULE_URL)
        result['release_schedule'] = {'total': len(releases)}
    except Exception as e:
        result['release_schedule'] = {'error': str(e)[:100]}

    return jsonify(result)


# ---------------------------------------------------------------------------
# Google Docs Integration
# ---------------------------------------------------------------------------

@app.route('/api/settings/google/status')
def google_status():
    try:
        from shared.google_auth import is_connected, get_user_email, SCOPES
        connected = is_connected()
        email = get_user_email() if connected else None
        return jsonify({
            'connected': connected,
            'email': email,
            'scopes': SCOPES if connected else [],
        })
    except Exception as e:
        return jsonify({'connected': False, 'email': None, 'scopes': [], 'error': str(e)})


@app.route('/api/settings/google/connect', methods=['POST'])
def google_connect():
    """Start OAuth flow in background thread. Returns auth URL for frontend to open.
    Frontend should poll /api/settings/google/status to detect completion."""
    try:
        from shared.google_auth import start_oauth_flow
        auth_url = start_oauth_flow()
        return jsonify({'ok': True, 'auth_url': auth_url})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/settings/google/disconnect', methods=['POST'])
def google_disconnect():
    try:
        from shared.google_auth import disconnect
        disconnect()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/settings/google/docs')
def google_docs_list():
    from shared.history import get_all_artist_docs
    docs = get_all_artist_docs()
    return jsonify(docs)


@app.route('/api/settings/google/docs', methods=['POST'])
def google_docs_link():
    data = request.json or {}
    artist_name = (data.get('artist_name') or '').strip()
    doc_url = (data.get('doc_url') or '').strip()

    if not artist_name or not doc_url:
        return jsonify({'ok': False, 'error': 'artist_name and doc_url are required'}), 400

    if 'docs.google.com/document/d/' not in doc_url:
        return jsonify({'ok': False, 'error': 'Invalid Google Doc URL'}), 400

    from shared.history import save_artist_doc, _extract_doc_id
    doc_id = _extract_doc_id(doc_url)
    if not doc_id:
        return jsonify({'ok': False, 'error': 'Could not extract document ID from URL'}), 400

    # Verify access to the doc
    try:
        from shared.google_auth import get_docs_service
        service = get_docs_service()
        doc = service.documents().get(documentId=doc_id).execute()
        doc_title = doc.get('title', 'Untitled')
    except Exception as e:
        err = str(e)
        if '403' in err or 'permission' in err.lower():
            return jsonify({
                'ok': False,
                'error': "Can't access this doc. Make sure it's shared with the connected Google account."
            }), 403
        if '404' in err:
            return jsonify({'ok': False, 'error': 'Document not found. Check the URL.'}), 404
        return jsonify({'ok': False, 'error': f'Could not access document: {err}'}), 400

    save_artist_doc(artist_name, doc_url, doc_id)
    return jsonify({'ok': True, 'doc_id': doc_id, 'doc_title': doc_title})


@app.route('/api/settings/google/docs/<path:artist_name>', methods=['DELETE'])
def google_docs_unlink(artist_name):
    from shared.history import delete_artist_doc
    delete_artist_doc(artist_name)
    return jsonify({'ok': True})


@app.route('/api/google/doc-info/<doc_id>')
def google_doc_info(doc_id):
    try:
        from shared.google_auth import get_docs_service
        service = get_docs_service()
        doc = service.documents().get(documentId=doc_id).execute()
        return jsonify({
            'accessible': True,
            'title': doc.get('title', 'Untitled'),
            'doc_id': doc_id,
        })
    except Exception as e:
        err = str(e)
        if '403' in err or 'permission' in err.lower():
            return jsonify({'accessible': False, 'error': 'Permission denied'}), 403
        if '404' in err:
            return jsonify({'accessible': False, 'error': 'Document not found'}), 404
        return jsonify({'accessible': False, 'error': str(e)}), 400


@app.route('/api/google/artist-doc/<path:artist_name>')
def google_artist_doc(artist_name):
    """Get the linked doc for a specific artist (used by tool result pages)."""
    from shared.history import get_artist_doc
    doc = get_artist_doc(artist_name)
    if doc:
        return jsonify(doc)
    return jsonify(None)


@app.route('/api/google/scan-insertion/<path:artist_name>', methods=['POST'])
def google_scan_insertion(artist_name):
    """Scan an artist's linked doc for the insertion point."""
    from shared.history import get_artist_doc
    doc = get_artist_doc(artist_name)
    if not doc:
        return jsonify({'error': f'No Google Doc linked for {artist_name}'}), 404

    try:
        from shared.google_docs import scan_document_for_insertion_point, read_document_structure
        scan = scan_document_for_insertion_point(doc['doc_id'])
        structure = read_document_structure(doc['doc_id'], max_paragraphs=30) if not scan['found'] else None
        return jsonify({
            'scan': scan,
            'structure': structure,
            'doc_id': doc['doc_id'],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/google/confirm-insertion/<path:artist_name>', methods=['POST'])
def google_confirm_insertion(artist_name):
    """Confirm the insertion point for an artist's doc."""
    from shared.history import update_artist_doc_bookmark, confirm_artist_doc_insertion
    data = request.get_json(silent=True) or {}
    index = data.get('index')
    if index is None:
        return jsonify({'error': 'index is required'}), 400
    update_artist_doc_bookmark(artist_name, int(index))
    confirm_artist_doc_insertion(artist_name)
    return jsonify({'ok': True})


@app.route('/api/google/append/<path:artist_name>', methods=['POST'])
def google_append(artist_name):
    """Append report data to an artist's linked Google Doc."""
    from shared.history import get_artist_doc, update_artist_doc_append_status, save_artist_doc_undo

    doc = get_artist_doc(artist_name)
    if not doc:
        return jsonify({'error': f'No Google Doc linked for {artist_name}'}), 404

    data = request.get_json(silent=True) or {}
    dsp_data = data.get('dsp_data')
    radio_data = data.get('radio_data')
    press_data = data.get('press_data')
    date_label = data.get('date_label')
    radio_date_range = data.get('radio_date_range')

    if not dsp_data and not radio_data and not press_data:
        return jsonify({'error': 'No data provided to append.'}), 400

    try:
        from shared.google_docs import append_report_to_doc
        result = append_report_to_doc(
            doc_id=doc['doc_id'],
            dsp_data=dsp_data,
            radio_data=radio_data,
            press_data=press_data,
            artist_name=artist_name,
            date_label=date_label,
            radio_date_range=radio_date_range,
        )

        status = 'success' if result['success'] else f'error: {result["error"]}'
        update_artist_doc_append_status(artist_name, status)

        if result['success'] and result.get('inserted_at') and result.get('insert_end'):
            save_artist_doc_undo(artist_name, doc['doc_id'],
                                 result['inserted_at'], result['insert_end'])

        if result['success']:
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        update_artist_doc_append_status(artist_name, f'error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/google/append-from-job/<job_id>', methods=['POST'])
def google_append_from_job(job_id):
    """Append report data from a completed job to the artist's Google Doc."""
    from shared.history import get_artist_doc, update_artist_doc_append_status, save_artist_doc_undo

    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404

    job = jobs[job_id]
    artist_name = job.get('artist', '')
    if not artist_name:
        # Try to extract from job params
        data = request.get_json(silent=True) or {}
        artist_name = data.get('artist_name', '')
    if not artist_name:
        return jsonify({'error': 'Artist name required (not found in job)'}), 400

    doc = get_artist_doc(artist_name)
    if not doc:
        return jsonify({'error': f'No Google Doc linked for {artist_name}'}), 404

    # The job stores structured data in the job dict when the report compiler saves it
    dsp_data = job.get('dsp_data')
    radio_data = job.get('radio_data')
    press_data = job.get('press_data')
    req_data = request.get_json(silent=True) or {}
    date_label = req_data.get('date_label')
    radio_date_range = req_data.get('radio_date_range') or job.get('radio_date_range')

    # Check for actual data (not just None/empty)
    has_dsp = dsp_data and any(
        matches for rel in dsp_data.values() for matches in rel.values()
    ) if isinstance(dsp_data, dict) else bool(dsp_data)
    has_radio = bool(radio_data)
    has_press = press_data and any(
        v for v in press_data.values()
    ) if isinstance(press_data, dict) else bool(press_data)

    if not has_dsp and not has_radio and not has_press:
        return jsonify({'error': 'No report data available to append. The report may have found no results, or this tool does not yet support Google Doc append.'}), 400

    # Resolve proof image paths from the job
    proof_image_paths = []
    if has_dsp:
        proof_names = job.get('proof_images', [])
        if proof_names:
            # Try job-scoped proof dir first, then shared dir
            job_proof_dir = REPORT_DIR / f'dsp_{job_id}' / 'dsp_proofs'
            shared_proof_dir = REPORT_DIR / 'dsp_proofs'
            for name in proof_names:
                for d in [job_proof_dir, shared_proof_dir]:
                    p = d / name
                    if p.exists():
                        proof_image_paths.append(str(p))
                        break

    try:
        from shared.google_docs import append_report_to_doc
        result = append_report_to_doc(
            doc_id=doc['doc_id'],
            dsp_data=dsp_data,
            radio_data=radio_data,
            press_data=press_data,
            artist_name=artist_name,
            date_label=date_label,
            proof_image_paths=proof_image_paths if proof_image_paths else None,
            radio_date_range=radio_date_range,
        )

        status = 'success' if result['success'] else f'error: {result["error"]}'
        update_artist_doc_append_status(artist_name, status)

        if result['success'] and result.get('inserted_at') and result.get('insert_end'):
            save_artist_doc_undo(artist_name, doc['doc_id'],
                                 result['inserted_at'], result['insert_end'])

        if result['success']:
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        update_artist_doc_append_status(artist_name, f'error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 400


# ---------------------------------------------------------------------------
# Google Docs: Undo, Bulk Link, Retry
# ---------------------------------------------------------------------------

@app.route('/api/google/undo-append/<path:artist_name>', methods=['POST'])
def google_undo_append(artist_name):
    """Undo the last append for an artist by deleting the inserted range."""
    from shared.history import get_artist_doc_undo, clear_artist_doc_undo, update_artist_doc_append_status

    undo = get_artist_doc_undo(artist_name)
    if not undo:
        return jsonify({'error': 'No undo data available (expired or no recent append).'}), 404

    try:
        from shared.google_docs import undo_last_append
        result = undo_last_append(undo['doc_id'], undo['start'], undo['end'])

        if result['success']:
            clear_artist_doc_undo(artist_name)
            update_artist_doc_append_status(artist_name, 'undone')
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/google/undo-status/<path:artist_name>', methods=['GET'])
def google_undo_status(artist_name):
    """Check if undo is available for an artist."""
    from shared.history import get_artist_doc_undo
    undo = get_artist_doc_undo(artist_name)
    return jsonify({
        'available': undo is not None,
        'inserted_at': undo['inserted_at'] if undo else None,
    })


@app.route('/api/settings/google/docs/bulk', methods=['POST'])
def google_docs_bulk_link():
    """Bulk-link multiple artist-doc mappings at once.

    Request body: {mappings: [{artist_name, doc_url}, ...]}
    """
    from shared.history import save_artist_doc
    from shared.google_docs import get_document_title, scan_document_for_insertion_point
    from shared.history import confirm_artist_doc_insertion, update_artist_doc_bookmark
    from shared.google_auth import is_connected

    if not is_connected():
        return jsonify({'error': 'Google account not connected.'}), 400

    data = request.get_json(silent=True) or {}
    mappings = data.get('mappings', [])
    if not mappings:
        return jsonify({'error': 'No mappings provided.'}), 400

    results = []
    for m in mappings:
        artist = m.get('artist_name', '').strip()
        url = m.get('doc_url', '').strip()
        if not artist or not url:
            continue
        if 'docs.google.com/document/d/' not in url:
            results.append({'artist_name': artist, 'ok': False, 'error': 'Invalid URL format'})
            continue

        # Extract doc_id
        try:
            doc_id = url.split('/document/d/')[1].split('/')[0]
        except (IndexError, AttributeError):
            results.append({'artist_name': artist, 'ok': False, 'error': 'Could not extract doc ID'})
            continue

        # Test access
        try:
            title = get_document_title(doc_id)
        except Exception as e:
            err = str(e)
            if '403' in err:
                err = 'Permission denied'
            elif '404' in err:
                err = 'Document not found'
            results.append({'artist_name': artist, 'ok': False, 'error': err})
            continue

        # Save mapping
        save_artist_doc(artist, url, doc_id)

        # Auto-scan insertion point
        try:
            scan = scan_document_for_insertion_point(doc_id)
            if scan['found']:
                update_artist_doc_bookmark(artist, scan['index'])
                confirm_artist_doc_insertion(artist)
        except Exception:
            pass

        results.append({'artist_name': artist, 'ok': True, 'doc_title': title})

    return jsonify({'results': results})


@app.route('/api/google/retry-append/<path:artist_name>', methods=['POST'])
def google_retry_append(artist_name):
    """Retry appending to a Google Doc from cached batch data.

    Request body: {batch_id: str} — the batch job that generated data for this artist.
    """
    from shared.history import get_artist_doc

    doc = get_artist_doc(artist_name)
    if not doc:
        return jsonify({'error': f'No Google Doc linked for {artist_name}'}), 404

    data = request.get_json(silent=True) or {}
    batch_id = data.get('batch_id', '')

    if batch_id not in jobs:
        return jsonify({'error': 'Batch job not found or expired.'}), 404

    job = jobs[batch_id]

    # Try to find cached data for this artist in batch_artist_data
    artist_data = job.get('batch_artist_data', {}).get(artist_name, {})
    radio_data = artist_data.get('radio_data')
    press_data = artist_data.get('press_data')
    dsp_data = artist_data.get('dsp_data')

    if not radio_data and not press_data and not dsp_data:
        return jsonify({'error': 'No cached data found for this artist in the batch.'}), 404

    ar = _batch_auto_append(artist_name, doc['doc_id'],
                            radio_data=radio_data, press_data=press_data, dsp_data=dsp_data,
                            radio_date_range=artist_data.get('radio_date_range'))

    # Update batch append_results
    if 'append_results' in job:
        job['append_results'][artist_name] = ar

    return jsonify(ar)


# ---------------------------------------------------------------------------
# Backup endpoint — downloads a zip of all data files + history
# ---------------------------------------------------------------------------
@app.route('/api/backup')
def download_backup():
    import zipfile
    backup_dir = ROOT_DIR / 'data'
    ts = time.strftime('%Y%m%d_%H%M%S')
    zip_path = Path(tempfile.mkdtemp()) / f'dmm_backup_{ts}.zip'

    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        # Data files
        for pattern in ['*.csv', '*.json']:
            for f in backup_dir.glob(pattern):
                if f.name.startswith('google_'):
                    continue  # skip credentials
                zf.write(str(f), f'data/{f.name}')
        # History database
        db_path = backup_dir / 'history.db'
        if db_path.exists():
            zf.write(str(db_path), 'data/history.db')
        # Logs
        log_dir = ROOT_DIR / 'logs'
        if log_dir.exists():
            for f in log_dir.glob('*.log*'):
                zf.write(str(f), f'logs/{f.name}')

    logger.info('Backup created: %s', zip_path.name)
    return send_file(str(zip_path), as_attachment=True, download_name=f'dmm_backup_{ts}.zip')


# ---------------------------------------------------------------------------
# Social Metrics
# ---------------------------------------------------------------------------

SOCIAL_METRICS_KNOWN_HEADERS = {
    'link': 'link',
    'post': 'link',
    'url': 'link',
    'tiktok link': 'link',
    'instagram link': 'link',
    'youtube link': 'link',
    'views': 'views',
    'likes': 'likes',
    'comments': 'comments',
    'shares': 'shares',
    'saves': 'saves',
    'total eng': 'total_eng',
    'total eng.': 'total_eng',
    'total engagement': 'total_eng',
    'eng. rate': 'eng_rate',
    'eng rate': 'eng_rate',
    'engagement rate': 'eng_rate',
    'creator': 'creator',
    'tiktok - creator': 'creator',
    'country': 'country',
    'territory': 'country',
    'vertical': 'vertical',
    'creative': 'vertical',
    'platform': 'platform',
    'total posts': 'total_posts',
    'boost code': '_skip',
    'live stats': '_skip',
}


def _get_gsheets_credentials():
    """Load service account credentials with Sheets + Drive scopes."""
    sa_path = ROOT_DIR / 'data' / 'google_service_account.json'
    if not sa_path.exists():
        return None, 'Service account JSON not configured. Go to Settings to add it.'
    try:
        from google.oauth2.service_account import Credentials
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly',
        ]
        creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
        return creds, None
    except Exception as e:
        return None, f'Failed to authenticate: {str(e)[:200]}'


def _get_gsheets_client(creds):
    """Build a gspread client from existing credentials."""
    import gspread
    return gspread.authorize(creds)


def _discover_spreadsheets(creds):
    """Auto-discover ALL spreadsheets shared with the service account via Drive API."""
    from googleapiclient.discovery import build
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    query = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"

    all_files = []
    page_token = None
    while True:
        results = service.files().list(
            q=query,
            fields='nextPageToken, files(id, name)',
            pageSize=100,
            pageToken=page_token,
        ).execute()
        all_files.extend(results.get('files', []))
        page_token = results.get('nextPageToken')
        if not page_token:
            break

    return all_files


def _get_service_account_email():
    """Read the service account email from the saved JSON."""
    sa_path = ROOT_DIR / 'data' / 'google_service_account.json'
    if not sa_path.exists():
        return None
    try:
        with open(sa_path) as f:
            return json.load(f).get('client_email')
    except Exception:
        return None


def _parse_number(val):
    """Parse a cell value into an int or float, stripping commas and percent signs."""
    if val is None:
        return 0
    s = str(val).strip().replace(',', '').replace(' ', '')
    if not s or s == '-' or s.lower() in ('n/a', 'n/d', ''):
        return 0
    if s.endswith('%'):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return 0
    try:
        f = float(s)
        return int(f) if f == int(f) and '.' not in s else f
    except ValueError:
        return 0


def _detect_headers(rows):
    """Scan first 5 rows to find the header row. Returns (header_map, header_row_index)."""
    for idx, row in enumerate(rows[:5]):
        header_map = {}
        for col_idx, cell in enumerate(row):
            cell_lower = str(cell).strip().lower()
            # Try exact match first, then stripped of trailing punctuation
            matched = SOCIAL_METRICS_KNOWN_HEADERS.get(cell_lower)
            if not matched:
                cleaned = cell_lower.rstrip('.,:;')
                matched = SOCIAL_METRICS_KNOWN_HEADERS.get(cleaned)
            if matched and matched != '_skip':
                header_map[matched] = col_idx
        if 'link' in header_map and 'views' in header_map:
            return header_map, idx
    return None, None


def _parse_spreadsheet(gc, spreadsheet_id, campaign_name):
    """Parse all valid tabs from a single spreadsheet."""
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
    except Exception as e:
        err = str(e)[:200]
        if '404' in err or 'not found' in err.lower():
            return {'campaign_name': campaign_name, 'spreadsheet_id': spreadsheet_id,
                    'error': 'Spreadsheet not found.', 'tabs': []}
        if '403' in err or 'permission' in err.lower():
            sa_email = _get_service_account_email() or 'your service account'
            return {'campaign_name': campaign_name, 'spreadsheet_id': spreadsheet_id,
                    'error': f'Access denied. Share the sheet with {sa_email}', 'tabs': []}
        return {'campaign_name': campaign_name, 'spreadsheet_id': spreadsheet_id,
                'error': err, 'tabs': []}

    tabs = []
    for worksheet in spreadsheet.worksheets():
        try:
            all_values = worksheet.get_all_values()
            if not all_values:
                continue
            header_map, header_row = _detect_headers(all_values)
            if header_map is None:
                continue

            # Check for "Last Updated" cell in first few rows
            last_updated = ''
            for row in all_values[:header_row + 1] if header_row else all_values[:3]:
                for cell in row:
                    cell_str = str(cell).strip()
                    if cell_str.lower().startswith('last updated'):
                        last_updated = cell_str.replace('Last Updated:', '').replace('Last updated:', '').replace('last updated:', '').strip()
                        break

            creators = []
            data_rows = all_values[header_row + 1:]
            for row in data_rows:
                while len(row) <= max(header_map.values()):
                    row.append('')

                link = str(row[header_map['link']]).strip()
                link_lower = link.lower()
                if not link or not any(d in link_lower for d in ('tiktok.com', 'instagram.com', 'youtube.com', 'youtu.be')):
                    continue

                if 'tiktok.com' in link_lower:
                    platform = 'TikTok'
                elif 'instagram.com' in link_lower:
                    platform = 'Instagram'
                elif 'youtube.com' in link_lower or 'youtu.be' in link_lower:
                    platform = 'YouTube'
                else:
                    platform = ''

                _PLATFORM_ALIASES = {
                    'tt': 'TikTok', 'tiktok': 'TikTok',
                    'ig': 'Instagram', 'instagram': 'Instagram', 'insta': 'Instagram',
                    'yt': 'YouTube', 'youtube': 'YouTube',
                }
                if 'platform' in header_map:
                    p = str(row[header_map['platform']]).strip()
                    if p:
                        platform = _PLATFORM_ALIASES.get(p.lower(), p)

                creator_name = ''
                if 'creator' in header_map:
                    creator_name = str(row[header_map['creator']]).strip()

                creators.append({
                    'name': creator_name,
                    'country': str(row[header_map['country']]).strip() if 'country' in header_map else '',
                    'vertical': str(row[header_map['vertical']]).strip() if 'vertical' in header_map else '',
                    'platform': platform,
                    'url': link,
                    'views': _parse_number(row[header_map['views']]) if 'views' in header_map else 0,
                    'likes': _parse_number(row[header_map['likes']]) if 'likes' in header_map else 0,
                    'comments': _parse_number(row[header_map['comments']]) if 'comments' in header_map else 0,
                    'shares': _parse_number(row[header_map['shares']]) if 'shares' in header_map else 0,
                    'saves': _parse_number(row[header_map['saves']]) if 'saves' in header_map else 0,
                    'total_eng': _parse_number(row[header_map['total_eng']]) if 'total_eng' in header_map else 0,
                    'eng_rate': _parse_number(row[header_map['eng_rate']]) if 'eng_rate' in header_map else 0,
                })

            if not creators:
                continue

            total_views = sum(c['views'] for c in creators)
            total_eng = sum(c['total_eng'] for c in creators)
            rates = [c['eng_rate'] for c in creators if c['eng_rate'] > 0]
            avg_rate = sum(rates) / len(rates) if rates else 0

            tabs.append({
                'name': worksheet.title,
                'last_updated': last_updated,
                'creators': creators,
                'totals': {
                    'views': total_views,
                    'likes': sum(c['likes'] for c in creators),
                    'comments': sum(c['comments'] for c in creators),
                    'shares': sum(c['shares'] for c in creators),
                    'saves': sum(c['saves'] for c in creators),
                    'total_eng': total_eng,
                    'avg_eng_rate': avg_rate,
                    'creator_count': len(creators),
                },
            })
        except Exception:
            continue

    return {
        'campaign_name': campaign_name,
        'spreadsheet_id': spreadsheet_id,
        'tabs': tabs,
    }


_DETACHED_SHEETS_PATH = ROOT_DIR / 'data' / 'social_metrics_detached.json'


def _load_detached_sheets():
    if _DETACHED_SHEETS_PATH.exists():
        try:
            return json.loads(_DETACHED_SHEETS_PATH.read_text())
        except Exception:
            pass
    return []


def _save_detached_sheets(detached):
    _DETACHED_SHEETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DETACHED_SHEETS_PATH.write_text(json.dumps(detached, indent=2))


@app.route('/social-metrics')
def social_metrics():
    sa_email = _get_service_account_email()
    creds, auth_error = _get_gsheets_credentials()
    detached_ids = {d['id'] for d in _load_detached_sheets()}

    campaigns = []
    discovered_count = 0
    if creds:
        try:
            discovered = _discover_spreadsheets(creds)
            discovered_count = len(discovered)
            gc = _get_gsheets_client(creds)
            for file_info in discovered:
                if file_info['id'] in detached_ids:
                    continue
                campaign = _parse_spreadsheet(gc, file_info['id'], file_info['name'])
                # Only include spreadsheets that have valid data tabs (or errors)
                if campaign.get('tabs') or campaign.get('error'):
                    campaigns.append(campaign)
        except Exception as e:
            auth_error = f'Failed to discover spreadsheets: {str(e)[:200]}'

    has_github = bool(os.environ.get('GITHUB_PAT', '').strip())
    return render_template('social_metrics.html',
                           campaigns=campaigns,
                           discovered_count=discovered_count,
                           auth_error=auth_error,
                           sa_email=sa_email,
                           has_credentials=creds is not None,
                           has_github=has_github)


@app.route('/social-metrics/detach', methods=['POST'])
def detach_spreadsheet():
    """Detach a spreadsheet — hides it from the dashboard and attempts to remove
    the service account's Drive permission so the scraper also stops seeing it."""
    data = request.get_json(force=True)
    sid = data.get('id', '').strip()
    name = data.get('name', '').strip()
    if not sid:
        return jsonify({'error': 'Missing spreadsheet ID.'}), 400

    # Best-effort: try to revoke the SA's own Drive permission
    permission_removed = False
    creds, _ = _get_gsheets_credentials()
    if creds:
        try:
            from googleapiclient.discovery import build
            service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            about = service.about().get(fields='user(permissionId)').execute()
            my_perm_id = about['user']['permissionId']
            service.permissions().delete(
                fileId=sid, permissionId=my_perm_id, supportsAllDrives=True,
            ).execute()
            permission_removed = True
        except Exception:
            pass

    # Always store locally so it's hidden from the dashboard
    detached = _load_detached_sheets()
    if not any(d['id'] == sid for d in detached):
        detached.append({'id': sid, 'name': name})
        _save_detached_sheets(detached)

    if permission_removed:
        msg = 'Detached. The scraper will also stop seeing this sheet. Re-share to reconnect.'
    else:
        msg = ('Hidden from dashboard. To also stop the scraper, '
               'open the sheet in Google Sheets and remove the service account from sharing.')
    return jsonify({'ok': True, 'message': msg})


@app.route('/social-metrics/trigger-update', methods=['POST'])
def trigger_metrics_update():
    """Trigger the GitHub Actions scraper workflow on demand."""
    import requests as req
    pat = os.environ.get('GITHUB_PAT', '').strip()
    repo = os.environ.get('GITHUB_REPO', 'gobtech/DMM-Sheets').strip()
    if not pat:
        return jsonify({'status': 'error', 'message': 'GitHub token not configured. Add it in Settings.'}), 400
    try:
        resp = req.post(
            f'https://api.github.com/repos/{repo}/actions/workflows/update-metrics.yml/dispatches',
            headers={
                'Authorization': f'token {pat}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={'ref': 'main'},
            timeout=15,
        )
        if resp.status_code == 204:
            return jsonify({'status': 'ok', 'message': 'Update triggered. Metrics will refresh in ~2 minutes.'})
        elif resp.status_code == 404:
            return jsonify({'status': 'error', 'message': f'Workflow not found in {repo}. Check the repository name and workflow file.'}), 400
        elif resp.status_code == 401 or resp.status_code == 403:
            return jsonify({'status': 'error', 'message': 'Access denied. Check that the token has repo scope.'}), 400
        else:
            return jsonify({'status': 'error', 'message': f'GitHub API returned {resp.status_code}: {resp.text[:200]}'}), 400
    except req.exceptions.Timeout:
        return jsonify({'status': 'error', 'message': 'GitHub API timed out.'}), 504
    except req.exceptions.ConnectionError:
        return jsonify({'status': 'error', 'message': 'Could not connect to GitHub.'}), 502


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Reconcile scheduled jobs on startup
    from shared.history import get_all_schedules, mark_stale_runs
    mark_stale_runs()
    for _sched in get_all_schedules():
        if _sched['enabled']:
            try:
                _register_scheduler_job(_sched['id'], _sched['cron_expression'])
            except Exception:
                pass

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
