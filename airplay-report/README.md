# Airplay Report Generator

Generates formatted `.docx` radio airplay reports from CSV data. Supports multiple artists, multiple countries, and full automation via GitHub Actions.

## Recommended: Use the Web UI

The web UI at `http://localhost:5000` (run `python web/app.py` from the project root) auto-fetches airplay data from Soundcharts and generates the report in one click — no manual CSV downloads needed. It supports:

- **LATAM-only** (default) or **all countries** region filter
- **Time ranges**: 7 Days, Previous 7 Days, 28 Days, 1 Year, or **Custom Date Range** (calendar picker)
- Automatic Soundcharts login (no manual token extraction)
- Song picker with search filter — select which songs to include
- Paginated data fetch via Soundcharts GraphQL API
- Direct .docx download

## CLI Quick Start

For manual/batch use cases:

```bash
# Single artist, folder of CSVs
node generate_report.js --artist "Djo" --input ./data/djo/

# Single artist, specific files
node generate_report.js --artist "Djo" --files ar.csv,br.csv,co.csv,mx.csv --output djo_report.docx

# Batch: all artists in artists.json
./batch_generate.sh

# Batch: single artist
./batch_generate.sh --artist "Djo"
```

## Setup

```bash
npm install docx
chmod +x batch_generate.sh
```

## Repo Structure

```
├── generate_report.js          # Core CLI tool
├── batch_generate.sh           # Batch runner
├── artists.json                # Artist config
├── data/
│   ├── djo/
│   │   ├── djo_airplay_ar_20260220.csv
│   │   ├── djo_airplay_br_20260220.csv
│   │   └── ...
│   └── another-artist/
│       └── ...
├── reports/                    # Generated output
│   └── djo_radio_plays_28d.docx
└── .github/workflows/
    └── generate-airplay-reports.yml
```

## CSV Format

The CSVs must include these columns (other columns are ignored):

| Column    | Description                          |
|-----------|--------------------------------------|
| `Song`    | Track name                           |
| `Station` | Radio station name                   |
| `28D`     | Play count in the last 28 days       |
| `Country` | Country name (used for grouping)     |

> When using the Soundcharts auto-fetch mode (web UI), the CSV is generated automatically from the API response in this exact format.

## Adding a New Artist

1. Create a folder under `data/` with the artist's CSVs
2. Add an entry to `artists.json`:
   ```json
   {
     "name": "Artist Name",
     "input_dir": "./data/artist-name/"
   }
   ```
3. Run `./batch_generate.sh` or push to trigger GitHub Action

> For one-off reports, the web UI is faster — just type the artist name and click Generate.

## Automation

The GitHub Action triggers on:
- **Push**: When CSV files in `data/` are updated
- **Schedule**: Every Friday at 1pm Lima time
- **Manual**: From the Actions tab in GitHub

Reports are auto-committed to `reports/`. Optionally configure Google Drive upload by uncommenting the relevant section in the workflow and adding a `GOOGLE_CREDENTIALS` secret.
