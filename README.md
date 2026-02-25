# DMM Automation Tools

Automation suite for Dorado Music Marketing workflows. Replaces manual press pickup, radio reporting, and DSP playlist checking. Includes a web UI for running all tools from the browser.

## Tools

| Tool | What it does | Manual time saved |
|------|-------------|-------------------|
| **Radio Report** | Auto-fetches airplay data from Soundcharts and generates formatted Word reports (LATAM-focused) | ~1-2 hrs/artist |
| **Press Pickup** | Searches Google News, Brave, and Serper for Spanish/Portuguese-language press + social media posts, matches against media database, formats report | ~2-3 hrs/artist |
| **DSP Pickup** | Checks 99 LATAM editorial playlists for artist releases across Spotify/Deezer/Apple Music/Amazon Music/Claro Música/YouTube Music | ~3-4 hrs/week |

## Web UI (Recommended)

The easiest way to use all three tools:

```bash
source .venv/bin/activate
python web/app.py
# Opens http://localhost:5000
```

The web UI provides:
- **Radio Report**: Type an artist name → auto-fetches from Soundcharts → downloads .docx (LATAM or all countries, with custom date range support)
- **Press Pickup**: Type an artist name + date range → searches Google News RSS + Brave + Serper → displays formatted report (press articles + social media posts)
- **DSP Pickup**: Search by artist, week, or all releases → checks playlists across platforms

## Quick Setup

```bash
# 1. Install dependencies
pip install requests flask googlenewsdecoder
npm install docx

# 2. Copy your data files
cp Descripción_de_prensa_*_all.csv data/press_database.csv
cp Untitled_*_all.csv data/playlist_database.csv

# 3. Set API keys in .env
export SERPER_API_KEY="..."         # Serper.dev (for Press Pickup — Google results)
export BRAVE_API_KEY="..."          # Brave Search (supplementary, for Press Pickup)
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
├── .env                            ← API keys (SERPER_API_KEY, BRAVE_API_KEY, SOUNDCHARTS_EMAIL/PASSWORD)
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
│   └── press_pickup.py             ← Press pickup automation (Google News RSS + Brave + Serper)
├── dsp-pickup/
│   └── dsp_pickup.py               ← DSP playlist checker
└── reports/                        ← Generated output
```

## API Keys Setup

### Serper.dev (primary Google results for Press Pickup)
1. Go to [serper.dev](https://serper.dev/)
2. Sign up and create an API key (2,500 free credits on signup)
3. Add to `.env`: `export SERPER_API_KEY="..."`

> Press Pickup uses 3 Serper credits per artist search (1 news + 2 organic queries). This provides actual Google results including social media posts (Instagram, Facebook, X).

### Brave Search (supplementary for Press Pickup)
1. Go to [brave.com/search/api](https://brave.com/search/api/)
2. Sign up and create an API key
3. Add to `.env`: `export BRAVE_API_KEY="BSAM..."`

> Free tier: 2,000 queries/month (recurring). Used as a supplementary source alongside Google News RSS and Serper.

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

- **New media outlet discovery**: The tool flags outlets not in the database, but adding them to Notion is manual.
- **Slack responses**: Still human territory.
