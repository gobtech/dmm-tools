"""
Shared utilities for DMM automation tools.
Loads and indexes the press description database from Notion export.
"""

import csv
import re
from pathlib import Path


def load_press_database(csv_path):
    """
    Load the press description Notion database.
    Returns a dict: { normalized_name: { name, territory, description, website, ... } }
    Also returns a list for fuzzy matching.
    """
    entries = []
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('NAME OF MEDIA', '').strip()
            territory = row.get('Territory', '').strip()
            description = row.get('DESCRIPTION & SM', '').strip()
            website = row.get('WEBSITE', '').strip()
            reach = row.get('REACH', '').strip()
            
            if not name:
                continue
            
            entries.append({
                'name': name,
                'territory': territory,
                'description': description,
                'website': website,
                'reach': reach,
            })
    
    # Domains too generic to index (social media platforms)
    SKIP_INDEX_DOMAINS = {
        'instagram.com', 'facebook.com', 'x.com', 'twitter.com',
        'youtube.com', 'tiktok.com', 'linkedin.com', 'threads.net',
    }

    # Build lookup index: multiple keys per entry for flexible matching
    index = {}
    for entry in entries:
        # Exact name (lowercased)
        key = entry['name'].lower().strip()
        index[key] = entry

        # Also index by website domain if available
        if entry['website']:
            domain = extract_domain(entry['website'])
            if domain and domain not in SKIP_INDEX_DOMAINS:
                index[domain] = entry
    
    return index, entries


def extract_domain(url):
    """Extract clean domain from URL."""
    url = url.strip().lower()
    if not url.startswith('http'):
        url = 'https://' + url
    match = re.match(r'https?://(?:www\.)?([^/]+)', url)
    if match:
        return match.group(1)
    return None


def match_url_to_media(url, press_index):
    """
    Given a URL from a search result, try to match it to a media outlet
    in the press database. Returns the entry or None.
    """
    domain = extract_domain(url)
    if not domain:
        return None

    # Social media URLs should never match a press DB entry by domain
    SOCIAL_DOMAINS = {'instagram.com', 'facebook.com', 'x.com', 'twitter.com',
                      'youtube.com', 'tiktok.com', 'linkedin.com', 'threads.net'}
    if domain in SOCIAL_DOMAINS:
        return None

    # Direct domain match
    if domain in press_index:
        return press_index[domain]
    
    # Try partial domain match (e.g., 'clarin.com' matches 'www.clarin.com')
    for key, entry in press_index.items():
        if entry.get('website'):
            entry_domain = extract_domain(entry['website'])
            if entry_domain and (domain.endswith(entry_domain) or entry_domain.endswith(domain)):
                return entry
    
    # Try matching domain core against media names (require meaningful match)
    # Strip TLD extensions to get core domain name
    domain_core = domain
    for ext in ['.com.ar', '.com.br', '.com.mx', '.com.co', '.com.cl', '.com.pe',
                '.com.ec', '.com.uy', '.com.ve', '.com', '.br', '.ar', '.mx',
                '.co', '.cl', '.pe', '.ec', '.org', '.net']:
        domain_core = domain_core.replace(ext, '')
    domain_core = domain_core.strip('.')

    if len(domain_core) < 3:  # Skip very short domain cores
        return None

    # Detect country from URL TLD for territory-aware matching
    url_country = None
    for tld, country in [('.com.ar', 'ARGENTINA'), ('.com.br', 'BRAZIL'), ('.br', 'BRAZIL'),
                          ('.com.co', 'COLOMBIA'), ('.com.mx', 'MEXICO'), ('.mx', 'MEXICO'),
                          ('.cl', 'CHILE'), ('.com.pe', 'PERU'), ('.com.ec', 'ECUADOR')]:
        if tld in domain:
            url_country = country
            break

    best_match = None
    for key, entry in press_index.items():
        entry_name_lower = entry['name'].lower().strip()
        if len(entry_name_lower) < 3:  # Skip garbage entries
            continue
        # Require close length similarity to prevent false substring matches
        # e.g. "esto" matching inside "readgroovestories"
        shorter = min(len(domain_core), len(entry_name_lower))
        longer = max(len(domain_core), len(entry_name_lower))
        if shorter / longer < 0.5:
            continue  # Too different in length — skip
        if domain_core == entry_name_lower or domain_core.startswith(entry_name_lower) or entry_name_lower.startswith(domain_core):
            # If we know the URL's country, prefer territory-matching entries
            if url_country and entry.get('territory'):
                if url_country in entry['territory'].upper():
                    return entry  # Exact country match — return immediately
                elif best_match is None:
                    best_match = entry  # Keep as fallback
            else:
                if best_match is None:
                    best_match = entry

    return best_match


def load_playlist_database(csv_path):
    """
    Load the playlist database from Notion export.
    Returns list of playlists with name, country, platform, link, followers.
    """
    playlists = []
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('Playlist Name', '').strip()
            country = row.get('Country', '').strip()
            platform = row.get('Platform', '').strip()
            link = row.get('Link', '').strip()
            followers = row.get('Followers', '').strip()
            mood = row.get('Mood', '').strip()
            
            if not name or not link:
                continue
            
            # Extract Spotify playlist ID if applicable
            spotify_id = None
            if 'spotify.com/playlist/' in link:
                match = re.search(r'playlist/([a-zA-Z0-9]+)', link)
                if match:
                    spotify_id = match.group(1)
            
            # Extract Deezer playlist ID
            deezer_id = None
            if 'deezer.com' in link:
                match = re.search(r'playlist/(\d+)', link)
                if match:
                    deezer_id = match.group(1)

            # Extract Apple Music playlist ID
            apple_music_id = None
            if 'music.apple.com' in link and '/playlist/' in link:
                match = re.search(r'/(pl\.[a-zA-Z0-9]+)', link)
                if match:
                    apple_music_id = match.group(1)

            playlists.append({
                'name': name,
                'country': country,
                'platform': platform,
                'link': link,
                'followers': followers,
                'mood': mood,
                'spotify_id': spotify_id,
                'deezer_id': deezer_id,
                'apple_music_id': apple_music_id,
            })
    
    return playlists


def load_release_schedule(csv_path_or_url):
    """
    Load release schedule from local CSV or published Google Sheets URL.
    Returns list of releases with artist, title, date, spotify_uri, isrc, etc.
    """
    import io
    
    content = None
    if csv_path_or_url.startswith('http'):
        import urllib.request
        response = urllib.request.urlopen(csv_path_or_url)
        content = response.read().decode('utf-8')
    else:
        with open(csv_path_or_url, encoding='utf-8') as f:
            content = f.read()
    
    releases = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        artist = row.get('ARTIST', '').strip()
        title = row.get('TITLE', '').strip()
        date = row.get('DATE', '').strip()
        
        # Handle trailing space in column name
        spotify_uri = (row.get('SPOTIFY URI', '') or row.get('SPOTIFY URI ', '') or '').strip()
        isrc = row.get('ISRC', '').strip()
        focus_track = row.get('FOCUS TRACK', '').strip()
        priority = row.get('PRIORITY', '').strip()
        label = row.get('LABEL', '').strip()
        format_ = row.get('FORMAT', '').strip()
        
        if not artist:
            continue
        
        # Extract Spotify track/album ID from URI
        spotify_id = None
        spotify_type = None
        if spotify_uri:
            match = re.match(r'spotify:(track|album):(\w+)', spotify_uri)
            if match:
                spotify_type = match.group(1)
                spotify_id = match.group(2)
        
        releases.append({
            'artist': artist,
            'title': title,
            'date': date,
            'spotify_uri': spotify_uri,
            'spotify_id': spotify_id,
            'spotify_type': spotify_type,
            'isrc': isrc,
            'focus_track': focus_track,
            'priority': priority,
            'label': label,
            'format': format_,
        })
    
    return releases


def get_territory_for_country(country_name):
    """Map various country name formats to standardized territory names."""
    mapping = {
        'argentina': 'ARGENTINA',
        'brazil': 'BRAZIL',
        'brasil': 'BRAZIL',
        'chile': 'CHILE',
        'colombia': 'COLOMBIA',
        'ecuador': 'ECUADOR',
        'mexico': 'MÉXICO',
        'méxico': 'MÉXICO',
        'peru': 'PERU',
        'perú': 'PERU',
        'uruguay': 'URUGUAY',
        'venezuela': 'VENEZUELA',
        'panama': 'PANAMA',
        'panamá': 'PANAMA',
        'costa rica': 'COSTA RICA',
        'latam': 'LATAM',
    }
    return mapping.get(country_name.lower().strip(), country_name.upper())
