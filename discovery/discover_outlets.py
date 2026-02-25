#!/usr/bin/env python3
"""
Contact & Outlet Discovery Assistant
=====================================
Proactively searches for new LATAM music/entertainment outlets not yet in the
press database. Uses the same Brave/Serper/Google News sources as Press Pickup
but with discovery-focused queries.

Results are deduplicated against the existing press_database.csv and optionally
enriched with LLM-generated descriptions.

Called from the web UI via /api/discovery/search.
"""

import os
import re
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

from shared.database import load_press_database, extract_domain

PRESS_DB_PATH = os.environ.get(
    'PRESS_DB_PATH',
    str(ROOT_DIR / 'data' / 'press_database.csv')
)

# Countries with search locales
COUNTRY_CONFIG = {
    'Mexico':      {'gl': 'MX', 'hl': 'es-419', 'tld': '.mx',    'lang': 'es'},
    'Brazil':      {'gl': 'BR', 'hl': 'pt-BR',  'tld': '.br',    'lang': 'pt'},
    'Argentina':   {'gl': 'AR', 'hl': 'es-419', 'tld': '.ar',    'lang': 'es'},
    'Chile':       {'gl': 'CL', 'hl': 'es-419', 'tld': '.cl',    'lang': 'es'},
    'Colombia':    {'gl': 'CO', 'hl': 'es-419', 'tld': '.co',    'lang': 'es'},
    'Peru':        {'gl': 'PE', 'hl': 'es-419', 'tld': '.pe',    'lang': 'es'},
    'Ecuador':     {'gl': 'EC', 'hl': 'es-419', 'tld': '.ec',    'lang': 'es'},
    'Uruguay':     {'gl': 'UY', 'hl': 'es-419', 'tld': '.uy',    'lang': 'es'},
    'Venezuela':   {'gl': 'VE', 'hl': 'es-419', 'tld': '.ve',    'lang': 'es'},
    'Costa Rica':  {'gl': 'CR', 'hl': 'es-419', 'tld': '.cr',    'lang': 'es'},
    'All LATAM':   {'gl': 'MX', 'hl': 'es-419', 'tld': None,     'lang': 'es'},
}

# Genre query templates (Spanish and Portuguese)
GENRE_QUERIES = {
    'electronic': {
        'es': ['música electrónica', 'DJ', 'techno', 'house music', 'EDM'],
        'pt': ['música eletrônica', 'DJ', 'techno', 'house music', 'EDM'],
    },
    'indie/alternative': {
        'es': ['música indie', 'rock alternativo', 'indie rock'],
        'pt': ['música indie', 'rock alternativo', 'indie rock'],
    },
    'pop': {
        'es': ['música pop', 'pop latino', 'pop en español'],
        'pt': ['música pop', 'pop brasileiro'],
    },
    'hip-hop/rap': {
        'es': ['hip hop latino', 'rap en español', 'trap latino'],
        'pt': ['hip hop brasileiro', 'rap brasileiro', 'trap'],
    },
    'reggaeton/urban': {
        'es': ['reggaetón', 'música urbana', 'perreo'],
        'pt': ['reggaeton', 'funk brasileiro', 'música urbana'],
    },
    'rock': {
        'es': ['rock en español', 'rock latino'],
        'pt': ['rock brasileiro', 'rock nacional'],
    },
    'general music': {
        'es': ['música', 'entretenimiento', 'cultura musical'],
        'pt': ['música', 'entretenimento', 'cultura musical'],
    },
}

# Discovery-focused search suffixes
OUTLET_TYPES = {
    'es': ['blog', 'revista', 'podcast', 'medio digital', 'magazine'],
    'pt': ['blog', 'revista', 'podcast', 'mídia digital', 'magazine'],
}

# Domains to skip entirely
SKIP_DOMAINS = {
    'spotify.com', 'apple.com', 'music.apple.com', 'deezer.com',
    'amazon.com', 'music.amazon.com', 'youtube.com', 'youtu.be',
    'soundcloud.com', 'bandcamp.com', 'tidal.com',
    'instagram.com', 'facebook.com', 'x.com', 'twitter.com',
    'tiktok.com', 'linkedin.com', 'threads.net', 'reddit.com',
    'wikipedia.org', 'wikidata.org', 'discogs.com',
    'google.com', 'google.com.mx', 'google.com.br',
    'translate.google.com', 'news.google.com',
    'pinterest.com', 'tumblr.com', 'medium.com',
}


def discover_outlets(
    genre='general music',
    countries=None,
    custom_query='',
    max_results_per_source=20,
    use_llm=True,
    log_fn=None,
):
    """
    Search for new outlets not in the press database.

    Args:
        genre: Key from GENRE_QUERIES or 'custom'
        countries: List of country names from COUNTRY_CONFIG (default: All LATAM)
        custom_query: Custom search terms (used when genre='custom')
        max_results_per_source: Max results per search call
        use_llm: Whether to use Claude for description enrichment
        log_fn: Logging function

    Returns dict with:
        - outlets: list of discovered outlet dicts
        - total_searched: number of raw results before dedup
        - already_in_db: number of results that matched existing DB
        - new_count: number of genuinely new outlets
    """
    if log_fn is None:
        log_fn = print

    if not countries:
        countries = ['All LATAM']

    # Load press database for deduplication
    log_fn('Loading press database for deduplication...')
    press_index, press_entries = load_press_database(PRESS_DB_PATH)
    known_domains = set()
    for entry in press_entries:
        if entry.get('website'):
            d = extract_domain(entry['website'])
            if d:
                known_domains.add(d)
    # Also add indexed domains
    for key in press_index:
        if '.' in key:  # It's a domain key
            known_domains.add(key)
    log_fn(f'  Loaded {len(press_entries)} outlets, {len(known_domains)} known domains')

    # Build search queries
    queries = _build_queries(genre, countries, custom_query)
    log_fn(f'  Built {len(queries)} search queries across {len(countries)} region(s)')

    # Execute searches
    all_raw = []
    seen_urls = set()

    for q in queries:
        query_text = q['query']
        gl = q['gl']
        hl = q['hl']
        source = q['source']

        if source == 'google_news':
            log_fn(f'\n  Google News [{q["country"]}]: {query_text[:80]}...' if len(query_text) > 80 else f'\n  Google News [{q["country"]}]: {query_text}')
            results = _search_google_news(query_text, gl, hl, max_results_per_source)
        elif source == 'brave':
            log_fn(f'  Brave [{q["country"]}]: {query_text[:80]}...' if len(query_text) > 80 else f'  Brave [{q["country"]}]: {query_text}')
            results = _search_brave(query_text, max_results_per_source)
        elif source == 'serper':
            log_fn(f'  Serper [{q["country"]}]: {query_text[:80]}...' if len(query_text) > 80 else f'  Serper [{q["country"]}]: {query_text}')
            results = _search_serper(query_text, gl, max_results_per_source)
        else:
            continue

        for r in results:
            if r['link'] not in seen_urls:
                seen_urls.add(r['link'])
                r['country'] = q['country']
                all_raw.append(r)

        log_fn(f'    → {len(results)} results')
        time.sleep(0.3)

    total_searched = len(all_raw)
    log_fn(f'\n  Total raw results: {total_searched}')

    # Deduplicate against press DB — group by domain
    domain_groups = {}
    for r in all_raw:
        domain = r.get('domain', '')
        if not domain or domain in SKIP_DOMAINS:
            continue
        if domain not in domain_groups:
            domain_groups[domain] = {
                'domain': domain,
                'articles': [],
                'countries': set(),
                'in_db': False,
            }
        domain_groups[domain]['articles'].append(r)
        domain_groups[domain]['countries'].add(r.get('country', ''))

    # Check each domain against known DB
    already_in_db = 0
    new_outlets = []
    for domain, group in domain_groups.items():
        # Check if domain (or close variant) is in DB
        if _domain_in_db(domain, known_domains, press_index):
            group['in_db'] = True
            already_in_db += 1
            continue
        new_outlets.append(group)

    log_fn(f'  Unique domains found: {len(domain_groups)}')
    log_fn(f'  Already in DB: {already_in_db}')
    log_fn(f'  New outlets: {len(new_outlets)}')

    # Sort by number of mentions (more mentions = more relevant)
    new_outlets.sort(key=lambda g: len(g['articles']), reverse=True)

    # Enrich with LLM descriptions (optional)
    enriched = []
    for group in new_outlets:
        best = group['articles'][0]  # Most representative article
        outlet_name = _guess_outlet_name(best)

        outlet = {
            'name': outlet_name,
            'domain': group['domain'],
            'url': f"https://{group['domain']}",
            'countries': sorted(group['countries']),
            'mentions': len(group['articles']),
            'sample_title': best.get('title', ''),
            'sample_snippet': best.get('snippet', ''),
            'sample_url': best.get('link', ''),
            'description': '',
        }

        enriched.append(outlet)

    # LLM enrichment pass
    if use_llm and enriched:
        log_fn('\n── Generating descriptions with LLM ──')
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            log_fn('  ANTHROPIC_API_KEY not set — using basic descriptions')
            for o in enriched:
                o['description'] = _basic_description(o)
        else:
            for i, o in enumerate(enriched):
                log_fn(f'  [{i+1}/{len(enriched)}] {o["name"]}...')
                o['description'] = _llm_description(api_key, o)
                time.sleep(0.3)
    elif enriched:
        for o in enriched:
            o['description'] = _basic_description(o)

    # Build output
    result = {
        'outlets': enriched,
        'total_searched': total_searched,
        'already_in_db': already_in_db,
        'new_count': len(enriched),
        'html': _build_html(enriched, genre, countries),
        'csv_rows': _build_csv_rows(enriched),
    }

    log_fn(f'\n  Discovery complete — {len(enriched)} new outlets found')
    return result


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------

def _build_queries(genre, countries, custom_query):
    """Build search queries for each country and source."""
    queries = []

    for country_name in countries:
        config = COUNTRY_CONFIG.get(country_name, COUNTRY_CONFIG['All LATAM'])
        lang = config['lang']
        gl = config['gl']
        hl = config['hl']

        if custom_query.strip():
            # Custom query mode
            queries.append({
                'query': custom_query,
                'gl': gl, 'hl': hl,
                'country': country_name,
                'source': 'google_news',
            })
            queries.append({
                'query': custom_query,
                'gl': gl, 'hl': hl,
                'country': country_name,
                'source': 'brave',
            })
            queries.append({
                'query': custom_query,
                'gl': gl, 'hl': hl,
                'country': country_name,
                'source': 'serper',
            })
        else:
            # Genre-based queries
            genre_terms = GENRE_QUERIES.get(genre, GENRE_QUERIES['general music'])
            terms = genre_terms.get(lang, genre_terms['es'])
            outlet_types = OUTLET_TYPES.get(lang, OUTLET_TYPES['es'])

            # Query 1: Genre + outlet type (Google News)
            for term in terms[:2]:
                for otype in outlet_types[:2]:
                    q = f'{term} {otype}'
                    queries.append({
                        'query': q,
                        'gl': gl, 'hl': hl,
                        'country': country_name,
                        'source': 'google_news',
                    })

            # Query 2: Genre + "entrevista" / "reseña" (Brave)
            review_words = ['entrevista', 'reseña'] if lang == 'es' else ['entrevista', 'resenha']
            for term in terms[:2]:
                q = f'{term} {" OR ".join(review_words)}'
                queries.append({
                    'query': q,
                    'gl': gl, 'hl': hl,
                    'country': country_name,
                    'source': 'brave',
                })

            # Query 3: Genre + discovery keywords (Serper)
            for term in terms[:2]:
                q = f'{term} {" OR ".join(outlet_types[:3])}'
                queries.append({
                    'query': q,
                    'gl': gl, 'hl': hl,
                    'country': country_name,
                    'source': 'serper',
                })

    return queries


# ---------------------------------------------------------------------------
# Search functions (reusing press_pickup patterns)
# ---------------------------------------------------------------------------

def _search_google_news(query, gl, hl, max_results):
    """Search Google News RSS (free, no API key)."""
    import requests
    import xml.etree.ElementTree as ET

    try:
        from googlenewsdecoder import new_decoderv1
    except ImportError:
        new_decoderv1 = None

    ceid = f'{gl}:{hl.split("-")[0]}'
    rss_url = f'https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}'

    try:
        resp = requests.get(rss_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    results = []
    seen = set()

    for item in root.findall('.//item')[:max_results]:
        title_el = item.find('title')
        link_el = item.find('link')
        source_el = item.find('source')
        desc_el = item.find('description')

        title = title_el.text if title_el is not None else ''
        google_link = link_el.text if link_el is not None else ''
        source_name = source_el.text if source_el is not None else ''
        snippet = desc_el.text if desc_el is not None else ''

        if source_name and title.endswith(f' - {source_name}'):
            title = title[: -len(f' - {source_name}')]

        # Decode Google News redirect
        link = google_link
        if new_decoderv1:
            try:
                decoded = new_decoderv1(google_link)
                if decoded.get('status'):
                    link = decoded['decoded_url']
            except Exception:
                pass

        domain = extract_domain(link) or ''
        if domain in SKIP_DOMAINS or link in seen:
            continue
        seen.add(link)

        results.append({
            'title': title,
            'link': link,
            'snippet': snippet,
            'domain': domain,
            'source_name': source_name,
        })
        time.sleep(0.1)

    return results


def _search_brave(query, max_results):
    """Search Brave (requires BRAVE_API_KEY)."""
    import requests

    api_key = os.environ.get('BRAVE_API_KEY')
    if not api_key:
        return []

    try:
        resp = requests.get(
            'https://api.search.brave.com/res/v1/web/search',
            headers={'X-Subscription-Token': api_key, 'Accept': 'application/json'},
            params={
                'q': query,
                'count': max_results,
                'search_lang': 'es',
                'text_decorations': 'false',
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get('web', {}).get('results', []):
        link = item.get('url', '')
        domain = extract_domain(link) or ''
        if domain in SKIP_DOMAINS:
            continue
        results.append({
            'title': item.get('title', ''),
            'link': link,
            'snippet': item.get('description', ''),
            'domain': domain,
            'source_name': '',
        })

    return results


def _search_serper(query, gl, max_results):
    """Search via Serper.dev (requires SERPER_API_KEY)."""
    import requests

    api_key = os.environ.get('SERPER_API_KEY')
    if not api_key:
        return []

    try:
        resp = requests.post(
            'https://google.serper.dev/search',
            headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'},
            json={'q': query, 'gl': gl.lower(), 'hl': 'es', 'num': max_results},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        return []

    results = []
    for item in resp.json().get('organic', []):
        link = item.get('link', '')
        domain = extract_domain(link) or ''
        if domain in SKIP_DOMAINS:
            continue
        results.append({
            'title': item.get('title', ''),
            'link': link,
            'snippet': item.get('snippet', ''),
            'domain': domain,
            'source_name': '',
        })

    return results


# ---------------------------------------------------------------------------
# Deduplication & enrichment
# ---------------------------------------------------------------------------

def _domain_in_db(domain, known_domains, press_index):
    """Check if a domain (or close variant) is already in the press DB."""
    if domain in known_domains or domain in press_index:
        return True
    # Check without 'www.'
    bare = domain.replace('www.', '')
    if bare in known_domains or bare in press_index:
        return True
    # Check core domain (e.g., "indierocks" from "indierocks.mx")
    core = bare.split('.')[0] if '.' in bare else bare
    for known in known_domains:
        known_core = known.replace('www.', '').split('.')[0]
        if core == known_core and len(core) > 3:
            return True
    return False


def _guess_outlet_name(article):
    """Guess the outlet name from search result metadata."""
    # Use source_name if available (from Google News RSS)
    if article.get('source_name'):
        return article['source_name']
    # Fall back to a cleaned-up domain
    domain = article.get('domain', '')
    name = domain.replace('www.', '').split('.')[0]
    return name.title() if name else domain


def _basic_description(outlet):
    """Generate a basic description without LLM."""
    parts = []
    if outlet.get('sample_snippet'):
        # Take first sentence of snippet
        snippet = outlet['sample_snippet']
        first_sentence = snippet.split('.')[0].strip()
        if len(first_sentence) > 20:
            parts.append(first_sentence + '.')
    if outlet.get('countries'):
        parts.append(f"Found in: {', '.join(outlet['countries'])}.")
    if outlet.get('mentions', 0) > 1:
        parts.append(f"Appeared in {outlet['mentions']} search results.")
    return ' '.join(parts) if parts else 'Music/entertainment outlet discovered via search.'


def _llm_description(api_key, outlet):
    """Generate an enriched description using Claude."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""Write a one-sentence description of this media outlet for a music marketing team's contact database.

Domain: {outlet['domain']}
Sample article title: {outlet['sample_title']}
Sample snippet: {outlet['sample_snippet'][:200]}
Countries found in: {', '.join(outlet['countries'])}

Format: "[Type of outlet] covering [focus]. [Optional: Social Media: XK]"
Examples:
- "Digital music magazine covering indie and alternative music in Mexico."
- "Brazilian entertainment blog focused on electronic music and DJ culture."
- "Chilean podcast network covering Latin American rock and pop."
Just output the description, nothing else."""
            }]
        )
        return response.content[0].text.strip()
    except Exception:
        return _basic_description(outlet)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _build_html(outlets, genre, countries):
    """Build HTML summary of discovered outlets."""
    country_str = ', '.join(countries)
    genre_label = genre.replace('/', ' / ').title()

    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.6;max-width:700px;">
<h2 style="margin:0 0 8px;font-size:20px;">New Outlet Discoveries</h2>
<p style="color:#666;margin:0 0 20px;">Genre: <strong>{escape(genre_label)}</strong> | Region: <strong>{escape(country_str)}</strong> | Found: <strong>{len(outlets)}</strong> new outlets</p>
"""

    if not outlets:
        html += '<p style="color:#888;font-style:italic;">No new outlets discovered. The existing database may already have good coverage for this genre/region.</p>\n'
    else:
        for i, o in enumerate(outlets, 1):
            countries_str = ', '.join(o.get('countries', []))
            html += f"""<div style="margin:0 0 16px;padding:12px 16px;border:1px solid #e5e5e5;border-radius:8px;">
<p style="margin:0 0 4px;"><strong>{escape(o['name'])}</strong> <span style="color:#888;">({escape(o['domain'])})</span></p>
<p style="margin:0 0 4px;color:#555;font-size:13px;">{escape(o.get('description', ''))}</p>
<p style="margin:0;font-size:12px;color:#888;">Region: {escape(countries_str)} | Mentions: {o.get('mentions', 1)} | <a href="{escape(o.get('sample_url', o['url']))}" style="color:#2e74b5;">Sample article</a></p>
</div>
"""

    html += '</div>'
    return html


def _build_csv_rows(outlets):
    """Build CSV-ready rows for Notion import."""
    rows = []
    for o in outlets:
        rows.append({
            'NAME OF MEDIA': o['name'],
            'Territory': ', '.join(o.get('countries', [])),
            'DESCRIPTION & SM': o.get('description', ''),
            'WEBSITE': o['url'],
            'REACH': '',
        })
    return rows
