#!/usr/bin/env python3
"""
RSS & WordPress Feed Discovery Script
Scans the press database for RSS feeds and WordPress REST API endpoints.
Saves results to data/feed_registry.json for use by Press Pickup.
"""

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
_ENRICHED_CSV = ROOT / "data" / "press_database_enriched.csv"
CSV_PATH = _ENRICHED_CSV if _ENRICHED_CSV.exists() else ROOT / "data" / "press_database.csv"
REGISTRY_PATH = ROOT / "data" / "feed_registry.json"

# ── Constants ──────────────────────────────────────────────────────────────────
TIMEOUT = 5
MAX_WORKERS = 40
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

COMMON_FEED_PATHS = [
    "/feed", "/rss", "/feed/rss", "/rss.xml",
    "/atom.xml", "/feed/atom", "/index.xml", "/?feed=rss2",
]

RSS_CONTENT_TYPES = {
    "application/rss+xml", "application/atom+xml",
    "application/xml", "text/xml",
}

# Domains that are not real outlet websites
SKIP_DOMAINS = {
    "instagram.com", "facebook.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "linkedin.com", "threads.net",
    "open.spotify.com", "soundcloud.com", "apple.com",
    "music.apple.com", "music.amazon.com",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str | None:
    """Extract clean domain from URL (no www. prefix)."""
    url = url.strip().lower()
    if not url.startswith("http"):
        url = "https://" + url
    match = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else None


def normalize_base_url(url: str) -> str:
    """Ensure URL has scheme and no trailing slash."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def load_outlets() -> list[dict]:
    """Load outlets from press database CSV."""
    outlets = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("NAME OF MEDIA", "").strip()
            website = row.get("WEBSITE", "").strip()
            territory = row.get("Territory", "").strip()
            description = row.get("DESCRIPTION & SM", "").strip()

            if not name:
                continue

            # Skip outlets with no usable website
            if not website or website.lower() in ("", "n/a", "-"):
                continue

            domain = extract_domain(website)
            if not domain:
                continue

            # Skip social media / platform links
            if any(domain.endswith(sd) for sd in SKIP_DOMAINS):
                continue

            outlets.append({
                "name": name,
                "website": website,
                "domain": domain,
                "territory": territory,
                "description": description,
            })

    # Deduplicate by domain (keep first occurrence)
    seen = set()
    unique = []
    for o in outlets:
        if o["domain"] not in seen:
            seen.add(o["domain"])
            unique.append(o)
    return unique


def is_valid_rss(content: str) -> bool:
    """Quick check if content looks like a valid RSS/Atom feed."""
    # Check first 1000 chars for RSS/Atom markers
    head = content[:1000].lower()
    return any(tag in head for tag in ("<rss", "<feed", "<channel"))


def has_rss_content_type(response: requests.Response) -> bool:
    """Check if response Content-Type suggests RSS/XML."""
    ct = response.headers.get("Content-Type", "").lower().split(";")[0].strip()
    return ct in RSS_CONTENT_TYPES


def discover_feed(outlet: dict) -> dict:
    """
    Probe a single outlet for RSS feed or WordPress API.
    Returns a result dict with feed_url, wp_api_url, feed_type, etc.
    """
    base_url = normalize_base_url(outlet["website"])
    result = {
        "name": outlet["name"],
        "feed_url": None,
        "wp_api_url": None,
        "feed_type": None,
        "country": outlet["territory"],
        "description": outlet["description"],
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Step 1: Check homepage HTML for <link rel="alternate"> RSS tags ──
    try:
        resp = session.get(base_url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            html = resp.text[:20_000]  # Only scan the head area
            # Find all RSS/Atom link tags
            pattern = r'<link[^>]+type=["\']application/(rss|atom)\+xml["\'][^>]*>'
            for match in re.finditer(pattern, html, re.IGNORECASE):
                tag = match.group(0)
                href_match = re.search(r'href=["\']([^"\']+)', tag)
                if href_match:
                    feed_url = href_match.group(1)
                    # Handle relative URLs
                    if feed_url.startswith("/"):
                        feed_url = base_url + feed_url
                    elif not feed_url.startswith("http"):
                        feed_url = base_url + "/" + feed_url
                    result["feed_url"] = feed_url
                    result["feed_type"] = "rss"
                    return result

            # Also check reversed attribute order: type after href
            pattern2 = r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/(rss|atom)\+xml["\'][^>]*>'
            for match in re.finditer(pattern2, html, re.IGNORECASE):
                feed_url = match.group(1)
                if feed_url.startswith("/"):
                    feed_url = base_url + feed_url
                elif not feed_url.startswith("http"):
                    feed_url = base_url + "/" + feed_url
                result["feed_url"] = feed_url
                result["feed_type"] = "rss"
                return result
    except Exception:
        pass

    # ── Step 2: Try common feed paths ──
    for path in COMMON_FEED_PATHS:
        try:
            url = base_url + path
            resp = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                if has_rss_content_type(resp) or is_valid_rss(resp.text):
                    result["feed_url"] = url
                    result["feed_type"] = "rss"
                    return result
        except Exception:
            continue

    # ── Step 3: Try WordPress REST API ──
    try:
        wp_posts_url = base_url + "/wp-json/wp/v2/posts?per_page=1"
        resp = session.get(wp_posts_url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "").lower()
            if "json" in ct:
                data = resp.json()
                if (isinstance(data, list) and len(data) > 0
                        and isinstance(data[0], dict)
                        and "title" in data[0] and "link" in data[0]):
                    result["wp_api_url"] = base_url + "/wp-json/wp/v2/posts"
                    result["feed_type"] = "wordpress"
                    return result
    except Exception:
        pass

    # Simpler WP detection: just /wp-json/
    try:
        wp_root_url = base_url + "/wp-json/"
        resp = session.get(wp_root_url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "").lower()
            if "json" in ct:
                data = resp.json()
                if isinstance(data, dict) and "name" in data and "routes" in data:
                    result["wp_api_url"] = base_url + "/wp-json/wp/v2/posts"
                    result["feed_type"] = "wordpress"
                    return result
    except Exception:
        pass

    return result


def scan_outlets(outlets: list[dict], label: str = "Scanning", workers: int = MAX_WORKERS) -> dict:
    """Run feed discovery concurrently across all outlets. Returns registry dict."""
    results = {}
    errors = 0
    completed = 0
    total = len(outlets)

    print(f"\n{label} {total} outlets with {workers} workers...\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_outlet = {
            executor.submit(discover_feed, o): o for o in outlets
        }

        for future in as_completed(future_to_outlet):
            completed += 1
            outlet = future_to_outlet[future]
            try:
                result = future.result()
                results[outlet["domain"]] = result

                # Progress indicator
                status = "---"
                if result["feed_type"] == "rss":
                    status = "RSS"
                elif result["feed_type"] == "wordpress":
                    status = "WP "
                if completed % 25 == 0 or completed == total:
                    print(f"  [{completed:>4}/{total}] Last: {outlet['domain']:<40} {status}")

            except Exception as e:
                errors += 1
                results[outlet["domain"]] = {
                    "name": outlet["name"],
                    "feed_url": None,
                    "wp_api_url": None,
                    "feed_type": None,
                    "country": outlet["territory"],
                    "description": outlet["description"],
                    "error": str(e),
                }
                if completed % 25 == 0:
                    print(f"  [{completed:>4}/{total}] ERROR: {outlet['domain']}: {e}")

    return results, errors


def print_summary(results: dict, errors: int):
    """Print scan summary with stats and top feed patterns."""
    total = len(results)
    rss_count = sum(1 for r in results.values() if r.get("feed_type") == "rss")
    wp_count = sum(1 for r in results.values() if r.get("feed_type") == "wordpress")
    none_count = sum(1 for r in results.values() if r.get("feed_type") is None)

    print("\n" + "=" * 60)
    print("  FEED DISCOVERY RESULTS")
    print("=" * 60)
    print(f"  Total outlets scanned:   {total}")
    print(f"  RSS feeds found:         {rss_count:>4}  ({rss_count/total*100:.1f}%)" if total else "")
    print(f"  WordPress APIs found:    {wp_count:>4}  ({wp_count/total*100:.1f}%)" if total else "")
    print(f"  Neither found:           {none_count:>4}  ({none_count/total*100:.1f}%)" if total else "")
    print(f"  Errors:                  {errors:>4}")
    print("=" * 60)

    # Top 5 feed URL patterns
    feed_paths = []
    for r in results.values():
        url = r.get("feed_url")
        if url:
            try:
                parsed = urlparse(url)
                feed_paths.append(parsed.path or "/")
            except Exception:
                pass

    if feed_paths:
        print("\n  Top 5 feed URL patterns:")
        for path, count in Counter(feed_paths).most_common(5):
            print(f"    {path:<30} {count:>4} outlets")
    print()


def main():
    parser = argparse.ArgumentParser(description="Discover RSS feeds and WordPress APIs for press outlets")
    parser.add_argument("--update", action="store_true",
                        help="Only re-scan outlets previously marked as no feed found")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"Number of concurrent workers (default: {MAX_WORKERS})")
    args = parser.parse_args()
    workers = args.workers

    print("=" * 60)
    print("  DMM Feed Discovery Scanner")
    print("=" * 60)

    # Load outlets from press database
    outlets = load_outlets()
    print(f"\nLoaded {len(outlets)} outlets with website URLs from press database")

    if args.update:
        # Load existing registry and only scan outlets with no feed
        if not REGISTRY_PATH.exists():
            print("ERROR: No existing registry found. Run without --update first.")
            sys.exit(1)

        with open(REGISTRY_PATH) as f:
            existing = json.load(f)

        existing_outlets = existing.get("outlets", {})
        rescan_domains = {
            domain for domain, data in existing_outlets.items()
            if data.get("feed_type") is None
        }

        outlets = [o for o in outlets if o["domain"] in rescan_domains]
        print(f"--update mode: re-scanning {len(outlets)} outlets with no feed found")

        if not outlets:
            print("Nothing to re-scan. All outlets already have feeds.")
            sys.exit(0)

        results, errors = scan_outlets(outlets, label="Re-scanning", workers=workers)

        # Merge results back into existing registry
        for domain, data in results.items():
            existing_outlets[domain] = data

        # Recalculate stats from merged data
        all_results = existing_outlets
    else:
        results, errors = scan_outlets(outlets, workers=workers)
        all_results = results

    # Build stats from all results
    total = len(all_results)
    rss_count = sum(1 for r in all_results.values() if r.get("feed_type") == "rss")
    wp_count = sum(1 for r in all_results.values() if r.get("feed_type") == "wordpress")
    none_count = sum(1 for r in all_results.values() if r.get("feed_type") is None)
    error_count = sum(1 for r in all_results.values() if r.get("error"))

    registry = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_outlets": total,
            "rss_found": rss_count,
            "wordpress_api_found": wp_count,
            "no_feed_found": none_count,
            "errors": error_count,
        },
        "outlets": all_results,
    }

    # Save registry
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    print(f"\nRegistry saved to {REGISTRY_PATH}")

    # Print summary for the current scan
    print_summary(results if not args.update else all_results, errors)


if __name__ == "__main__":
    main()
