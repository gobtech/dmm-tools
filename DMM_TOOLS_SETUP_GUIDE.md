# DMM Tools — Setup Guide

## What is this?

This is an automation toolkit built to streamline the repetitive reporting workflows at Dorado Music Marketing (DMM), a digital music marketing company that connects international artists with the Latin American market. DMM handles radio campaigns, out-of-home campaigns, DSP pitching and reporting, press outreach, and general marketing campaigns across the LATAM region.

A significant portion of DMM's operational work involves manual data collection and formatting — searching for press coverage, pulling radio play numbers from Soundcharts, checking dozens of editorial playlists for artist placements, and compiling all of it into formatted reports. These tasks are time-consuming, error-prone when done by hand, and fundamentally automatable since they consist of information retrieval, database lookups, and document generation.

This toolkit replaces that manual work with three tools:

- **Radio Report Generator** — Auto-fetches airplay data directly from Soundcharts (using your existing paid account session) and produces formatted Word documents with radio play data grouped by country and station. Defaults to LATAM-only data, with an option for all countries. What used to involve manual CSV downloads and copy-pasting into Google Docs now runs in seconds with zero transcription errors.

- **Press Pickup Tool** — Searches for Spanish and Portuguese-language press coverage using a 7-source pipeline: RSS/WordPress feed scanning (430 feeds), XML sitemap mining (333 outlets), Google News RSS (free, unlimited — 5 LATAM regions concurrent), Brave Search (free, 2,000/month), Serper.dev (targeted site: queries against known outlets), Tavily (free 1,000/month — AI-optimized search), and DuckDuckGo News (free, unlimited). A Groq AI relevance filter removes false positives (robust JSON parsing handles malformed LLM responses). Results are matched against DMM's internal media database (1,500+ outlets), grouped by outlet (multiple URLs from the same outlet merge into one entry with article titles), and formatted into reports sorted by country. Social media posts are intelligently classified using a handle registry (536 outlets with discovered handles): posts from known press outlets are included with the outlet's name and description, artist's own accounts are excluded, and unknown accounts are filtered out. US editions of multi-regional outlets (e.g. rollingstone.com) are excluded entirely when the article URL has no LATAM language indicators. Title-based dedup within outlet groups catches near-duplicates with different URLs but identical content (unicode-normalized comparison). URL normalization (amp stripping, tracking param removal) applied consistently across all 7 sources. New outlet descriptions are auto-generated via Groq AI. Reports include article titles and are downloadable as formatted .docx files.

- **DSP Pickup Tool** — Checks 99 LATAM editorial playlists across Spotify, Deezer, Apple Music, Amazon Music, Claro Música, and YouTube Music against DMM's release schedule (pulled live from a shared Google Sheet) to find artist placements. All 6 platforms are fully automated with no API keys required: Spotify uses public embed page scraping (50 playlists), Deezer uses its public API (6 playlists), Apple Music uses public page scraping (16 playlists), Amazon Music uses public embed page scraping (6 playlists), Claro Música uses anonymous login with server-side rendered state parsing (4 playlists), and YouTube Music uses the innertube API for clean song titles (16 playlists). Each match includes the playlist link for quick verification. The tool generates composite proof images (showing playlist cover art, track position, and platform badge) and a formatted .docx report with platform headers, country labels, playlist metadata, and embedded proof images — ready to share with clients.

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
pip install requests googlenewsdecoder python-docx Pillow
```

## Step 3: Get API keys

### Serper.dev (for Press Pickup — Google results + social media)

1. Go to [serper.dev](https://serper.dev/)
2. Sign up and create an API key
3. Copy the key — this is your `SERPER_API_KEY`

> New accounts get 2,500 free credits (one-time). Press Pickup uses only 3 credits per artist search (1 news query + 2 organic queries), so this lasts ~830 searches. Serper provides actual Google results including social media posts that Google News RSS and Brave miss.

### Brave Search (supplementary for Press Pickup)

1. Go to [brave.com/search/api](https://brave.com/search/api/)
2. Sign up and create an API key
3. Copy the key — this is your `BRAVE_API_KEY`

> Free tier: 2,000 queries/month (recurring). Used as a supplementary source — the bulk of press results come from Google News RSS (free, unlimited) and Serper.

### Soundcharts (for Radio Report)

The Radio Report auto-fetches airplay data using your existing Soundcharts paid account — no separate API subscription needed. Authentication is fully automatic: the app logs in with your credentials and refreshes the token before it expires (~48hr lifetime). No manual token extraction from browser DevTools required.

Just add your Soundcharts login credentials to `.env` (see Step 4).

> **Note:** The DSP Pickup tool does **not** require any API keys. All 6 platforms use public scraping: Spotify (embed pages), Deezer (public API), Apple Music (page scraping), Amazon Music (embed pages), Claro Música (anonymous login + SSR state), and YouTube Music (innertube API) — no credentials needed for any of them.

## Step 4: Configure environment

```bash
cp .env.template .env
nano .env  # or: code .env
```

Fill in your keys:

```bash
export SERPER_API_KEY="..."                # Serper.dev (Google results for Press Pickup)
export BRAVE_API_KEY="BSAM..."             # Brave Search (supplementary for Press Pickup)
export SOUNDCHARTS_EMAIL="your@email.com"  # Soundcharts (for Radio Report)
export SOUNDCHARTS_PASSWORD="your-password"
export TAVILY_API_KEY="tvly-..."           # Tavily (optional, for Press Pickup — free 1000/mo)
export GEMINI_API_KEY="..."                # Google Gemini (optional, for PR Translator AI mode)
export GROQ_API_KEY="..."                  # Groq (optional, for Discovery + Proposal + Digest AI — free)
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

1. **Radio Report** — Select "Fetch from Soundcharts", enter an artist name, pick LATAM region and time range (7D/28D/1Y/Custom Range), click Fetch Songs, select songs, click Generate
2. **Press Pickup** — Enter an artist name, pick a date range, click Search → download .docx report
3. **DSP Pickup** — Enter an artist name, click Check Playlists → view proof images → download .docx report

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
| Soundcharts auth | Automatic — token refreshes programmatically via login |
| Press database | Re-export from Notion, replace `data/press_database.csv`, then regenerate registries: `python press-pickup/discover_feeds.py` and `python press-pickup/discover_social_handles.py` |
| Playlist database | Re-export from Notion, replace `data/playlist_database.csv` |
| Release schedule | Automatic — pulls live from Google Sheets on every run |

## What's automated vs. manual

| Task | Status |
|------|--------|
| Radio play reports (Soundcharts auto-fetch) | Fully automated (LATAM default, all countries optional) |
| Press pickup (7-source pipeline) | Fully automated (RSS feeds + sitemaps + Google News + Brave + Serper + Tavily + DDG News, smart social media classification via handle registry, .docx download) |
| DSP pickup — Spotify playlists (50) | Fully automated (embed scraping, no API key) |
| DSP pickup — Deezer playlists (6) | Fully automated (public API, no key) |
| DSP pickup — Apple Music playlists (16) | Fully automated (page scraping, no API key) |
| DSP pickup — Amazon Music playlists (6) | Fully automated (embed scraping, no API key) |
| DSP pickup — Claro Música playlists (4) | Fully automated (anonymous login + SSR scraping, no API key) |
| DSP pickup — YouTube Music playlists (16) | Fully automated (innertube API, no API key) |
| DSP pickup — proof images + .docx report | Fully automated (composite proof images with playlist cover art, formatted Word document) |
| Soundcharts token refresh | Fully automated (programmatic login, auto-refresh) |
| New media outlet discovery | Flagged automatically, adding to Notion is manual |

## Troubleshooting

**`Error: SERPER_API_KEY environment variable required`**
→ Run `source .env` or check that your `.env` file has the correct Serper API key. Get one at [serper.dev](https://serper.dev/)

**`Error: Cannot find module 'docx'`**
→ Run `npm install docx` from the `dmm-tools` directory (installs locally, not globally)

**`ModuleNotFoundError: No module named 'requests'`** (or `googlenewsdecoder`)
→ Make sure the venv is activated: `source ~/projects/dmm-tools/.venv/bin/activate`, then run `pip install requests googlenewsdecoder python-docx Pillow`

**Press pickup returns few or no results**
→ Try broadening the date range with `--days 30` or `--days 90`. Check that your API keys are valid: Serper credits at [serper.dev/dashboard](https://serper.dev/dashboard), Brave quota at [api-dashboard.search.brave.com](https://api-dashboard.search.brave.com). Google News RSS is free and unlimited, so at minimum you should always get press articles

**Spotify playlist says "Could not parse playlist"**
→ Some playlist types (mood mixes, personalized playlists) use a different embed format that doesn't include track data. These are rare among editorial playlists — the tool will skip them and continue.

**Spotify playlist says "Error parsing playlist data: 'state'"**
→ Same as above — a small number of playlists use a different embed structure. The tool handles this gracefully and moves on.

**Press database matching misses an outlet**
→ The outlet probably doesn't have a website URL in the Notion database. Add the URL in Notion, re-export, and it'll match next time. Meanwhile, the tool flags it as `[NEW — not in DB]` and uses a generic description.

**Radio Report: "Soundcharts credentials not configured"**
→ Add `SOUNDCHARTS_EMAIL` and `SOUNDCHARTS_PASSWORD` to `.env` (see Step 4 above). Restart the web server after editing `.env`.

**Radio Report: "Soundcharts login failed: Bad credentials"**
→ Check that the email and password in `.env` match your Soundcharts account. Make sure there are no extra quotes or spaces.

**Radio Report: "Failed to fetch airplay data. Token may be expired."**
→ This shouldn't happen with auto-login, but if it does, restart the web server to force a fresh login. If the issue persists, verify your Soundcharts account is still active.

**Radio Report: "Artist not found on Soundcharts"**
→ Check the artist name spelling. The search is fuzzy but needs a close match. Try the exact name as shown on Soundcharts.
