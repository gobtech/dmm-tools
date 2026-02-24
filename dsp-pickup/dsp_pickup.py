#!/usr/bin/env python3
"""
DSP Pickup Tool
===============
Checks LATAM editorial playlists for artist releases from the release schedule.
Supports Spotify (embed scraping), Deezer (API), and Apple Music (page scraping).
Amazon/Claro require manual checks.

Usage:
  python dsp_pickup.py --week current              # Check this week's releases
  python dsp_pickup.py --week 2026-02-21           # Check specific week
  python dsp_pickup.py --artist "Djo"              # Check one artist across all playlists
  python dsp_pickup.py --all                        # Check all artists from schedule

Requirements:
  pip install requests
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.database import load_playlist_database, load_release_schedule

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLAYLIST_DB_PATH = os.environ.get(
    'PLAYLIST_DB_PATH',
    str(Path(__file__).parent.parent / 'data' / 'playlist_database.csv')
)

RELEASE_SCHEDULE_URL = os.environ.get(
    'RELEASE_SCHEDULE_URL',
    'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
)


def get_spotify_playlist_tracks(playlist_id):
    """
    Fetch tracks from a Spotify playlist via the public embed endpoint.
    Returns list of { artist, track, position }.
    """
    import requests
    import time

    url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error fetching playlist {playlist_id}: {e}")
        return []

    # Extract __NEXT_DATA__ JSON from the embed page
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not match:
        print(f"    Could not parse playlist {playlist_id}")
        return []

    try:
        data = json.loads(match.group(1))
        entity = data['props']['pageProps']['state']['data']['entity']
        track_list = entity.get('trackList', [])
    except (json.JSONDecodeError, KeyError) as e:
        print(f"    Error parsing playlist data: {e}")
        return []

    tracks = []
    for i, item in enumerate(track_list):
        subtitle = item.get('subtitle', '')
        # subtitle contains artist names like "Artist1, Artist2"
        artists = [a.strip() for a in subtitle.split(',')] if subtitle else []
        tracks.append({
            'artist': subtitle,
            'artists_list': artists,
            'track': item.get('title', ''),
            'album': '',
            'position': i + 1,
        })

    # Small delay to avoid rate limiting
    time.sleep(0.5)
    return tracks


def get_deezer_playlist_tracks(playlist_id):
    """
    Fetch tracks from a Deezer playlist using their public API.
    Returns list of { artist, track, album }.
    """
    import requests
    
    tracks = []
    url = f"https://api.deezer.com/playlist/{playlist_id}/tracks"
    
    while url:
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
        except Exception as e:
            print(f"  Error fetching Deezer playlist {playlist_id}: {e}")
            break
        
        for i, item in enumerate(data.get('data', [])):
            tracks.append({
                'artist': item.get('artist', {}).get('name', ''),
                'artists_list': [item.get('artist', {}).get('name', '')],
                'track': item.get('title', ''),
                'album': item.get('album', {}).get('title', ''),
                'position': len(tracks) + 1,
            })
        
        url = data.get('next')
    
    return tracks


def get_apple_music_playlist_tracks(playlist_id):
    """
    Fetch tracks from an Apple Music playlist by scraping the public page.
    Returns list of { artist, artists_list, track, album, position }.
    """
    import requests
    import time

    url = f"https://music.apple.com/us/playlist/-/{playlist_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error fetching Apple Music playlist {playlist_id}: {e}")
        return []

    tracks = []

    # Try hydration JSON first: <script type="application/json">
    json_blocks = re.findall(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', resp.text, re.DOTALL
    )
    for block in json_blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue

        # Navigate to sections — handle both structures:
        #   dict: data['data'][0]['data']['sections']
        #   list: data[0]['data']['sections']
        try:
            root = data['data'] if isinstance(data, dict) and 'data' in data else data
            if isinstance(root, list) and len(root) > 0:
                sections = root[0]['data']['sections']
            else:
                continue
        except (KeyError, IndexError, TypeError):
            continue

        for section in sections:
            # Prefer section with 'track-list' in its id
            sec_id = section.get('id', '')
            items = section.get('items', [])
            if not items or len(items) < 2:
                continue
            first = items[0]
            if not isinstance(first, dict) or 'title' not in first:
                continue
            # Must be a track section (has artist info or is explicitly track-list)
            is_track_section = (
                'track-list' in sec_id or
                'subtitleLinks' in first or
                'artistName' in first
            )
            if not is_track_section:
                continue

            for i, item in enumerate(items):
                artist_name = item.get('artistName', '')
                # Build artists_list from subtitleLinks (each artist is a separate entry)
                subtitle_links = item.get('subtitleLinks', [])
                if subtitle_links and isinstance(subtitle_links, list):
                    artists_list = [link.get('title', '') for link in subtitle_links if link.get('title')]
                else:
                    # Fallback: split artistName on comma and ampersand
                    artists_list = [a.strip() for a in re.split(r'[,&]', artist_name) if a.strip()]
                # Build display artist from subtitleLinks if artistName is empty
                if not artist_name and artists_list:
                    artist_name = ', '.join(artists_list)
                album = ''
                tertiary = item.get('tertiaryLinks', [])
                if tertiary and isinstance(tertiary, list):
                    album = tertiary[0].get('title', '')

                tracks.append({
                    'artist': artist_name,
                    'artists_list': artists_list,
                    'track': item.get('title', ''),
                    'album': album,
                    'position': i + 1,
                })

            if tracks:
                break  # Found the track section, stop searching

        if tracks:
            break  # Found data in this JSON block

    # Fallback: try ld+json for partial data (track names, no artist)
    if not tracks:
        ld_blocks = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', resp.text, re.DOTALL
        )
        for block in ld_blocks:
            try:
                ld_data = json.loads(block)
            except (json.JSONDecodeError, ValueError):
                continue

            # MusicPlaylist schema has 'track' as dict with 'itemListElement' or as a list
            track_list = None
            playlist_obj = None
            if isinstance(ld_data, dict) and ld_data.get('@type') == 'MusicPlaylist':
                playlist_obj = ld_data
            elif isinstance(ld_data, list):
                for item in ld_data:
                    if isinstance(item, dict) and item.get('@type') == 'MusicPlaylist':
                        playlist_obj = item
                        break

            if playlist_obj:
                track_obj = playlist_obj.get('track', [])
                if isinstance(track_obj, dict):
                    track_list = track_obj.get('itemListElement', [])
                elif isinstance(track_obj, list):
                    track_list = track_obj

            if track_list:
                for i, entry in enumerate(track_list):
                    if isinstance(entry, dict):
                        item = entry.get('item', entry)
                    else:
                        continue
                    by_artist = item.get('byArtist', {})
                    artist_name = ''
                    if isinstance(by_artist, dict):
                        artist_name = by_artist.get('name', '')
                    elif isinstance(by_artist, str):
                        artist_name = by_artist
                    artists_list = [a.strip() for a in re.split(r'[,&]', artist_name) if a.strip()] if artist_name else []
                    tracks.append({
                        'artist': artist_name,
                        'artists_list': artists_list,
                        'track': item.get('name', ''),
                        'album': '',
                        'position': i + 1,
                    })
                break

    if not tracks:
        print(f"    Could not parse Apple Music playlist {playlist_id}")

    # Apple Music is stricter — longer delay between requests
    time.sleep(1)
    return tracks


def normalize_name(name):
    """Normalize artist/track name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes/prefixes
    name = re.sub(r'\s*\(.*?\)\s*', '', name)  # Remove parenthetical
    name = re.sub(r'\s*\[.*?\]\s*', '', name)  # Remove brackets
    name = re.sub(r'\s*-\s*.*$', '', name)       # Remove after dash (for "Artist - feat. X")
    name = re.sub(r'\s*feat\.?\s.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*ft\.?\s.*$', '', name, flags=re.IGNORECASE)
    # Normalize unicode
    name = name.replace('é', 'e').replace('á', 'a').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    name = name.replace('ñ', 'n').replace('ü', 'u').replace('ö', 'o')
    return name.strip()


def check_release_in_playlist(release, playlist_tracks):
    """
    Check if a release appears in a playlist's tracks.
    Returns match info or None.
    """
    release_artist = normalize_name(release['artist'])
    release_title = normalize_name(release['title'])

    # Clean focus_track: treat placeholders like "-", "–", "N/A", "TBD" as empty
    raw_focus = (release.get('focus_track', '') or '').strip()
    if raw_focus in ('-', '–', '—', 'N/A', 'n/a', 'TBD', 'tbd', ''):
        focus_track = ''
    else:
        focus_track = normalize_name(raw_focus)

    for track in playlist_tracks:
        # Check if any artist matches
        artist_match = False
        for pl_artist in track.get('artists_list', [track.get('artist', '')]):
            pl_artist_norm = normalize_name(pl_artist)
            if not pl_artist_norm:
                continue
            if pl_artist_norm == release_artist:
                artist_match = True
                break
            # Partial match — require minimum length to avoid false positives
            if len(release_artist) >= 3 and len(pl_artist_norm) >= 3:
                if release_artist in pl_artist_norm or pl_artist_norm in release_artist:
                    artist_match = True
                    break

        if not artist_match:
            continue

        # Check track/album title match
        pl_track = normalize_name(track.get('track', ''))
        pl_album = normalize_name(track.get('album', ''))

        # Skip empty values in substring checks to prevent "" matching everything
        title_match = False
        if release_title and pl_track:
            if release_title == pl_track:
                title_match = True
            # Substring match only if the shorter string is long enough (>=4 chars)
            elif len(release_title) >= 4 and len(pl_track) >= 4:
                if release_title in pl_track or pl_track in release_title:
                    title_match = True
        if not title_match and focus_track and pl_track:
            if focus_track == pl_track:
                title_match = True
            elif len(focus_track) >= 4 and len(pl_track) >= 4:
                if focus_track in pl_track or pl_track in focus_track:
                    title_match = True
        if not title_match and release_title and pl_album:
            if release_title == pl_album:
                title_match = True

        if title_match:
            return {
                'playlist_track': track.get('track', ''),
                'playlist_artist': track.get('artist', ''),
                'position': track.get('position', '?'),
                'added_at': track.get('added_at', ''),
            }
    
    return None


def run_dsp_pickup(releases, playlists, output_path=None):
    """
    Main DSP pickup workflow.
    Check releases against all playlists and generate report.
    """
    spotify_playlists = [p for p in playlists if p['platform'] == 'Spotify' and p['spotify_id']]
    deezer_playlists = [p for p in playlists if p['platform'] == 'Deezer' and p['deezer_id']]
    apple_playlists = [p for p in playlists if p['platform'] == 'Apple Music' and p.get('apple_music_id')]
    amazon_playlists = [p for p in playlists if 'Amazon' in p.get('platform', '')]
    other_playlists = [p for p in playlists if p not in spotify_playlists + deezer_playlists + apple_playlists + amazon_playlists]

    print(f"\nPlaylists to check:")
    print(f"  Spotify:     {len(spotify_playlists)}")
    print(f"  Deezer:      {len(deezer_playlists)}")
    print(f"  Apple Music: {len(apple_playlists)}")
    print(f"  Amazon:      {len(amazon_playlists)} (manual check needed)")
    print(f"  Other:       {len(other_playlists)} (manual check needed)")
    print(f"\nReleases to check: {len(releases)}")
    
    # Cache playlist tracks to avoid re-fetching
    playlist_cache = {}
    
    # Results: { artist: { release_title: [playlist_matches] } }
    results = {}
    
    # Check Spotify playlists
    for pl in spotify_playlists:
        pl_id = pl['spotify_id']
        print(f"\n  Checking: {pl['name']} ({pl['country']}) [{pl['followers']} followers]")
        
        if pl_id not in playlist_cache:
            tracks = get_spotify_playlist_tracks(pl_id)
            playlist_cache[pl_id] = tracks
            print(f"    → {len(tracks)} tracks loaded")
        else:
            tracks = playlist_cache[pl_id]
        
        for release in releases:
            match = check_release_in_playlist(release, tracks)
            if match:
                artist = release['artist']
                title = release['title']
                
                if artist not in results:
                    results[artist] = {}
                if title not in results[artist]:
                    results[artist][title] = []
                
                results[artist][title].append({
                    'playlist_name': pl['name'],
                    'playlist_country': pl['country'],
                    'playlist_followers': pl['followers'],
                    'platform': 'Spotify',
                    **match,
                })
                print(f"    ✓ MATCH: {artist} — {title} (position #{match['position']})")
    
    # Check Deezer playlists
    for pl in deezer_playlists:
        pl_id = pl['deezer_id']
        print(f"\n  Checking: {pl['name']} ({pl['country']}) [Deezer]")
        
        tracks = get_deezer_playlist_tracks(pl_id)
        print(f"    → {len(tracks)} tracks loaded")
        
        for release in releases:
            match = check_release_in_playlist(release, tracks)
            if match:
                artist = release['artist']
                title = release['title']
                
                if artist not in results:
                    results[artist] = {}
                if title not in results[artist]:
                    results[artist][title] = []
                
                results[artist][title].append({
                    'playlist_name': pl['name'],
                    'playlist_country': pl['country'],
                    'playlist_followers': pl['followers'],
                    'platform': 'Deezer',
                    **match,
                })
                print(f"    ✓ MATCH: {artist} — {title} (position #{match['position']})")

    # Check Apple Music playlists
    for pl in apple_playlists:
        pl_id = pl['apple_music_id']
        print(f"\n  Checking: {pl['name']} ({pl['country']}) [Apple Music]")

        if pl_id not in playlist_cache:
            tracks = get_apple_music_playlist_tracks(pl_id)
            playlist_cache[pl_id] = tracks
            print(f"    → {len(tracks)} tracks loaded")
        else:
            tracks = playlist_cache[pl_id]
            print(f"    → {len(tracks)} tracks (cached)")

        for release in releases:
            match = check_release_in_playlist(release, tracks)
            if match:
                artist = release['artist']
                title = release['title']

                if artist not in results:
                    results[artist] = {}
                if title not in results[artist]:
                    results[artist][title] = []

                results[artist][title].append({
                    'playlist_name': pl['name'],
                    'playlist_country': pl['country'],
                    'playlist_followers': pl['followers'],
                    'platform': 'Apple Music',
                    **match,
                })
                print(f"    ✓ MATCH: {artist} — {title} (position #{match['position']})")

    # Format output
    output_lines = ["DSP Pickup Report", "=" * 50, ""]

    # List all artists/releases that were checked
    checked_artists = {}
    for r in releases:
        a = r['artist']
        if a not in checked_artists:
            checked_artists[a] = []
        checked_artists[a].append(r['title'])

    output_lines.append(f"Releases checked ({len(releases)}):")
    for artist in sorted(checked_artists.keys()):
        titles = ', '.join(checked_artists[artist])
        output_lines.append(f"  • {artist} — {titles}")
    output_lines.append("")

    if not results:
        output_lines.append("No matches found in any checked playlists.")
    else:
        # Show which artists had no matches
        no_match_artists = [a for a in sorted(checked_artists.keys()) if a not in results]
        if no_match_artists:
            output_lines.append(f"No placements found for: {', '.join(no_match_artists)}")
            output_lines.append("")

        for artist in sorted(results.keys()):
            output_lines.append(f"\n{artist}")
            output_lines.append("-" * len(artist))

            for title, matches in sorted(results[artist].items()):
                output_lines.append(f"  {title}:")
                for m in sorted(matches, key=lambda x: x.get('playlist_name', '')):
                    followers = f" ({m['playlist_followers']} followers)" if m.get('playlist_followers') else ""
                    output_lines.append(
                        f"    • {m['playlist_name']} [{m['platform']}] — "
                        f"{m['playlist_country']}{followers} — Position #{m['position']}"
                    )
    
    # Note manual checks needed
    if amazon_playlists or other_playlists:
        output_lines.append("\n" + "=" * 50)
        output_lines.append("MANUAL CHECK NEEDED:")
        for pl in amazon_playlists + other_playlists:
            output_lines.append(f"  • {pl['name']} [{pl['platform']}] — {pl['country']}")
            output_lines.append(f"    {pl['link']}")
    
    output_text = '\n'.join(output_lines)
    
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"\nReport saved: {output_path}")
    else:
        print("\n" + output_text)
    
    # Also save raw results as JSON for further processing
    if output_path:
        json_path = output_path.replace('.txt', '.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Raw data saved: {json_path}")
    
    return results


def _parse_release_date(date_str, ref_year=None):
    """Parse date strings like 'Feb 23', 'Mar 6', 'April 10' into datetime."""
    if ref_year is None:
        ref_year = datetime.now().year
    date_str = date_str.strip()
    # Try common formats: "Feb 23", "Mar 6", "April 10"
    for fmt in ('%b %d', '%B %d'):
        try:
            return datetime.strptime(f"{date_str} {ref_year}", f'{fmt} %Y')
        except ValueError:
            continue
    return None


def filter_releases_by_week(releases, target_date_str):
    """
    Filter releases to a specific week block from the release schedule.
    Uses the week_block field (derived from separator rows in the Google Sheet)
    to identify which releases belong together in a week.
    Falls back to date proximity if week_block data is missing.
    """
    # Parse target date
    if target_date_str.lower() == 'current':
        target = datetime.now()
    else:
        target = datetime.strptime(target_date_str, '%Y-%m-%d')

    # Group releases by week_block
    blocks = {}
    for r in releases:
        wb = r.get('week_block', -1)
        if wb not in blocks:
            blocks[wb] = []
        blocks[wb].append(r)

    # Find the block whose date range contains the target date
    best_block = None
    best_distance = None
    for wb, block_releases in blocks.items():
        # Parse all dates in this block
        dates = []
        for r in block_releases:
            d = _parse_release_date(r.get('date', ''), target.year)
            if d:
                dates.append(d)
        if not dates:
            continue

        block_start = min(dates)
        block_end = max(dates)

        # Target falls within this block's date range
        if block_start <= target <= block_end:
            return block_releases

        # Track closest block as fallback
        dist = min(abs((target - block_start).days), abs((target - block_end).days))
        if best_distance is None or dist < best_distance:
            best_distance = dist
            best_block = wb

    # Fallback: return the closest block (within 7 days)
    if best_block is not None and best_distance <= 7:
        return blocks[best_block]

    return []


def main():
    parser = argparse.ArgumentParser(
        description='DSP Pickup Tool — Check LATAM editorial playlists for artist releases',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dsp_pickup.py --week current
  python dsp_pickup.py --week 2026-02-21
  python dsp_pickup.py --artist "Djo"
  python dsp_pickup.py --all --output dsp_report.txt

Environment Variables:
  PLAYLIST_DB_PATH       Path to playlist database CSV
  RELEASE_SCHEDULE_URL   Published Google Sheets URL for release schedule
        """
    )
    
    parser.add_argument('--artist', help='Check specific artist across all playlists')
    parser.add_argument('--week', help='Check releases from specific week (YYYY-MM-DD or "current")')
    parser.add_argument('--all', action='store_true', help='Check all releases from schedule')
    parser.add_argument('--output', help='Output file path')
    parser.add_argument('--playlist-db', help='Path to playlist database CSV')
    parser.add_argument('--release-schedule', help='Path or URL to release schedule')
    parser.add_argument('--spotify-only', action='store_true', help='Only check Spotify playlists')
    
    args = parser.parse_args()
    
    if not args.artist and not args.week and not args.all:
        parser.error('One of --artist, --week, or --all is required')
    
    # Load databases
    pl_path = args.playlist_db or PLAYLIST_DB_PATH
    print(f"Loading playlist database from {pl_path}...")
    playlists = load_playlist_database(pl_path)
    print(f"  Loaded {len(playlists)} playlists")
    
    if args.spotify_only:
        playlists = [p for p in playlists if p['platform'] == 'Spotify']
        print(f"  Filtered to {len(playlists)} Spotify playlists")
    
    schedule_source = args.release_schedule or RELEASE_SCHEDULE_URL
    print(f"Loading release schedule from {schedule_source}...")
    releases = load_release_schedule(schedule_source)
    print(f"  Loaded {len(releases)} releases")
    
    # Filter releases
    if args.artist:
        search_lower = args.artist.lower()
        releases = [r for r in releases if search_lower in r['artist'].lower() or r['artist'].lower() in search_lower]
        print(f"  Filtered to {len(releases)} releases for {args.artist}")
    elif args.week:
        releases = filter_releases_by_week(releases, args.week)
        print(f"  Filtered to {len(releases)} releases for week of {args.week}")
    
    if not releases:
        print("No releases found matching criteria.")
        sys.exit(0)
    
    run_dsp_pickup(releases, playlists, args.output)


if __name__ == '__main__':
    main()
