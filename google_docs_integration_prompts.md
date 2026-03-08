# Google Docs Auto-Append — Claude Code Session Prompts

## Prerequisites

Before Session 1, Jose needs to manually:
1. Go to https://console.cloud.google.com/
2. Create a new project (e.g., "DMM Tools")
3. Enable the Google Docs API and Google Drive API
4. Go to Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: Desktop App (or Web App if you want the OAuth flow in the browser)
6. Download the credentials JSON file → save as `data/google_credentials.json`
7. Add `data/google_credentials.json` and `data/google_token.json` to `.gitignore`

---

## Session 1: Google Docs API Setup + Artist-Doc Mapping

```
We're adding Google Docs integration so the tool can automatically append weekly reports (DSP, Radio, Press) directly into each artist's Google Doc. This is Session 1 of 3 — setting up the API connection and the artist-to-doc mapping.

### Part A: Google Auth Module

Create `shared/google_auth.py`:

1. Load OAuth credentials from `data/google_credentials.json`
2. Token storage at `data/google_token.json` — auto-refresh when expired
3. Required scopes:
   - `https://www.googleapis.com/auth/documents` (read/write Docs)
   - `https://www.googleapis.com/auth/drive.readonly` (search for docs by name)
4. Provide two functions:
   - `get_docs_service()` → returns an authenticated Google Docs API service object
   - `get_drive_service()` → returns an authenticated Google Drive API service object
5. If no token exists or token is expired and can't refresh, raise a clear error:
   "Google account not connected. Go to Settings → Google Account to connect."
6. Install: `pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client`
7. Add these to start.sh dependency check

Use the standard google-auth-oauthlib flow. For the initial authorization, the flow should:
- If running locally (detected by checking if we're in a TTY or have a display), open the browser for consent
- Save the resulting token to `data/google_token.json`
- On subsequent runs, load the saved token and refresh if needed

### Part B: Artist-Doc Mapping Database

In `shared/history.py`, add a new table to `init_db()`:

```sql
CREATE TABLE IF NOT EXISTS artist_google_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_name TEXT NOT NULL,
    artist_name_normalized TEXT NOT NULL,
    doc_url TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    bookmark_index INTEGER DEFAULT NULL,
    insertion_confirmed INTEGER DEFAULT 0,
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_appended_at TIMESTAMP DEFAULT NULL,
    last_append_status TEXT DEFAULT NULL
)
```

Add CRUD functions:
- `get_artist_doc(artist_name)` → returns the row or None. Match on normalized name (same normalize_name() used elsewhere)
- `save_artist_doc(artist_name, doc_url, doc_id)` → insert or update. Extract doc_id from the URL: the Google Doc URL format is `https://docs.google.com/document/d/{DOC_ID}/edit`
- `update_artist_doc_bookmark(artist_name, bookmark_index)` → store the insertion point index
- `update_artist_doc_append_status(artist_name, status)` → update last_appended_at and last_append_status
- `get_all_artist_docs()` → returns all linked docs
- `delete_artist_doc(artist_name)` → remove mapping
- `confirm_artist_doc_insertion(artist_name)` → set insertion_confirmed = 1

### Part C: Settings Page — Google Account Section

In `web/app.py` and the Settings page (if it exists) or `web/templates/index.html`, add a "Google Account" section:

1. **Connection status**: Show "Connected as [email]" or "Not connected"
   - API endpoint: `GET /api/settings/google/status` → returns `{connected: bool, email: str|null, scopes: [...]}`
   - Check by loading the token and making a lightweight API call (e.g., get user info)

2. **Connect button**: Triggers the OAuth flow
   - API endpoint: `POST /api/settings/google/connect`
   - Since this is a local app, the OAuth flow can open a browser tab for consent
   - After consent, save the token, return success
   - For the web UI flow: the endpoint returns an auth URL, the frontend opens it in a new tab, the OAuth callback saves the token, and the frontend polls for completion

3. **Disconnect button**: Revokes token and deletes `data/google_token.json`
   - API endpoint: `POST /api/settings/google/disconnect`

4. **Linked Docs list**: Show all artist → Google Doc mappings
   - API endpoint: `GET /api/settings/google/docs` → returns list of `{artist_name, doc_url, linked_at, last_appended_at, last_append_status, insertion_confirmed}`
   - Each row has: artist name, clickable doc link, last append date, status badge, "Unlink" button
   - "Unlink" calls `DELETE /api/settings/google/docs/<artist_name>`

### Part D: Link Google Doc UI on Tool Results

After each tool generates results (Full Report, Press Pickup, Radio Report, DSP Pickup), add a "Google Doc" section at the bottom of the results area:

If the artist already has a linked doc:
- Show: "📄 Linked to: [Doc Title] — Last updated: [date]"  
- Button: "Append to Google Doc" (this will be wired in Session 2)
- Button: "Unlink"

If the artist has no linked doc:
- Show: "No Google Doc linked for [Artist]"
- Input field: "Paste Google Doc URL"
- Button: "Link & Save"
- When saved, call `POST /api/settings/google/docs` with `{artist_name, doc_url}`
- Validate the URL format: must contain `docs.google.com/document/d/`
- Extract the doc_id from the URL
- Test that the API can access the doc (try to read the title). If permission denied: "Can't access this doc. Make sure it's shared with [connected Google account email]."

Also add endpoints:
- `POST /api/settings/google/docs` — link a new doc `{artist_name, doc_url}`
- `DELETE /api/settings/google/docs/<artist_name>` — unlink
- `GET /api/google/doc-info/<doc_id>` — returns doc title and access status (for validation)

Don't implement the actual append logic yet — that's Session 2. Just wire up the connection, mapping, and UI.
```

---

## Session 2: Document Scanning + Insertion Logic

```
This is Session 2 of the Google Docs auto-append feature. Session 1 set up Google Auth, artist-doc mapping, and the Settings UI. Now we implement the actual document insertion logic.

### Part A: Document Scanner

Create `shared/google_docs.py` with the following functions:

**`scan_document_for_insertion_point(doc_id)`**

Uses the Google Docs API to read the document structure and find where weekly reports should be inserted. The Docs API returns the document as a structured JSON with `body.content` containing a list of structural elements (paragraphs, tables, etc.) each with a `startIndex` and `endIndex`.

Scan the document looking for the FIRST occurrence of any of these patterns (case-insensitive):
- "Streaming" or "Playlist Highlights" or "Streaming / Playlist" or "Streaming/Playlist"
- "Radio Plays" or "Radio Play"
- "Press Pick" or "Press pickup"
- "UPDATES" (as a standalone line, not inside a longer sentence)
- Any line matching the pattern: dashes + "Sent" + date-like text + dashes (e.g., "—Sent Feb 24—", "—-------Sent Aug 21—------", "SENT_____________")

The scan should find the paragraph startIndex of the FIRST match. This is the proposed insertion point — new content will be inserted just BEFORE this index (above the existing content).

Return: `{found: bool, index: int|null, matched_text: str|null, context: str}` where context is the 2-3 lines around the match for the user to confirm.

**`get_document_title(doc_id)`**

Simple: fetch the doc, return its title.

**`read_document_structure(doc_id)`**

Returns a simplified view of the document structure for debugging: list of `{index, text_preview, is_heading, style}` for the first 50 paragraphs. Useful for the insertion point confirmation UI.

### Part B: Insertion Point Confirmation Flow

When a user links a Google Doc for the first time (or clicks "Set insertion point"), the tool needs to confirm where reports should go.

Add API endpoint: `POST /api/google/scan-insertion/<artist_name>`

Flow:
1. Load the artist's linked doc_id
2. Call `scan_document_for_insertion_point(doc_id)`
3. If found: return the proposed insertion point with context. The frontend shows: "I'll insert new reports here: [context preview]. Is this correct?" with Confirm / Choose Different buttons
4. If not found: return the document structure (first 30 lines). The frontend shows the lines and lets the user click where reports should start
5. On confirmation, call `update_artist_doc_bookmark(artist_name, confirmed_index)` and `confirm_artist_doc_insertion(artist_name)`

Important: We store the character index, but the document can change between weeks. So on each append, we need to RE-SCAN for our own divider (see Part C) rather than relying on a stored index. The stored index is only used as a fallback if the divider isn't found.

### Part C: Report Formatter for Google Docs

**`format_report_for_docs(dsp_data, radio_data, press_data, artist_name, date_label)`**

Takes the structured output from the three tools and converts it into a list of Google Docs API "insert" requests. The Google Docs API uses `batchUpdate` with requests like:

```python
requests = [
    {"insertText": {"location": {"index": insert_at}, "text": "Some text\n"}},
    {"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": {"bold": True}, "fields": "bold"}},
    {"updateParagraphStyle": {...}}
]
```

The formatter builds these requests to produce:

```
——— DMM Report [Mar 7, 2026] ———

Streaming / Playlist Highlights
Spotify
Playlist Name - Followers - Date
[screenshot placeholder line if applicable]

Playlist Name - Followers - Date

Apple Music
LATAM
Playlist Name - Apple Music - Date

[etc. for each platform]

Radio Plays (last 7 days)
COUNTRY
Station Name
  •  Song Title (Nx)
  •  Song Title (Nx)
Station Name
  •  Song Title (Nx)

[etc. for each country]

Press Pick Up
COUNTRY
Outlet Name: Description. Social Media: XK
https://url.com/article-url

[etc. for each country/outlet]

```

Formatting rules:
- "——— DMM Report [date] ———" → bold, slightly larger if possible, acts as divider
- Section headers ("Streaming / Playlist Highlights", "Radio Plays", "Press Pick Up") → bold
- Country names → bold, underlined
- Platform headers ("Spotify", "Apple Music", etc.) → bold
- Outlet names → bold (the "Outlet Name:" part only)
- URLs → formatted as hyperlinks using updateTextStyle with link field
- Bullet points for radio plays: use "  •  " prefix (matching the existing format in their docs)
- Normal text for everything else

The function returns: `(requests_list, total_text_length)` where requests_list is the full set of batchUpdate requests ready to send, and total_text_length is how many characters were inserted (needed to calculate correct indices since Google Docs uses absolute character positions).

CRITICAL: Google Docs API inserts work in reverse — if you insert at index 10, everything after index 10 shifts. So either:
- Build all text as one big string, insert it in one `insertText` call, then apply formatting with calculated offsets, OR
- Insert in reverse order (last paragraph first)

The single-insert-then-format approach is more reliable. Build the complete text block, insert it all at once at the target index, then apply bold/underline/hyperlink formatting using the known offsets within that block.

**`format_dsp_section(dsp_data)`** — formats just the DSP portion
**`format_radio_section(radio_data)`** — formats just the radio portion  
**`format_press_section(press_data)`** — formats just the press portion

Each returns: `(text_string, formatting_ranges)` where formatting_ranges is a list of `{start_offset, end_offset, bold, underline, link_url}` relative to the start of this section's text.

### Part D: Append Execution

**`append_report_to_doc(doc_id, dsp_data, radio_data, press_data, artist_name)`**

The main function that puts it all together:

1. Read the document
2. Find the insertion point. Search strategy (in order):
   a. Look for our own divider: "——— DMM Report" — if found, insert ABOVE the most recent one (new report goes on top)
   b. Look for the stored bookmark_index and scan nearby for familiar content (Streaming, Radio, Press headers)
   c. If neither found, use scan_document_for_insertion_point() to find organic content markers
   d. If nothing found, insert at the end of the document
3. Build the formatted report via format_report_for_docs()
4. Execute the batchUpdate with all insert + formatting requests
5. Return: `{success: bool, inserted_at: int, characters_inserted: int, error: str|null}`

Add API endpoint: `POST /api/google/append/<artist_name>`
- Request body: `{dsp_data, radio_data, press_data}` OR `{job_id}` to pull data from an already-completed job
- Calls append_report_to_doc()
- Updates last_appended_at and status in the mapping table
- Returns success/failure with details

Also add: `POST /api/google/append-from-job/<job_id>`
- For use after a Full Report job completes
- Pulls the structured data from the job's results
- Looks up the artist's linked doc
- Calls append_report_to_doc()

### Part E: "Append to Google Doc" Button

Wire up the button added in Session 1:

On the Full Report results page, when the user clicks "Append to Google Doc":
1. If insertion not yet confirmed for this artist → trigger the scan/confirmation flow first (Part B)
2. Once confirmed → call the append endpoint
3. Show progress: "Appending to Google Doc..." → "✓ Report appended to [Doc Title]" with a link to the doc
4. On error: "Failed to append: [error message]. You can still download the .docx and paste manually."

For individual tools (Press, Radio, DSP): the append button sends only that tool's data. The formatter handles missing sections gracefully — if only press data is provided, it only inserts the Press Pick Up section.

### Error Handling

- Doc not accessible → "Can't access [Doc Title]. Check sharing permissions."
- API quota exceeded → "Google API rate limit reached. Try again in a minute."
- Doc was deleted → "This document no longer exists. Unlink and re-link a new doc."
- Insertion point ambiguous → Fall back to the confirmation flow
- Auth token expired and can't refresh → "Google account disconnected. Reconnect in Settings."
- Any error during append → log full error, show friendly message, never leave the doc in a corrupted state. Google Docs API batchUpdate is atomic — if any request fails, none are applied. So partial corruption is not a risk.
```

---

## Session 3: Batch Integration + Friday Flow

```
This is Session 3 of the Google Docs auto-append feature. Sessions 1-2 set up Google Auth, artist-doc mapping, document scanning, and the append logic. Now we wire it into the batch workflow so all reports can auto-append on Friday with one click.

### Part A: Batch Append After Report Generation

Modify the existing batch endpoints to optionally auto-append to Google Docs after generating each report.

In the "This week's releases" and "All releases" batch modes for Full Report, add a checkbox in the UI:

☑ Auto-append to Google Docs

When checked, after each artist's report finishes generating:
1. Check if the artist has a linked Google Doc with confirmed insertion point
2. If yes → call append_report_to_doc() with the structured data from the job
3. Log progress: "[3/14] Appended to Google Doc: Mitski ✓" or "[5/14] No Google Doc linked: NewArtist — skipped"
4. If append fails for one artist, log the error and continue with the next artist. Don't stop the batch.
5. If no, skip and note it in the summary

Also add auto-append support to the individual batch modes (Press batch, Radio batch):
- Press batch with auto-append → appends only the press section to each artist's doc
- Radio batch with auto-append → appends only the radio section

### Part B: Batch Summary View

After a batch completes with auto-append enabled, show a summary:

```
Batch Complete — 14 artists

Google Docs Updated:
  ✓ Mitski — appended to "Mitski 2026 -- LATAM"
  ✓ Bad Bunny — appended to "Bad Bunny 2026"
  ✓ Laufey — appended to "Laufey LATAM 2026"
  ... (8 more)

Needs Attention:
  ⚠ NewArtist — no Google Doc linked [Link Doc]
  ⚠ AnotherArtist — no Google Doc linked [Link Doc]
  ✗ SomeArtist — append failed: permission denied [Retry] [Download .docx]

All .docx reports available: [Download All (.zip)]
```

Each line in "Needs Attention" has action buttons:
- [Link Doc] → opens the Google Doc URL input inline
- [Retry] → retries the append for that artist
- [Download .docx] → fallback to manual workflow

The .zip download is always available as a fallback regardless of Google Docs status.

### Part C: Smart Linking Prompts

On the batch summary, for artists without linked docs, make linking frictionless:

When the user clicks [Link Doc] next to "NewArtist":
1. Show an input field for the Google Doc URL
2. On paste, immediately validate the URL and test access
3. Auto-run the insertion point scan
4. If scan finds a clear insertion point → auto-confirm and show "✓ Linked & insertion point set"
5. If scan is ambiguous → show the confirmation UI inline
6. After linking, offer: "Append now?" → immediately appends the already-generated report

This means: even for new artists on their first Friday, the workflow is paste URL → auto-detect → append. Three clicks.

### Part D: Scheduled Auto-Append

Integrate with the existing Schedules system (APScheduler). When a scheduled run completes:

1. Check if auto-append is enabled for that schedule (add a toggle to the schedule creation form: "Auto-append to Google Docs")
2. If enabled, after all artists finish generating, run the append for each one that has a linked doc
3. Store append results in the schedule_runs details JSON
4. If the schedule runs at e.g., Monday 9 AM, by the time the team arrives, all reports are already in their Google Docs

Add to the schedule creation/edit form:
- ☑ Auto-append to Google Docs (only shown if Google account is connected)
- Note below: "Reports will be appended to linked Google Docs. Artists without linked docs will be skipped."

### Part E: Management & Safety

**Duplicate prevention:**
Before appending, check if a report with the same date label already exists in the doc. Search for "——— DMM Report [Mar 7, 2026] ———" — if found, warn: "A report for this date already exists in [Doc Title]. Append anyway?" In batch mode, skip duplicates silently and note in summary: "⚠ Mitski — report for Mar 7 already exists, skipped"

**Undo support:**
After a successful append, store the range that was inserted (startIndex, endIndex). Add an "Undo last append" button on the artist's doc card in Settings that deletes that range from the doc. This is a safety net — if something goes wrong with formatting, the user can undo without manually editing the doc. The undo data expires after 24 hours (after that, manual editing is the only option).

**Rate limiting:**
Google Docs API has a quota of 300 requests per minute per user. A single append is ~2-5 requests (1 insert + a few format updates). For a 14-artist batch, that's ~30-70 requests — well within limits. But add a 1-second delay between artists in batch mode to be safe, and handle 429 responses with exponential backoff.

**Offline/error resilience:**
If Google API is unreachable during a batch:
- Log the error for that artist
- Continue generating reports (the .docx files are still created)
- Show in summary: "Google Docs unavailable — all reports saved as .docx"
- The user can retry individual appends later from the summary view

### Part F: First-Time Experience

When a user first enables batch auto-append (or visits the Linked Docs settings):

If no Google account is connected:
- Show: "Connect your Google account to auto-append reports to Google Docs" → [Connect Google Account]
- After connecting, show: "Now link your artists' Google Docs. You can do this one by one, or paste multiple at once."

Bulk linking option in Settings:
- A table with two columns: Artist Name | Google Doc URL
- Pre-populated with all artists from the release schedule / dashboard
- User pastes URLs next to each artist
- "Validate All" button → tests access to each doc in parallel, shows ✓/✗
- "Save All" button → saves all mappings at once

This makes the initial setup for 30-40 artists a one-time 10-minute task instead of linking one at a time over multiple Fridays.
```

---

## Testing Checklist

After all three sessions, verify:

1. Google OAuth connect/disconnect works from Settings
2. Link a doc for a test artist → URL validates, doc title shows
3. Scan insertion point → finds correct location in varied doc formats
4. Confirm insertion point → stores correctly
5. Single append (Full Report) → report appears in Google Doc with correct formatting
6. Single append (Press only) → only press section appears
7. Append to doc with existing DMM divider → inserts above it correctly
8. Append to doc with no previous DMM content → insertion scan works
9. Batch "This week's releases" with auto-append → all linked docs updated
10. Batch with mix of linked/unlinked → linked ones update, unlinked flagged
11. Duplicate prevention → same-date report detected and skipped
12. Undo last append → content removed cleanly
13. Error cases: doc deleted, permissions revoked, API down → graceful handling
14. Scheduled run with auto-append → reports land in docs automatically
15. Bulk linking in Settings → validates and saves multiple docs at once
