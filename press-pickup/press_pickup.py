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
  Press articles: No API key required (Google News RSS).
  Social media supplement (optional): export BRAVE_API_KEY="your-brave-api-key"

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

# Social media domains to include (not skip, not press — treated specially)
SOCIAL_MEDIA_DOMAINS = {
    'instagram.com': 'Instagram',
    'facebook.com': 'Facebook',
    'x.com': 'X (Twitter)',
    'twitter.com': 'X (Twitter)',
}

# Domains to skip (streaming platforms, ticket sales, lyrics, etc.)
SKIP_DOMAINS = {
    'spotify.com', 'apple.com', 'music.apple.com', 'youtube.com',
    'youtu.be', 'tiktok.com', 'wikipedia.org', 'wikidata.org',
    'amazon.com', 'deezer.com', 'soundcloud.com', 'genius.com',
    'letras.com', 'letras.mus.br', 'musica.com', 'last.fm', 'discogs.com',
    'bandcamp.com', 'shazam.com', 'setlist.fm', 'songkick.com',
    'ticketmaster.com', 'stubhub.com', 'seatgeek.com',
}


def google_news_rss(query, gl='MX', hl='es-419', max_results=50, days=None):
    """
    Search Google News via free RSS feed. No API key required.

    Returns list of { title, link, snippet, domain, source }.
    Links are decoded from Google News redirects to actual article URLs.
    If days is set, filters results to only include articles from the last N days.
    """
    import requests
    import xml.etree.ElementTree as ET
    import time
    from email.utils import parsedate_to_datetime
    from googlenewsdecoder import new_decoderv1

    # URL path segments that indicate non-press content
    NON_PRESS_PATHS = ('/product/', '/shop/', '/cart/', '/store/', '/merch/',
                       '/buy/', '/order/', '/checkout/', '/tienda/')

    ceid = f'{gl}:{hl.split("-")[0]}'
    rss_url = f'https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}'

    try:
        resp = requests.get(rss_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"    RSS fetch failed: {e}")
        return []

    results = []
    seen_urls = set()

    # Date cutoff for filtering
    cutoff = None
    if days:
        cutoff = datetime.now().astimezone() - timedelta(days=days)

    items = root.findall('.//item')[:max_results]

    for item in items:
        title_el = item.find('title')
        link_el = item.find('link')
        source_el = item.find('source')
        desc_el = item.find('description')
        pub_el = item.find('pubDate')

        title = title_el.text if title_el is not None else ''
        google_link = link_el.text if link_el is not None else ''
        source_name = source_el.text if source_el is not None else ''
        snippet = desc_el.text if desc_el is not None else ''

        # Filter by date if cutoff is set
        if cutoff and pub_el is not None and pub_el.text:
            try:
                pub_dt = parsedate_to_datetime(pub_el.text)
                if pub_dt < cutoff:
                    continue
            except Exception:
                pass  # Include if date can't be parsed

        # Strip source name suffix from title (e.g. " - Indie Rocks! Magazine")
        if source_name and title.endswith(f' - {source_name}'):
            title = title[: -len(f' - {source_name}')]

        # Decode Google News redirect URL to actual article URL
        try:
            decoded = new_decoderv1(google_link)
            if decoded.get('status'):
                link = decoded['decoded_url']
            else:
                link = google_link  # Fallback to Google URL
        except Exception:
            link = google_link

        domain = extract_domain(link) or ''

        # Skip non-press domains
        if any(skip in domain for skip in SKIP_DOMAINS):
            continue

        # Skip non-article URLs
        link_lower = link.lower()
        if any(seg in link_lower for seg in NON_PRESS_PATHS):
            continue

        if link not in seen_urls:
            seen_urls.add(link)
            results.append({
                'title': title,
                'link': link,
                'snippet': snippet,
                'domain': domain,
                'source': source_name,
            })

        # Brief pause between URL decodings to be polite
        time.sleep(0.1)

    return results


def brave_search(query, api_key, num_results=20, freshness=None, search_type='web'):
    """
    Brave Search for organic or news results.
    search_type: 'web' for organic, 'news' for news articles.
    Returns list of { title, link, snippet, domain }.
    """
    import requests

    NON_PRESS_PATHS = ('/product/', '/shop/', '/cart/', '/store/', '/merch/',
                       '/buy/', '/order/', '/checkout/', '/tienda/')

    endpoint = f'https://api.search.brave.com/res/v1/{search_type}/search'
    params = {
        'q': query,
        'count': num_results,
        'search_lang': 'es',
        'text_decorations': 'false',
    }
    if freshness:
        params['freshness'] = freshness

    try:
        resp = requests.get(
            endpoint,
            headers={'X-Subscription-Token': api_key, 'Accept': 'application/json'},
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    Brave search failed: {e}")
        return []

    # News endpoint returns 'results' directly, web returns 'web.results'
    if search_type == 'news':
        raw_items = data.get('results', [])
    else:
        raw_items = data.get('web', {}).get('results', [])

    results = []
    for item in raw_items:
        link = item.get('url', '')
        domain = extract_domain(link) or ''

        if any(skip in domain for skip in SKIP_DOMAINS):
            continue

        link_lower = link.lower()
        if any(seg in link_lower for seg in NON_PRESS_PATHS):
            continue

        results.append({
            'title': item.get('title', ''),
            'link': link,
            'snippet': item.get('description', ''),
            'domain': domain,
        })

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


def _serper_date_within(date_str, cutoff):
    """Check if a Serper date string falls within the cutoff.
    Handles Spanish relative dates ('hace 3 días', 'hace 1 semana') and
    absolute dates ('8 oct 2025', '11 feb 2026').
    Returns True if the date is recent enough or can't be parsed.
    """
    if not date_str:
        return True  # Include if no date

    date_str = date_str.lower().strip()

    # Relative dates: "hace X días/horas/semanas/meses"
    match = re.match(r'hace\s+(\d+)\s+(hora|día|semana|mes|min)', date_str)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        if unit.startswith('min') or unit.startswith('hora'):
            return True  # Always recent
        elif unit.startswith('día'):
            article_date = datetime.now().astimezone() - timedelta(days=num)
        elif unit.startswith('semana'):
            article_date = datetime.now().astimezone() - timedelta(weeks=num)
        elif unit.startswith('mes'):
            article_date = datetime.now().astimezone() - timedelta(days=num * 30)
        else:
            return True
        return article_date >= cutoff

    # Absolute dates: "8 oct 2025", "11 feb 2026"
    MONTHS_ES = {
        'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
    }
    match = re.match(r'(\d{1,2})\s+(\w{3})\s+(\d{4})', date_str)
    if match:
        day, month_str, year = int(match.group(1)), match.group(2), int(match.group(3))
        month = MONTHS_ES.get(month_str[:3])
        if month:
            try:
                article_date = datetime(year, month, day).astimezone()
                return article_date >= cutoff
            except ValueError:
                pass

    return True  # Include if can't parse


def parse_search_terms(raw_input):
    """Split free-text input into individual search keywords.
    Handles: 'PNAU, Meduza', 'PNAU ft. Meduza', 'PNAU & Meduza', 'PNAU Meduza', etc.
    """
    # Split on common separators (comma, ampersand, slash, ft., feat., etc.)
    terms = re.split(r'[,&/]\s*|\s+(?:ft\.?|feat\.?|featuring|x|w/)\s+', raw_input, flags=re.IGNORECASE)
    terms = [t.strip() for t in terms if t.strip()]
    # If no explicit separator was found, treat the entire input as one term
    return terms if terms else [raw_input.strip()]


def run_press_pickup(artist, days=28, output_path=None, press_db_path=None):
    """
    Main press pickup workflow for a single artist.
    """
    # Load press database
    db_path = press_db_path or PRESS_DB_PATH
    if os.path.exists(db_path):
        print(f"Loading press database from {db_path}...")
        press_index, press_entries = load_press_database(db_path)
        print(f"  Loaded {len(press_entries)} media outlets")
    else:
        print(f"Warning: Press database not found at {db_path}")
        press_index, press_entries = {}, []

    keywords = parse_search_terms(artist)

    # Search across LATAM regions via Google News RSS (free, unlimited)
    regions = [
        ('MX', 'es-419'),  # Mexico (Latin American Spanish)
        ('AR', 'es-419'),  # Argentina
        ('BR', 'pt-BR'),   # Brazil (Portuguese)
        ('CL', 'es-419'),  # Chile
        ('CO', 'es-419'),  # Colombia
    ]

    print(f"\nSearching press for: {artist} (last {days} days)")

    all_results = []
    seen_urls = set()

    # 1) Google News RSS — free, unlimited, best for press articles
    for gl, hl in regions:
        query_parts = [f'"{kw}"' for kw in keywords]
        query = ' OR '.join(query_parts)
        print(f"  Google News [{gl}]: {query}")
        results = google_news_rss(query, gl=gl, hl=hl, days=days)
        for r in results:
            if r['link'] not in seen_urls:
                seen_urls.add(r['link'])
                all_results.append(r)

    print(f"  Found {len(all_results)} results from Google News")

    # 2) Brave organic search — catches social media, blogs (free tier: 2000/month)
    brave_key = os.environ.get('BRAVE_API_KEY')
    if brave_key:
        if days <= 1:
            freshness = 'pd'
        elif days <= 7:
            freshness = 'pw'
        elif days <= 30:
            freshness = 'pm'
        else:
            freshness = 'py'

        # Brave News — catches press articles Google News RSS might miss
        for kw in keywords:
            query = f'"{kw}"'
            print(f"  Brave News: {query}")
            results = brave_search(query, brave_key, num_results=20, freshness=freshness, search_type='news')
            for r in results:
                if r['link'] not in seen_urls:
                    seen_urls.add(r['link'])
                    all_results.append(r)

        # Brave Organic — catches blogs, smaller outlets
        for kw in keywords:
            query = f'"{kw}" música'
            print(f"  Brave Web: {query}")
            results = brave_search(query, brave_key, num_results=20, freshness=freshness, search_type='web')
            for r in results:
                if r['link'] not in seen_urls:
                    seen_urls.add(r['link'])
                    all_results.append(r)

    # 3) Serper — 3 credits per search: 1 news + 2 organic (social media + press keywords)
    serper_key = os.environ.get('SERPER_API_KEY')
    if serper_key:
        import requests as _requests

        if days <= 1:
            tbs = 'qdr:d'
        elif days <= 7:
            tbs = 'qdr:w'
        elif days <= 30:
            tbs = 'qdr:m'
        else:
            tbs = 'qdr:y'

        query_parts = [f'"{kw}"' for kw in keywords]
        base = ' OR '.join(query_parts)

        serper_calls = [
            ('news',   base),
            ('search', f'{base} música'),
            ('search', f'{base} lanzamiento OR álbum OR disco OR entrevista'),
        ]

        for search_type, query in serper_calls:
            label = 'News' if search_type == 'news' else 'Web'
            print(f"  Serper {label}: {query}")
            try:
                payload = {'q': query, 'gl': 'mx', 'hl': 'es', 'num': 20}
                # Only use tbs date filter for organic search; news is already sorted by recency
                if search_type == 'search':
                    payload['tbs'] = tbs
                resp = _requests.post(
                    f'https://google.serper.dev/{search_type}',
                    headers={'X-API-KEY': serper_key, 'Content-Type': 'application/json'},
                    json=payload,
                )
                resp.raise_for_status()
                result_key = 'news' if search_type == 'news' else 'organic'
                cutoff = datetime.now().astimezone() - timedelta(days=days)
                for item in resp.json().get(result_key, []):
                    # Filter news results by date (Serper returns 'date' like "hace 3 días", "8 oct 2025")
                    if search_type == 'news':
                        date_str = item.get('date', '')
                        if not _serper_date_within(date_str, cutoff):
                            continue

                    link = item.get('link', '')
                    domain = extract_domain(link) or ''
                    if any(skip in domain for skip in SKIP_DOMAINS):
                        continue
                    if link not in seen_urls:
                        seen_urls.add(link)
                        all_results.append({
                            'title': item.get('title', ''),
                            'link': link,
                            'snippet': item.get('snippet', ''),
                            'domain': domain,
                        })
            except Exception as e:
                print(f"    Serper failed: {e}")

    print(f"\nFound {len(all_results)} total unique results")
    
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
        snippet_lower = result['snippet'].lower()
        if not any(kw in title_lower or kw in snippet_lower for kw in keywords_lower):
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
        elif domain in SOCIAL_MEDIA_DOMAINS:
            # Social media post — include under LATAM with platform name
            media_name = SOCIAL_MEDIA_DOMAINS[domain]
            description = result['title']
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

        # Generate formatted .docx alongside the .txt
        try:
            docx_path = output_path.replace('.txt', '.docx') if output_path.endswith('.txt') else output_path + '.docx'
            _generate_press_docx(artist, country_results, docx_path)
            print(f"Word report saved: {docx_path}")
        except Exception as e:
            print(f"Warning: Could not generate .docx: {e}")
    else:
        print("\n" + "=" * 60)
        print(output_text)

    return country_results


def _generate_press_docx(artist, country_results, docx_path):
    """Generate a formatted .docx Press Pickup report."""
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Set default font and zero paragraph spacing
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(10)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)

    # Title: "Press Pick Up" in bold red
    title_para = doc.add_paragraph()
    title_run = title_para.add_run('Press Pick Up')
    title_run.bold = True
    title_run.font.color.rgb = RGBColor(0xC4, 0x30, 0x30)
    title_run.font.size = Pt(12)
    title_para.paragraph_format.space_after = Pt(4)

    for country in sorted(country_results.keys()):
        entries = country_results[country]

        # Country header: underlined, not bold — extra space before to separate sections
        country_para = doc.add_paragraph()
        country_run = country_para.add_run(country)
        country_run.underline = True
        country_run.font.size = Pt(10)
        country_para.paragraph_format.space_before = Pt(12)
        country_para.paragraph_format.space_after = Pt(2)

        # Deduplicate by media name
        seen_media = set()
        for entry in entries:
            if entry['media_name'] in seen_media:
                continue
            seen_media.add(entry['media_name'])

            db_flag = "" if entry['in_database'] else " [NEW — not in DB]"

            # Media entry: bold name + normal description
            media_para = doc.add_paragraph()
            name_run = media_para.add_run(f"{entry['media_name']}: ")
            name_run.bold = True
            name_run.font.size = Pt(10)

            desc_text = f"{entry['description']}{db_flag}"
            desc_run = media_para.add_run(desc_text)
            desc_run.font.size = Pt(10)
            media_para.paragraph_format.space_before = Pt(6)

            # URL as a clickable hyperlink on its own paragraph
            url_para = doc.add_paragraph()
            _add_hyperlink(url_para, entry['url'], entry['url'])

    doc.save(docx_path)


def _add_hyperlink(paragraph, url, text):
    """Add a clickable hyperlink to a paragraph in a .docx document."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    part = paragraph.part
    r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)

    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)

    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')

    # Blue color
    color = OxmlElement('w:color')
    color.set(qn('w:val'), '2E74B5')
    rPr.append(color)

    # Underline
    u = OxmlElement('w:u')
    u.set(qn('w:val'), 'single')
    rPr.append(u)

    # Font size
    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), '20')  # 10pt = 20 half-points
    rPr.append(sz)

    new_run.append(rPr)
    new_run.text = text
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


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
