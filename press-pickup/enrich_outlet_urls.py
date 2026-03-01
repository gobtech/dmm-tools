#!/usr/bin/env python3
"""
Outlet URL Enrichment Script
Searches Brave Search API to discover website URLs for press outlets that are
missing them in the database. Produces enriched JSON + updated CSV.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "press_database.csv"
ENRICHED_JSON = ROOT / "data" / "outlet_urls_enriched.json"
ENRICHED_CSV = ROOT / "data" / "press_database_enriched.csv"

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_WORKERS = 5
SEARCH_DELAY = 0.5   # seconds between requests (Brave limit is generous)
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

SKIP_DOMAINS = {
    # Social / video platforms
    "spotify.com", "apple.com", "youtube.com", "instagram.com",
    "facebook.com", "x.com", "twitter.com", "tiktok.com",
    "linkedin.com", "threads.net", "pinterest.com", "reddit.com",
    # Music / lyrics databases
    "amazon.com", "deezer.com", "soundcloud.com", "last.fm",
    "genius.com", "letras.com", "discogs.com", "bandcamp.com",
    "shazam.com", "musixmatch.com", "allmusic.com",
    # Reference / encyclopedias
    "wikipedia.org", "wikidata.org", "wikiwand.com",
    # Search engines
    "google.com", "bing.com", "zhihu.com", "quora.com",
    "baidu.com", "yandex.com", "ask.com",
}

# Map territory strings to country names for search queries
TERRITORY_COUNTRIES = {
    "MÉXICO": "Mexico", "MEXICO": "Mexico",
    "BRAZIL": "Brasil", "BRASIL": "Brasil",
    "ARGENTINA": "Argentina", "CHILE": "Chile",
    "COLOMBIA": "Colombia", "PERU": "Peru", "PERÚ": "Peru",
    "ECUADOR": "Ecuador", "URUGUAY": "Uruguay",
    "VENEZUELA": "Venezuela", "PARAGUAY": "Paraguay",
    "PANAMA": "Panama", "PANAMÁ": "Panama",
    "COSTA RICA": "Costa Rica", "LATAM": "Latinoamerica",
    "EL SALVADOR": "El Salvador", "GUATEMALA": "Guatemala",
    "BOLIVIA": "Bolivia", "CUBA": "Cuba",
    "REPÚBLICA DOMINICANA": "Republica Dominicana",
}

# LATAM TLD mapping for confidence scoring
COUNTRY_TLDS = {
    "MÉXICO": {".mx", ".com.mx"}, "MEXICO": {".mx", ".com.mx"},
    "BRAZIL": {".br", ".com.br"}, "BRASIL": {".br", ".com.br"},
    "ARGENTINA": {".ar", ".com.ar"}, "CHILE": {".cl"},
    "COLOMBIA": {".co", ".com.co"},
    "PERU": {".pe", ".com.pe"}, "PERÚ": {".pe", ".com.pe"},
    "ECUADOR": {".ec", ".com.ec"}, "URUGUAY": {".uy", ".com.uy"},
    "VENEZUELA": {".ve", ".com.ve"}, "PARAGUAY": {".py", ".com.py"},
    "PANAMA": {".pa", ".com.pa"}, "PANAMÁ": {".pa", ".com.pa"},
    "COSTA RICA": {".cr"}, "BOLIVIA": {".bo", ".com.bo"},
    "CUBA": {".cu"}, "GUATEMALA": {".gt", ".com.gt"},
    "EL SALVADOR": {".sv", ".com.sv"},
}

# Brave country codes for search localization
TERRITORY_BRAVE_COUNTRY = {
    "MÉXICO": "MX", "MEXICO": "MX",
    "BRAZIL": "BR", "BRASIL": "BR",
    "ARGENTINA": "AR", "CHILE": "CL",
    "COLOMBIA": "CO", "PERU": "PE", "PERÚ": "PE",
    "ECUADOR": "EC", "URUGUAY": "UY",
    "VENEZUELA": "VE", "PARAGUAY": "PY",
    "PANAMA": "PA", "PANAMÁ": "PA",
    "COSTA RICA": "CR", "LATAM": "MX",
    "EL SALVADOR": "SV", "GUATEMALA": "GT",
    "BOLIVIA": "BO", "CUBA": "CU",
    "REPÚBLICA DOMINICANA": "DO",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str | None:
    """Extract clean domain from URL (no www. prefix)."""
    url = url.strip().lower()
    if not url.startswith("http"):
        url = "https://" + url
    match = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else None


def normalize_name(name: str) -> str:
    """Strip spaces, punctuation, accents → lowercase for matching."""
    nfkd = unicodedata.normalize("NFKD", name.lower())
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_only)


def domain_matches_name(domain: str, name: str) -> bool:
    """Check if the outlet name appears within the domain."""
    norm_name = normalize_name(name)
    if len(norm_name) < 3:
        return False
    # Strip TLD to get domain core
    domain_core = domain.lower()
    for ext in [".com.ar", ".com.br", ".com.mx", ".com.co", ".com.cl",
                ".com.pe", ".com.ec", ".com.uy", ".com.ve", ".com.py",
                ".com.pa", ".com.gt", ".com.sv", ".com.bo",
                ".com", ".br", ".ar", ".mx", ".co", ".cl", ".pe",
                ".ec", ".org", ".net", ".la", ".fm", ".tv", ".io",
                ".info", ".me", ".uy", ".ve", ".py"]:
        if domain_core.endswith(ext):
            domain_core = domain_core[: -len(ext)]
            break
    domain_core = re.sub(r"[^a-z0-9]", "", domain_core)
    if not domain_core:
        return False
    return norm_name in domain_core or domain_core in norm_name


def domain_has_country_tld(domain: str, territory: str) -> bool:
    """Check if domain has a TLD matching the outlet's country."""
    for part in territory.upper().split(","):
        part = part.strip()
        tlds = COUNTRY_TLDS.get(part, set())
        for tld in tlds:
            if domain.endswith(tld):
                return True
    return False


def is_skipped_domain(domain: str) -> bool:
    """Check if domain is in the skip list."""
    for sd in SKIP_DOMAINS:
        if domain == sd or domain.endswith("." + sd):
            return True
    return False


def get_search_query(name: str, territory: str) -> str:
    """Build the search query for an outlet."""
    territory_upper = territory.upper().strip()

    # Brazilian outlets get Portuguese query
    if "BRAZIL" in territory_upper or "BRASIL" in territory_upper:
        return f'"{name}" Brasil site oficial'

    # Map territory to a country name for the query
    country = None
    for part in territory_upper.split(","):
        part = part.strip()
        if part in TERRITORY_COUNTRIES:
            country = TERRITORY_COUNTRIES[part]
            break

    if country:
        return f'"{name}" {country} sitio web'

    # Fallback for unknown/empty territory
    return f'"{name}" sitio web musica'


def score_confidence(domain: str, name: str, territory: str) -> str:
    """Score the confidence of a URL match."""
    if domain_matches_name(domain, name):
        return "high"
    if territory and domain_has_country_tld(domain, territory):
        return "medium"
    return "low"


def result_is_relevant(title: str, name: str) -> bool:
    """Check if a search result title is relevant to the outlet name."""
    title_lower = title.lower()

    # Extract meaningful words from the outlet name (3+ chars)
    name_words = [w for w in re.split(r"[^a-záéíóúñãõç]+", name.lower()) if len(w) >= 3]

    if not name_words:
        # Very short name (e.g. "TKM") — check if full name appears
        norm = normalize_name(name)
        return norm in normalize_name(title_lower) if len(norm) >= 2 else True

    # At least one meaningful word from the outlet name must appear in the result
    return any(word in title_lower for word in name_words)


def search_outlet(outlet: dict, brave_key: str) -> dict:
    """Search Brave for an outlet's website. Returns result dict."""
    name = outlet["name"]
    territory = outlet["territory"]
    query = get_search_query(name, territory)

    # Pick Brave country code based on territory
    country_code = None
    for part in territory.upper().split(","):
        part = part.strip()
        if part in TERRITORY_BRAVE_COUNTRY:
            country_code = TERRITORY_BRAVE_COUNTRY[part]
            break

    result = {
        "name": name,
        "territory": territory,
        "discovered_url": None,
        "discovered_domain": None,
        "search_query": query,
        "confidence": None,
    }

    try:
        params = {"q": query, "count": 3}
        if country_code:
            params["country"] = country_code

        resp = requests.get(
            BRAVE_ENDPOINT,
            headers={"X-Subscription-Token": brave_key},
            params=params,
            timeout=10,
        )

        if resp.status_code == 429:
            result["error"] = "rate_limited"
            return result

        resp.raise_for_status()
        data = resp.json()
        hits = data.get("web", {}).get("results", [])

        if not hits:
            return result

        # Prefer high-confidence matches, then take first relevant non-skipped
        best = None
        for hit in hits:
            url = hit.get("url", "")
            title = hit.get("title", "")
            if not url:
                continue
            domain = extract_domain(url)
            if not domain:
                continue
            if is_skipped_domain(domain):
                continue

            confidence = score_confidence(domain, name, territory)

            # High confidence (name in domain) — return immediately
            if confidence == "high":
                result["discovered_url"] = url
                result["discovered_domain"] = domain
                result["confidence"] = confidence
                return result

            # For medium/low: require the result title to mention the outlet name
            if not result_is_relevant(title, name):
                continue

            # Keep first viable result as fallback
            if best is None:
                best = (url, domain, confidence)

        if best:
            result["discovered_url"] = best[0]
            result["discovered_domain"] = best[1]
            result["confidence"] = best[2]

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def load_outlets_missing_urls() -> tuple[list[dict], list[dict]]:
    """Load CSV. Returns (outlets_missing_url, all_rows)."""
    all_rows = []
    missing = []

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_rows.append(row)
            name = row.get("NAME OF MEDIA", "").strip()
            website = row.get("WEBSITE", "").strip()
            territory = row.get("Territory", "").strip()

            if not name:
                continue
            if website:
                continue
            # Skip PENDING/CANCELLED with no territory info
            if territory.upper() in ("PENDING", "CANCELLED", ""):
                continue

            missing.append({
                "name": name,
                "territory": territory,
            })

    return missing, all_rows


def run_enrichment(outlets: list[dict], brave_key: str, workers: int) -> list[dict]:
    """Run Brave searches concurrently. Returns list of result dicts."""
    results = []
    completed = 0
    total = len(outlets)

    print(f"\nSearching {total} outlets with {workers} workers (Brave Search API)...\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_outlet = {}
        for outlet in outlets:
            future = executor.submit(search_outlet, outlet, brave_key)
            future_to_outlet[future] = outlet

        for future in as_completed(future_to_outlet):
            completed += 1
            outlet = future_to_outlet[future]

            try:
                result = future.result()
                results.append(result)

                # Progress logging
                if completed % 50 == 0 or completed == total:
                    found_so_far = sum(1 for r in results if r["discovered_url"])
                    print(f"  [{completed:>4}/{total}] Found: {found_so_far} URLs so far "
                          f"| Last: {outlet['name'][:40]}")

            except Exception as e:
                results.append({
                    "name": outlet["name"],
                    "territory": outlet["territory"],
                    "discovered_url": None,
                    "discovered_domain": None,
                    "search_query": get_search_query(outlet["name"], outlet["territory"]),
                    "confidence": None,
                    "error": str(e),
                })

            # Polite delay between requests
            time.sleep(SEARCH_DELAY)

    return results


def write_enriched_csv(all_rows: list[dict], results: list[dict], fieldnames: list[str]):
    """Write updated CSV with discovered URLs filled in (high/medium only)."""
    # Build lookup: outlet name → discovered URL (high/medium confidence only)
    url_lookup = {}
    for r in results:
        if r["discovered_url"] and r["confidence"] in ("high", "medium"):
            url_lookup[r["name"]] = r["discovered_url"]

    with open(ENRICHED_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            name = row.get("NAME OF MEDIA", "").strip()
            website = row.get("WEBSITE", "").strip()
            if not website and name in url_lookup:
                row = dict(row)  # Don't mutate original
                row["WEBSITE"] = url_lookup[name]
            writer.writerow(row)

    filled = len(url_lookup)
    print(f"\nEnriched CSV saved to {ENRICHED_CSV}")
    print(f"  {filled} outlets had their WEBSITE field filled (high/medium confidence)")


def print_summary(results: list[dict]):
    """Print detailed summary of enrichment results."""
    total = len(results)
    found = [r for r in results if r["discovered_url"]]
    no_result = [r for r in results if not r["discovered_url"] and not r.get("error")]
    errors = [r for r in results if r.get("error")]

    high = [r for r in found if r["confidence"] == "high"]
    medium = [r for r in found if r["confidence"] == "medium"]
    low = [r for r in found if r["confidence"] == "low"]

    print("\n" + "=" * 65)
    print("  OUTLET URL ENRICHMENT RESULTS")
    print("=" * 65)
    print(f"  Total searched:    {total}")
    print(f"  URLs found:        {len(found):>4}  ({len(found)/total*100:.1f}%)" if total else "")
    print(f"  No result:         {len(no_result):>4}  ({len(no_result)/total*100:.1f}%)" if total else "")
    print(f"  Errors:            {len(errors):>4}")
    print()
    print(f"  Confidence breakdown:")
    print(f"    High  (name in domain):   {len(high):>4}")
    print(f"    Medium (country TLD):     {len(medium):>4}")
    print(f"    Low (other):              {len(low):>4}")
    print("=" * 65)

    # Breakdown by country
    country_counts = {}
    for r in found:
        t = r["territory"] or "(unknown)"
        country_counts[t] = country_counts.get(t, 0) + 1

    if country_counts:
        print("\n  URLs found per territory:")
        for territory, count in sorted(country_counts.items(), key=lambda x: -x[1]):
            print(f"    {territory:<35} {count:>4}")

    # List low-confidence matches for manual review
    if low:
        print(f"\n  Low-confidence matches ({len(low)}) — review manually:")
        print("  " + "-" * 63)
        for r in low:
            print(f"    {r['name'][:30]:<32} → {r['discovered_domain']}")
        print("  " + "-" * 63)

    print()


def main():
    parser = argparse.ArgumentParser(description="Enrich press outlets with website URLs via Brave Search API")
    parser.add_argument("--dry-run", action="store_true",
                        help="Search first 20 outlets and print results without saving")
    parser.add_argument("--resume", action="store_true",
                        help="Skip outlets already in existing enriched JSON")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"Number of concurrent workers (default: {MAX_WORKERS})")
    parser.add_argument("--batch-size", type=int, default=0,
                        help="Limit to N outlets per run (use with --resume for chunked runs)")
    args = parser.parse_args()

    print("=" * 65)
    print("  DMM Outlet URL Enrichment (Brave Search)")
    print("=" * 65)

    # Check for API key
    brave_key = os.environ.get("BRAVE_API_KEY", "")
    if not brave_key:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        brave_key = os.environ.get("BRAVE_API_KEY", "")

    if not brave_key:
        print("\nERROR: BRAVE_API_KEY not found in environment or .env file.")
        sys.exit(1)

    missing, all_rows = load_outlets_missing_urls()
    fieldnames = list(all_rows[0].keys()) if all_rows else []

    print(f"\nLoaded {len(all_rows)} total rows from press database")
    print(f"Found {len(missing)} outlets with name + territory but no website URL")

    # Resume mode: skip already-searched outlets
    existing_results = []
    if args.resume and ENRICHED_JSON.exists():
        with open(ENRICHED_JSON) as f:
            existing = json.load(f)
        existing_results = existing.get("results", [])
        already_searched = {r["name"] for r in existing_results}
        before = len(missing)
        missing = [o for o in missing if o["name"] not in already_searched]
        print(f"--resume: {before - len(missing)} outlets already searched, {len(missing)} remaining")

    if not missing:
        print("No outlets to search.")
        sys.exit(0)

    # Dry run: only search first 20
    if args.dry_run:
        missing = missing[:20]
        print(f"\n--dry-run: searching first {len(missing)} outlets only")

    # Batch size limit
    if args.batch_size > 0 and not args.dry_run:
        missing = missing[:args.batch_size]
        print(f"--batch-size: limiting to {len(missing)} outlets this run")

    results = run_enrichment(missing, brave_key, workers=args.workers)

    # Merge with existing results if resuming
    all_results = existing_results + results

    print_summary(all_results if args.resume else results)

    if args.dry_run:
        print("Dry run complete — nothing saved.")
        return

    # Save JSON
    total = len(all_results)
    found = sum(1 for r in all_results if r["discovered_url"])
    no_result = sum(1 for r in all_results if not r["discovered_url"] and not r.get("error"))
    error_count = sum(1 for r in all_results if r.get("error"))

    registry = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_searched": total,
            "urls_found": found,
            "no_result": no_result,
            "errors": error_count,
        },
        "results": all_results,
    }

    ENRICHED_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(ENRICHED_JSON, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    print(f"Enrichment JSON saved to {ENRICHED_JSON}")

    # Write enriched CSV
    write_enriched_csv(all_rows, all_results, fieldnames)


if __name__ == "__main__":
    main()
