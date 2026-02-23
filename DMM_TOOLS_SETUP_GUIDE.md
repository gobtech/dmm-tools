# DMM Tools — Setup Guide

## What is this?

This is an automation toolkit built to streamline the repetitive reporting workflows at Dorado Music Marketing (DMM), a digital music marketing company that connects international artists with the Latin American market. DMM handles radio campaigns, out-of-home campaigns, DSP pitching and reporting, press outreach, and general marketing campaigns across the LATAM region.

A significant portion of DMM's operational work involves manual data collection and formatting — searching for press coverage, pulling radio play numbers from Soundcharts, checking dozens of editorial playlists for artist placements, and compiling all of it into formatted reports. These tasks are time-consuming, error-prone when done by hand, and fundamentally automatable since they consist of information retrieval, database lookups, and document generation.

This toolkit replaces that manual work with three tools:

- **Radio Report Generator** — Auto-fetches airplay data directly from Soundcharts (using your existing paid account session) and produces formatted Word documents with radio play data grouped by country and station. Defaults to LATAM-only data, with an option for all countries. What used to involve manual CSV downloads and copy-pasting into Google Docs now runs in seconds with zero transcription errors.

- **Press Pickup Tool** — Searches Brave for Spanish and Portuguese-language press coverage of artists (with smart paginated search — up to 100 results per query with early-stop optimization), matches results against DMM's internal media database (1,500+ outlets with descriptions and reach metrics from Notion), and generates formatted reports sorted by country. When an outlet isn't found in the database, it uses a generic music media description.

- **DSP Pickup Tool** — Checks 82 LATAM editorial playlists across Spotify, Deezer, Apple Music, Amazon Music, and Claro Música against DMM's release schedule (pulled live from a shared Google Sheet) to find artist placements. Spotify (50 playlists), Deezer (6 playlists), and Apple Music (13 playlists) are fully automated — Spotify uses public embed page scraping (no API key needed), Deezer uses its public API, and Apple Music uses public page scraping. Amazon and Claro are flagged for manual checking since they lack public APIs.

All three tools are accessible via a **web UI** at `http://localhost:5000` — no terminal needed.

The goal is to reduce the time spent on these reporting tasks from several hours per artist per week to a few minutes of review, freeing up the person in this role to work on higher-value projects. The release schedule updates automatically via a published Google Sheets link, so the tools always operate on current data.

---

## Step 1: Extract and place the folder

Put it wherever you keep your projects:

```bash
cd ~/projects
tar -xzf dmm-tools-with-data.tar.gz
cd dmm-tools
```

## Step 2: Install dependencies

Node (for radio reports) — install locally in the project:

```bash
cd ~/projects/dmm-tools
npm init -y
npm install docx
```

Python (for press + DSP pickup) — use a virtual environment:

```bash
cd ~/projects/dmm-tools
python3 -m venv .venv
source .venv/bin/activate
pip install requests
```

## Step 3: Get API keys

### Brave Search (for Press Pickup)

1. Go to [brave.com/search/api](https://brave.com/search/api/)
2. Sign up and create an API key
3. Copy the key — this is your `BRAVE_API_KEY`

> New accounts get $5/month in free credits (~1,000 queries). Press pickup uses ~50 API calls per artist search (smart early-stop pagination keeps costs low — ~$0.25 per search).

### Soundcharts (for Radio Report)

The Radio Report auto-fetches airplay data using your existing Soundcharts paid account session — no separate API subscription needed.

1. Log in to [app.soundcharts.com](https://app.soundcharts.com)
2. Open DevTools (`F12`) → Network tab
3. Navigate to any artist page
4. Click any request to `graphql.soundcharts.com` or `search.soundcharts.com`
5. In the Headers tab, find `Authorization: Bearer eyJ...`
6. Copy everything after `Bearer ` — this is your `SOUNDCHARTS_TOKEN`

> The token expires ~48 hours after login. When it expires, repeat steps 1-6 to get a fresh one.

> **Note:** The DSP Pickup tool does **not** require any API keys. Spotify playlists are checked via public embed page scraping, Deezer uses its public API, and Apple Music playlists are checked via public page scraping — no credentials needed for any of them.

## Step 4: Configure environment

```bash
cp .env.template .env
nano .env  # or: code .env
```

Fill in your keys:

```bash
export BRAVE_API_KEY="BSAM..."
export SOUNDCHARTS_TOKEN="eyJ..."
```

Then load them:

```bash
source .env
```

> **Tip:** Add these lines to your `~/.bashrc` so everything loads automatically on terminal start:
> ```bash
> source ~/projects/dmm-tools/.env
> source ~/projects/dmm-tools/.venv/bin/activate
> ```

## Step 5: Verify the data files are in place

The archive already includes them, but confirm:

```bash
ls data/
# Should show: press_database.csv  playlist_database.csv  release_schedule.csv  djo/
```

If you need to update the Notion databases later, just re-export from Notion and replace the CSVs in `data/`.

The release schedule pulls live from the published Google Sheets URL by default, so the local CSV is just a fallback.

## Step 6: Test via Web UI (recommended)

```bash
source .venv/bin/activate
python web/app.py
```

Open http://localhost:5000 and test each tool:

1. **Radio Report** — Select "Fetch from Soundcharts", enter an artist name, pick LATAM region, click Generate
2. **Press Pickup** — Enter an artist name, pick a date range, click Search
3. **DSP Pickup** — Enter an artist name, click Check Playlists

If all three produce results, the setup is done.

### CLI testing (alternative)

```bash
# Radio Report (manual CSV mode)
node airplay-report/generate_report.js \
  --artist "Djo" \
  --input ./data/djo/ \
  --output ./reports/djo_radio.docx

# Press Pickup
python3 press-pickup/press_pickup.py \
  --artist "Djo" \
  --days 28 \
  --press-db ./data/press_database.csv

# DSP Pickup
python3 dsp-pickup/dsp_pickup.py \
  --artist "Djo" \
  --playlist-db ./data/playlist_database.csv \
  --release-schedule ./data/release_schedule.csv
```

## Day-to-day usage

### Web UI (recommended for all tools)

```bash
source .venv/bin/activate
python web/app.py
# Opens http://localhost:5000
```

### Radio report for a single artist (via CLI)

```bash
# Manual CSV mode (if you have CSVs already)
node airplay-report/generate_report.js --artist "Djo" --input ./data/djo/ --output ./reports/djo_radio.docx
```

> For auto-fetch from Soundcharts, use the web UI — it handles the API calls, CSV generation, and report creation in one click.

### Radio report for all artists (batch)

```bash
cd airplay-report
bash batch_generate.sh
```

Add artists to `airplay-report/artists.json` and put their CSVs in `data/<artist-name>/`.

### Press pickup for a single artist

```bash
python3 press-pickup/press_pickup.py --artist "Djo" --days 7 --output ./reports/djo_press.txt
```

### Press pickup for all artists on the release schedule

```bash
python3 press-pickup/press_pickup.py --all --days 7 --output ./reports/
```

### DSP pickup for this week's releases

```bash
python3 dsp-pickup/dsp_pickup.py --week current --output ./reports/dsp_weekly.txt
```

### DSP pickup for a specific artist

```bash
python3 dsp-pickup/dsp_pickup.py --artist "Djo" --output ./reports/djo_dsp.txt
```

### DSP pickup for all releases (Spotify only)

```bash
python3 dsp-pickup/dsp_pickup.py --all --spotify-only --output ./reports/dsp_full.txt
```

## Updating data sources

| Source | How to update |
|--------|--------------|
| Soundcharts airplay | Automatic — fetched live via API on each Radio Report run |
| Soundcharts token | Refresh from browser DevTools every ~48hrs (see Step 3) |
| Press database | Re-export from Notion, replace `data/press_database.csv` |
| Playlist database | Re-export from Notion, replace `data/playlist_database.csv` |
| Release schedule | Automatic — pulls live from Google Sheets on every run |

## What's automated vs. manual

| Task | Status |
|------|--------|
| Radio play reports (Soundcharts auto-fetch) | Fully automated (LATAM default, all countries optional) |
| Press pickup (Brave Search + database matching) | Fully automated (paginated search, up to 100 results/query) |
| DSP pickup — Spotify playlists (50) | Fully automated (embed scraping, no API key) |
| DSP pickup — Deezer playlists (6) | Fully automated (public API, no key) |
| DSP pickup — Apple Music playlists (13) | Fully automated (page scraping, no API key) |
| DSP pickup — Amazon Music playlists | Manual (no public API) |
| DSP pickup — Claro Música playlists | Manual (no public API) |
| Soundcharts token refresh | Manual (~48hr expiry, refresh from browser DevTools) |
| New media outlet discovery | Flagged automatically, adding to Notion is manual |

## Troubleshooting

**`Error: BRAVE_API_KEY environment variable required`**
→ Run `source .env` or check that your `.env` file has the correct key

**`Error: Cannot find module 'docx'`**
→ Run `npm install docx` from the `dmm-tools` directory (installs locally, not globally)

**`ModuleNotFoundError: No module named 'requests'`**
→ Make sure the venv is activated: `source ~/projects/dmm-tools/.venv/bin/activate`, then run `pip install requests`

**Brave search returns no results**
→ Try broadening the date range with `--days 30` or `--days 90`. Check that your Brave API key is valid and has remaining credits at [api-dashboard.search.brave.com](https://api-dashboard.search.brave.com)

**Spotify playlist says "Could not parse playlist"**
→ Some playlist types (mood mixes, personalized playlists) use a different embed format that doesn't include track data. These are rare among editorial playlists — the tool will skip them and continue.

**Spotify playlist says "Error parsing playlist data: 'state'"**
→ Same as above — a small number of playlists use a different embed structure. The tool handles this gracefully and moves on.

**Press database matching misses an outlet**
→ The outlet probably doesn't have a website URL in the Notion database. Add the URL in Notion, re-export, and it'll match next time. Meanwhile, the tool flags it as `[NEW — not in DB]` and uses a generic description.

**Radio Report: "SOUNDCHARTS_TOKEN not configured in .env"**
→ Add your Soundcharts session token to `.env` (see Step 3 above). Make sure to restart the web server after editing `.env`.

**Radio Report: "Failed to fetch airplay data. Token may be expired."**
→ Your Soundcharts token has expired (~48hrs). Log in to app.soundcharts.com, grab a fresh token from DevTools, and update `.env`.

**Radio Report: "Artist not found on Soundcharts"**
→ Check the artist name spelling. The search is fuzzy but needs a close match. Try the exact name as shown on Soundcharts.
