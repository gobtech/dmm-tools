#!/usr/bin/env python3
"""
Social Handle Discovery Script
===============================
Scans outlet websites for Instagram, Facebook, and X/Twitter links.
Saves results to data/social_handle_registry.json for use by Press Pickup.

Usage:
  python discover_social_handles.py              # Full scan
  python discover_social_handles.py --update     # Re-scan outlets with no handles
  python discover_social_handles.py --workers 50 # Custom concurrency
"""

import argparse
import csv
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
_ENRICHED_CSV = ROOT / "data" / "press_database_enriched.csv"
CSV_PATH = _ENRICHED_CSV if _ENRICHED_CSV.exists() else ROOT / "data" / "press_database.csv"
REGISTRY_PATH = ROOT / "data" / "social_handle_registry.json"

# ── Constants ──────────────────────────────────────────────────────────────────
TIMEOUT = 5
MAX_WORKERS = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

# Domains that are not real outlet websites
SKIP_DOMAINS = {
    "instagram.com", "facebook.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "linkedin.com", "threads.net",
    "open.spotify.com", "soundcloud.com", "apple.com",
    "music.apple.com", "music.amazon.com",
}

# Instagram paths that are NOT handles
INSTAGRAM_SKIP = {
    "accounts", "explore", "p", "reel", "reels", "stories", "tv",
    "direct", "about", "legal", "privacy", "terms", "developer",
    "static", "emails", "challenge", "web", "nametag",
}

# Facebook paths that are NOT pages
FACEBOOK_SKIP = {
    "sharer", "sharer.php", "share", "dialog", "plugins", "login",
    "groups", "watch", "marketplace", "gaming", "events", "help",
    "policies", "privacy", "terms", "about", "settings", "recover",
    "permalink.php", "story.php", "photo.php", "video", "pg",
    "profile.php", "pages",
}

# X/Twitter paths that are NOT handles
TWITTER_SKIP = {
    "intent", "share", "search", "explore", "home", "hashtag",
    "settings", "login", "i", "compose", "messages", "notifications",
    "about", "tos", "privacy", "help",
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
    """Load outlets with website URLs from press database CSV."""
    outlets = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("NAME OF MEDIA", "").strip()
            website = row.get("WEBSITE", "").strip()
            territory = row.get("Territory", "").strip()

            if not name:
                continue
            if not website or website.lower() in ("", "n/a", "-"):
                continue

            domain = extract_domain(website)
            if not domain:
                continue
            if any(domain.endswith(sd) for sd in SKIP_DOMAINS):
                continue

            outlets.append({
                "name": name,
                "website": website,
                "domain": domain,
                "territory": territory,
            })

    # Deduplicate by domain (keep first occurrence)
    seen = set()
    unique = []
    for o in outlets:
        if o["domain"] not in seen:
            seen.add(o["domain"])
            unique.append(o)
    return unique


def normalize_handle(raw: str) -> str | None:
    """Normalize a social media handle: lowercase, strip @, clean up."""
    if not raw:
        return None
    handle = unquote(raw).strip().lower().strip("@").strip("/")
    handle = handle.split("?")[0].split("#")[0].strip("/")
    # Only keep the first path segment
    if "/" in handle:
        handle = handle.split("/")[0]
    if not handle or len(handle) < 2:
        return None
    return handle


def extract_instagram(href: str) -> str | None:
    """Extract Instagram handle from a URL."""
    match = re.search(r"instagram\.com/([^/?&#]+)", href, re.IGNORECASE)
    if not match:
        return None
    handle = normalize_handle(match.group(1))
    if not handle or handle in INSTAGRAM_SKIP:
        return None
    return handle


def extract_facebook(href: str) -> str | None:
    """Extract Facebook page name from a URL."""
    match = re.search(r"facebook\.com/([^/?&#]+)", href, re.IGNORECASE)
    if not match:
        return None
    handle = normalize_handle(match.group(1))
    if not handle or handle in FACEBOOK_SKIP:
        return None
    return handle


def extract_twitter(href: str) -> str | None:
    """Extract X/Twitter handle from a URL."""
    match = re.search(r"(?:twitter\.com|x\.com)/([^/?&#]+)", href, re.IGNORECASE)
    if not match:
        return None
    handle = normalize_handle(match.group(1))
    if not handle or handle in TWITTER_SKIP:
        return None
    return handle


def discover_social(outlet: dict) -> dict:
    """
    Fetch outlet homepage and extract social media handles.
    Returns a result dict with instagram, facebook, twitter handles.
    """
    base_url = normalize_base_url(outlet["website"])
    result = {
        "name": outlet["name"],
        "country": outlet["territory"],
        "instagram": None,
        "facebook": None,
        "twitter": None,
        "error": None,
    }

    try:
        resp = requests.get(
            base_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        html = resp.text

        instagram_candidates = []
        facebook_candidates = []
        twitter_candidates = []

        # Scan all <a> href attributes
        for href_match in re.finditer(
            r'<a\s[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE
        ):
            href = href_match.group(1)

            if "instagram.com/" in href:
                handle = extract_instagram(href)
                if handle:
                    instagram_candidates.append(handle)
            if "facebook.com/" in href:
                handle = extract_facebook(href)
                if handle:
                    facebook_candidates.append(handle)
            if "twitter.com/" in href or "x.com/" in href:
                handle = extract_twitter(href)
                if handle:
                    twitter_candidates.append(handle)

        # Also check <meta> tags (og:see_also, article:author, etc.)
        for meta_match in re.finditer(
            r'<meta\s[^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE
        ):
            content = meta_match.group(1)
            if "instagram.com/" in content:
                handle = extract_instagram(content)
                if handle:
                    instagram_candidates.append(handle)
            if "facebook.com/" in content:
                handle = extract_facebook(content)
                if handle:
                    facebook_candidates.append(handle)
            if "twitter.com/" in content or "x.com/" in content:
                handle = extract_twitter(content)
                if handle:
                    twitter_candidates.append(handle)

        # Pick the most frequently linked handle per platform
        if instagram_candidates:
            result["instagram"] = Counter(instagram_candidates).most_common(1)[0][0]
        if facebook_candidates:
            result["facebook"] = Counter(facebook_candidates).most_common(1)[0][0]
        if twitter_candidates:
            result["twitter"] = Counter(twitter_candidates).most_common(1)[0][0]

    except requests.exceptions.Timeout:
        result["error"] = "timeout"
    except requests.exceptions.ConnectionError:
        result["error"] = "connection_error"
    except Exception as e:
        result["error"] = str(e)[:100]

    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Discover social media handles for press outlets"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="Only re-scan outlets with no social handles found",
    )
    parser.add_argument(
        "--workers", type=int, default=MAX_WORKERS,
        help=f"Number of concurrent workers (default: {MAX_WORKERS})",
    )
    args = parser.parse_args()

    print(f"Loading outlets from {CSV_PATH.name}...")
    outlets = load_outlets()
    print(f"  {len(outlets)} outlets with website URLs")

    # Load existing registry for --update mode
    existing = {}
    if args.update and REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("outlets", {})
        print(f"  Loaded existing registry: {len(existing)} outlets")

        to_scan = []
        for o in outlets:
            entry = existing.get(o["domain"])
            if entry and (
                entry.get("instagram")
                or entry.get("facebook")
                or entry.get("twitter")
            ):
                continue
            to_scan.append(o)
        print(f"  Re-scanning {len(to_scan)} outlets with no handles")
        outlets = to_scan

    if not outlets:
        print("Nothing to scan.")
        return

    print(f"\nScanning {len(outlets)} outlets with {args.workers} workers...")
    start = time.time()

    results = {}
    errors = 0
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(discover_social, o): o for o in outlets}
        for future in as_completed(futures):
            outlet = futures[future]
            domain = outlet["domain"]
            done += 1

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "name": outlet["name"],
                    "country": outlet["territory"],
                    "instagram": None,
                    "facebook": None,
                    "twitter": None,
                    "error": str(e)[:100],
                }

            if result.get("error"):
                errors += 1

            results[domain] = {
                "name": result["name"],
                "country": result["country"],
                "instagram": result["instagram"],
                "facebook": result["facebook"],
                "twitter": result["twitter"],
            }

            if done % 50 == 0 or done == len(outlets):
                elapsed = time.time() - start
                print(f"  [{done}/{len(outlets)}] {elapsed:.1f}s — {domain}")

    elapsed = time.time() - start
    print(f"\nScanned {len(results)} outlets in {elapsed:.1f}s ({errors} errors)")

    # Merge with existing if --update
    if existing:
        for domain, entry in existing.items():
            if domain not in results:
                results[domain] = entry

    # Build stats
    with_ig = sum(1 for r in results.values() if r.get("instagram"))
    with_fb = sum(1 for r in results.values() if r.get("facebook"))
    with_tw = sum(1 for r in results.values() if r.get("twitter"))
    with_any = sum(
        1 for r in results.values()
        if r.get("instagram") or r.get("facebook") or r.get("twitter")
    )
    with_none = len(results) - with_any

    stats = {
        "total_outlets": len(results),
        "with_instagram": with_ig,
        "with_facebook": with_fb,
        "with_twitter": with_tw,
        "with_any_social": with_any,
        "with_none": with_none,
        "errors": errors,
    }

    # Build reverse lookup: handle → outlet info
    handle_to_outlet = {"instagram": {}, "facebook": {}, "twitter": {}}
    for domain, entry in results.items():
        info = {"name": entry["name"], "domain": domain, "country": entry["country"]}
        if entry.get("instagram"):
            handle_to_outlet["instagram"][entry["instagram"]] = info
        if entry.get("facebook"):
            handle_to_outlet["facebook"][entry["facebook"]] = info
        if entry.get("twitter"):
            handle_to_outlet["twitter"][entry["twitter"]] = info

    registry = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "outlets": dict(sorted(results.items())),
        "handle_to_outlet": handle_to_outlet,
    }

    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {REGISTRY_PATH}")
    print(f"\n{'=' * 50}")
    print(f"  Total outlets:    {stats['total_outlets']}")
    print(f"  With Instagram:   {stats['with_instagram']}")
    print(f"  With Facebook:    {stats['with_facebook']}")
    print(f"  With X/Twitter:   {stats['with_twitter']}")
    print(f"  With any social:  {stats['with_any_social']}")
    print(f"  With none:        {stats['with_none']}")
    print(f"  Errors:           {stats['errors']}")
    print(f"{'=' * 50}")

    # Show examples of outlets with all 3 platforms
    all_three = [
        (d, e) for d, e in sorted(results.items())
        if e.get("instagram") and e.get("facebook") and e.get("twitter")
    ]
    if all_three:
        print(f"\nExamples with all 3 platforms ({len(all_three)} total):")
        for domain, entry in all_three[:10]:
            print(f"  {entry['name']} ({domain}) [{entry['country']}]")
            print(
                f"    IG: @{entry['instagram']}  "
                f"FB: {entry['facebook']}  "
                f"X: @{entry['twitter']}"
            )


if __name__ == "__main__":
    main()
