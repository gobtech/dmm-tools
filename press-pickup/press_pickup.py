#!/usr/bin/env python3
"""
Press Pickup Tool
=================
Searches for Spanish-language press coverage of artists, matches results
against the press description database, and generates a formatted report.

Usage:
  python press_pickup.py --artist "Djo" --days 28
  python press_pickup.py --artist "Djo" --days 7 --output djo_press.txt
  python press_pickup.py --all --days 7  # All artists from release schedule

Requirements:
  pip install requests

Setup:
  1. Get a Brave Search API key: https://brave.com/search/api/
  2. Set environment variable:
     export BRAVE_API_KEY="your-brave-api-key"

  Optional (for auto-generating missing media descriptions):
     export ANTHROPIC_API_KEY="your-anthropic-api-key"
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent dir to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.database import load_press_database, match_url_to_media, extract_domain

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRESS_DB_PATH = os.environ.get(
    'PRESS_DB_PATH',
    str(Path(__file__).parent.parent / 'data' / 'press_database.csv')
)

RELEASE_SCHEDULE_URL = os.environ.get(
    'RELEASE_SCHEDULE_URL',
    'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
)

# Map TLDs / URL patterns to countries for grouping (longer patterns first)
DOMAIN_TO_COUNTRY = {
    '.com.ar': 'ARGENTINA', '.gob.ar': 'ARGENTINA', '.ar': 'ARGENTINA',
    '.com.br': 'BRAZIL', '.org.br': 'BRAZIL', '.br': 'BRAZIL',
    '.cl': 'CHILE',
    '.com.co': 'COLOMBIA',
    '.com.mx': 'MEXICO', '.gob.mx': 'MEXICO', '.mx': 'MEXICO',
    '.com.pe': 'PERU', '.pe': 'PERU',
    '.com.ec': 'ECUADOR', '.ec': 'ECUADOR',
    '.com.uy': 'URUGUAY', '.uy': 'URUGUAY',
    '.com.ve': 'VENEZUELA', '.ve': 'VENEZUELA',
    '.com.pa': 'PANAMA', '.pa': 'PANAMA',
    '.cr': 'COSTA RICA',
    '.com.gt': 'GUATEMALA', '.gt': 'GUATEMALA',
    '.hn': 'HONDURAS',
    '.com.sv': 'EL SALVADOR', '.sv': 'EL SALVADOR',
    '.com.ni': 'NICARAGUA', '.ni': 'NICARAGUA',
    '.com.do': 'DOMINICAN REPUBLIC', '.do': 'DOMINICAN REPUBLIC',
    '.com.py': 'PARAGUAY', '.py': 'PARAGUAY',
    '.com.bo': 'BOLIVIA', '.bo': 'BOLIVIA',
    '.cu': 'CUBA',
}

# TLD suffixes that confirm a domain is LATAM
LATAM_TLD_SUFFIXES = {
    '.ar', '.br', '.cl', '.co', '.mx', '.pe', '.ec', '.uy', '.ve', '.pa',
    '.cr', '.gt', '.hn', '.sv', '.ni', '.do', '.py', '.bo', '.cu',
}

# Domains to skip (not press / not LATAM)
SKIP_DOMAINS = {
    'spotify.com', 'apple.com', 'music.apple.com', 'youtube.com',
    'youtu.be', 'tiktok.com', 'instagram.com', 'facebook.com',
    'twitter.com', 'x.com', 'wikipedia.org', 'wikidata.org',
    'amazon.com', 'deezer.com', 'soundcloud.com', 'genius.com',
    'letras.com', 'musica.com', 'last.fm', 'discogs.com',
    'bandcamp.com', 'shazam.com', 'setlist.fm', 'songkick.com',
    'ticketmaster.com', 'stubhub.com', 'seatgeek.com',
}


def brave_search(query, api_key, num_results=20, freshness=None, pages=5):
    """
    Search using Brave Search API with pagination.
    Fetches multiple pages of results for deeper coverage.
    Returns list of { title, link, snippet, domain }.
    """
    import requests
    import time

    # URL path segments that indicate non-press content
    NON_PRESS_PATHS = ('/product/', '/shop/', '/cart/', '/store/', '/merch/',
                       '/buy/', '/order/', '/checkout/', '/tienda/')

    results = []
    seen_urls = set()
    per_page = min(20, num_results)

    for page in range(pages):
        offset = page * per_page

        params = {
            'q': query,
            'count': per_page,
            'offset': offset,
            'search_lang': 'es',
            'text_decorations': 'false',
        }
        if freshness:
            params['freshness'] = freshness

        try:
            resp = requests.get(
                'https://api.search.brave.com/res/v1/web/search',
                headers={'X-Subscription-Token': api_key, 'Accept': 'application/json'},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"    Page {page + 1} failed: {e}")
            break

        web_results = data.get('web', {}).get('results', [])

        if not web_results:
            break  # No more results available

        new_count = 0
        for item in web_results:
            link = item.get('url', '')
            domain = extract_domain(link) or ''

            # Skip non-press domains
            if any(skip in domain for skip in SKIP_DOMAINS):
                continue

            # Skip non-article URLs (product pages, shops, etc.)
            link_lower = link.lower()
            if any(seg in link_lower for seg in NON_PRESS_PATHS):
                continue

            if link not in seen_urls:
                seen_urls.add(link)
                new_count += 1
                results.append({
                    'title': item.get('title', ''),
                    'link': link,
                    'snippet': item.get('description', ''),
                    'domain': domain,
                })

        # Stop early if this page returned fewer than 5 new unique results —
        # deeper pages are just recycling content, not worth the API call
        if new_count < 5 and page > 0:
            print(f"    Stopped at page {page + 1} (only {new_count} new results)")
            break

        # Also stop if Brave returned a short page (fewer results than requested)
        if len(web_results) < per_page:
            break

        # Brief pause between pages to respect rate limits
        if page < pages - 1:
            time.sleep(0.3)

    return results


def detect_country_from_url(url):
    """Detect country from URL's TLD. Returns None for non-LATAM domains."""
    domain = extract_domain(url) or ''
    # Check specific TLDs (longer first to avoid false matches)
    for tld, country in sorted(DOMAIN_TO_COUNTRY.items(), key=lambda x: -len(x[0])):
        if domain.endswith(tld):
            return country
    return None


def is_latam_domain(domain):
    """Check if a domain has a LATAM country-code TLD."""
    for suffix in LATAM_TLD_SUFFIXES:
        if domain.endswith(suffix):
            return True
    return False


def normalize_country(name):
    """Normalize country names to a consistent format."""
    mapping = {
        'MÉXICO': 'MEXICO',
        'PERÚ': 'PERU',
        'PANAMÁ': 'PANAMA',
        'REPÚBLICA DOMINICANA': 'DOMINICAN REPUBLIC',
    }
    return mapping.get(name, name)


def generate_description_with_llm(media_name, url, snippet):
    """
    Generate a press description using Claude API for outlets not in the database.
    Falls back to a basic description if API is not available.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return f"Online media outlet covering entertainment and music news."
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""Write a one-sentence description of the media outlet "{media_name}" based on this context:
URL: {url}
Snippet: {snippet}

Format it like: "Description of outlet type and focus. Social Media: [X]K" 
If you don't know the social media count, omit it. Keep it factual and concise, similar to:
"Top newspaper in the country, distribution 700K a week. Social Media: 7M"
"Digital platform focused on music, cinema, shows and culture news."
Just output the description, nothing else."""
            }]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"  Warning: LLM description generation failed: {e}")
        return f"Online media outlet covering entertainment and music news."


def parse_search_terms(raw_input):
    """Split free-text input into individual search keywords.
    Handles: 'PNAU, Meduza', 'PNAU ft. Meduza', 'PNAU & Meduza', 'PNAU Meduza', etc.
    """
    # Split on common separators (comma, ampersand, slash, ft., feat., etc.)
    terms = re.split(r'[,&/]\s*|\s+(?:ft\.?|feat\.?|featuring|x|w/)\s+', raw_input, flags=re.IGNORECASE)
    terms = [t.strip() for t in terms if t.strip()]
    # If no explicit separator was found, split on whitespace as fallback
    if len(terms) <= 1:
        terms = raw_input.strip().split()
    return terms if terms else [raw_input.strip()]


def run_press_pickup(artist, days=28, output_path=None, press_db_path=None):
    """
    Main press pickup workflow for a single artist.
    """
    api_key = os.environ.get('BRAVE_API_KEY')

    if not api_key:
        print("Error: BRAVE_API_KEY environment variable required.")
        print("See --help for setup instructions.")
        sys.exit(1)
    
    # Load press database
    db_path = press_db_path or PRESS_DB_PATH
    if os.path.exists(db_path):
        print(f"Loading press database from {db_path}...")
        press_index, press_entries = load_press_database(db_path)
        print(f"  Loaded {len(press_entries)} media outlets")
    else:
        print(f"Warning: Press database not found at {db_path}")
        press_index, press_entries = {}, []
    
    # Build search queries — Brave freshness format
    if days <= 1:
        freshness = 'pd'      # past day
    elif days <= 7:
        freshness = 'pw'      # past week
    elif days <= 30:
        freshness = 'pm'      # past month
    else:
        freshness = 'py'      # past year
    
    keywords = parse_search_terms(artist)

    queries = []
    for kw in keywords:
        queries.append(f'"{kw}" música')
        queries.append(f'"{kw}" concierto')
        queries.append(f'"{kw}" entrevista')
        queries.append(f'"{kw}" lanzamiento')
        queries.append(f'"{kw}" música show Brasil')
    
    print(f"\nSearching press for: {artist} (last {days} days)")
    
    all_results = []
    seen_urls = set()
    
    pages_per_query = 5
    print(f"  Fetching {pages_per_query} pages per query ({pages_per_query * 20} results each)")

    for query in queries:
        print(f"  Searching: {query}")
        results = brave_search(query, api_key, num_results=20, freshness=freshness, pages=pages_per_query)
        for r in results:
            if r['link'] not in seen_urls:
                seen_urls.add(r['link'])
                all_results.append(r)
    
    print(f"\nFound {len(all_results)} unique results")
    
    # Match against press database and group by country
    country_results = {}
    skipped = 0
    keywords_lower = [k.lower() for k in keywords]

    for result in all_results:
        domain = result['domain']

        # Check if article is actually about any of the search keywords
        # Require at least one keyword in the title (snippet alone is too loose —
        # e.g. "Meduza" the Russian news outlet can appear in unrelated articles)
        title_lower = result['title'].lower()
        if not any(kw in title_lower for kw in keywords_lower):
            skipped += 1
            continue

        country = detect_country_from_url(result['link'])
        media_entry = match_url_to_media(result['link'], press_index)

        if media_entry:
            # Known outlet from DB — always include
            description = media_entry['description']
            media_name = media_entry['name']
            if media_entry['territory'] and media_entry['territory'] not in ('PENDING', 'CANCELLED'):
                territory = media_entry['territory']
                if ',' not in territory:
                    country = normalize_country(territory.upper())
            if not country:
                country = 'LATAM'
        elif is_latam_domain(domain):
            # New outlet with LATAM TLD — include and flag
            media_name = domain.split('.')[0].title() if domain else 'Unknown'
            description = generate_description_with_llm(media_name, result['link'], result['snippet'])
            if not country:
                country = 'LATAM'
            print(f"  New outlet (not in DB): {media_name} ({domain})")
        else:
            # Non-LATAM domain, not in DB — skip (likely US/UK/Spain)
            skipped += 1
            continue

        country = normalize_country(country)

        if country not in country_results:
            country_results[country] = []

        country_results[country].append({
            'media_name': media_name,
            'description': description,
            'url': result['link'],
            'title': result['title'],
            'snippet': result['snippet'],
            'in_database': media_entry is not None,
        })

    if skipped:
        print(f"  Filtered out {skipped} non-LATAM or irrelevant results")
    
    # Format output
    output_lines = [f"Press Pickup — {artist}\n"]
    
    for country in sorted(country_results.keys()):
        entries = country_results[country]
        output_lines.append(f"\n{country}")
        
        # Deduplicate by media name
        seen_media = set()
        for entry in entries:
            if entry['media_name'] in seen_media:
                continue
            seen_media.add(entry['media_name'])
            
            db_flag = "" if entry['in_database'] else " [NEW — not in DB]"
            output_lines.append(f"{entry['media_name']}: {entry['description']}{db_flag}")
            output_lines.append(entry['url'])
            output_lines.append("")
    
    output_text = '\n'.join(output_lines)
    
    # Save or print
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"\nReport saved: {output_path}")
    else:
        print("\n" + "=" * 60)
        print(output_text)
    
    return country_results


def main():
    parser = argparse.ArgumentParser(
        description='Press Pickup Tool — Find and format press coverage for artists',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python press_pickup.py --artist "Djo" --days 28
  python press_pickup.py --artist "Djo" --days 7 --output djo_press.txt
  python press_pickup.py --all --days 7

Environment Variables:
  BRAVE_API_KEY      Brave Search API key (required)
  ANTHROPIC_API_KEY  Anthropic API key (optional, for generating missing descriptions)
  PRESS_DB_PATH      Path to press description database CSV
  RELEASE_SCHEDULE_URL  Published Google Sheets URL for release schedule
        """
    )
    
    parser.add_argument('--artist', help='Artist name to search for')
    parser.add_argument('--all', action='store_true', help='Process all artists from release schedule')
    parser.add_argument('--days', type=int, default=28, help='Number of days to search back (default: 28)')
    parser.add_argument('--output', help='Output file path (default: print to stdout)')
    parser.add_argument('--press-db', help='Path to press description database CSV')
    parser.add_argument('--release-schedule', help='Path or URL to release schedule CSV')
    
    args = parser.parse_args()
    
    if not args.artist and not args.all:
        parser.error('Either --artist or --all is required')
    
    if args.all:
        # Load release schedule and process all artists
        schedule_source = args.release_schedule or RELEASE_SCHEDULE_URL
        print(f"Loading release schedule from {schedule_source}...")
        
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from shared.database import load_release_schedule
        
        releases = load_release_schedule(schedule_source)
        artists = sorted(set(r['artist'] for r in releases))
        print(f"Found {len(artists)} unique artists")
        
        for artist in artists:
            print(f"\n{'=' * 60}")
            output_path = None
            if args.output:
                safe_name = re.sub(r'[^a-zA-Z0-9]', '_', artist).lower()
                output_path = f"{args.output}/{safe_name}_press.txt"
            
            run_press_pickup(artist, args.days, output_path, args.press_db)
    else:
        run_press_pickup(args.artist, args.days, args.output, args.press_db)


if __name__ == '__main__':
    main()
