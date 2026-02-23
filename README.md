# DMM Automation Tools

Automation suite for Dorado Music Marketing workflows. Replaces manual press pickup, radio reporting, and DSP playlist checking. Includes a web UI for running all tools from the browser.

## Tools

| Tool | What it does | Manual time saved |
|------|-------------|-------------------|
| **Radio Report** | Auto-fetches airplay data from Soundcharts and generates formatted Word reports (LATAM-focused) | ~1-2 hrs/artist |
| **Press Pickup** | Searches Brave for Spanish/Portuguese-language press, matches against media database, formats report | ~2-3 hrs/artist |
| **DSP Pickup** | Checks 82 LATAM editorial playlists for artist releases across Spotify/Deezer/Apple Music | ~3-4 hrs/week |

## Web UI (Recommended)

The easiest way to use all three tools:

```bash
source .venv/bin/activate
python web/app.py
# Opens http://localhost:5000
```

The web UI provides:
- **Radio Report**: Type an artist name → auto-fetches from Soundcharts → downloads .docx (LATAM or all countries, with custom date range support)
- **Press Pickup**: Type an artist name + date range → searches Brave → displays formatted report
- **DSP Pickup**: Search by artist, week, or all releases → checks playlists across platforms

## Quick Setup

```bash
# 1. Install dependencies
pip install requests flask
npm install docx

# 2. Copy your data files
cp Descripción_de_prensa_*_all.csv data/press_database.csv
cp Untitled_*_all.csv data/playlist_database.csv

# 3. Set API keys in .env
export BRAVE_API_KEY="..."          # Brave Search (for Press Pickup)
export SOUNDCHARTS_EMAIL="..."      # Soundcharts login (for Radio Report)
export SOUNDCHARTS_PASSWORD="..."
```

## CLI Usage

### Radio Report
```bash
# Via Soundcharts auto-fetch (recommended — used by the web UI)
# Use the web UI at http://localhost:5000

# Manual CSV mode
node airplay-report/generate_report.js --artist "Djo" --input ./data/djo/

# Batch — all artists
bash airplay-report/batch_generate.sh
```

### Press Pickup
```bash
# Single artist, last 28 days
python press-pickup/press_pickup.py --artist "Djo" --days 28

# Single artist, last 7 days, save to file
python press-pickup/press_pickup.py --artist "Djo" --days 7 --output reports/djo_press.txt

# All artists from release schedule
python press-pickup/press_pickup.py --all --days 7 --output reports/
```

### DSP Pickup
```bash
# This week's releases — check all playlists
python dsp-pickup/dsp_pickup.py --week current

# Specific week
python dsp-pickup/dsp_pickup.py --week 2026-02-21

# Single artist across all playlists
python dsp-pickup/dsp_pickup.py --artist "Djo" --output reports/djo_dsp.txt

# All releases, Spotify only
python dsp-pickup/dsp_pickup.py --all --spotify-only --output reports/dsp_full.txt
```

## Directory Structure

```
dmm-tools/
├── README.md
├── .env                            ← API keys (BRAVE_API_KEY, SOUNDCHARTS_EMAIL/PASSWORD)
├── data/
│   ├── press_database.csv          ← Notion export (media outlets)
│   ├── playlist_database.csv       ← Notion export (target playlists)
│   └── djo/                        ← Manual Soundcharts CSVs (optional fallback)
├── shared/
│   ├── database.py                 ← Shared data loaders + press matching
│   └── soundcharts.py              ← Soundcharts API client (auto-login, search, airplay fetch)
├── web/
│   ├── app.py                      ← Flask web server
│   └── templates/
│       └── index.html              ← Web UI (single-page app)
├── airplay-report/
│   ├── generate_report.js          ← Radio play report generator (.docx)
│   ├── batch_generate.sh
│   └── artists.json
├── press-pickup/
│   └── press_pickup.py             ← Press pickup automation (Brave Search)
├── dsp-pickup/
│   └── dsp_pickup.py               ← DSP playlist checker
└── reports/                        ← Generated output
```

## API Keys Setup

### Brave Search (for Press Pickup)
1. Go to [brave.com/search/api](https://brave.com/search/api/)
2. Sign up and create an API key
3. Add to `.env`: `export BRAVE_API_KEY="BSAM..."`

> Free tier: $5/month (~1,000 queries). Press pickup uses ~50 queries per artist search (smart early-stop pagination).

### Soundcharts (for Radio Report)
The Radio Report auto-fetches airplay data using your Soundcharts account credentials (no paid API tier required — uses the internal web API with your existing paid account). Authentication is fully automatic — the app logs in programmatically and refreshes the token before it expires.

1. Add your Soundcharts credentials to `.env`:
   ```bash
   export SOUNDCHARTS_EMAIL="your@email.com"
   export SOUNDCHARTS_PASSWORD="your-password"
   ```

> No manual token extraction needed. The app handles login and token refresh automatically.

## Data Sources

| Source | Type | Update Frequency |
|--------|------|-----------------|
| Release Schedule | Live Google Sheets (published CSV) | Weekly (automatic) |
| Press Database | Notion export → CSV | As needed |
| Playlist Database | Notion export → CSV | As needed |
| Soundcharts Airplay | Auto-fetched via API | Live (per request) |

The release schedule pulls live from the published Google Sheets URL, so it's always current.
The Notion databases need periodic re-export if outlets/playlists are added.
Soundcharts data is fetched on-demand — no more manual CSV downloads.

## Automation (GitHub Actions)

See `airplay-report/.github/workflows/` for the radio report automation.
Similar workflows can be set up for press and DSP pickup — store API keys as GitHub Secrets.

## What's NOT Automated

- **Amazon Music / Claro Música playlists**: No public API. The DSP tool flags these for manual checking.
- **New media outlet discovery**: The tool flags outlets not in the database, but adding them to Notion is manual.
- **Slack responses**: Still human territory.
