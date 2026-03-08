# DMM Tools — Launch Preparation Tracker

## Overview

This document covers every milestone between the current state and a bulletproof, demo-ready product that non-technical users can operate without developer support. Work is organized into 6 phases with clear dependencies. Estimated total: 3-4 weeks of focused sessions.

---

## Phase 1: Failure Mode Audit & Error Handling (Week 1)

The single most important phase. A non-technical user who hits an unhandled error will lose trust permanently. Every tool needs to fail gracefully with a clear, human-readable message — never a traceback, never a frozen spinner, never silence.

### Milestone 1.1: Systematic Crash Test (Day 1-2) — DONE

Go through every tool in the web UI and deliberately try to break it. Document every failure. This is a testing session, not a coding session.

**Radio Report — test these scenarios:**
- Empty artist name → submit
- Artist name that doesn't exist on Soundcharts (e.g., "asdfghjkl")
- Artist name with special characters (e.g., "Ñ", accents, ampersands: "Simon & Garfunkel")
- Soundcharts credentials expired or wrong
- Soundcharts server down (disconnect your internet mid-request)
- Custom date range where start > end
- Custom date range in the future
- Very long artist name (100+ characters)
- Artist with zero radio plays in the selected period

**Press Pickup — test these scenarios:**
- Empty artist name → submit
- Artist name with only 1-2 characters (e.g., "AI")
- Artist name that matches common English words (e.g., "The", "Future")
- No internet connection during search
- Serper API key expired or invalid
- Brave API key expired or invalid
- Groq API key expired or invalid (relevance filter should fail open)
- feed_registry.json missing or corrupted
- social_handle_registry.json missing or corrupted
- Custom date range: 0 days, negative days
- Artist with zero results across all sources

**DSP Pickup — test these scenarios:**
- Empty artist name
- Artist not in release schedule
- Spotify/Apple Music/etc. returning errors
- Playlist database CSV missing
- All platforms deselected → submit
- Artist name that partially matches multiple releases

**Full Report — test these scenarios:**
- Empty artist name
- One sub-tool fails (e.g., Soundcharts down but Press/DSP work)
- All sub-tools fail
- Artist with data in only 1 of 3 tools
- Very long "Overall Efforts" text

**Weekly Digest — test these scenarios:**
- Batch mode with 0 artists selected
- Batch mode with all artists + snapshot mode
- Groq down during AI analysis
- Artist with no data at all

**Proposal Generator — test these scenarios:**
- No genre selected
- No countries selected  
- Empty budget fields
- Groq down during AI strategy generation

**PR Translator — test these scenarios:**
- Empty text, no file uploaded → submit
- Upload a non-.docx file (e.g., .pdf, .jpg)
- Upload a corrupted .docx
- Very large .docx (10+ MB)
- Text in a language that isn't English/Spanish/Portuguese

**Outlet Discovery — test these scenarios:**
- No genre selected
- No region selected
- Groq unavailable
- Brave API exhausted

**Release Calendar — test these scenarios:**
- Google Sheets URL unreachable
- Google Sheets format changed (columns reordered)
- Empty release schedule

**Schedules — test these scenarios:**
- Invalid cron expression
- Schedule triggers while Flask is restarting
- Two schedules fire at the same time
- Schedule references artists that no longer exist in dashboard

**Dashboard — test these scenarios:**
- Artist with zero snapshots
- Compare with only 1 artist entered
- Export to PNG/PDF with very long artist names
- Collect Data when all APIs are down

**Playlist Database — test these scenarios:**
- Add playlist with invalid URL
- Add playlist from unsupported platform
- Remove all playlists then try DSP Pickup

For each failure, log: tool name, input used, what happened (error message? frozen? crash?), what SHOULD happen.

### Milestone 1.2: Backend Error Handling (Day 2-4) — DONE

Using the crash test log, add try/except blocks and user-friendly error messages for every failure point. Pattern for every API call:

```python
try:
    result = call_external_api()
except requests.exceptions.Timeout:
    return {"error": "Soundcharts is taking too long to respond. Try again in a few minutes."}
except requests.exceptions.ConnectionError:
    return {"error": "Can't reach Soundcharts right now. Check your internet connection."}
except Exception as e:
    logger.error(f"Soundcharts error: {e}")
    return {"error": "Something went wrong fetching radio data. The error has been logged."}
```

**Priority fixes (these will happen most often):**
- Soundcharts auth failure → "Soundcharts login failed. Check credentials in Settings."
- Serper 402 (out of credits) → "Serper credits exhausted. Press results may be incomplete."
- Groq 429 (rate limited) → Silent fallback, no error shown (already designed this way)
- Network timeout on any API → "Service temporarily unavailable. Results from other sources are still included."
- Missing data files → "Database file not found. Contact administrator." (not a traceback)

### Milestone 1.3: Frontend Error Display (Day 4-5) — DONE

Every tool's result area needs a standardized error display pattern:

- Error messages appear in a visible, styled box (not console.log)
- Red/orange border, clear icon, plain language
- If partial results are available, show them WITH the error ("Press results found 15 articles. Note: Serper search was unavailable — results may be incomplete.")
- Loading states: every button that triggers a backend call should show a spinner/progress indicator AND disable itself to prevent double-clicks
- Timeout handling: if a request takes >3 minutes, show "This is taking longer than usual. You can wait or try again."
- Never show raw JSON error responses to the user

### Milestone 1.4: Input Validation (Day 5) — DONE

Prevent bad inputs from ever reaching the backend:

- Artist name: trim whitespace, require ≥2 characters, strip leading/trailing quotes
- Date ranges: validate start < end, not in the future, not more than 1 year ago
- Custom cron in Schedules: validate format before submission, show next 3 run times as preview
- File uploads (PR Translator): validate file extension before upload, show file size, reject >20MB
- Budget fields (Proposal): numbers only, no negatives, reasonable maximums
- All required fields: disable submit button until minimums are met, highlight empty required fields on submit attempt

---

## Phase 2: Dependency Management & Configuration (Week 1-2)

The tool depends on external services that can change. Non-technical users need a way to update configurations without touching code or .env files.

### Milestone 2.1: Settings Page (Day 6-8) — DONE

Create a `/settings` page accessible from the main nav. Sections:

**API Credentials**
- Soundcharts: email + password fields (masked). Test button that attempts login and shows "Connected ✓" or "Login failed ✗" with the specific error
- Serper: API key field (masked). Shows remaining credits count. Test button
- Brave: API key field (masked). Shows monthly usage / quota. Test button  
- Groq: API key field (masked). Test button
- Tavily: API key field (masked). Test button
- Gemini: API key field (masked). Test button

Each credential should:
- Show current status (connected/disconnected/expired)
- Have a "Test Connection" button
- Save to a secure config file (not .env — something the web app can write to)
- Show last successful connection timestamp
- Flag which tools are affected if this credential is missing

**Data Sources**
- Release Schedule Google Sheets URL — editable field with "Test" button that fetches and shows row count
- Press Database — show current row count, last updated date, "Re-scan Feeds" button (runs discover_feeds.py), "Re-scan Social Handles" button (runs discover_social_handles.py)
- Playlist Database — show current playlist count by platform, link to Playlist Database page

**System Status**
- Dashboard showing green/yellow/red for each external dependency
- Green: last successful call <1 hour ago
- Yellow: last successful call 1-24 hours ago
- Red: last successful call >24 hours ago or last call failed

This directly solves the Soundcharts credential problem you raised. If Flor leaves, anyone with a Soundcharts account goes to Settings, enters new credentials, clicks Test, done.

### Milestone 2.2: Graceful Degradation (Day 8-9) — DONE

When a dependency is down, the tool should still work with whatever's available:

- Soundcharts down → Radio section shows "Radio data unavailable — Soundcharts connection failed" instead of crashing the entire Full Report
- Serper exhausted → Press Pickup skips Serper, shows results from the other 6 sources with note "Some search sources were unavailable"
- Groq down → AI descriptions show "Description pending" instead of empty, relevance filter skipped (already fail-open), digest AI analysis shows "AI analysis unavailable — manual summary recommended"
- Google Sheets unreachable → Release Calendar shows cached version with "Last updated: [date]. Live data temporarily unavailable."
- No internet at all → Show clear message on every tool: "No internet connection detected. These tools require internet access to fetch data."

### Milestone 2.3: Data Freshness Monitoring (Day 9-10) — DONE

Add visible indicators for data that can go stale:

- Feed registry: "Last scanned: Feb 28, 2026 (422 feeds). Re-scan recommended monthly."
- Social handle registry: "Last scanned: Feb 28, 2026 (536 outlets)."
- Press database: "1,533 outlets. Last Notion export: [date]."
- Playlist database: "116 playlists. Last Notion export: [date]."

Show a subtle warning banner on relevant tools when data is >30 days old: "Press database hasn't been updated in 45 days. Some new outlets may be missing."

---

## Phase 3: UI/UX Polish for Non-Technical Users (Week 2)

### Milestone 3.1: Tool Readiness Audit (Day 10-11) — DONE

Go through every tool and classify:

- **Ship-ready**: Works reliably, error handling solid, UI clean → show in demo
- **Needs polish**: Core functionality works but UX rough → fix before demo
- **Not ready**: Half-implemented or unreliable → HIDE from UI

For tools classified as "Not ready": remove from the homepage card grid and the tab bar. Add them back when they're ready. 8 polished tools > 12 tools where 4 are broken. Consider hiding the WIP badges entirely — either a tool works or it doesn't appear.

### Milestone 3.2: Remove Prototype Framing (Day 11) — DONE

- Remove the "PROTOTYPE" badge from the top-left
- Remove the "This is an early prototype — features may change or break" disclaimer
- Remove WIP badges from tools that work
- Change footer from "Internal use only. Confidential." to something that sounds like a product, or remove the confidential note
- Keep the "Dorado Music Marketing © 2026" branding

This is a presentation change, not a code change. But it shifts the perception from "experiment" to "product."

### Milestone 3.3: Navigation Improvements (Day 11-12) — DONE

The tab bar with 11+ items is getting crowded. Consider:

**Option A — Grouped navigation:**
- Core Tools: Radio Report, Press Pickup, DSP Pickup
- Reports: Full Report, Weekly Digest
- Management: Proposal Generator, PR Translator, Discovery
- System: Schedules, Dashboard, Settings

**Option B — Keep the homepage cards as primary navigation, remove the tab bar entirely.** Each tool is a full-page experience. "← All Tools" link at top-left takes you back to the card grid. This is cleaner and scales better. The cards already do a great job of showing what's available.

**Option C — Keep tabs but limit to the 5-6 most-used tools, with a "More" dropdown for the rest.**

Recommendation: Option B. The homepage cards are already the strongest UI element. Let them be the navigation.

### Milestone 3.4: Loading & Progress Experience (Day 12-13) — DONE

Every tool that takes >2 seconds needs real-time feedback:

**Press Pickup (most important — takes ~2 minutes):**
- Show a progress stepper: "Step 1/7: Scanning RSS feeds (422 outlets)..." → "Step 2/7: Mining sitemaps..." → "Step 3/7: Searching Google News..." etc.
- Each step shows a checkmark when done with count: "✓ RSS feeds: 18 articles found"
- Final step: "Filtering results... Done. 14 articles across 4 countries."

**Radio Report (~10-30 seconds):**
- "Connecting to Soundcharts..." → "Fetching airplay data for [Artist]..." → "Generating report..."

**DSP Pickup (~30-60 seconds depending on platforms):**
- Show per-platform progress: "Checking Spotify (51 playlists)..." → "✓ Spotify: 3 placements" → "Checking Apple Music (29 playlists)..." etc.

**Full Report (~3-5 minutes):**
- Three-section progress: "Running Radio Report... ✓" → "Running DSP Check... ✓" → "Running Press Pickup... ✓" → "Compiling report..."

This turns waiting time into a feature demonstration. The user watches their data being assembled in real time.

### Milestone 3.5: Help & Tooltips (Day 13-14) — DONE

Non-technical users will have questions. Add lightweight guidance:

- Each tool's "Tips & Info" section (already exists) should be expanded with: what this tool does in 1 sentence, what you need to run it, what the output looks like, common issues
- Hover tooltips on non-obvious controls: "LATAM" button → "Latin American radio stations only", "Custom Range" → "Select specific start and end dates"
- Empty states: when a tool returns 0 results, show helpful context: "No press coverage found for [Artist] in the last 7 days. Try expanding to 28 days, or check that the artist name is spelled correctly."
- First-time user experience: consider a subtle "Welcome" overlay on first visit that shows the 3 most important tools and what they do (dismissible, remembers via localStorage)

### Milestone 3.6: Mobile Responsiveness Check (Day 14) — DONE

The screenshots show a desktop layout. Check on tablet/phone:

- Do the homepage cards stack properly on narrow screens?
- Do the platform toggle buttons (DSP Pickup) wrap or overflow?
- Are form inputs usable on touch devices?
- Does the dashboard chart render on small screens?
- Does the Release Calendar scroll horizontally or collapse?

These users might check results on their phone during a meeting. It doesn't need to be perfect on mobile, but it shouldn't be broken.

---

## Phase 4: Data & Content Quality (Week 2-3)

### Milestone 4.1: Stress Test with Real Artist Roster (Day 14-16)

Run every tool against 8-10 real artists from the active release schedule, covering:

- A superstar (Bad Bunny) — high volume, lots of results
- A mid-tier LATAM artist — moderate coverage
- An indie/niche artist — sparse coverage
- A new/debut artist — minimal or zero existing data
- An artist with a common name that could cause collisions
- An artist with accented characters in their name
- A Brazilian artist (Portuguese-language results)
- A recently released artist (should have DSP placements + fresh press)

For each: run Radio, Press, DSP, Full Report, Digest. Check output for accuracy, false positives, missing coverage, formatting issues, stale articles. Fix anything that surfaces.

### Milestone 4.2: Report Output Quality (Day 16-17)

Download and open every .docx the tools produce. Check in Microsoft Word AND Google Docs (DMM team might use either):

- Fonts render correctly
- Hyperlinks are clickable
- Proof images (DSP) display at proper size
- Country headers are properly formatted
- No empty sections (if a section has 0 results, omit it entirely rather than showing an empty header)
- Article titles display properly (no broken encoding, no HTML entities)
- Grouped outlets with multiple URLs display correctly
- Social media platform labels appear correctly
- Press outlet descriptions don't have [NEW — not in DB] markers (those are internal — strip them from client-facing output, or rephrase to something neutral)

### Milestone 4.3: Description Quality for Unknown Outlets (Day 17-18)

When the Groq-generated descriptions for new outlets appear in reports, verify quality:

- Are descriptions accurate? (Spot-check 10 against actual websites)
- Are they consistent in format with the database descriptions?
- Do they include social media follower counts when available?
- Could any be embarrassingly wrong? (AI hallucination risk)

If descriptions aren't reliable enough, consider showing "Independent music publication" as a safe generic fallback instead of a potentially wrong AI-generated description.

### Milestone 4.4: [NEW — not in DB] Cleanup (Day 18)

The press reports currently mark outlets not in the Notion database with "[NEW — not in DB]". For client-facing reports, this should either:
- Be removed entirely (just show the Groq-generated description)
- Be replaced with a subtle visual indicator (like an asterisk)
- Be kept only in an internal/admin view

The DMM team might want to know which outlets are new discoveries, but the client shouldn't see internal database status markers.

---

## Phase 5: Security & Operational Hardening (Week 3)

### Milestone 5.1: Credential Security (Day 18-19)

Currently API keys are in .env files. For a product:

- Settings page stores credentials in an encrypted config file (not plain text)
- Passwords (Soundcharts) never displayed in full after saving — show "••••••••" with a "Show" toggle
- API keys show only last 4 characters after saving
- No credentials in any log output
- No credentials in error messages (sanitize before logging)
- Git: verify .env and any config files with credentials are in .gitignore

### Milestone 5.2: Access Control (Day 19-20)

If this is going to run on a network where multiple people access it:

- Add a simple login page (username/password). Not complex — just enough to prevent random access
- Session-based auth (Flask-Login or simple session cookie)
- Settings page accessible only to admin role
- Regular users can run tools but not change API keys or schedules
- Consider: does the tool need to be accessible outside the local network? If so, HTTPS is required (ngrok for demo is fine, but production needs real SSL)

If the service model means YOU maintain it remotely, you need SSH or a VPN to their machine. Document this requirement.

### Milestone 5.3: Logging & Diagnostics (Day 20-21)

For the service model, you need to be able to diagnose issues remotely:

- Structured logging to a file (not just stdout): timestamp, tool name, action, result/error
- Log rotation (don't fill up disk)
- A `/admin/logs` page that shows recent errors (admin-only)
- Each tool run gets a unique ID logged so you can trace issues
- Optional: error notification (email or Slack webhook) when a critical failure occurs — so you know before the client tells you

### Milestone 5.4: Backup & Recovery (Day 21)

- Automated backup of history.db (contains all dashboard snapshots, schedule runs)
- Automated backup of data/ directory (feed registry, social handles, databases)
- Document the recovery process: "If something goes wrong, here's how to restore"
- Consider: GitHub repo IS the backup for code, but data files need their own backup strategy

---

## Phase 6: Demo Preparation & Pitch Materials (Week 3-4)

### Milestone 6.1: Demo Script (Day 22-23)

Write a step-by-step demo script you'll follow during the presentation. Suggested flow:

1. **Open with the problem**: "Right now, generating a client report takes 2-3 hours of manual work across Soundcharts, Google, and spreadsheets."
2. **Show the homepage**: Quick tour of what's available, without clicking everything
3. **Live demo — Full Report**: Type an artist name the audience knows, hit generate, watch the progress stepper, download the .docx. Open it. This is the "wow" moment — the entire report generated while they watched
4. **Show the Dashboard**: Switch to an artist with 30+ snapshots. Show the charts, the trend over time, the comparison view
5. **Show the Release Calendar**: 198 releases, phase tracking, action buttons
6. **Mention scale**: "This is tracking 1,500 press outlets, 422 RSS feeds, 116 playlists across 6 platforms, all automated"
7. **Show the Schedules**: "This runs automatically every Monday at 9 AM. Reports are waiting for you when you arrive"
8. **Close with the value proposition**: Hours saved per week, cost comparison, reliability

Pre-load the dashboard with real data for 5-6 artists so the charts look populated during the demo. Don't demo live API calls for the first time — test the exact demo flow 3 times before the real presentation.

### Milestone 6.2: Backup Demo Materials (Day 23)

Things go wrong during live demos. Prepare:

- Pre-generated .docx reports for 3 artists (radio, press, DSP, full report)
- Dashboard screenshots showing populated data
- Screen recording of a full report generation (fallback if internet dies during demo)
- A one-page PDF summary of capabilities and time savings

### Milestone 6.3: Time Savings Documentation (Day 24)

Build a concrete time-savings spreadsheet. For each tool:

| Task | Manual Time | Tool Time | Weekly Frequency | Weekly Savings |
|------|-------------|-----------|------------------|----------------|
| Client report (radio + press + DSP) | 3-4 hours | 5 minutes | 3-5 per week | 9-20 hours |
| Press pickup per artist | 2-3 hours | 2 minutes | 5-10 per week | 10-30 hours |
| Radio report | 1-2 hours | 30 seconds | 5-10 per week | 5-20 hours |
| DSP playlist check | 3-4 hours | 1 minute | 1-2 per week | 3-8 hours |
| Weekly digest | 30-60 min | 2 minutes | 10-20 per week | 5-20 hours |
| PR translation | 30-60 min | 1 minute | 2-3 per week | 1-3 hours |

Get real numbers from your actual usage. "This saved me X hours last week" is more powerful than estimates.

### Milestone 6.4: Pricing & Service Model Preparation (Day 25-26)

We'll have a deep conversation about this, but prepare:

- Monthly cost of running the tool (hosting, API credits, your maintenance time)
- Value of the hours saved (what DMM pays for the roles this replaces or augments)
- Comparable SaaS pricing in the music industry (Chartmetric, Soundcharts themselves, etc.)
- 3 pricing tiers to present as options (gives the buyer a sense of control):
  - Tier 1: Tool access only (they host, you provide updates quarterly)
  - Tier 2: Managed service (you host, maintain, fix bugs, monthly updates)
  - Tier 3: Managed service + priority support + custom feature development
- Service agreement template covering: what's included, response time for bugs, update frequency, data ownership

---

## Dependency Map

Things that block other things:

```
Phase 1 (Error Handling) → blocks everything else
  ├── 1.1 Crash Test → feeds into 1.2 and 1.3
  ├── 1.2 Backend Fixes → must complete before Phase 4 stress tests
  └── 1.3 Frontend Error Display → must complete before Phase 3 UX work

Phase 2 (Dependencies) → blocks Phase 5
  ├── 2.1 Settings Page → blocks 5.1 (credential security)
  └── 2.2 Graceful Degradation → blocks Phase 4 stress tests

Phase 3 (UI/UX) → blocks Phase 6
  ├── 3.1 Tool Audit → determines what gets demoed
  ├── 3.4 Loading Experience → critical for demo impact
  └── 3.2 Remove Prototype Framing → cosmetic but essential for demo

Phase 4 (Data Quality) → blocks Phase 6
  └── 4.1 Stress Tests → may surface issues requiring Phase 1 rework

Phase 5 (Security) → independent, can run parallel to Phase 4
Phase 6 (Demo Prep) → final phase, requires all others complete
```

---

## Quick Reference: Critical Path

If you only have 2 weeks instead of 4, do these in order:

1. Crash test every tool (1 day)
2. Fix the top 10 most likely errors with user-friendly messages (2 days)
3. Hide unfinished tools, remove PROTOTYPE badge (1 hour)
4. Add loading/progress indicators to Press Pickup and Full Report (1 day)
5. Settings page with Soundcharts credential management (2 days)
6. Stress test with 5 real artists, fix what surfaces (2 days)
7. Strip [NEW — not in DB] from client-facing reports (1 hour)
8. Pre-load dashboard with real data for demo (1 day)
9. Write and rehearse demo script (1 day)
10. Prepare backup demo materials (half day)

That gets you from "working internal tool" to "presentable product" in the minimum time.

---

## Post-Launch Roadmap (After Sale/Agreement)

Once the tool is in their hands and the service agreement is signed:

- **Month 1**: Monitor usage, fix bugs as reported, tune Groq prompts based on real edge cases
- **Month 2**: Implement top-requested feature (likely from user feedback), refresh outlet database from Notion
- **Month 3**: Add email delivery for scheduled reports, expand playlist database
- **Ongoing**: Monthly feed registry refresh, quarterly outlet URL enrichment, API key rotation as needed, database updates when Notion exports change
