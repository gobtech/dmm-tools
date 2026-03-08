"""
Google Docs document scanning, formatting, and append logic.
Handles insertion point detection, report formatting for the Docs API,
and atomic append execution via batchUpdate.
"""

import re
import time
from datetime import datetime
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from shared.google_auth import get_docs_service, get_drive_service


# ---------------------------------------------------------------------------
# Image Upload to Google Drive
# ---------------------------------------------------------------------------

DMM_PROOFS_FOLDER_NAME = 'DMM Proofs'
_proofs_folder_id = None


def _get_or_create_proofs_folder():
    """Get or create the 'DMM Proofs' folder in Google Drive."""
    global _proofs_folder_id
    if _proofs_folder_id:
        return _proofs_folder_id

    drive = get_drive_service()
    # Search for existing folder
    resp = drive.files().list(
        q=f"name='{DMM_PROOFS_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields='files(id)',
        spaces='drive',
    ).execute()
    files = resp.get('files', [])
    if files:
        _proofs_folder_id = files[0]['id']
        return _proofs_folder_id

    # Create folder
    metadata = {
        'name': DMM_PROOFS_FOLDER_NAME,
        'mimeType': 'application/vnd.google-apps.folder',
    }
    folder = drive.files().create(body=metadata, fields='id').execute()
    _proofs_folder_id = folder['id']
    return _proofs_folder_id


def upload_proof_image(image_path):
    """Upload a proof image to Google Drive and return a publicly accessible URL.

    Returns the web content link or None on failure.
    """
    path = Path(image_path)
    if not path.exists():
        return None

    try:
        drive = get_drive_service()
        folder_id = _get_or_create_proofs_folder()

        metadata = {
            'name': path.name,
            'parents': [folder_id],
        }
        media = MediaFileUpload(str(path), mimetype='image/png', resumable=False)
        uploaded = drive.files().create(
            body=metadata,
            media_body=media,
            fields='id,webContentLink',
        ).execute()

        file_id = uploaded['id']

        # Make it accessible via link (anyone with link can view)
        drive.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'},
        ).execute()

        # Return direct content URL for Google Docs insertInlineImage
        return f'https://drive.google.com/uc?id={file_id}&export=download'
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Part A: Document Scanner
# ---------------------------------------------------------------------------

INSERTION_PATTERNS = [
    re.compile(r'\b(streaming|playlist\s*highlights|streaming\s*/?\s*playlist)\b', re.I),
    re.compile(r'\bradio\s*plays?\b', re.I),
    re.compile(r'\bpress\s*pick[\s-]?ups?\b', re.I),
    re.compile(r'^UPDATES$', re.M),
    re.compile(r'[-—_]+\s*Sent\s+.*[-—_]+', re.I),
    re.compile(r'\bSENT[_]+', re.I),
]

DMM_DIVIDER_PATTERN = re.compile(r'———\s*DMM Report', re.I)


def _extract_paragraphs(doc):
    """Extract paragraphs from a Google Docs document structure.
    Returns list of {index, end_index, text, is_heading, style}.
    """
    paragraphs = []
    for element in doc.get('body', {}).get('content', []):
        if 'paragraph' not in element:
            continue
        para = element['paragraph']
        start = element.get('startIndex', 0)
        end = element.get('endIndex', start)
        style = para.get('paragraphStyle', {}).get('namedStyleType', '')

        text_parts = []
        for elem in para.get('elements', []):
            tr = elem.get('textRun', {})
            text_parts.append(tr.get('content', ''))
        text = ''.join(text_parts).rstrip('\n')

        paragraphs.append({
            'index': start,
            'end_index': end,
            'text': text,
            'is_heading': 'HEADING' in style,
            'style': style,
        })
    return paragraphs


def check_duplicate_report(doc_id, date_label=None):
    """Check if a DMM Report with the given date already exists in the doc.

    Returns: {duplicate: bool, date_label: str}
    """
    if not date_label:
        date_label = datetime.now().strftime('%b %d, %Y')

    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    paragraphs = _extract_paragraphs(doc)

    search = f'DMM Report [{date_label}]'
    for para in paragraphs:
        if search in para['text']:
            return {'duplicate': True, 'date_label': date_label}

    return {'duplicate': False, 'date_label': date_label}


def get_document_title(doc_id):
    """Fetch and return a Google Doc's title."""
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id, fields='title').execute()
    return doc.get('title', '')


def read_document_structure(doc_id, max_paragraphs=50):
    """Return a simplified view of the document structure for debugging/UI."""
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    paragraphs = _extract_paragraphs(doc)
    result = []
    for p in paragraphs[:max_paragraphs]:
        result.append({
            'index': p['index'],
            'text_preview': p['text'][:120],
            'is_heading': p['is_heading'],
            'style': p['style'],
        })
    return result


def scan_document_for_insertion_point(doc_id):
    """Scan a document for where weekly reports should be inserted.

    Returns: {found, index, matched_text, context}
    """
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    paragraphs = _extract_paragraphs(doc)

    for i, para in enumerate(paragraphs):
        text = para['text']
        if not text.strip():
            continue
        for pattern in INSERTION_PATTERNS:
            if pattern.search(text):
                # Build context: 1 line before + match + 1 line after
                context_lines = []
                if i > 0:
                    context_lines.append(paragraphs[i - 1]['text'][:100])
                context_lines.append(f'>>> {text[:100]}')
                if i + 1 < len(paragraphs):
                    context_lines.append(paragraphs[i + 1]['text'][:100])

                return {
                    'found': True,
                    'index': para['index'],
                    'matched_text': text[:100],
                    'context': '\n'.join(context_lines),
                }

    return {'found': False, 'index': None, 'matched_text': None, 'context': ''}


# ---------------------------------------------------------------------------
# Part C: Report Formatter for Google Docs
# ---------------------------------------------------------------------------

def _format_radio_section(radio_data, play_key='plays_28d'):
    """Format radio data into plain text + formatting ranges.

    Returns: (text, formatting_ranges)
    where formatting_ranges is a list of {start, end, bold, underline, link}
    """
    if not radio_data:
        return '', []

    text_parts = []
    formats = []

    # Group by country -> station -> songs
    country_stations = {}
    for entry in radio_data:
        country = entry.get('country', 'UNKNOWN')
        station = entry.get('station', 'Unknown')
        song = entry.get('song', '')
        plays = entry.get(play_key, 0) or entry.get('plays_28d', 0)
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

    if not country_stations:
        return '', []

    # Section header (bold, red, 14pt — matching .docx)
    header = 'Radio Plays\n'
    start = 0
    formats.append({'start': start, 'end': start + len(header) - 1, 'bold': True, 'font_size': 14, 'color': '#C43030'})
    text_parts.append(header)

    for country in sorted(country_stations.keys()):
        # Country name (underline, 10pt)
        country_line = f'{country}\n'
        pos = sum(len(p) for p in text_parts)
        formats.append({'start': pos, 'end': pos + len(country_line) - 1, 'underline': True})
        text_parts.append(country_line)

        stations = country_stations[country]
        for station_name in sorted(stations.keys()):
            songs = sorted(stations[station_name], key=lambda s: s['plays'], reverse=True)
            # Station name (bold)
            station_line = f'{station_name}\n'
            pos = sum(len(p) for p in text_parts)
            formats.append({'start': pos, 'end': pos + len(station_line) - 1, 'bold': True})
            text_parts.append(station_line)

            for song_info in songs:
                text_parts.append(f'  \u2022  {song_info["song"]} ({song_info["plays"]}x)\n')

        text_parts.append('\n')

    return ''.join(text_parts), formats


def _format_dsp_section(dsp_data, proof_images=None):
    """Format DSP data into plain text + formatting ranges.

    Args:
        dsp_data: DSP results dict
        proof_images: dict mapping (track, playlist) -> image_url for inline images

    Returns: (text, formatting_ranges)
    where formatting_ranges may include {'image_url': url, 'start': offset} entries
    """
    if not dsp_data:
        return '', []

    text_parts = []
    formats = []

    # Flatten all matches
    all_matches = []
    for releases_dict in dsp_data.values():
        for matches in releases_dict.values():
            all_matches.extend(matches)

    if not all_matches:
        return '', []

    platform_order = ['Spotify', 'Apple Music', 'Deezer', 'Amazon Music', 'YouTube Music', 'Claro M\u00fasica']

    def sort_key(m):
        try:
            idx = platform_order.index(m.get('platform', ''))
        except ValueError:
            idx = 99
        return (idx, m.get('playlist_country', ''), m.get('playlist_name', ''))

    all_matches.sort(key=sort_key)

    # Section header (bold, red, 14pt — matching .docx)
    header = 'Streaming / Playlist Highlights\n'
    formats.append({'start': 0, 'end': len(header) - 1, 'bold': True, 'font_size': 14, 'color': '#C43030'})
    text_parts.append(header)

    current_platform = None
    today_str = datetime.now().strftime('%b %d, %Y')

    for m in all_matches:
        platform = m.get('platform', '')

        if platform != current_platform:
            if current_platform is not None:
                text_parts.append('\n')
            # Platform header (bold, blue, 12pt — matching .docx)
            platform_line = f'{platform}\n'
            pos = sum(len(p) for p in text_parts)
            formats.append({'start': pos, 'end': pos + len(platform_line) - 1, 'bold': True, 'font_size': 12, 'color': '#0056D2'})
            text_parts.append(platform_line)
            current_platform = platform

        # Country (underline)
        country = m.get('playlist_country', '')
        if country:
            country_line = f'{country}\n'
            pos = sum(len(p) for p in text_parts)
            formats.append({'start': pos, 'end': pos + len(country_line) - 1, 'underline': True})
            text_parts.append(country_line)

        # Playlist info
        info_parts = [m.get('playlist_name', '')]
        if m.get('playlist_followers'):
            info_parts.append(m['playlist_followers'])
        info_parts.append(today_str)
        info_line = ' - '.join(info_parts) + '\n'
        pos = sum(len(p) for p in text_parts)
        formats.append({'start': pos, 'end': pos + len(info_line) - 1, 'bold': True})
        text_parts.append(info_line)

        # Image placeholder — a newline where the image will be inserted
        if proof_images:
            track = m.get('playlist_track', '')
            playlist = m.get('playlist_name', '')
            img_url = proof_images.get((track, playlist))
            if img_url:
                placeholder = '\n'
                pos = sum(len(p) for p in text_parts)
                formats.append({'image_url': img_url, 'start': pos})
                text_parts.append(placeholder)

    text_parts.append('\n')
    return ''.join(text_parts), formats


def _format_press_section(press_data):
    """Format press data into plain text + formatting ranges.

    Returns: (text, formatting_ranges)
    """
    if not press_data:
        return '', []

    text_parts = []
    formats = []

    # Section header (bold, red, 14pt — matching .docx)
    header = 'Press Pick Up\n'
    formats.append({'start': 0, 'end': len(header) - 1, 'bold': True, 'font_size': 14, 'color': '#C43030'})
    text_parts.append(header)

    for country in sorted(press_data.keys()):
        entries = press_data[country]

        # Country name (underline, 11pt — matching .docx press style)
        country_line = f'{country}\n'
        pos = sum(len(p) for p in text_parts)
        formats.append({'start': pos, 'end': pos + len(country_line) - 1, 'underline': True, 'font_size': 11})
        text_parts.append(country_line)

        for entry in entries:
            media_name = entry.get('media_name', '')
            description = entry.get('description', '')

            # "Outlet Name: " part is bold, 11pt
            outlet_prefix = f'{media_name}: '
            pos = sum(len(p) for p in text_parts)
            entry_line = f'{outlet_prefix}{description}\n'
            # Bold the outlet name part
            formats.append({'start': pos, 'end': pos + len(outlet_prefix) - 1, 'bold': True, 'font_size': 11})
            # Set the full entry line to 11pt
            formats.append({'start': pos, 'end': pos + len(entry_line) - 1, 'font_size': 11})
            text_parts.append(entry_line)

            # URLs as hyperlinks
            urls = entry.get('urls', [])
            if not urls and entry.get('url'):
                urls = [{'url': entry['url']}]
            for u in urls:
                url_text = u['url'] + '\n'
                pos = sum(len(p) for p in text_parts)
                formats.append({'start': pos, 'end': pos + len(url_text) - 1, 'link': u['url']})
                text_parts.append(url_text)

            text_parts.append('\n')

    return ''.join(text_parts), formats


def format_report_for_docs(dsp_data, radio_data, press_data, artist_name,
                           date_label=None, proof_images=None):
    """Build the complete report text and Google Docs API formatting requests.

    Args:
        proof_images: dict mapping (track, playlist) -> image_url for inline images

    Returns: (full_text, all_formats)
    """
    if not date_label:
        date_label = datetime.now().strftime('%b %d, %Y')

    # Build full text block
    sections = []

    # Divider header (bold, 12pt)
    divider = f'\u2014\u2014\u2014 DMM Report [{date_label}] \u2014\u2014\u2014\n\n'
    sections.append((divider, [{'start': 0, 'end': len(divider) - 2, 'bold': True, 'font_size': 12}]))

    # DSP section
    if dsp_data:
        dsp_text, dsp_fmt = _format_dsp_section(dsp_data, proof_images=proof_images)
        if dsp_text:
            sections.append((dsp_text, dsp_fmt))

    # Radio section
    if radio_data:
        radio_text, radio_fmt = _format_radio_section(radio_data)
        if radio_text:
            sections.append((radio_text, radio_fmt))

    # Press section
    if press_data:
        press_text, press_fmt = _format_press_section(press_data)
        if press_text:
            sections.append((press_text, press_fmt))

    # Combine all sections into one text block with adjusted offsets
    full_text = ''
    all_formats = []
    for section_text, section_formats in sections:
        offset = len(full_text)
        for fmt in section_formats:
            adjusted = dict(fmt)
            adjusted['start'] += offset
            if 'end' in adjusted:
                adjusted['end'] += offset
            all_formats.append(adjusted)
        full_text += section_text

    # Trailing newline separator
    full_text += '\n'

    return full_text, all_formats


def _rgb(hex_color):
    """Convert '#C43030' to Google Docs rgbColor dict."""
    h = hex_color.lstrip('#')
    return {
        'red': int(h[0:2], 16) / 255.0,
        'green': int(h[2:4], 16) / 255.0,
        'blue': int(h[4:6], 16) / 255.0,
    }


# Match the .docx report styling
BASE_FONT = 'Arial'
BASE_SIZE_PT = 11
COLOR_BLACK = _rgb('#000000')
COLOR_RED = _rgb('#C43030')
COLOR_BLUE = _rgb('#0056D2')
COLOR_LINK = _rgb('#2E74B5')


def _build_batch_requests(insert_at, full_text, all_formats):
    """Build Google Docs API batchUpdate requests for insertion + formatting.

    Uses single-insert-then-format approach for reliability.
    """
    requests = []
    text_end = insert_at + len(full_text)

    # 1. Insert all text at once
    requests.append({
        'insertText': {
            'location': {'index': insert_at},
            'text': full_text,
        }
    })

    # 2. Apply base style to ALL inserted text (Arial 10pt, black)
    requests.append({
        'updateTextStyle': {
            'range': {'startIndex': insert_at, 'endIndex': text_end},
            'textStyle': {
                'weightedFontFamily': {'fontFamily': BASE_FONT, 'weight': 400},
                'fontSize': {'magnitude': BASE_SIZE_PT, 'unit': 'PT'},
                'foregroundColor': {'color': {'rgbColor': COLOR_BLACK}},
                'bold': False,
                'underline': False,
            },
            'fields': 'weightedFontFamily,fontSize,foregroundColor,bold,underline',
        }
    })

    # 3. Apply specific formatting overrides (skip image entries)
    image_inserts = []
    for fmt in all_formats:
        if fmt.get('image_url'):
            image_inserts.append(fmt)
            continue

        abs_start = insert_at + fmt['start']
        abs_end = insert_at + fmt.get('end', fmt['start'])

        if abs_start >= abs_end:
            continue

        # Build combined style + fields for this range
        style = {}
        fields = []

        if fmt.get('bold'):
            style['bold'] = True
            fields.append('bold')

        if fmt.get('underline'):
            style['underline'] = True
            fields.append('underline')

        if fmt.get('font_size'):
            style['fontSize'] = {'magnitude': fmt['font_size'], 'unit': 'PT'}
            fields.append('fontSize')

        if fmt.get('color'):
            style['foregroundColor'] = {'color': {'rgbColor': _rgb(fmt['color'])}}
            fields.append('foregroundColor')

        if fmt.get('link'):
            style['link'] = {'url': fmt['link']}
            style['foregroundColor'] = {'color': {'rgbColor': COLOR_LINK}}
            style['underline'] = True
            fields.extend(['link', 'foregroundColor', 'underline'])

        if style and fields:
            requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': abs_start, 'endIndex': abs_end},
                    'textStyle': style,
                    'fields': ','.join(dict.fromkeys(fields)),  # dedupe
                }
            })

    # 4. Insert images in REVERSE order (last first) so indices stay valid
    for img in sorted(image_inserts, key=lambda x: x['start'], reverse=True):
        abs_index = insert_at + img['start']
        requests.append({
            'insertInlineImage': {
                'location': {'index': abs_index},
                'uri': img['image_url'],
                'objectSize': {
                    'width': {'magnitude': 468, 'unit': 'PT'},   # ~6.5 inches
                    'height': {'magnitude': 264, 'unit': 'PT'},  # ~3.7 inches (16:9)
                },
            }
        })

    return requests


def _find_proof_for_match(match, proof_image_paths):
    """Find the proof image path for a DSP match, using the same naming as dsp_pickup."""
    import unicodedata

    def _ascii_safe(s, maxlen):
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
        return re.sub(r'[^\w\s-]', '', s)[:maxlen].strip().replace(' ', '_') or 'item'

    track = match.get('playlist_track', '')
    playlist = match.get('playlist_name', '')
    safe_track = _ascii_safe(track, 30)
    safe_playlist = _ascii_safe(playlist, 40)
    target = f'proof_{safe_track}_{safe_playlist}.png'

    for p in proof_image_paths:
        if Path(p).name == target:
            return p
    return None


def _upload_proof_images(proof_image_paths, dsp_data):
    """Upload proof images to Drive and return mapping of (track, playlist) -> url."""
    proof_images = {}

    # Flatten all matches to find which ones have proof images
    for releases_dict in dsp_data.values():
        for matches in releases_dict.values():
            for m in matches:
                track = m.get('playlist_track', '')
                playlist = m.get('playlist_name', '')
                img_path = _find_proof_for_match(m, proof_image_paths)
                if img_path:
                    url = upload_proof_image(img_path)
                    if url:
                        proof_images[(track, playlist)] = url

    return proof_images


# ---------------------------------------------------------------------------
# Part D: Append Execution
# ---------------------------------------------------------------------------

def append_report_to_doc(doc_id, dsp_data=None, radio_data=None, press_data=None,
                         artist_name='', date_label=None, proof_image_paths=None,
                         skip_if_duplicate=False):
    """Append a formatted report to a Google Doc.

    Args:
        proof_image_paths: list of local file paths to proof images (uploaded to Drive)
        skip_if_duplicate: if True, silently skip when a report for this date already exists

    Insertion strategy (in order):
    1. Look for our own divider "--- DMM Report" -> insert ABOVE the most recent one
    2. Use scan_document_for_insertion_point() for organic content markers
    3. Fall back to end of document

    Returns: {success, inserted_at, characters_inserted, error, skipped}
    """
    if not dsp_data and not radio_data and not press_data:
        return {'success': False, 'inserted_at': None, 'characters_inserted': 0,
                'error': 'No data provided to append.', 'skipped': False}

    try:
        # Upload proof images to Google Drive if provided
        proof_images = {}
        if proof_image_paths and dsp_data:
            proof_images = _upload_proof_images(proof_image_paths, dsp_data)

        service = get_docs_service()
        doc = service.documents().get(documentId=doc_id).execute()
        paragraphs = _extract_paragraphs(doc)

        # Duplicate check
        if not date_label:
            date_label = datetime.now().strftime('%b %d, %Y')
        dup_search = f'DMM Report [{date_label}]'
        for para in paragraphs:
            if dup_search in para['text']:
                if skip_if_duplicate:
                    return {'success': True, 'inserted_at': None,
                            'characters_inserted': 0, 'error': None,
                            'skipped': True, 'reason': f'Report for {date_label} already exists'}
                # Single-artist mode: warn but still allow (caller decides)
                break

        insert_at = None

        # Strategy 1: Find our own divider
        for para in paragraphs:
            if DMM_DIVIDER_PATTERN.search(para['text']):
                insert_at = para['index']
                break

        # Strategy 2: Scan for organic content markers
        if insert_at is None:
            scan = scan_document_for_insertion_point(doc_id)
            if scan['found']:
                insert_at = scan['index']

        # Strategy 3: End of document
        if insert_at is None:
            body_content = doc.get('body', {}).get('content', [])
            if body_content:
                insert_at = body_content[-1].get('endIndex', 1) - 1
            else:
                insert_at = 1

        # Ensure index is at least 1 (can't insert at 0 — that's before the doc start)
        insert_at = max(insert_at, 1)

        # Build the report
        full_text, all_formats = format_report_for_docs(
            dsp_data, radio_data, press_data, artist_name, date_label,
            proof_images=proof_images if proof_images else None,
        )

        # Build and execute the batch request
        requests = _build_batch_requests(insert_at, full_text, all_formats)

        service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests}
        ).execute()

        return {
            'success': True,
            'inserted_at': insert_at,
            'characters_inserted': len(full_text),
            'insert_end': insert_at + len(full_text),
            'error': None,
            'skipped': False,
        }

    except Exception as e:
        error_msg = str(e)
        if 'HttpError 404' in error_msg:
            error_msg = 'This document no longer exists. Unlink and re-link a new doc.'
        elif 'HttpError 403' in error_msg:
            error_msg = "Can't access this document. Check sharing permissions."
        elif 'HttpError 429' in error_msg:
            error_msg = 'Google API rate limit reached. Try again in a minute.'
        elif 'invalid_grant' in error_msg or 'Token has been expired' in error_msg:
            error_msg = 'Google account disconnected. Reconnect in Settings.'
        return {
            'success': False,
            'inserted_at': None,
            'characters_inserted': 0,
            'error': error_msg,
            'skipped': False,
        }


def undo_last_append(doc_id, start_index, end_index):
    """Delete the specified range from a Google Doc (undo an append).

    Returns: {success: bool, characters_deleted: int, error: str|None}
    """
    try:
        service = get_docs_service()
        # Verify the document still exists and range is valid
        doc = service.documents().get(documentId=doc_id).execute()
        body_content = doc.get('body', {}).get('content', [])
        if not body_content:
            return {'success': False, 'characters_deleted': 0,
                    'error': 'Document appears empty.'}

        doc_end = body_content[-1].get('endIndex', 1)
        if end_index > doc_end:
            return {'success': False, 'characters_deleted': 0,
                    'error': 'The document has been modified since the append. Undo is no longer safe.'}

        # Verify the range starts with our divider
        paragraphs = _extract_paragraphs(doc)
        range_text = ''
        for p in paragraphs:
            if p['index'] >= start_index and p['index'] < end_index:
                range_text = p['text']
                break
        if not DMM_DIVIDER_PATTERN.search(range_text):
            return {'success': False, 'characters_deleted': 0,
                    'error': 'The content at the stored range doesn\'t look like a DMM Report. Undo aborted for safety.'}

        chars = end_index - start_index
        service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': [{
                'deleteContentRange': {
                    'range': {
                        'startIndex': start_index,
                        'endIndex': end_index,
                    }
                }
            }]}
        ).execute()

        return {'success': True, 'characters_deleted': chars, 'error': None}

    except Exception as e:
        error_msg = str(e)
        if 'HttpError 404' in error_msg:
            error_msg = 'Document no longer exists.'
        elif 'HttpError 403' in error_msg:
            error_msg = 'Permission denied. Check sharing settings.'
        return {'success': False, 'characters_deleted': 0, 'error': error_msg}
