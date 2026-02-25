#!/usr/bin/env python3
"""
Weekly Digest Generator
=======================
Generates lightweight email-ready summaries by reusing the same Radio, DSP,
and Press data pipelines as the Full Report — but outputs formatted HTML and
plain text instead of a .docx.

Called from the web UI via /api/digest/generate.
"""

import importlib.util
import io
import os
import sys
from datetime import datetime
from pathlib import Path
from html import escape

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

REPORT_DIR = ROOT_DIR / 'reports'
REPORT_DIR.mkdir(exist_ok=True)

RELEASE_SCHEDULE_URL = os.environ.get(
    'RELEASE_SCHEDULE_URL',
    'https://docs.google.com/spreadsheets/d/e/2PACX-1vTSd9mhkVibb7AwXtsZjRgBfuRT9sLY_qhhu-rB_P35CX2vFk_fZw_f31AJyW84KrCzWLLMUcTzzgqU/pub?gid=497066221&single=true&output=csv'
)

PLAY_KEY_MAP = {
    '7d':   'weekly_plays',
    '28d':  'plays_28d',
    '1y':   'yearly_plays',
}

SORT_COL_MAP = {
    '7d':  'weeklyPlaysCount',
    '28d': 'monthlyPlaysCount',
    '1y':  'yearlyPlaysCount',
}


def generate_digest(
    artist,
    days=7,
    radio_region='latam',
    radio_time_range='7d',
    next_steps='',
    sender_name='',
    contact_name='',
    include_radio=True,
    include_dsp=True,
    include_press=True,
    log_fn=None,
):
    """
    Generate a weekly digest email for an artist.

    Returns dict with:
      - html: formatted HTML email body
      - text: plain text version
      - radio_count: number of radio entries
      - dsp_count: number of playlist placements
      - press_count: number of press results
    """
    if log_fn is None:
        log_fn = print

    safe_artist = artist.lower().replace(' ', '_')

    result = {
        'html': '',
        'text': '',
        'radio_count': 0,
        'dsp_count': 0,
        'press_count': 0,
    }

    radio_data = None
    press_data = None
    dsp_data = None

    # ─── Load release schedule ─────────────────────────────────────
    log_fn('Loading release schedule...')
    from shared.database import load_release_schedule, load_playlist_database

    all_releases = load_release_schedule(RELEASE_SCHEDULE_URL)
    search_lower = artist.lower()
    artist_releases = [
        r for r in all_releases
        if search_lower in r['artist'].lower() or r['artist'].lower() in search_lower
    ]
    log_fn(f'  Found {len(artist_releases)} releases for {artist}')

    # ─── 1. Radio Report (Soundcharts) ────────────────────────────
    if include_radio:
        log_fn('\n── Radio ──')
        try:
            from shared.soundcharts import search_artist, fetch_airplay_data, get_token

            token = get_token()
            if not token:
                log_fn('  Soundcharts credentials not configured — skipping radio.')
            else:
                log_fn(f'  Searching Soundcharts for "{artist}"...')
                match = search_artist(artist, token=token)
                if not match:
                    log_fn(f'  Artist "{artist}" not found on Soundcharts.')
                else:
                    log_fn(f'  Found: {match["name"]}')
                    sort_col = SORT_COL_MAP.get(radio_time_range, 'weeklyPlaysCount')
                    airplay = fetch_airplay_data(
                        match['uuid'], token,
                        sort_by=sort_col,
                        region=radio_region if radio_region != 'all' else None,
                        log_fn=log_fn,
                    )
                    if airplay:
                        radio_data = airplay
                        log_fn(f'  Total: {len(radio_data)} station entries')
                    else:
                        log_fn('  No airplay data found.')
        except Exception as e:
            log_fn(f'  Radio fetch failed: {e}')

    # ─── 2. Press Pickup ──────────────────────────────────────────
    if include_press:
        log_fn('\n── Press ──')
        try:
            spec_path = ROOT_DIR / 'press-pickup' / 'press_pickup.py'
            spec = importlib.util.spec_from_file_location('press_pickup', str(spec_path))
            mod = importlib.util.module_from_spec(spec)

            old_stdout = sys.stdout
            buf = io.StringIO()
            sys.stdout = buf
            try:
                spec.loader.exec_module(mod)
                press_output = str(REPORT_DIR / f'{safe_artist}_press.txt')
                press_data = mod.run_press_pickup(artist, days, press_output)
            finally:
                sys.stdout = old_stdout

            for line in buf.getvalue().splitlines():
                log_fn(line)

            total_press = sum(len(v) for v in press_data.values()) if press_data else 0
            log_fn(f'  Found {total_press} press results')
        except Exception as e:
            log_fn(f'  Press pickup failed: {e}')

    # ─── 3. DSP Pickup ────────────────────────────────────────────
    if include_dsp and artist_releases:
        log_fn('\n── DSP ──')
        try:
            pl_path = os.environ.get(
                'PLAYLIST_DB_PATH',
                str(ROOT_DIR / 'data' / 'playlist_database.csv')
            )
            playlists = load_playlist_database(pl_path)
            log_fn(f'  Loaded {len(playlists)} playlists')

            dsp_output = str(REPORT_DIR / f'{safe_artist}_dsp.txt')

            old_stdout = sys.stdout
            buf = io.StringIO()
            sys.stdout = buf
            try:
                spec_path = ROOT_DIR / 'dsp-pickup' / 'dsp_pickup.py'
                spec = importlib.util.spec_from_file_location('dsp_pickup_run', str(spec_path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                dsp_data = mod.run_dsp_pickup(artist_releases, playlists, dsp_output)
            finally:
                sys.stdout = old_stdout

            for line in buf.getvalue().splitlines():
                log_fn(line)

            total_dsp = sum(
                len(matches)
                for rel in dsp_data.values()
                for matches in rel.values()
            ) if dsp_data else 0
            log_fn(f'  Found {total_dsp} playlist placements')
        except Exception as e:
            log_fn(f'  DSP pickup failed: {e}')
    elif include_dsp:
        log_fn('\n── DSP ──')
        log_fn('  No releases found — skipping DSP check.')

    # ─── Build digest ─────────────────────────────────────────────
    log_fn('\n── Building digest ──')

    play_key = PLAY_KEY_MAP.get(radio_time_range, 'weekly_plays')
    greeting = contact_name.strip() if contact_name.strip() else 'team'
    sign_off = sender_name.strip() if sender_name.strip() else 'DMM Team'

    html, text, counts = _build_digest(
        artist=artist,
        radio_data=radio_data,
        press_data=press_data,
        dsp_data=dsp_data,
        play_key=play_key,
        next_steps=next_steps,
        greeting=greeting,
        sign_off=sign_off,
    )

    result['html'] = html
    result['text'] = text
    result['radio_count'] = counts['radio']
    result['dsp_count'] = counts['dsp']
    result['press_count'] = counts['press']

    log_fn(f'  Digest ready — Radio: {counts["radio"]}, DSP: {counts["dsp"]}, Press: {counts["press"]}')

    return result


def _build_digest(artist, radio_data, press_data, dsp_data, play_key,
                  next_steps, greeting, sign_off):
    """Build HTML and plain text versions of the digest email."""

    counts = {'radio': 0, 'dsp': 0, 'press': 0}
    html_sections = []
    text_sections = []

    # ─── Radio ─────────────────────────────────────────────────
    if radio_data:
        # Group by country -> station -> songs
        country_stations = {}
        for entry in radio_data:
            country = entry.get('country', 'UNKNOWN')
            station = entry.get('station', 'Unknown')
            song = entry.get('song', '')
            plays = entry.get(play_key, 0) or entry.get('plays_28d', 0) or entry.get('weekly_plays', 0)

            if not plays or not song:
                continue

            if country not in country_stations:
                country_stations[country] = {}
            if station not in country_stations[country]:
                country_stations[country][station] = []

            existing = [s for s in country_stations[country][station] if s['song'] == song]
            if existing:
                existing[0]['plays'] = max(existing[0]['plays'], plays)
            else:
                country_stations[country][station].append({'song': song, 'plays': plays})
                counts['radio'] += 1

        if country_stations:
            h = '<h3 style="margin:20px 0 10px;font-size:16px;color:#1a1a1a;">Radio</h3>\n'
            t = '\nRADIO\n' + '─' * 40 + '\n'

            for country in sorted(country_stations.keys()):
                h += f'<p style="margin:10px 0 4px;font-weight:600;color:#444;">{escape(country)}</p>\n'
                t += f'\n{country}\n'
                for station in sorted(country_stations[country].keys()):
                    songs = country_stations[country][station]
                    songs.sort(key=lambda s: s['plays'], reverse=True)
                    for s in songs:
                        h += f'<p style="margin:2px 0 2px 16px;color:#555;">• {escape(station)}: <strong>{escape(s["song"])}</strong> — {s["plays"]}x</p>\n'
                        t += f'  • {station}: {s["song"]} — {s["plays"]}x\n'

            html_sections.append(h)
            text_sections.append(t)

    # ─── DSP / Playlists ───────────────────────────────────────
    if dsp_data:
        all_matches = []
        for a, releases_dict in dsp_data.items():
            for title, matches in releases_dict.items():
                for m in matches:
                    all_matches.append(m)

        if all_matches:
            counts['dsp'] = len(all_matches)

            platform_order = [
                'Spotify', 'Apple Music', 'Deezer',
                'Amazon Music', 'YouTube Music', 'Claro Música',
            ]
            def sort_key(m):
                try:
                    idx = platform_order.index(m.get('platform', ''))
                except ValueError:
                    idx = 99
                return (idx, m.get('playlist_name', ''))
            all_matches.sort(key=sort_key)

            h = '<h3 style="margin:20px 0 10px;font-size:16px;color:#1a1a1a;">Playlist Placements</h3>\n'
            t = '\nPLAYLIST PLACEMENTS\n' + '─' * 40 + '\n'

            current_platform = None
            for m in all_matches:
                platform = m.get('platform', '')
                if platform != current_platform:
                    h += f'<p style="margin:12px 0 4px;font-weight:600;color:#444;">{escape(platform)}</p>\n'
                    t += f'\n{platform}\n'
                    current_platform = platform

                playlist = m.get('playlist_name', '')
                followers = m.get('playlist_followers', '')
                track = m.get('playlist_track', '')
                pos = m.get('position', '?')

                detail = f'{playlist}'
                if followers:
                    detail += f' ({followers})'
                detail += f' — #{pos}'
                if track:
                    detail += f' "{track}"'

                h += f'<p style="margin:2px 0 2px 16px;color:#555;">• <strong>{escape(playlist)}</strong>'
                if followers:
                    h += f' <span style="color:#888;">({escape(followers)})</span>'
                h += f' — #{escape(str(pos))}'
                if track:
                    h += f' <em>"{escape(track)}"</em>'
                h += '</p>\n'

                t += f'  • {detail}\n'

            html_sections.append(h)
            text_sections.append(t)

    # ─── Press ─────────────────────────────────────────────────
    if press_data:
        total_press = sum(len(v) for v in press_data.values())
        if total_press > 0:
            counts['press'] = total_press

            h = '<h3 style="margin:20px 0 10px;font-size:16px;color:#1a1a1a;">Press Coverage</h3>\n'
            t = '\nPRESS COVERAGE\n' + '─' * 40 + '\n'

            for country in sorted(press_data.keys()):
                entries = press_data[country]
                h += f'<p style="margin:10px 0 4px;font-weight:600;color:#444;">{escape(country)}</p>\n'
                t += f'\n{country}\n'

                seen = set()
                for entry in entries:
                    name = entry.get('media_name', '')
                    if name in seen:
                        continue
                    seen.add(name)

                    url = entry.get('url', '')
                    title = entry.get('title', '')

                    h += f'<p style="margin:2px 0 2px 16px;color:#555;">• <strong>{escape(name)}</strong>'
                    if title:
                        h += f': {escape(title)}'
                    if url:
                        h += f'<br><a href="{escape(url)}" style="color:#2e74b5;font-size:13px;">{escape(url)}</a>'
                    h += '</p>\n'

                    t += f'  • {name}'
                    if title:
                        t += f': {title}'
                    t += '\n'
                    if url:
                        t += f'    {url}\n'

            html_sections.append(h)
            text_sections.append(t)

    # ─── Next Steps ────────────────────────────────────────────
    if next_steps and next_steps.strip():
        h = '<h3 style="margin:20px 0 10px;font-size:16px;color:#1a1a1a;">Next Steps</h3>\n'
        t = '\nNEXT STEPS\n' + '─' * 40 + '\n'

        for line in next_steps.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            clean = line.lstrip('-•* ')
            h += f'<p style="margin:2px 0 2px 16px;color:#555;">• {escape(clean)}</p>\n'
            t += f'  • {clean}\n'

        html_sections.append(h)
        text_sections.append(t)

    # ─── Compose full email ────────────────────────────────────
    has_content = counts['radio'] > 0 or counts['dsp'] > 0 or counts['press'] > 0

    # HTML version
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.6;max-width:600px;">
<p>Hi {escape(greeting)},</p>
<p>Here's this week's update for <strong>{escape(artist)}</strong>:</p>
"""
    if has_content:
        html += '\n'.join(html_sections)
    else:
        html += '<p style="color:#888;font-style:italic;">No new activity found for this period.</p>\n'

    html += f"""
<p style="margin-top:24px;">Best,<br><strong>{escape(sign_off)}</strong></p>
</div>"""

    # Plain text version
    text = f'Hi {greeting},\n\nHere\'s this week\'s update for {artist}:\n'
    if has_content:
        text += '\n'.join(text_sections)
    else:
        text += '\nNo new activity found for this period.\n'

    text += f'\n\nBest,\n{sign_off}\n'

    return html, text, counts
