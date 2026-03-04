# Scheduled Automated Runs — Implementation Plan

## Context
All DMM tools currently require manual web UI interaction. The team wants weekly batch digest/snapshot runs to happen automatically — collect radio, press, and DSP data for selected artists on a schedule, store snapshots in history.db, and show run history in the web UI. No email or Slack delivery needed.

## Approach: APScheduler in Flask + SQLite persistence

### Step 1: Install APScheduler
- `pip install APScheduler` in the venv
- Add auto-install check to `start.sh` (same pattern as Flask check on line 6)

### Step 2: Add schedule tables to `shared/history.py`
Extend `init_db()` to create two new tables:

**`schedules`** — name, artist_source (`manual`/`all_with_data`/`all_schedule`/`all`), artists JSON, mode (`snapshot`/`digest`), radio_region, radio_time_range, include_radio/dsp/press, cron_expression, enabled, created_at, updated_at, last_run_at, last_run_status

**`schedule_runs`** — schedule_id FK, started_at, finished_at, status (`running`/`success`/`partial`/`error`/`interrupted`), total_artists, artists_with_data, artists_failed, duration_seconds, details JSON (per-artist results), error text

Add CRUD functions (~120 lines):
- `get_all_schedules()`, `get_schedule(id)`, `save_schedule(data)`, `update_schedule_db(id, data)`, `delete_schedule_db(id)`
- `save_schedule_run()`, `update_schedule_run()`, `update_schedule_last_run()`
- `get_schedule_runs(schedule_id, limit)`
- `mark_stale_runs()` — marks any `status='running'` as `'interrupted'` on startup

### Step 3: Add scheduler + execution to `web/app.py`

**Scheduler init** (after `jobs = {}` block, ~line 51):
- `BackgroundScheduler` with `SQLAlchemyJobStore` pointing at `data/history.db`
- `coalesce=True` (missed runs fire once), `max_instances=1` (no overlap), `misfire_grace_time=3600`

**`_execute_schedule(schedule_id, job_id=None)`** (~80 lines):
- Resolves artist list based on `artist_source` (manual list, or dynamic via `get_artists()`/`load_release_schedule()`)
- Creates a `schedule_runs` record
- Loops through artists, calling `generate_digest()` via importlib (same pattern as existing batch endpoint at line 1301)
- Stores per-artist results, counts successes/failures
- Updates run record and schedule's `last_run_at/status`
- If `job_id` provided (manual trigger), logs to the live job queue for UI streaming

**`_register_scheduler_job(schedule_id, cron_expression)`** — wraps `scheduler.add_job()` with CronTrigger

**Startup in `__main__`** (before `app.run()`):
- `scheduler.start()` + `atexit.register(shutdown)`
- `mark_stale_runs()` for interrupted runs
- Reconciliation loop: re-register any enabled schedule missing from APScheduler's job store

### Step 4: Add 6 API endpoints to `web/app.py`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/schedules` | GET | List all schedules with next_run_time from APScheduler |
| `/api/schedules` | POST | Create schedule, validate cron, register with APScheduler |
| `/api/schedules/<id>` | PUT | Update schedule, re-register job if cron/enabled changed |
| `/api/schedules/<id>` | DELETE | Remove schedule + APScheduler job |
| `/api/schedules/<id>/run` | POST | Manual trigger — returns job_id for live log polling |
| `/api/schedules/history` | GET | Recent runs, filterable by schedule_id |

Cron validation via `CronTrigger.from_crontab()` in try/except — return 400 on invalid.

### Step 5: Add Schedules tab to `web/templates/index.html`

**Tab button** at line 1732 (before Dashboard link):
```html
<button class="tab-btn" onclick="switchTab('schedules')">Schedules</button>
```
Update `tabs` array at line 2512 to include `'schedules'`.

**Tab panel** with 3 sections:

**A. Active Schedules List** — table showing name, cadence (human-readable), artist count/source, last run status + time, next run time, enabled toggle, Edit/Delete/Run Now buttons

**B. Create/Edit Form** (hidden by default, shown on click):
- Name text input
- Artist source radio: "Select Artists" / "All Dashboard Artists" / "All Schedule Artists" / "All"
- Artist checkbox picker (reuses `/api/dashboard/artists` pattern from batch digest)
- Mode radio: "Snapshot Only" / "Full Digest"
- Cadence presets: "Daily (6 PM)" / "Weekly Monday (9 AM)" / "Weekly Friday (6 PM)" / "Custom Cron"
- Custom cron text input (shown only when Custom selected)
- Region, time range, section toggles (same controls as digest tab)

**C. Run History** — table of recent runs: schedule name, started, duration, status badge, artist counts, expandable details

**JS functions** (~200 lines): `loadSchedules()`, `loadScheduleHistory()`, `showScheduleForm()`, `saveSchedule()`, `deleteSchedule()`, `toggleSchedule()`, `triggerSchedule()`, `cronToHuman()`, lazy-load on first tab visit.

## Files to modify

| File | Changes | Est. lines |
|------|---------|-----------|
| `shared/history.py` | Add schedule tables to `init_db()`, 8 CRUD functions | +120 |
| `web/app.py` | Scheduler init, `_execute_schedule()`, `_register_scheduler_job()`, 6 endpoints, startup code | +220 |
| `web/templates/index.html` | Tab button, tab panel HTML, CSS, ~200 lines JS | +350 |
| `start.sh` | APScheduler auto-install check | +1 |

**No changes to**: `generate_digest.py`, `shared/database.py`, or any tool modules.

## Key reuse
- `generate_digest()` from `digest-generator/generate_digest.py` — called via importlib exactly like existing batch endpoint (app.py:1301)
- `get_artists()` from `shared/history.py` — resolves "all dashboard artists"
- `load_release_schedule()` from `shared/database.py` — resolves "all schedule artists"
- `/api/dashboard/artists` pattern for artist checkbox picker in UI
- Existing `new_job()`/`log_line()`/`finish_job()` for manual trigger live streaming
- Same `_get_conn()` + `init_db()` pattern in history.py

## Verification
1. Start app via `./start.sh`, verify no startup errors
2. Open Schedules tab — should show empty state
3. Create a test schedule: "Test Run", select 1-2 artists manually, snapshot mode, custom cron `*/5 * * * *` (every 5 min)
4. Verify schedule appears in list with correct next run time
5. Click "Run Now" — verify live log streaming shows artist progress, run completes
6. Check Run History — should show the run with status/counts
7. Toggle schedule disabled — verify next_run shows null
8. Wait for the 5-min cron to fire — verify a new run appears in history automatically
9. Delete the test schedule, verify it's gone from both UI and history
10. Restart Flask — verify schedules persist and APScheduler re-registers jobs
