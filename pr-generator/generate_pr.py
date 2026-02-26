#!/usr/bin/env python3
"""
Press Release Translator
========================
Translates press releases from any language into Spanish and/or Brazilian
Portuguese for LATAM distribution.

Accepts either pasted text or an uploaded .docx file.

Two translation modes:
  - Google Translate (default, free, no API key)
  - Claude AI (optional, higher quality for music-industry tone, requires ANTHROPIC_API_KEY)

Called from the web UI via /api/pr/translate.
"""

import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))


# ═════════════════════════════════════════════════════════════════════════
#  DOCX TEXT EXTRACTION
# ═════════════════════════════════════════════════════════════════════════

def extract_docx_text(docx_path):
    """Extract text from a .docx file, preserving paragraph breaks."""
    from docx import Document
    doc = Document(docx_path)
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            paragraphs.append(text)
    return '\n\n'.join(paragraphs)


# ═════════════════════════════════════════════════════════════════════════
#  LANGUAGE DETECTION
# ═════════════════════════════════════════════════════════════════════════

# ISO codes for translation engines
LANG_CODES = {
    'English': 'en',
    'French': 'fr',
    'Spanish': 'es',
    'Portuguese': 'pt',
}

def _detect_language(text):
    """Detect likely source language from common word patterns. Returns label string."""
    sample = text[:3000].lower()

    # Word-boundary markers for more accurate detection
    en_markers = [' the ', ' and ', ' is ', ' for ', ' with ', ' this ', ' that ', ' from ', ' are ', ' will ', ' their ', ' has ', ' been ']
    fr_markers = [' le ', ' la ', ' les ', ' des ', ' est ', ' une ', ' dans ', ' pour ', ' avec ', ' qui ', ' sur ', ' sont ', ' du ']
    es_markers = [' el ', ' los ', ' las ', ' del ', ' con ', ' por ', ' una ', ' está ', ' para ', ' sus ', ' más ', ' será ']
    pt_markers = [' os ', ' das ', ' dos ', ' uma ', ' com ', ' para ', ' está ', ' não ', ' seu ', ' sua ', ' mais ', ' será ']

    scores = {
        'English': sum(sample.count(m) for m in en_markers),
        'French': sum(sample.count(m) for m in fr_markers),
        'Spanish': sum(sample.count(m) for m in es_markers),
        'Portuguese': sum(sample.count(m) for m in pt_markers),
    }

    return max(scores, key=scores.get)


# ═════════════════════════════════════════════════════════════════════════
#  GOOGLE TRANSLATE (free, default)
# ═════════════════════════════════════════════════════════════════════════

def _translate_google(text, target_lang, source_lang=None, log_fn=print):
    """
    Translate using Google Translate (free, no API key).

    Splits text into chunks to handle long PRs, preserving paragraph structure.
    """
    from deep_translator import GoogleTranslator

    src_code = LANG_CODES.get(source_lang, 'auto')
    tgt_code = 'es' if target_lang == 'es' else 'pt'

    # Google Translate has a ~5000 char limit per request.
    # Split by paragraphs, batch into chunks under 4500 chars.
    paragraphs = text.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 1  # +1 for newline
        if current_len + para_len > 4500 and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [para]
            current_len = para_len
        else:
            current_chunk.append(para)
            current_len += para_len

    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    translator = GoogleTranslator(source=src_code, target=tgt_code)

    translated_chunks = []
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            translated_chunks.append(chunk)
            continue
        try:
            result = translator.translate(chunk)
            translated_chunks.append(result)
            if len(chunks) > 1:
                log_fn(f'  Chunk {i + 1}/{len(chunks)} translated.')
        except Exception as e:
            log_fn(f'  Warning: chunk {i + 1} failed ({e}), keeping original.')
            translated_chunks.append(chunk)

    return '\n'.join(translated_chunks)


# ═════════════════════════════════════════════════════════════════════════
#  GEMINI AI TRANSLATION (free tier, high quality)
# ═════════════════════════════════════════════════════════════════════════

def _translate_gemini(text, target_lang, source_lang=None, notes='', log_fn=print):
    """
    Translate a press release using Google Gemini Flash (free).

    Returns translated text string, or None on failure.
    """
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        return None

    import requests as req

    lang_name = 'Latin American Spanish' if target_lang == 'es' else 'Brazilian Portuguese'
    src_label = source_lang or 'the source language'

    system_prompt = (
        f"You are an expert music industry translator specializing in press releases for Latin American markets. "
        f"Translate the following press release from {src_label} into {lang_name}.\n\n"
        f"CRITICAL RULES:\n"
        f"- Preserve ALL formatting: paragraph breaks, section headers, bullet points, tracklists, tour dates, links.\n"
        f"- Keep artist names, song/album titles, venue names, label names, and proper nouns EXACTLY as-is (do NOT translate them).\n"
        f"- Keep all URLs and email addresses exactly as-is.\n"
        f"- Translate quotes naturally — they should sound like the person said them in {lang_name}.\n"
        f"- Use professional music press release tone appropriate for {lang_name}-speaking media outlets.\n"
        f"- Localize date formats (e.g., 'June 5' → '5 de junio' for Spanish, '5 de junho' for Portuguese).\n"
        f"- If the PR contains sections in multiple languages, translate ALL sections into {lang_name}.\n"
        f"- Output ONLY the translated press release. No preamble, no notes, no commentary.\n"
    )

    if notes:
        system_prompt += f"\nAdditional instructions from the user: {notes}\n"

    try:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}'

        resp = req.post(
            url,
            headers={'content-type': 'application/json'},
            json={
                'system_instruction': {
                    'parts': [{'text': system_prompt}],
                },
                'contents': [{
                    'parts': [{'text': text}],
                }],
                'generationConfig': {
                    'maxOutputTokens': 8192,
                    'temperature': 0.3,
                },
            },
            timeout=120,
        )

        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get('candidates', [])
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                if parts:
                    return parts[0].get('text', '').strip()
            log_fn('  Gemini returned empty response.')
            return None
        else:
            log_fn(f'  Gemini API error: {resp.status_code} — {resp.text[:200]}')
            return None
    except Exception as e:
        log_fn(f'  Gemini translation error: {e}')
        return None


# ═════════════════════════════════════════════════════════════════════════
#  MAIN FUNCTION
# ═════════════════════════════════════════════════════════════════════════

def translate_pr(
    text='',
    docx_path='',
    target_es=True,
    target_pt=True,
    use_ai=False,
    notes='',
    log_fn=None,
):
    """
    Translate a press release into Spanish and/or Portuguese.

    Provide either `text` (pasted PR content) or `docx_path` (uploaded .docx).

    Args:
        use_ai: If True, use Claude AI for premium translation.
                If False (default), use Google Translate (free).

    Returns dict with:
      - source_text: the original text used
      - source_lang: detected source language
      - es_text: Spanish translation (empty string if not requested)
      - pt_text: Portuguese translation (empty string if not requested)
      - engine: 'google' or 'claude'
    """
    if log_fn is None:
        log_fn = print

    result = {
        'source_text': '',
        'source_lang': '',
        'es_text': '',
        'pt_text': '',
        'engine': '',
    }

    # ── Extract source text ───────────────────────────────────
    if docx_path:
        log_fn('Extracting text from .docx...')
        try:
            text = extract_docx_text(docx_path)
            log_fn(f'  Extracted {len(text):,} characters from document.')
        except Exception as e:
            raise ValueError(f'Failed to read .docx file: {e}')

    if not text or not text.strip():
        raise ValueError('No text provided. Paste the PR content or upload a .docx file.')

    result['source_text'] = text.strip()

    # ── Detect source language ────────────────────────────────
    source_lang = _detect_language(text)
    result['source_lang'] = source_lang
    log_fn(f'Detected source language: {source_lang}')

    # ── Choose engine ─────────────────────────────────────────
    if use_ai:
        api_key = os.environ.get('GEMINI_API_KEY', '')
        if not api_key:
            log_fn('GEMINI_API_KEY not set — falling back to Google Translate.')
            use_ai = False
        else:
            log_fn('Using Gemini Flash AI for translation.')

    if not use_ai:
        log_fn('Using Google Translate (free).')

    result['engine'] = 'gemini' if use_ai else 'google'

    # ── Translate to Spanish ──────────────────────────────────
    if target_es:
        if source_lang == 'Spanish':
            log_fn('Source is already Spanish — skipping ES translation.')
            result['es_text'] = text.strip()
        else:
            log_fn('Translating to Spanish...')
            if use_ai:
                es = _translate_gemini(text, 'es', source_lang, notes, log_fn)
            else:
                es = _translate_google(text, 'es', source_lang, log_fn)
            if es:
                result['es_text'] = es
                log_fn(f'  Spanish translation complete ({len(es):,} chars).')
            else:
                raise ValueError('Spanish translation failed.')

    # ── Translate to Portuguese ───────────────────────────────
    if target_pt:
        if source_lang == 'Portuguese':
            log_fn('Source is already Portuguese — skipping PT translation.')
            result['pt_text'] = text.strip()
        else:
            log_fn('Translating to Portuguese...')
            if use_ai:
                pt = _translate_gemini(text, 'pt', source_lang, notes, log_fn)
            else:
                pt = _translate_google(text, 'pt', source_lang, log_fn)
            if pt:
                result['pt_text'] = pt
                log_fn(f'  Portuguese translation complete ({len(pt):,} chars).')
            else:
                raise ValueError('Portuguese translation failed.')

    log_fn('Translation complete!')
    return result


if __name__ == '__main__':
    sample = """BYE PARULA ANNOUNCES "SOMETHING OUT OF NOTHING"
A BRAND-NEW ALBUM OUT JUNE 5 VIA SECRET CITY RECORDS

LISTEN TO THE FIRST SINGLE "KISSBURN" AVAILABLE NOW

Bye Parula is thrilled to announce their brand-new album "Something Out Of Nothing" set to release on June 5 via Secret City Records in both LP and CD formats."""

    result = translate_pr(text=sample, target_es=True, target_pt=True)
    print(f'=== DETECTED: {result["source_lang"]} (engine: {result["engine"]}) ===')
    print()
    print('=== SPANISH ===')
    print(result['es_text'])
    print()
    print('=== PORTUGUESE ===')
    print(result['pt_text'])
