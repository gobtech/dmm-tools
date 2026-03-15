// =====================================================================
// Theme toggle
// =====================================================================
function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  document.getElementById('theme-icon').innerHTML = theme === 'dark' ? '&#9788;' : '&#9790;';
}
function toggleTheme() {
  const isDark = document.documentElement.classList.contains('dark');
  const next = isDark ? 'light' : 'dark';
  localStorage.setItem('dmm_theme', next);
  applyTheme(next);
}
applyTheme(localStorage.getItem('dmm_theme') || 'light');

// =====================================================================
// Landing / Tool Navigation
// =====================================================================
function goToTool(name) {
  document.getElementById('landing').style.display = 'none';
  document.getElementById('tool-view').style.display = 'block';
  // Animate in
  const tv = document.getElementById('tool-view');
  tv.style.animation = 'none';
  tv.offsetHeight;
  tv.style.animation = 'panelIn .4s cubic-bezier(.25,.46,.45,.94)';
  switchTab(name);
}

function goToLanding() {
  document.getElementById('tool-view').style.display = 'none';
  document.getElementById('landing').style.display = 'grid';
  // Animate in
  const lg = document.getElementById('landing');
  lg.style.animation = 'none';
  lg.offsetHeight;
  lg.style.animation = 'panelIn .4s cubic-bezier(.25,.46,.45,.94)';
}

// =====================================================================
// Tabs
// =====================================================================
const TOOL_TITLES = {radio:'Radio Report',press:'Press Pickup',dsp:'DSP Pickup',report:'Full Report',proposal:'Proposal Generator',digest:'Weekly Digest',discovery:'Discovery',pr:'PR Translator',schedules:'Schedules',settings:'Settings'};
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById('tab-' + name);
  panel.classList.add('active');
  const titleEl = document.getElementById('tool-title');
  if (titleEl) titleEl.textContent = TOOL_TITLES[name] || name;
  // Re-trigger entrance animation
  panel.style.animation = 'none';
  panel.offsetHeight; // reflow
  panel.style.animation = '';
  // Load proposal data on first visit
  if (name === 'proposal' && !proposalDataLoaded) {
    proposalDataLoaded = true;
    loadProposalData();
  }
  // Load schedules data on first visit
  if (name === 'schedules' && !schedulesLoaded) {
    schedulesLoaded = true;
    loadSchedules();
    loadScheduleHistory();
  }
  // Settings: show admin gate or load content if already unlocked
  if (name === 'settings') {
    if (window._adminUnlocked) {
      document.getElementById('settings-admin-gate').style.display = 'none';
      document.getElementById('settings-content').style.display = '';
      refreshGoogleSettings();
      loadSettingsCredentials();
      loadSettingsDataSources();
    } else {
      document.getElementById('settings-admin-gate').style.display = '';
      document.getElementById('settings-content').style.display = 'none';
    }
  }
}

// =====================================================================
// Radio mode toggle
// =====================================================================
function radioModeChanged() {
  const mode = document.querySelector('input[name="radio-mode"]:checked').value;
  document.getElementById('radio-soundcharts-fields').classList.toggle('visible', mode === 'soundcharts');
  document.getElementById('radio-csv-fields').classList.toggle('visible', mode === 'csv');
  // Update button text and hide song picker when switching modes
  const fetchBtn = document.getElementById('radio-fetch-btn');
  fetchBtn.textContent = mode === 'soundcharts' ? 'Fetch Songs' : 'Generate Report';
  document.getElementById('radio-song-picker').style.display = 'none';
  document.getElementById('radio-generate-btn').style.display = 'none';
  radioFetchJobId = null;
}

function radioRangeChanged() {
  const range = document.querySelector('input[name="radio-range"]:checked').value;
  document.getElementById('radio-custom-range-fields').style.display = range === 'custom' ? 'block' : 'none';
}

// =====================================================================
// Batch mode helpers (shared by Radio + Press)
// =====================================================================
async function loadBatchPreview(mode, weekInputId, previewElId) {
  const previewEl = document.getElementById(previewElId);
  if (mode === 'artist') {
    previewEl.classList.remove('visible');
    previewEl.innerHTML = '';
    previewEl._selectedArtists = null;
    return;
  }
  previewEl.classList.add('visible');
  previewEl.innerHTML = '<span style="color:var(--text-secondary)">Loading releases...</span>';
  const week = document.getElementById(weekInputId)?.value || 'current';
  try {
    const resp = await fetch('/api/releases/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, week }),
    });
    const data = await resp.json();
    if (data.error) {
      previewEl.innerHTML = `<span style="color:var(--accent)">${escapeHtml(data.error)}</span>`;
      return;
    }
    if (!data.artists || data.artists.length === 0) {
      previewEl.innerHTML = '<span style="color:var(--text-secondary)">No releases found for this period.</span>';
      return;
    }
    
    // Create rich selectable list
    const artists = data.artists.map(a => a.artist);
    previewEl._allArtists = artists;
    previewEl._selectedArtists = new Set(artists);

    renderBatchSelector(previewEl);
  } catch (e) {
    previewEl.innerHTML = '<span style="color:var(--accent)">Could not load releases.</span>';
  }
}

function renderBatchSelector(previewEl) {
  const artists = previewEl._allArtists;
  const selected = previewEl._selectedArtists;
  const searchId = `search-${previewEl.id}`;
  
  let html = `
    <div class="batch-selector">
      <div class="batch-selector-header">
        <strong>${artists.length} artist${artists.length !== 1 ? 's' : ''} found</strong>
        <div class="batch-selector-controls">
          <button class="btn btn-small" onclick="batchSelectAll('${previewEl.id}', true)">All</button>
          <button class="btn btn-small" onclick="batchSelectAll('${previewEl.id}', false)">None</button>
        </div>
      </div>
      <input type="text" id="${searchId}" class="batch-selector-search" placeholder="Filter artists..." oninput="filterBatchList('${previewEl.id}')">
      <div class="batch-selector-list" id="list-${previewEl.id}">
  `;
  
  artists.forEach((a, i) => {
    const checked = selected.has(a) ? 'checked' : '';
    html += `
      <label class="batch-selector-item">
        <input type="checkbox" ${checked} onchange="toggleBatchArtist('${previewEl.id}', '${escapeHtml(a).replace(/'/g, "\\'")}')">
        <span>${escapeHtml(a)}</span>
      </label>
    `;
  });
  
  html += `</div></div>`;
  previewEl.innerHTML = html;
}

function batchSelectAll(previewElId, val) {
  const el = document.getElementById(previewElId);
  if (val) el._selectedArtists = new Set(el._allArtists);
  else el._selectedArtists = new Set();
  renderBatchSelector(el);
}

function toggleBatchArtist(previewElId, artist) {
  const el = document.getElementById(previewElId);
  if (el._selectedArtists.has(artist)) el._selectedArtists.delete(artist);
  else el._selectedArtists.add(artist);
  // Update count in header without full re-render
  const countEl = el.querySelector('.batch-selector-header strong');
  const count = el._selectedArtists.size;
  countEl.textContent = `${count} artist${count !== 1 ? 's' : ''} selected`;
}

function filterBatchList(previewElId) {
  const el = document.getElementById(previewElId);
  const search = document.getElementById(`search-${previewElId}`).value.toLowerCase();
  const items = el.querySelectorAll('.batch-selector-item');
  items.forEach(item => {
    const text = item.textContent.toLowerCase();
    item.style.display = text.includes(search) ? 'flex' : 'none';
  });
}

function radioBatchModeChanged() {
  const mode = document.querySelector('input[name="radio-batch-mode"]:checked').value;
  const isArtist = mode === 'artist';
  document.getElementById('radio-artist-field').style.display = isArtist ? '' : 'none';
  document.getElementById('radio-week-field').classList.toggle('visible', mode === 'week');
  document.getElementById('radio-auto-append-field').classList.toggle('visible', !isArtist);
  // Hide CSV mode and data source selector in batch mode
  document.getElementById('radio-datasource-label').style.display = isArtist ? '' : 'none';
  document.getElementById('radio-datasource-group').style.display = isArtist ? '' : 'none';
  if (!isArtist) {
    // Force soundcharts mode in batch
    const scRadio = document.querySelector('input[name="radio-mode"][value="soundcharts"]');
    if (scRadio) { scRadio.checked = true; radioModeChanged(); }
    document.getElementById('radio-csv-fields').classList.remove('visible');
  }
  // Update button text + gating
  const btn = document.getElementById('radio-fetch-btn');
  btn.textContent = isArtist ? 'Fetch Songs' : 'Run Batch Radio Reports';
  btn.disabled = isArtist && !document.getElementById('radio-artist').value.trim();
  // Hide song picker in batch mode
  if (!isArtist) {
    document.getElementById('radio-song-picker').style.display = 'none';
    document.getElementById('radio-generate-btn').style.display = 'none';
  }
  loadBatchPreview(mode, 'radio-week', 'radio-batch-preview');
}

function pressModeChanged() {
  const mode = document.querySelector('input[name="press-mode"]:checked').value;
  const isArtist = mode === 'artist';
  document.getElementById('press-artist-field').style.display = isArtist ? '' : 'none';
  document.getElementById('press-week-field').classList.toggle('visible', mode === 'week');
  document.getElementById('press-auto-append-field').classList.toggle('visible', !isArtist);
  // Update button text + gating
  const btn = document.getElementById('press-btn');
  btn.textContent = isArtist ? 'Search for Press Coverage' : 'Run Batch Press Search';
  btn.disabled = isArtist && !document.getElementById('press-artist').value.trim();
  loadBatchPreview(mode, 'press-week', 'press-batch-preview');
}

function reportModeChanged() {
  const mode = document.querySelector('input[name="report-mode"]:checked').value;
  const isArtist = mode === 'artist';
  document.getElementById('report-artist-field').style.display = isArtist ? '' : 'none';
  document.getElementById('report-efforts-field').style.display = isArtist ? '' : 'none';
  document.getElementById('report-week-field').classList.toggle('visible', mode === 'week');
  document.getElementById('report-auto-append-field').classList.toggle('visible', !isArtist);
  const btn = document.getElementById('report-btn');
  btn.textContent = isArtist ? 'Generate Full Report' : 'Run Batch Full Reports';
  btn.disabled = isArtist && !document.getElementById('report-artist').value.trim();
  loadBatchPreview(mode, 'report-week', 'report-batch-preview');
}

// =====================================================================
// Dropzone
// =====================================================================
const dropzone = document.getElementById('radio-dropzone');
const fileInput = document.getElementById('radio-files');
const fileListEl = document.getElementById('radio-file-list');
let selectedFiles = [];

dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => addFiles(fileInput.files));

function addFiles(files) {
  for (const f of files) {
    if (f.name.endsWith('.csv') && !selectedFiles.some(s => s.name === f.name)) {
      selectedFiles.push(f);
    }
  }
  renderFileList();
}

function removeFile(idx) {
  selectedFiles.splice(idx, 1);
  renderFileList();
}

function renderFileList() {
  if (!selectedFiles.length) {
    fileListEl.innerHTML = '';
    return;
  }
  fileListEl.innerHTML = selectedFiles.map((f, i) =>
    `<div><span>${f.name}</span><a href="#" class="remove-btn" onclick="event.preventDefault();removeFile(${i})">remove</a></div>`
  ).join('');
}

// Week date inputs: reload preview on change
document.getElementById('radio-week')?.addEventListener('change', () => {
  const mode = document.querySelector('input[name="radio-batch-mode"]:checked').value;
  if (mode === 'week') loadBatchPreview('week', 'radio-week', 'radio-batch-preview');
});
document.getElementById('press-week')?.addEventListener('change', () => {
  const mode = document.querySelector('input[name="press-mode"]:checked').value;
  if (mode === 'week') loadBatchPreview('week', 'press-week', 'press-batch-preview');
});
document.getElementById('dsp-week')?.addEventListener('change', () => {
  const mode = document.querySelector('input[name="dsp-mode"]:checked').value;
  if (mode === 'week') loadBatchPreview('week', 'dsp-week', 'dsp-batch-preview');
});

// Initial disabled state for mode-dependent buttons (default = artist mode, empty input)
if (document.getElementById('press-btn')) document.getElementById('press-btn').disabled = true;
if (document.getElementById('dsp-btn')) document.getElementById('dsp-btn').disabled = true;

// Radio, Press & DSP artist input gating (mode-dependent)
document.getElementById('radio-artist')?.addEventListener('input', () => {
  const mode = document.querySelector('input[name="radio-batch-mode"]:checked').value;
  if (mode === 'artist') document.getElementById('radio-fetch-btn').disabled = !document.getElementById('radio-artist').value.trim();
});
document.getElementById('press-artist')?.addEventListener('input', () => {
  const mode = document.querySelector('input[name="press-mode"]:checked').value;
  if (mode === 'artist') document.getElementById('press-btn').disabled = !document.getElementById('press-artist').value.trim();
});
document.getElementById('dsp-artist')?.addEventListener('input', () => {
  const mode = document.querySelector('input[name="dsp-mode"]:checked').value;
  if (mode === 'artist') document.getElementById('dsp-btn').disabled = !document.getElementById('dsp-artist').value.trim();
});

// =====================================================================
// DSP conditional fields
// =====================================================================
function dspModeChanged() {
  const mode = document.querySelector('input[name="dsp-mode"]:checked').value;
  const isArtist = mode === 'artist';
  document.getElementById('dsp-artist-field').classList.toggle('visible', isArtist);
  document.getElementById('dsp-week-field').classList.toggle('visible', mode === 'week');
  document.getElementById('dsp-auto-append-field').classList.toggle('visible', !isArtist);
  const btn = document.getElementById('dsp-btn');
  btn.textContent = isArtist ? 'Check Playlists' : 'Run Batch Playlist Check';
  btn.disabled = isArtist && !document.getElementById('dsp-artist').value.trim();
  loadBatchPreview(mode, 'dsp-week', 'dsp-batch-preview');
}

// =====================================================================
// Log colorization
// =====================================================================
function colorizeLog(text) {
  return text
    .replace(/✓ MATCH:.*/g, m => `<span style="color:#4ade80">${escapeHtml(m)}</span>`)
    .replace(/Error .*/g, m => `<span style="color:#f87171">${escapeHtml(m)}</span>`)
    .replace(/→ (\d+) tracks loaded/g, (m, n) => `<span style="color:#6b7280">→ ${n} tracks loaded</span>`)
    .replace(/→ (\d+) tracks \(cached\)/g, (m, n) => `<span style="color:#6b7280">→ ${n} tracks (cached)</span>`)
    .replace(/\[Spotify\]/g, '<span style="color:var(--spotify)">[Spotify]</span>')
    .replace(/\[Deezer\]/g, '<span style="color:var(--deezer)">[Deezer]</span>')
    .replace(/\[Apple Music\]/g, '<span style="color:var(--apple)">[Apple Music]</span>');
}

// =====================================================================
// Progress Stepper
// =====================================================================
const STEP_CONFIGS = {
  press: [
    { label: 'Scanning RSS feeds', pattern: /Scanning outlet feeds/ },
    { label: 'Mining sitemaps', pattern: /Mining outlet sitemaps/ },
    { label: 'Scanning outlet adapters', pattern: /Scanning outlet adapters/ },
    { label: 'Google News', pattern: /Google News/ },
    { label: 'Web Search', pattern: /Web Search( News)?:/ },
    { label: 'Serper Search', pattern: /Serper targeted/ },
    { label: 'Tavily + DuckDuckGo', pattern: /Tavily|DuckDuckGo/ },
    { label: 'AI relevance filter', pattern: /AI relevance filter/ },
  ],
  radio: [
    { label: 'Connecting to Soundcharts', pattern: /Searching Soundcharts/ },
    { label: 'Fetching airplay data', pattern: /Fetching airplay/ },
    { label: 'Generating report', pattern: /Generating|report saved/ },
  ],
  dsp: [
    { label: 'Loading playlists', pattern: /Playlists to check/ },
    { label: 'Checking Spotify', pattern: /Checking:.*\[?Spotify/ },
    { label: 'Checking Deezer', pattern: /Checking:.*Deezer/ },
    { label: 'Checking Apple Music', pattern: /Checking:.*Apple/ },
    { label: 'Checking Amazon Music', pattern: /Checking:.*Amazon/ },
    { label: 'Checking Claro Música', pattern: /Checking:.*Claro/ },
    { label: 'Checking YouTube Music', pattern: /Checking:.*YouTube/ },
    { label: 'Generating report', pattern: /DSP report saved|Generating proof/ },
  ],
  report: [
    { label: 'Loading releases', pattern: /Loading release schedule/ },
    { label: 'Running Radio Report', pattern: /── Radio Report/ },
    { label: 'Running Press Pickup', pattern: /── Press Pickup/ },
    { label: 'Running DSP Pickup', pattern: /── DSP Pickup/ },
    { label: 'Compiling report', pattern: /Compiling|report saved/ },
  ],
  digest: [
    { label: 'Fetching radio data', pattern: /Radio Report|Soundcharts/ },
    { label: 'Running press search', pattern: /Press Pickup|Searching press/ },
    { label: 'Checking playlists', pattern: /DSP Pickup|Playlists to check/ },
    { label: 'AI campaign analysis', pattern: /campaign analysis|Groq/ },
    { label: 'Generating digest', pattern: /Generating digest|digest saved/ },
  ],
};

function createStepper(progressEl, toolName) {
  const config = STEP_CONFIGS[toolName];
  if (!config) return null;
  // Remove old stepper if any
  const old = progressEl.querySelector('.progress-stepper');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = 'progress-stepper';
  config.forEach((step, i) => {
    const row = document.createElement('div');
    row.className = 'step-row';
    row.innerHTML = `<span class="step-icon">○</span><span class="step-label">${step.label}</span><span class="step-detail"></span>`;
    el.appendChild(row);
  });
  // Insert before log-box
  const logBox = progressEl.querySelector('.log-box');
  if (logBox) progressEl.insertBefore(el, logBox);
  else progressEl.appendChild(el);
  return { el, config, currentStep: -1 };
}

function updateStepper(stepper, logLines) {
  if (!stepper) return;
  const { el, config } = stepper;
  const fullLog = logLines.join('\n');
  let lastMatch = -1;
  const details = {};
  config.forEach((step, i) => {
    if (step.pattern.test(fullLog)) {
      lastMatch = i;
      // Extract counts from log for this step
      const countMatch = fullLog.match(new RegExp(step.pattern.source + '.*?(\\d+)\\s*(article|result|track|playlist|station|entries|placement)'));
      if (countMatch) details[i] = countMatch[1] + ' ' + countMatch[2] + 's';
    }
  });
  const rows = el.querySelectorAll('.step-row');
  rows.forEach((row, i) => {
    const icon = row.querySelector('.step-icon');
    const detail = row.querySelector('.step-detail');
    row.classList.remove('done', 'active');
    if (i < lastMatch) {
      row.classList.add('done');
      icon.textContent = '✓';
    } else if (i === lastMatch) {
      row.classList.add('active');
      icon.textContent = '●';
    } else {
      icon.textContent = '○';
    }
    if (details[i]) detail.textContent = details[i];
  });
  stepper.currentStep = lastMatch;
}

// =====================================================================
// Polling helper
// =====================================================================
function pollJob(jobId, logEl, progressEl, resultEl, toolName, onDone) {
  if (typeof toolName === 'function') { onDone = toolName; toolName = null; }
  progressEl.classList.add('visible');
  resultEl.classList.remove('visible');
  resultEl.innerHTML = '';
  const stepper = createStepper(progressEl, toolName);
  let settled = false;
  const startTime = Date.now();
  let hintShown = false;
  let networkErrors = 0;
  const MAX_NETWORK_ERRORS = 10;
  const TIMEOUT_HINT_MS = 180000; // 3 minutes
  // Incremental log: accumulate lines client-side, only fetch new ones
  let logLines = [];
  let logOffset = 0;
  // Adaptive polling: start fast (500ms), ramp to 3s over 30s
  const POLL_MIN_MS = 500;
  const POLL_MAX_MS = 3000;
  const POLL_RAMP_MS = 30000; // reach max after 30s

  function getInterval() {
    const elapsed = Date.now() - startTime;
    if (elapsed >= POLL_RAMP_MS) return POLL_MAX_MS;
    return POLL_MIN_MS + (POLL_MAX_MS - POLL_MIN_MS) * (elapsed / POLL_RAMP_MS);
  }

  async function tick() {
    if (settled) return;

    // Show timeout hint after 3 minutes
    if (!hintShown && Date.now() - startTime > TIMEOUT_HINT_MS) {
      hintShown = true;
      const hint = document.createElement('div');
      hint.className = 'timeout-hint';
      hint.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> This is taking longer than usual. You can keep waiting or try again.`;
      progressEl.appendChild(hint);
    }

    try {
      const resp = await fetch('/api/status/' + jobId + '?log_offset=' + logOffset);
      if (resp.status === 401) {
        if (settled) return;
        settled = true;
        progressEl.classList.remove('visible');
        onDone({ status: 'error', error: 'Your login session expired or was replaced. Please sign in again and retry.' });
        return;
      }
      const data = await resp.json();
      networkErrors = 0; // reset on success

      // Append incremental log lines
      if (data.log && data.log.length > 0) {
        logLines = logLines.concat(data.log);
      }
      if (data.log_offset !== undefined) logOffset = data.log_offset;

      // Update stepper from full accumulated log
      if (stepper) updateStepper(stepper, logLines);

      // Update log display with colorization
      const rawLog = logLines.map(l => escapeHtml(l)).join('\n');
      logEl.innerHTML = colorizeLog(rawLog);
      logEl.scrollTop = logEl.scrollHeight;

      if (data.status === 'done' || data.status === 'error') {
        if (settled) return;
        settled = true;
        // Mark all steps done on success
        if (stepper && data.status === 'done') {
          stepper.el.querySelectorAll('.step-row').forEach(r => {
            r.classList.remove('active');
            r.classList.add('done');
            r.querySelector('.step-icon').textContent = '✓';
          });
        }
        progressEl.classList.remove('visible');
        onDone(data);
        return;
      }
    } catch (e) {
      networkErrors++;
      if (networkErrors >= MAX_NETWORK_ERRORS) {
        if (settled) return;
        settled = true;
        progressEl.classList.remove('visible');
        onDone({ status: 'error', error: 'Lost connection to server.' });
        return;
      }
      // Otherwise silently retry
    }
    // Schedule next poll with adaptive interval
    setTimeout(tick, getInterval());
  }

  // Start polling
  setTimeout(tick, POLL_MIN_MS);
}

function setLoading(btn, loading) {
  if (loading) {
    btn.disabled = true;
    btn._origText = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> Running...';
  } else {
    btn.disabled = false;
    btn.textContent = btn._origText || btn.textContent;
  }
}

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

const checkSvg = '<svg viewBox="0 0 12 12" fill="none" stroke="white" stroke-width="2"><path d="M2 6l3 3 5-5"/></svg>';
const errorSvg = '<svg viewBox="0 0 12 12" fill="none" stroke="white" stroke-width="2"><path d="M3 3l6 6M9 3l-6 6"/></svg>';
const warnSvg = '<svg viewBox="0 0 12 12" fill="none" stroke="white" stroke-width="2"><path d="M6 3v4M6 9v0"/></svg>';

function showError(resultEl, message) {
  resultEl.classList.add('visible');
  resultEl.innerHTML = `<div class="result-error"><span class="error-icon">${errorSvg}</span><span>${escapeHtml(message)}</span></div>`;
}

function showWarning(containerEl, message) {
  containerEl.insertAdjacentHTML('beforeend',
    `<div class="result-warning"><span class="warning-icon">${warnSvg}</span><span>${escapeHtml(message)}</span></div>`);
}

// =====================================================================
// Input Validation Helpers (Phase 1.4)
// =====================================================================
function validateArtist(value) {
  // Strip quotes and extra whitespace
  const cleaned = value.replace(/^["']+|["']+$/g, '').trim();
  if (!cleaned) return { error: 'Please enter an artist name.' };
  if (cleaned.length < 2) return { error: 'Artist name must be at least 2 characters.' };
  if (cleaned.length > 100) return { error: 'Artist name must be under 100 characters.' };
  return { value: cleaned };
}

function validateDateRange(startDate, endDate, label) {
  const prefix = label ? label + ': ' : '';
  if (!startDate || !endDate) return { error: `${prefix}Please select both From and To dates.` };
  if (startDate > endDate) return { error: `${prefix}From date must be before To date.` };
  const today = new Date().toISOString().split('T')[0];
  if (startDate > today) return { error: `${prefix}Start date cannot be in the future.` };
  const oneYearAgo = new Date();
  oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
  const minDate = oneYearAgo.toISOString().split('T')[0];
  if (startDate < minDate) return { error: `${prefix}Start date cannot be more than 1 year ago.` };
  return { start: startDate, end: endDate };
}

function validateCron(expr) {
  if (!expr || !expr.trim()) return { error: 'Please enter a cron expression.' };
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return { error: 'Cron expression must have 5 fields: minute hour day-of-month month day-of-week' };
  const ranges = [
    { name: 'minute', min: 0, max: 59 },
    { name: 'hour', min: 0, max: 23 },
    { name: 'day', min: 1, max: 31 },
    { name: 'month', min: 1, max: 12 },
    { name: 'weekday', min: 0, max: 7 },
  ];
  for (let i = 0; i < 5; i++) {
    const part = parts[i];
    if (part === '*') continue;
    // */N step syntax
    if (/^\*\/\d+$/.test(part)) {
      const step = parseInt(part.split('/')[1]);
      if (step < 1 || step > ranges[i].max) return { error: `Invalid step "/${step}" for ${ranges[i].name}.` };
      continue;
    }
    // N-M range, N-M/S
    if (/^\d+-\d+(\/\d+)?$/.test(part)) continue;
    // Comma-separated values
    const vals = part.split(',');
    for (const v of vals) {
      if (!/^\d+$/.test(v)) return { error: `Invalid value "${v}" in ${ranges[i].name} field.` };
      const n = parseInt(v);
      if (n < ranges[i].min || n > ranges[i].max) return { error: `${ranges[i].name} value ${n} out of range (${ranges[i].min}-${ranges[i].max}).` };
    }
  }
  return { value: expr.trim() };
}

function cronNextRuns(expr, count) {
  // Simple next-run estimator for common presets and basic crons
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return [];
  const [minP, hourP, domP, monP, dowP] = parts;
  const runs = [];
  const now = new Date();
  const d = new Date(now);
  d.setSeconds(0); d.setMilliseconds(0);

  // Only handle simple cases: fixed min/hour with * or fixed dow/dom
  const min = minP === '*' ? null : parseInt(minP);
  const hour = hourP === '*' ? null : parseInt(hourP);
  const dow = dowP === '*' ? null : parseInt(dowP);

  if (min === null && hour === null) return []; // too complex
  for (let attempt = 0; attempt < 1440 * 14 && runs.length < count; attempt++) {
    d.setMinutes(d.getMinutes() + 1);
    if (min !== null && d.getMinutes() !== min) continue;
    if (hour !== null && d.getHours() !== hour) continue;
    if (dow !== null && d.getDay() !== (dow % 7)) continue;
    if (domP !== '*' && d.getDate() !== parseInt(domP)) continue;
    if (monP !== '*' && (d.getMonth() + 1) !== parseInt(monP)) continue;
    runs.push(new Date(d));
  }
  return runs;
}

const MAX_UPLOAD_MB = 20;

// Submit button gating — disable until required fields have content
function guardSubmit(inputId, btnId) {
  const input = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  if (!input || !btn) return;
  const update = () => { btn.disabled = !input.value.trim(); };
  input.addEventListener('input', update);
  update(); // initial state
}

// Wire up artist-name guards (single-artist modes)
guardSubmit('radio-artist', 'radio-fetch-btn');
guardSubmit('report-artist', 'report-btn');
guardSubmit('proposal-artist', 'proposal-btn');
guardSubmit('digest-artist', 'digest-btn');
// Press & DSP have mode toggling — handled via their mode-change functions

// =====================================================================
// Radio Report
// =====================================================================
let radioFetchJobId = null;

async function runRadio() {
  const batchMode = document.querySelector('input[name="radio-batch-mode"]:checked').value;

  // Batch mode: week or all
  if (batchMode !== 'artist') {
    return runRadioBatch(batchMode);
  }

  const mode = document.querySelector('input[name="radio-mode"]:checked').value;
  if (mode === 'soundcharts') {
    return fetchRadioSongs();
  } else {
    const btn = document.getElementById('radio-fetch-btn');
    const logEl = document.getElementById('radio-log');
    const progressEl = document.getElementById('radio-progress');
    const resultEl = document.getElementById('radio-result');
    return runRadioCsv(btn, logEl, progressEl, resultEl);
  }
}

async function runRadioBatch(batchMode) {
  const btn = document.getElementById('radio-fetch-btn');
  const logEl = document.getElementById('radio-log');
  const progressEl = document.getElementById('radio-progress');
  const resultEl = document.getElementById('radio-result');

  const region = document.querySelector('input[name="radio-region"]:checked').value;
  const timeRange = document.querySelector('input[name="radio-range"]:checked').value;
  const week = document.getElementById('radio-week').value || 'current';

  // Get selected artists from preview element
  const previewEl = document.getElementById('radio-batch-preview');
  const artists = previewEl._selectedArtists ? Array.from(previewEl._selectedArtists) : [];
  if (batchMode !== 'artist' && artists.length === 0) return showToast('Please select at least one artist.');

  const autoAppend = document.getElementById('radio-auto-append').checked;
  const body = { mode: batchMode, week, region, time_range: timeRange, artists, auto_append: autoAppend };
  if (timeRange === 'custom') {
    body.start_date = document.getElementById('radio-start-date').value;
    body.end_date = document.getElementById('radio-end-date').value;
    if (!body.start_date || !body.end_date) return showToast('Please select both start and end dates.');
  }

  setLoading(btn, true);
  logEl.textContent = '';
  resultEl.classList.remove('visible');
  resultEl.innerHTML = '';
  document.getElementById('radio-song-picker').style.display = 'none';
  document.getElementById('radio-generate-btn').style.display = 'none';

  try {
    const resp = await fetch('/api/radio/soundcharts/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    const runId = data.batch_id || data.job_id;
    if (!runId) {
      setLoading(btn, false);
      showError(resultEl, 'Batch job started but no job ID was returned.');
      return;
    }

    pollJob(runId, logEl, progressEl, resultEl, 'radio', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>${escapeHtml(result.result)}</strong></div>`;
        html += renderAppendSummary(result.append_results, runId);
        html += `<div class="result-actions">`;
        if (result.has_batch_combined_docx) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/combined" download>Download Combined .docx</a>`;
        }
        if (result.has_batch_zip) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/zip" download>Download Individual (.zip)</a>`;
        }
        html += `</div>`;
        resultEl.innerHTML = html;
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

function renderAppendSummary(appendResults, batchId) {
  if (!appendResults || Object.keys(appendResults).length === 0) return '';

  const appended = [];
  const skipped = [];
  const noDoc = [];
  const errors = [];
  const total = Object.keys(appendResults).length;

  for (const [artist, ar] of Object.entries(appendResults)) {
    if (ar.status === 'appended') appended.push({ artist, doc_title: ar.doc_title });
    else if (ar.status === 'skipped') skipped.push({ artist, detail: ar.detail });
    else if (ar.status === 'no_doc') noDoc.push({ artist });
    else errors.push({ artist, detail: ar.detail });
  }

  const needsAttention = noDoc.length + errors.length;
  let html = '<div class="append-summary" style="margin:16px 0; padding:16px; background:var(--bg-secondary); border-radius:var(--radius-xs); font-size:13px;">';
  html += `<strong style="font-size:14px;">Google Docs Summary</strong> <span style="color:var(--text-tertiary);font-size:12px;">${total} artists</span>`;

  if (appended.length) {
    html += '<div style="margin-top:10px;"><div style="color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Updated</div>';
    for (const a of appended) {
      html += `<div style="color:#4ade80; margin:2px 0;">\u2713 ${escapeHtml(a.artist)} \u2014 appended to "${escapeHtml(a.doc_title)}"</div>`;
    }
    html += '</div>';
  }
  if (skipped.length) {
    html += '<div style="margin-top:10px;"><div style="color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Skipped</div>';
    for (const a of skipped) {
      html += `<div style="color:var(--text-tertiary); margin:2px 0;">\u26a0 ${escapeHtml(a.artist)} \u2014 ${escapeHtml(a.detail)}</div>`;
    }
    html += '</div>';
  }
  if (needsAttention) {
    html += '<div style="margin-top:10px;"><div style="color:var(--text-secondary);font-size:11px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Needs Attention</div>';
    for (const a of noDoc) {
      const safeArtist = escapeAttr(a.artist);
      const elId = `batch-link-${CSS.escape(a.artist)}`;
      html += `<div style="margin:4px 0;" id="${elId}">`;
      html += `<span style="color:var(--text-secondary);">\u2014 ${escapeHtml(a.artist)} \u2014 no Google Doc linked</span> `;
      html += `<button class="btn btn-small btn-secondary" onclick="showBatchLinkInput('${safeArtist}','${batchId || ''}')" style="font-size:11px;padding:2px 8px;">Link Doc</button>`;
      html += '</div>';
    }
    for (const a of errors) {
      const safeArtist = escapeAttr(a.artist);
      html += `<div style="margin:4px 0;" id="batch-link-${CSS.escape(a.artist)}">`;
      html += `<span style="color:#f87171;">\u2717 ${escapeHtml(a.artist)} \u2014 ${escapeHtml(a.detail)}</span> `;
      if (batchId) {
        html += `<button class="btn btn-small btn-secondary" onclick="retryBatchAppend('${safeArtist}','${batchId}')" style="font-size:11px;padding:2px 8px;">Retry</button> `;
      }
      html += '</div>';
    }
    html += '</div>';
  }

  html += '</div>';
  return html;
}

function showBatchLinkInput(artistName, batchId) {
  const el = document.getElementById(`batch-link-${CSS.escape(artistName)}`);
  if (!el) return;
  el.innerHTML = `
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
      <span style="color:var(--text-secondary);font-size:12px;">${escapeHtml(artistName)}:</span>
      <input type="text" id="batch-url-${CSS.escape(artistName)}" placeholder="Paste Google Doc URL"
        style="flex:1;min-width:200px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:12px;background:var(--bg-primary);color:var(--text-primary);">
      <button class="btn btn-small" onclick="batchLinkAndAppend('${escapeAttr(artistName)}','${batchId}')" style="font-size:11px;padding:2px 8px;">Link & Append</button>
    </div>`;
  const input = document.getElementById(`batch-url-${CSS.escape(artistName)}`);
  if (input) input.focus();
}

async function batchLinkAndAppend(artistName, batchId) {
  const input = document.getElementById(`batch-url-${CSS.escape(artistName)}`);
  const el = document.getElementById(`batch-link-${CSS.escape(artistName)}`);
  if (!input || !el) return;

  const url = input.value.trim();
  if (!url) return showToast('Please paste a Google Doc URL.');
  if (!url.includes('docs.google.com/document/d/')) return showToast('Invalid Google Doc URL.');

  el.innerHTML = `<span style="color:var(--text-secondary);">Linking & scanning ${escapeHtml(artistName)}...</span>`;

  try {
    // 1. Link the doc
    const linkResp = await fetch('/api/settings/google/docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist_name: artistName, doc_url: url }),
    });
    const linkData = await linkResp.json();
    if (!linkData.ok) {
      el.innerHTML = `<span style="color:#f87171;">\u2717 ${escapeHtml(artistName)} \u2014 ${escapeHtml(linkData.error || 'Link failed')}</span>`;
      return;
    }

    // 2. Auto-scan insertion point
    try {
      const scanResp = await fetch(`/api/google/scan-insertion/${encodeURIComponent(artistName)}`, { method: 'POST' });
      const scanData = await scanResp.json();
      if (scanData.found) {
        await fetch(`/api/google/confirm-insertion/${encodeURIComponent(artistName)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: scanData.index }),
        });
      }
    } catch { /* scan is optional */ }

    // 3. Retry append if batch data available
    if (batchId) {
      el.innerHTML = `<span style="color:var(--text-secondary);">Appending to "${escapeHtml(linkData.doc_title)}"...</span>`;
      const retryResp = await fetch(`/api/google/retry-append/${encodeURIComponent(artistName)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batchId }),
      });
      const retryData = await retryResp.json();
      if (retryData.status === 'appended') {
        el.innerHTML = `<span style="color:#4ade80;">\u2713 ${escapeHtml(artistName)} \u2014 linked & appended to "${escapeHtml(linkData.doc_title)}"</span>`;
      } else {
        el.innerHTML = `<span style="color:#4ade80;">\u2713 ${escapeHtml(artistName)} \u2014 linked to "${escapeHtml(linkData.doc_title)}"</span> <span style="color:var(--text-tertiary);">(append: ${escapeHtml(retryData.detail || retryData.error || 'no data')})</span>`;
      }
    } else {
      el.innerHTML = `<span style="color:#4ade80;">\u2713 ${escapeHtml(artistName)} \u2014 linked to "${escapeHtml(linkData.doc_title)}"</span>`;
    }

    refreshGoogleSettings();
  } catch (e) {
    el.innerHTML = `<span style="color:#f87171;">\u2717 ${escapeHtml(artistName)} \u2014 ${escapeHtml(e.message)}</span>`;
  }
}

async function retryBatchAppend(artistName, batchId) {
  const el = document.getElementById(`batch-link-${CSS.escape(artistName)}`);
  if (!el) return;

  el.innerHTML = `<span style="color:var(--text-secondary);">Retrying ${escapeHtml(artistName)}...</span>`;

  try {
    const resp = await fetch(`/api/google/retry-append/${encodeURIComponent(artistName)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: batchId }),
    });
    const data = await resp.json();
    if (data.status === 'appended') {
      el.innerHTML = `<span style="color:#4ade80;">\u2713 ${escapeHtml(artistName)} \u2014 appended to "${escapeHtml(data.doc_title)}"</span>`;
    } else if (data.error) {
      el.innerHTML = `<span style="color:#f87171;">\u2717 ${escapeHtml(artistName)} \u2014 ${escapeHtml(data.error)}</span> <button class="btn btn-small btn-secondary" onclick="retryBatchAppend('${escapeAttr(artistName)}','${batchId}')" style="font-size:11px;padding:2px 8px;">Retry</button>`;
    } else {
      el.innerHTML = `<span style="color:#f87171;">\u2717 ${escapeHtml(artistName)} \u2014 ${escapeHtml(data.detail || 'Failed')}</span>`;
    }
  } catch (e) {
    el.innerHTML = `<span style="color:#f87171;">\u2717 ${escapeHtml(artistName)} \u2014 ${escapeHtml(e.message)}</span>`;
  }
}

async function fetchRadioSongs() {
  const v = validateArtist(document.getElementById('radio-artist').value);
  if (v.error) return showToast(v.error);
  const artist = v.value;
  document.getElementById('radio-artist').value = artist;

  const btn = document.getElementById('radio-fetch-btn');
  const logEl = document.getElementById('radio-log');
  const progressEl = document.getElementById('radio-progress');
  const resultEl = document.getElementById('radio-result');

  // Reset UI
  document.getElementById('radio-song-picker').style.display = 'none';
  document.getElementById('radio-generate-btn').style.display = 'none';
  resultEl.classList.remove('visible');
  resultEl.innerHTML = '';
  radioFetchJobId = null;

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const timeRange = document.querySelector('input[name="radio-range"]:checked').value;
    const fetchBody = { artist, region: document.querySelector('input[name="radio-region"]:checked').value, time_range: timeRange };
    if (timeRange === 'custom') {
      fetchBody.start_date = document.getElementById('radio-start-date').value;
      fetchBody.end_date = document.getElementById('radio-end-date').value;
      const dv = validateDateRange(fetchBody.start_date, fetchBody.end_date, 'Radio');
      if (dv.error) {
        setLoading(btn, false);
        return showToast(dv.error);
      }
    }
    const resp = await fetch('/api/radio/soundcharts/fetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fetchBody),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, 'radio', (result) => {
      setLoading(btn, false);
      if (result.status === 'error') {
          showError(resultEl, result.error);
      } else {
        radioFetchJobId = data.job_id;
        renderSongPicker(result.result.songs, result.result.range_label, result.result.is_custom);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

function renderSongPicker(songs, rangeLabel, isCustom) {
  rangeLabel = rangeLabel || '28D';
  const refNote = isCustom ? ' (28D reference)' : '';
  const listEl = document.getElementById('radio-song-list');
  listEl.innerHTML = songs.map((s, i) => `
    <label class="song-row">
      <input type="checkbox" checked value="${escapeAttr(s.song)}" class="radio-song-cb">
      <span class="song-name">${escapeHtml(s.song)}</span>
      <span class="song-stats">${s.total_plays.toLocaleString()} plays (${rangeLabel})${refNote} &middot; ${s.station_count} station${s.station_count !== 1 ? 's' : ''}</span>
    </label>
  `).join('');
  document.getElementById('radio-song-picker').style.display = 'block';
  document.getElementById('radio-generate-btn').style.display = '';
  document.getElementById('radio-toggle-all').textContent = 'Deselect All';
  document.getElementById('radio-song-filter').value = '';
}

function toggleAllSongs() {
  const boxes = document.querySelectorAll('.radio-song-cb');
  const allChecked = Array.from(boxes).every(cb => cb.checked);
  boxes.forEach(cb => cb.checked = !allChecked);
  document.getElementById('radio-toggle-all').textContent = allChecked ? 'Select All' : 'Deselect All';
}

function filterSongs() {
  const q = document.getElementById('radio-song-filter').value.toLowerCase();
  document.querySelectorAll('#radio-song-list .song-row').forEach(row => {
    const name = row.querySelector('.song-name').textContent.toLowerCase();
    row.style.display = name.includes(q) ? '' : 'none';
  });
}

async function generateRadioReport() {
  const selected = Array.from(document.querySelectorAll('.radio-song-cb:checked')).map(cb => cb.value);
  if (!selected.length) return showToast('Please select at least one song.');
  if (!radioFetchJobId) return showToast('Please fetch songs first.');

  const artist = document.getElementById('radio-artist').value.trim();
  const btn = document.getElementById('radio-generate-btn');
  const logEl = document.getElementById('radio-generate-log');
  const progressEl = document.getElementById('radio-generate-progress');
  const resultEl = document.getElementById('radio-result');

  resultEl.classList.remove('visible');
  resultEl.innerHTML = '';

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const timeRange = document.querySelector('input[name="radio-range"]:checked').value;
    const genBody = { fetch_job_id: radioFetchJobId, artist, selected_songs: selected, time_range: timeRange };
    if (timeRange === 'custom') {
      genBody.start_date = document.getElementById('radio-start-date').value;
      genBody.end_date = document.getElementById('radio-end-date').value;
    }
    const resp = await fetch('/api/radio/soundcharts/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(genBody),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    const runId = data.batch_id || data.job_id;
    if (!runId) {
      setLoading(btn, false);
      showError(resultEl, 'Radio report job started but no job ID was returned.');
      return;
    }

    pollJob(runId, logEl, progressEl, resultEl, 'radio', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        resultEl.innerHTML = `
          <div class="result-success">
            <span class="check-icon">${checkSvg}</span>
            <strong>Report generated successfully!</strong>
          </div>
          <div class="result-actions">
            <a class="btn btn-small" href="/api/download/${runId}" download>Download Word Document</a>
          </div>`;
        if (artist) appendGoogleDocSectionToResults(resultEl, artist, runId);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

async function runRadioCsv(btn, logEl, progressEl, resultEl) {
  const artist = document.getElementById('radio-artist-csv').value.trim();
  if (!artist) return showToast('Please enter an artist name.');
  if (!selectedFiles.length) return showToast('Please upload at least one CSV file.');

  setLoading(btn, true);
  logEl.textContent = '';

  const fd = new FormData();
  fd.append('artist', artist);
  selectedFiles.forEach(f => fd.append('csvfiles', f));

  try {
    const resp = await fetch('/api/radio/run', { method: 'POST', body: fd });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    const runId = data.batch_id || data.job_id;
    if (!runId) {
      setLoading(btn, false);
      showError(resultEl, 'Radio CSV job started but no job ID was returned.');
      return;
    }

    pollJob(runId, logEl, progressEl, resultEl, 'radio', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        resultEl.innerHTML = `
          <div class="result-success">
            <span class="check-icon">${checkSvg}</span>
            <strong>Report generated successfully!</strong>
          </div>
          <div class="result-actions">
            <a class="btn btn-small" href="/api/download/${runId}" download>Download Word Document</a>
          </div>`;
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

// =====================================================================
// Press Pickup
// =====================================================================
function togglePressCustomDates() {
  const sel = document.querySelector('input[name="press-days"]:checked').value;
  const wrap = document.getElementById('press-custom-dates');
  wrap.style.display = sel === 'custom' ? '' : 'none';
  if (sel === 'custom') {
    const toEl = document.getElementById('press-date-to');
    const fromEl = document.getElementById('press-date-from');
    if (!toEl.value) toEl.value = new Date().toISOString().slice(0, 10);
    if (!fromEl.value) {
      const d = new Date(); d.setDate(d.getDate() - 28);
      fromEl.value = d.toISOString().slice(0, 10);
    }
  }
}

async function runPress() {
  const batchMode = document.querySelector('input[name="press-mode"]:checked').value;
  const days = document.querySelector('input[name="press-days"]:checked').value;
  const btn = document.getElementById('press-btn');
  const logEl = document.getElementById('press-log');
  const progressEl = document.getElementById('press-progress');
  const resultEl = document.getElementById('press-result');

  let body = {};

  // Get selected artists from preview element if in batch mode
  const previewEl = document.getElementById('press-batch-preview');
  const artists = previewEl._selectedArtists ? Array.from(previewEl._selectedArtists) : [];
  if (batchMode !== 'artist' && artists.length === 0) return showToast('Please select at least one artist.');

  // Date params (shared by both single and batch)
  if (days === 'custom') {
    const startDate = document.getElementById('press-date-from').value;
    const endDate = document.getElementById('press-date-to').value;
    const dv = validateDateRange(startDate, endDate, 'Press');
    if (dv.error) return showToast(dv.error);
    body.start_date = startDate;
    body.end_date = endDate;
  } else {
    body.days = parseInt(days);
  }

  if (batchMode === 'artist') {
    const v = validateArtist(document.getElementById('press-artist').value);
    if (v.error) return showToast(v.error);
    document.getElementById('press-artist').value = v.value;
    body.mode = 'artist';
    body.artist = v.value;
  } else {
    body.mode = batchMode;
    body.week = document.getElementById('press-week').value || 'current';
    body.artists = artists;
    body.auto_append = document.getElementById('press-auto-append').checked;
  }

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const resp = await fetch('/api/press/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    const runId = data.batch_id || data.job_id;
    if (!runId) {
      setLoading(btn, false);
      showError(resultEl, 'Press job started but no job ID was returned.');
      return;
    }

    pollJob(runId, logEl, progressEl, resultEl, 'press', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        const isBatch = batchMode !== 'artist';
        let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>${isBatch ? 'Batch press search complete!' : 'Press search complete!'}</strong></div>`;
        if (isBatch) html += renderAppendSummary(result.append_results, runId);
        if (result.result) {
          html += `<div class="result-report">${formatPressReport(escapeHtml(result.result))}</div>`;
        }
        html += `<div class="result-actions">`;
        if (isBatch && result.has_batch_combined_docx) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/combined" download>Download Combined .docx</a>`;
        }
        if (isBatch && result.has_batch_zip) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/zip" download>Download Individual (.zip)</a>`;
        }
        if (!isBatch && result.has_file) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/docx" download>Download .docx</a>`;
        }
        if (result.has_file) {
          html += `<a class="btn btn-small" href="/api/download/${runId}" download>Download .txt</a>`;
        }
        if (result.result) {
          html += `<button class="btn btn-small btn-secondary" onclick="copyText(this)" data-text="${escapeAttr(result.result)}">Copy to Clipboard</button>`;
        }
        html += `</div>`;
        resultEl.innerHTML = html;
        if (!isBatch) {
          const artistVal = document.getElementById('press-artist').value.trim();
          if (artistVal) appendGoogleDocSectionToResults(resultEl, artistVal, runId);
        }
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

// =====================================================================
// DSP Pickup
// =====================================================================
async function runDsp() {
  const mode = document.querySelector('input[name="dsp-mode"]:checked').value;
  let artist = document.getElementById('dsp-artist').value.trim();
  const week = document.getElementById('dsp-week').value;
  const platforms = [...document.querySelectorAll('.dsp-platform:checked')].map(el => el.value);
  const grouping = document.querySelector('input[name="dsp-grouping"]:checked').value;

  if (mode === 'artist') {
    const v = validateArtist(artist);
    if (v.error) return showToast(v.error);
    artist = v.value;
    document.getElementById('dsp-artist').value = artist;
  }
  if (!platforms.length) return showToast('Please select at least one platform.');

  // In batch mode, get selected artists from preview
  let artists = [];
  if (mode !== 'artist') {
    const previewEl = document.getElementById('dsp-batch-preview');
    artists = previewEl._selectedArtists ? Array.from(previewEl._selectedArtists) : [];
    if (artists.length === 0) return showToast('Please select at least one artist.');
  }

  const btn = document.getElementById('dsp-btn');
  const logEl = document.getElementById('dsp-log');
  const progressEl = document.getElementById('dsp-progress');
  const resultEl = document.getElementById('dsp-result');

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const body = { mode, artist, week: week || 'current', platforms, grouping };
    if (mode !== 'artist') {
      body.artists = artists;
      body.auto_append = document.getElementById('dsp-auto-append').checked;
    }
    const resp = await fetch('/api/dsp/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, 'dsp', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        // Parse platform match counts from the report text
        const counts = parsePlatformCounts(result.result || '');

        let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Playlist check complete!</strong></div>`;

        // Platform badges
        if (counts) {
          html += `<div class="platform-summary">`;
          if (counts.spotify) html += `<span class="platform-badge spotify"><span class="dot"></span>${counts.spotify} Spotify</span>`;
          if (counts.deezer) html += `<span class="platform-badge deezer"><span class="dot"></span>${counts.deezer} Deezer</span>`;
          if (counts.apple) html += `<span class="platform-badge apple"><span class="dot"></span>${counts.apple} Apple Music</span>`;
          if (counts.amazon) html += `<span class="platform-badge amazon"><span class="dot"></span>${counts.amazon} Amazon</span>`;
          if (counts.claro) html += `<span class="platform-badge claro"><span class="dot"></span>${counts.claro} Claro</span>`;
          if (counts.ytmusic) html += `<span class="platform-badge ytmusic"><span class="dot"></span>${counts.ytmusic} YouTube</span>`;
          if (counts.other) html += `<span class="platform-badge other"><span class="dot"></span>${counts.other} Other</span>`;
          html += `</div>`;
        }

        if (result.result) {
          html += `<div class="result-report">${colorizeReport(escapeHtml(result.result))}</div>`;
        }

        // Show proof images if available
        const proofImages = result.proof_images || [];
        if (proofImages.length > 0) {
          html += `<div class="proof-gallery">`;
          html += `<div class="proof-gallery-header" style="display:flex; align-items:center; justify-content:space-between;">`;
          html += `<span><strong>Proof Images</strong> <span style="color:var(--text-tertiary)">(${proofImages.length})</span></span>`;
          html += `<button class="btn btn-small" onclick="toggleProofGrid(this)" style="font-size:12px;">Hide</button>`;
          html += `</div>`;
          html += `<div class="proof-grid">`;
          for (const img of proofImages) {
            html += `<a href="/api/proof/${encodeURIComponent(img)}" target="_blank" class="proof-card">`;
            html += `<img src="/api/proof/${encodeURIComponent(img)}" alt="Proof" loading="lazy">`;
            html += `</a>`;
          }
          html += `</div></div>`;
        }

        html += `<div class="result-actions">`;
        if (result.has_file) {
          html += `<a class="btn btn-small" href="/api/download/${data.job_id}/docx" download>Download DSP .docx</a>`;
          html += `<a class="btn btn-small" href="/api/download/${data.job_id}/txt" download>Download .txt</a>`;
          html += `<a class="btn btn-small" href="/api/download/${data.job_id}/json" download>Download .json</a>`;
        }
        if (proofImages.length > 0) {
          html += `<a class="btn btn-small" href="/api/proofs/zip" download>Download Proofs (.zip)</a>`;
        }
        if (result.result) {
          html += `<button class="btn btn-small btn-secondary" onclick="copyText(this)" data-text="${escapeAttr(result.result)}">Copy to Clipboard</button>`;
        }
        html += `</div>`;
        if (mode !== 'artist' && result.append_results) {
          html += renderAppendSummary(result.append_results, data.job_id);
        }
        resultEl.innerHTML = html;
        if (mode === 'artist' && artist) appendGoogleDocSectionToResults(resultEl, artist, data.job_id);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

// =====================================================================
// Report Compiler
// =====================================================================
function toggleReportRadioCustomDates() {
  const sel = document.querySelector('input[name="report-radio-range"]:checked').value;
  const wrap = document.getElementById('report-radio-custom-dates');
  wrap.style.display = sel === 'custom' ? '' : 'none';
  if (sel === 'custom') {
    const toEl = document.getElementById('report-radio-date-to');
    const fromEl = document.getElementById('report-radio-date-from');
    if (!toEl.value) toEl.value = new Date().toISOString().slice(0, 10);
    if (!fromEl.value) {
      const d = new Date(); d.setDate(d.getDate() - 28);
      fromEl.value = d.toISOString().slice(0, 10);
    }
  }
}

function toggleReportPressCustomDates() {
  const sel = document.querySelector('input[name="report-press-range"]:checked').value;
  const wrap = document.getElementById('report-press-custom-dates');
  wrap.style.display = sel === 'custom' ? '' : 'none';
  if (sel === 'custom') {
    const toEl = document.getElementById('report-press-date-to');
    const fromEl = document.getElementById('report-press-date-from');
    if (!toEl.value) toEl.value = new Date().toISOString().slice(0, 10);
    if (!fromEl.value) {
      const d = new Date(); d.setDate(d.getDate() - 28);
      fromEl.value = d.toISOString().slice(0, 10);
    }
  }
}

async function runReport() {
  const batchMode = document.querySelector('input[name="report-mode"]:checked').value;
  if (batchMode !== 'artist') return runReportBatch(batchMode);

  const resultEl = document.getElementById('report-result');
  const av = validateArtist(document.getElementById('report-artist').value);
  if (av.error) { showError(resultEl, av.error); return; }
  const artist = av.value;

  const radioRange = document.querySelector('input[name="report-radio-range"]:checked').value;
  const pressRange = document.querySelector('input[name="report-press-range"]:checked').value;
  const region = document.querySelector('input[name="report-region"]:checked').value;
  const includeRadio = document.getElementById('report-inc-radio').checked;
  const includeDsp = document.getElementById('report-inc-dsp').checked;
  const includePress = document.getElementById('report-inc-press').checked;
  const efforts = document.getElementById('report-efforts').value;

  if (!includeRadio && !includeDsp && !includePress) {
    return showToast('Please select at least one section to include.');
  }

  // Radio: custom date range validation
  let radioStartDate, radioEndDate;
  if (radioRange === 'custom') {
    radioStartDate = document.getElementById('report-radio-date-from').value;
    radioEndDate = document.getElementById('report-radio-date-to').value;
    const rv = validateDateRange(radioStartDate, radioEndDate, 'Radio');
    if (rv.error) { showError(resultEl, rv.error); return; }
  }

  // Press: custom date range or preset days
  let pressDays, pressStartDate, pressEndDate;
  if (pressRange === 'custom') {
    pressStartDate = document.getElementById('report-press-date-from').value;
    pressEndDate = document.getElementById('report-press-date-to').value;
    const pv = validateDateRange(pressStartDate, pressEndDate, 'Press');
    if (pv.error) { showError(resultEl, pv.error); return; }
    pressDays = 28; // fallback, backend will use dates
  } else {
    pressDays = parseInt(pressRange);
  }

  const btn = document.getElementById('report-btn');
  const logEl = document.getElementById('report-log');
  const progressEl = document.getElementById('report-progress');

  setLoading(btn, true);
  logEl.textContent = '';

  const body = {
    mode: 'artist',
    artist,
    press_days: pressDays,
    radio_region: region,
    radio_time_range: radioRange,
    efforts_text: efforts,
    include_radio: includeRadio,
    include_dsp: includeDsp,
    include_press: includePress,
  };
  if (pressStartDate) {
    body.press_start_date = pressStartDate;
    body.press_end_date = pressEndDate;
  }
  if (radioStartDate) {
    body.radio_start_date = radioStartDate;
    body.radio_end_date = radioEndDate;
  }

  try {
    const resp = await fetch('/api/report/compile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, 'report', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Full report compiled!</strong></div>`;

        // Show summary badges
        if (result.result) {
          html += `<div style="margin:12px 0 16px; font-size:14px; color:var(--text-secondary); line-height:1.8;">${escapeHtml(result.result)}</div>`;
        }

        // Show proof images if DSP was included
        const proofImages = result.proof_images || [];
        if (proofImages.length > 0) {
          html += `<div class="proof-gallery">`;
          html += `<div class="proof-gallery-header" style="display:flex; align-items:center; justify-content:space-between;">`;
          html += `<span><strong>DSP Proof Images</strong> <span style="color:var(--text-tertiary)">(${proofImages.length})</span></span>`;
          html += `<button class="btn btn-small" onclick="toggleProofGrid(this)" style="font-size:12px;">Hide</button>`;
          html += `</div>`;
          html += `<div class="proof-grid">`;
          for (const img of proofImages) {
            html += `<a href="/api/proof/${encodeURIComponent(img)}" target="_blank" class="proof-card">`;
            html += `<img src="/api/proof/${encodeURIComponent(img)}" alt="Proof" loading="lazy">`;
            html += `</a>`;
          }
          html += `</div></div>`;
        }

        html += `<div class="result-actions">`;
        if (result.has_file) {
          html += `<a class="btn btn-small" href="/api/download/${data.job_id}" download>Download Full Report (.docx)</a>`;
        }
        if (proofImages.length > 0) {
          html += `<a class="btn btn-small" href="/api/proofs/zip" download>Download Proofs (.zip)</a>`;
        }
        html += `</div>`;
        resultEl.innerHTML = html;
        const reportArtist = document.getElementById('report-artist').value.trim();
        if (reportArtist) appendGoogleDocSectionToResults(resultEl, reportArtist, data.job_id);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

async function runReportBatch(batchMode) {
  const resultEl = document.getElementById('report-result');
  const btn = document.getElementById('report-btn');
  const logEl = document.getElementById('report-log');
  const progressEl = document.getElementById('report-progress');

  const previewEl = document.getElementById('report-batch-preview');
  const artists = previewEl._selectedArtists ? Array.from(previewEl._selectedArtists) : [];
  if (artists.length === 0) return showToast('Please select at least one artist.');

  const radioRange = document.querySelector('input[name="report-radio-range"]:checked').value;
  const pressRange = document.querySelector('input[name="report-press-range"]:checked').value;
  const region = document.querySelector('input[name="report-region"]:checked').value;
  const includeRadio = document.getElementById('report-inc-radio').checked;
  const includeDsp = document.getElementById('report-inc-dsp').checked;
  const includePress = document.getElementById('report-inc-press').checked;

  if (!includeRadio && !includeDsp && !includePress) {
    return showToast('Please select at least one section to include.');
  }

  // Radio: custom date range validation
  let radioStartDate, radioEndDate;
  if (radioRange === 'custom') {
    radioStartDate = document.getElementById('report-radio-date-from').value;
    radioEndDate = document.getElementById('report-radio-date-to').value;
    const rv = validateDateRange(radioStartDate, radioEndDate, 'Radio');
    if (rv.error) { showError(resultEl, rv.error); return; }
  }

  // Press: custom date range or preset days
  let pressDays, pressStartDate, pressEndDate;
  if (pressRange === 'custom') {
    pressStartDate = document.getElementById('report-press-date-from').value;
    pressEndDate = document.getElementById('report-press-date-to').value;
    const pv = validateDateRange(pressStartDate, pressEndDate, 'Press');
    if (pv.error) { showError(resultEl, pv.error); return; }
    pressDays = 28;
  } else {
    pressDays = parseInt(pressRange);
  }

  setLoading(btn, true);
  logEl.textContent = '';

  const body = {
    mode: batchMode,
    week: document.getElementById('report-week').value || 'current',
    artists,
    auto_append: document.getElementById('report-auto-append').checked,
    press_days: pressDays,
    radio_region: region,
    radio_time_range: radioRange,
    include_radio: includeRadio,
    include_dsp: includeDsp,
    include_press: includePress,
  };
  if (pressStartDate) {
    body.press_start_date = pressStartDate;
    body.press_end_date = pressEndDate;
  }
  if (radioStartDate) {
    body.radio_start_date = radioStartDate;
    body.radio_end_date = radioEndDate;
  }

  try {
    const resp = await fetch('/api/report/compile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    const runId = data.batch_id;
    if (!runId) {
      setLoading(btn, false);
      showError(resultEl, 'Batch job started but no job ID was returned.');
      return;
    }

    pollJob(runId, logEl, progressEl, resultEl, null, (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Batch full reports complete!</strong></div>`;
        if (result.result) {
          html += `<div style="margin:12px 0 16px; font-size:14px; color:var(--text-secondary); line-height:1.8;">${escapeHtml(result.result)}</div>`;
        }
        html += renderAppendSummary(result.append_results, runId);
        html += `<div class="result-actions">`;
        if (result.has_batch_combined_docx) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/combined" download>Download Combined .docx</a>`;
        }
        if (result.has_batch_zip) {
          html += `<a class="btn btn-small" href="/api/download/${runId}/zip" download>Download Individual (.zip)</a>`;
        }
        html += `</div>`;
        resultEl.innerHTML = html;
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

// =====================================================================
// Proposal Generator
// =====================================================================

let proposalData = null;

async function loadProposalData() {
  try {
    const resp = await fetch('/api/proposal/data');
    proposalData = await resp.json();
    renderRadioStations();
    updateBudgetPreview();
  } catch (e) {
    showToast('Could not load proposal data. Try refreshing the page.');
  }
}

function renderRadioStations() {
  if (!proposalData) return;
  const genre = document.getElementById('proposal-genre').value;
  const keywords = {
    electronic: ['electronic', 'dance', 'edm'],
    indie: ['indie', 'alternative'],
    rock: ['rock', 'punk'],
    pop: ['pop', 'chr'],
    urban: ['urban', 'reggaeton', 'hip-hop'],
    general: [],
  }[genre] || [];

  const container = document.getElementById('proposal-radio-list');
  const selectedCountries = [...document.querySelectorAll('.proposal-country:checked')].map(c => c.value);

  // Group by country
  const byCountry = {};
  proposalData.stations.forEach(s => {
    if (selectedCountries.length > 0) {
      const match = selectedCountries.some(c =>
        s.country.toUpperCase().includes(c.toUpperCase()) || c.toUpperCase().includes(s.country.toUpperCase())
      );
      if (!match) return;
    }
    if (!byCountry[s.country]) byCountry[s.country] = [];
    byCountry[s.country].push(s);
  });

  let html = '';
  const countryOrder = ['Mexico','Brazil','Argentina','Chile','Colombia','Ecuador','Peru','Uruguay','Venezuela','LATAM'];

  const sorted = Object.keys(byCountry).sort((a, b) => {
    const ai = countryOrder.indexOf(a), bi = countryOrder.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  let total = 0;
  sorted.forEach(country => {
    html += `<div class="station-country-header">${country}</div>`;
    byCountry[country].forEach(s => {
      const genreLower = s.genre.toLowerCase();
      const isRelevant = keywords.length === 0 || keywords.some(kw => genreLower.includes(kw));
      const checked = isRelevant ? 'checked' : '';
      if (isRelevant) total++;
      html += `<label class="station-row">
        <input type="checkbox" class="proposal-radio" value="${s.station}" ${checked} onchange="updateBudgetPreview()"><span class="checkmark"></span>
        <span class="station-name">${s.station}</span>
        <span class="station-genre">${s.genre}</span>
        <span class="station-price">$${s.price}</span>
      </label>`;
    });
  });

  container.innerHTML = html || '<span style="color:var(--text-tertiary);font-size:12px;">No stations match the selected countries/genre.</span>';
  document.getElementById('radio-count-label').textContent = `(${total} selected)`;
}

function addTimelineRow() {
  const container = document.getElementById('proposal-timeline');
  const row = document.createElement('div');
  row.style.cssText = 'display:grid;grid-template-columns:1fr 120px 100px 28px;gap:6px;align-items:center;';
  row.innerHTML = `
    <input type="text" class="form-control tl-title" placeholder="Track / EP title" style="font-size:12px;padding:6px 10px;">
    <input type="date" class="form-control tl-date" style="font-size:12px;padding:6px 10px;">
    <select class="form-control tl-format" style="font-size:12px;padding:6px 10px;">
      <option>Single</option><option>EP</option><option>Album</option><option>Remix</option>
    </select>
    <button type="button" onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:var(--text-tertiary);font-size:16px;" title="Remove">&times;</button>
  `;
  container.appendChild(row);
}

function toggleAllCountries(checked) {
  document.querySelectorAll('.proposal-country').forEach(cb => cb.checked = checked);
  renderRadioStations();
  updateBudgetPreview();
}

function updateBudgetPreview() {
  if (!proposalData) return;
  const pricing = proposalData.pricing;
  const duration = parseInt(document.getElementById('proposal-duration').value) || 3;

  const items = [];
  let total = 0;

  // Base fee
  const baseMo = pricing.base_fee?.monthly || 2000;
  const baseTotal = baseMo * duration;
  items.push({ label: 'DMM Management', detail: `${duration}mo × $${baseMo.toLocaleString()}`, amount: baseTotal });
  total += baseTotal;

  // Radio
  const selectedRadio = [...document.querySelectorAll('.proposal-radio:checked')];
  if (selectedRadio.length > 0) {
    let radioTotal = 0;
    selectedRadio.forEach(cb => {
      const station = proposalData.stations.find(s => s.station === cb.value);
      if (station) radioTotal += parseInt(station.price.replace(/,/g, '')) || 0;
    });
    if (radioTotal > 0) {
      items.push({ label: `Radio (${selectedRadio.length} stations)`, detail: '3-month rotation', amount: radioTotal });
      total += radioTotal;
    }
  }

  // Influencer
  const infTier = document.getElementById('proposal-influencer').value;
  if (infTier && pricing.influencers?.tiers?.[infTier]) {
    const inf = pricing.influencers.tiers[infTier];
    const infTotal = (inf.estimated_total || 0) * duration;
    items.push({ label: `Influencers (${inf.label})`, detail: inf.recommended_count, amount: infTotal });
    total += infTotal;
  }

  // DJ
  const djMarkets = [...document.querySelectorAll('.proposal-dj:checked')].map(c => c.value);
  if (djMarkets.length > 0) {
    let djTotal = 0;
    djMarkets.forEach(m => { djTotal += pricing.dj_club?.markets?.[m]?.price || 0; });
    items.push({ label: `DJ/Club (${djMarkets.length} markets)`, detail: djMarkets.join(', '), amount: djTotal });
    total += djTotal;
  }

  // Digital
  const digPkg = document.getElementById('proposal-digital').value;
  if (digPkg && pricing.digital_marketing?.packages?.[digPkg]) {
    const dig = pricing.digital_marketing.packages[digPkg];
    const digTotal = (dig.monthly || 0) * duration;
    items.push({ label: `Digital (${dig.label})`, detail: dig.includes, amount: digTotal });
    total += digTotal;
  }

  const preview = document.getElementById('proposal-budget-preview');
  const itemsEl = document.getElementById('proposal-budget-items');
  const totalEl = document.getElementById('proposal-budget-total');
  const monthlyEl = document.getElementById('proposal-budget-monthly');

  itemsEl.innerHTML = items.map(i =>
    `<div style="display:flex;justify-content:space-between;align-items:baseline;">
      <span>${i.label} <span style="color:var(--text-tertiary);font-size:11px;">${i.detail}</span></span>
      <span style="font-weight:600;">$${i.amount.toLocaleString()}</span>
    </div>`
  ).join('');

  totalEl.textContent = `$${total.toLocaleString()} USD`;
  monthlyEl.textContent = `($${Math.round(total / duration).toLocaleString()}/mo over ${duration} months)`;
  preview.style.display = 'block';
}

async function runProposal() {
  const resultEl = document.getElementById('proposal-result');
  const av = validateArtist(document.getElementById('proposal-artist').value);
  if (av.error) { showError(resultEl, av.error); return; }
  const artist = av.value;

  const genre = document.getElementById('proposal-genre').value;
  const duration = parseInt(document.getElementById('proposal-duration').value) || 3;
  const collaborators = document.getElementById('proposal-collaborators').value.trim();
  const goalStrategy = document.getElementById('proposal-goal').value.trim();
  const digitalMarketing = document.getElementById('proposal-digital-text').value.trim();

  // Timeline
  const timeline = [];
  document.querySelectorAll('#proposal-timeline > div').forEach(row => {
    const title = row.querySelector('.tl-title').value.trim();
    const date = row.querySelector('.tl-date').value;
    const format = row.querySelector('.tl-format').value;
    if (title) timeline.push({ title, date, format });
  });

  // Countries
  const countries = [...document.querySelectorAll('.proposal-country:checked')].map(c => c.value);

  // Radio stations
  const radioStations = [...document.querySelectorAll('.proposal-radio:checked')].map(c => c.value);

  // Budget options
  const influencerTier = document.getElementById('proposal-influencer').value || null;
  const digitalPackage = document.getElementById('proposal-digital').value || null;
  const djMarkets = [...document.querySelectorAll('.proposal-dj:checked')].map(c => c.value);

  const btn = document.getElementById('proposal-btn');
  const logEl = document.getElementById('proposal-log');
  const progressEl = document.getElementById('proposal-progress');

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const resp = await fetch('/api/proposal/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        artist, genre, campaign_duration: duration, collaborators,
        goal_strategy: goalStrategy, digital_marketing: digitalMarketing,
        timeline, countries,
        radio_stations: radioStations.length > 0 ? radioStations : null,
        influencer_tier: influencerTier,
        dj_markets: djMarkets.length > 0 ? djMarkets : null,
        digital_package: digitalPackage,
      }),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        resultEl.innerHTML = `
          <div class="result-success">${escapeHtml(result.result || 'Proposal generated.')}</div>
          ${result.has_file ? `<a href="/api/download/${data.job_id}" class="btn download-btn">Download .docx</a>` : ''}`;
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

// Load proposal data when tab is first activated
let proposalDataLoaded = false;


// =====================================================================
// Weekly Digest
// =====================================================================
async function runDigest() {
  const resultEl = document.getElementById('digest-result');
  const av = validateArtist(document.getElementById('digest-artist').value);
  if (av.error) { showError(resultEl, av.error); return; }
  const artist = av.value;

  const timeRange = document.querySelector('input[name="digest-range"]:checked').value;
  const region = document.querySelector('input[name="digest-region"]:checked').value;
  const includeRadio = document.getElementById('digest-inc-radio').checked;
  const includeDsp = document.getElementById('digest-inc-dsp').checked;
  const includePress = document.getElementById('digest-inc-press').checked;
  const nextSteps = document.getElementById('digest-steps').value;
  const contactName = document.getElementById('digest-contact').value.trim();
  const senderName = document.getElementById('digest-sender').value.trim();

  if (!includeRadio && !includeDsp && !includePress) {
    return showToast('Please select at least one section to include.');
  }

  const daysMap = { '7d': 7, '28d': 28 };

  const btn = document.getElementById('digest-btn');
  const logEl = document.getElementById('digest-log');
  const progressEl = document.getElementById('digest-progress');

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const resp = await fetch('/api/digest/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        artist,
        days: daysMap[timeRange] || 7,
        radio_region: region,
        radio_time_range: timeRange,
        next_steps: nextSteps,
        sender_name: senderName,
        contact_name: contactName,
        include_radio: includeRadio,
        include_dsp: includeDsp,
        include_press: includePress,
      }),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, 'digest', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        renderDigest(result, resultEl);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

function renderDigest(result, resultEl) {
  const digestHtml = result.digest_html || '';
  const digestText = result.digest_text || '';

  let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Weekly digest ready!</strong></div>`;

  if (result.result) {
    html += `<div style="margin:12px 0 16px; font-size:14px; color:var(--text-secondary); line-height:1.8;">${escapeHtml(result.result)}</div>`;
  }

  // Toggle between HTML preview and plain text
  html += `<div style="margin:16px 0 8px; display:flex; gap:8px;">`;
  html += `<button class="btn btn-small" onclick="showDigestView('html')" id="digest-view-html-btn" style="opacity:1;">Email Preview</button>`;
  html += `<button class="btn btn-small" onclick="showDigestView('text')" id="digest-view-text-btn" style="opacity:.5;">Plain Text</button>`;
  html += `</div>`;

  // HTML preview
  html += `<div id="digest-view-html" style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius-sm); padding:24px; margin:8px 0 16px;">`;
  html += digestHtml;
  html += `</div>`;

  // Plain text (hidden by default)
  html += `<div id="digest-view-text" style="display:none; margin:8px 0 16px;">`;
  html += `<pre style="background:var(--bg-input); border:1px solid var(--border); border-radius:var(--radius-sm); padding:16px; font-size:13px; line-height:1.6; white-space:pre-wrap; color:var(--text-primary); overflow-x:auto;">${escapeHtml(digestText)}</pre>`;
  html += `</div>`;

  // Copy buttons
  html += `<div class="result-actions">`;
  html += `<button class="btn btn-small" onclick="copyDigestHtml()" id="copy-html-btn">Copy HTML</button>`;
  html += `<button class="btn btn-small" onclick="copyDigestText()" id="copy-text-btn">Copy Plain Text</button>`;
  html += `</div>`;

  resultEl.innerHTML = html;

  // Store for copy functions
  resultEl._digestHtml = digestHtml;
  resultEl._digestText = digestText;
}

function showDigestView(view) {
  const htmlView = document.getElementById('digest-view-html');
  const textView = document.getElementById('digest-view-text');
  const htmlBtn = document.getElementById('digest-view-html-btn');
  const textBtn = document.getElementById('digest-view-text-btn');

  if (view === 'html') {
    htmlView.style.display = '';
    textView.style.display = 'none';
    htmlBtn.style.opacity = '1';
    textBtn.style.opacity = '.5';
  } else {
    htmlView.style.display = 'none';
    textView.style.display = '';
    htmlBtn.style.opacity = '.5';
    textBtn.style.opacity = '1';
  }
}

function copyDigestHtml() {
  const el = document.getElementById('digest-result');
  const html = el._digestHtml || '';
  if (navigator.clipboard && navigator.clipboard.write) {
    const blob = new Blob([html], { type: 'text/html' });
    const textBlob = new Blob([el._digestText || ''], { type: 'text/plain' });
    navigator.clipboard.write([
      new ClipboardItem({ 'text/html': blob, 'text/plain': textBlob })
    ]).then(() => showToast('HTML copied to clipboard!')).catch(() => {
      // Fallback
      navigator.clipboard.writeText(html).then(() => showToast('HTML copied as text!'));
    });
  } else {
    const ta = document.createElement('textarea');
    ta.value = html;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('HTML copied!');
  }
}

function copyDigestText() {
  const el = document.getElementById('digest-result');
  const text = el._digestText || '';
  navigator.clipboard.writeText(text).then(() => showToast('Plain text copied to clipboard!'));
}

// =====================================================================
// Batch Digest
// =====================================================================
let digestBatchArtists = [];  // cached artist list

function toggleDigestMode() {
  const isBatch = document.querySelector('input[name="digest-mode"]:checked').value === 'batch';
  document.getElementById('digest-single-fields').style.display = isBatch ? 'none' : '';
  document.getElementById('digest-batch-fields').style.display = isBatch ? '' : 'none';
  document.getElementById('digest-single-steps').style.display = isBatch ? 'none' : '';
  document.getElementById('digest-btn').style.display = isBatch ? 'none' : '';
  document.getElementById('digest-batch-btn').style.display = isBatch ? '' : 'none';
  if (isBatch) {
    loadBatchPreview('week', null, 'digest-batch-preview');
  }
}

async function runBatchDigest() {
  const previewEl = document.getElementById('digest-batch-preview');
  const selected = previewEl._selectedArtists ? Array.from(previewEl._selectedArtists) : [];
  if (!selected.length) return showToast('Please select at least one artist.');

  const mode = document.querySelector('input[name="digest-batch-output"]:checked').value;
  const timeRange = document.querySelector('input[name="digest-range"]:checked').value;
  const region = document.querySelector('input[name="digest-region"]:checked').value;
  const includeRadio = document.getElementById('digest-inc-radio').checked;
  const includeDsp = document.getElementById('digest-inc-dsp').checked;
  const includePress = document.getElementById('digest-inc-press').checked;

  if (!includeRadio && !includeDsp && !includePress) {
    return showToast('Please select at least one section to include.');
  }

  const btn = document.getElementById('digest-batch-btn');
  const logEl = document.getElementById('digest-log');
  const progressEl = document.getElementById('digest-progress');
  const resultEl = document.getElementById('digest-result');

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const resp = await fetch('/api/digest/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        artists: selected,
        mode,
        radio_region: region,
        radio_time_range: timeRange,
        include_radio: includeRadio,
        include_dsp: includeDsp,
        include_press: includePress,
      }),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, 'digest', (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        renderBatchDigest(result, mode);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

function renderBatchDigest(result, mode) {
  const resultEl = document.getElementById('digest-result');
  const batchResults = result.batch_results || {};
  const artists = Object.keys(batchResults);

  let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Batch complete</strong></div>`;
  if (result.result) {
    html += `<div style="margin:12px 0 16px; font-size:14px; color:var(--text-secondary); line-height:1.8;">${escapeHtml(result.result)}</div>`;
  }

  if (mode === 'snapshot') {
    // Compact table view
    html += '<div style="border:1px solid var(--border); border-radius:var(--radius-sm); overflow:hidden; margin-top:8px;">';
    html += '<table style="width:100%; border-collapse:collapse; font-size:13px;">';
    html += '<thead><tr style="background:var(--bg-input);"><th style="text-align:left; padding:10px 12px; border-bottom:1px solid var(--border);">Artist</th><th style="padding:10px 8px; border-bottom:1px solid var(--border);">Radio</th><th style="padding:10px 8px; border-bottom:1px solid var(--border);">DSP</th><th style="padding:10px 8px; border-bottom:1px solid var(--border);">Press</th></tr></thead><tbody>';
    artists.forEach(name => {
      const r = batchResults[name];
      const err = r.error ? ' title="' + escapeHtml(r.error) + '"' : '';
      const rowStyle = r.error ? ' style="color:var(--accent-red);"' : (!r.radio_count && !r.dsp_count && !r.press_count ? ' style="color:var(--text-tertiary);"' : '');
      html += `<tr${rowStyle}><td style="padding:8px 12px; border-bottom:1px solid var(--border);"${err}>${escapeHtml(name)}${r.error ? ' &#9888;' : ''}</td>`;
      html += `<td style="text-align:center; padding:8px; border-bottom:1px solid var(--border);">${r.radio_count || 0}</td>`;
      html += `<td style="text-align:center; padding:8px; border-bottom:1px solid var(--border);">${r.dsp_count || 0}</td>`;
      html += `<td style="text-align:center; padding:8px; border-bottom:1px solid var(--border);">${r.press_count || 0}</td></tr>`;
    });
    html += '</tbody></table></div>';
  } else {
    // Expandable cards for full digest mode
    artists.forEach((name, idx) => {
      const r = batchResults[name];
      const counts = [];
      if (r.radio_count) counts.push('Radio: ' + r.radio_count);
      if (r.dsp_count) counts.push('DSP: ' + r.dsp_count);
      if (r.press_count) counts.push('Press: ' + r.press_count);
      const countStr = counts.length ? counts.join(' | ') : 'No activity';
      const hasContent = r.html || r.text;
      const cardId = 'batch-card-' + idx;

      html += `<div style="border:1px solid var(--border); border-radius:var(--radius-sm); margin-top:8px; overflow:hidden;">`;
      html += `<div style="display:flex; justify-content:space-between; align-items:center; padding:12px 16px; background:var(--bg-input); cursor:${hasContent ? 'pointer' : 'default'};" ${hasContent ? `onclick="document.getElementById('${cardId}').style.display = document.getElementById('${cardId}').style.display === 'none' ? '' : 'none'"` : ''}>`;
      html += `<div><strong>${escapeHtml(name)}</strong>`;
      if (r.error) html += ` <span style="color:var(--accent-red); font-size:12px;">Error</span>`;
      html += `</div>`;
      html += `<div style="font-size:13px; color:var(--text-secondary);">${escapeHtml(countStr)}${hasContent ? ' &#9660;' : ''}</div>`;
      html += `</div>`;

      if (hasContent) {
        html += `<div id="${cardId}" style="display:none; padding:16px; border-top:1px solid var(--border);">`;
        // Toggle + preview
        html += `<div style="display:flex; gap:8px; margin-bottom:8px;">`;
        html += `<button class="btn btn-small" onclick="showBatchCardView(${idx},'html')" id="bc-html-btn-${idx}" style="opacity:1;">Email Preview</button>`;
        html += `<button class="btn btn-small" onclick="showBatchCardView(${idx},'text')" id="bc-text-btn-${idx}" style="opacity:.5;">Plain Text</button>`;
        html += `<button class="btn btn-small" onclick="copyBatchHtml(${idx})" style="margin-left:auto;">Copy HTML</button>`;
        html += `<button class="btn btn-small" onclick="copyBatchText(${idx})">Copy Text</button>`;
        html += `</div>`;
        html += `<div id="bc-html-${idx}" style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius-sm); padding:16px; max-height:400px; overflow-y:auto;">${r.html || ''}</div>`;
        html += `<div id="bc-text-${idx}" style="display:none;"><pre style="background:var(--bg-input); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; font-size:13px; line-height:1.6; white-space:pre-wrap; color:var(--text-primary); max-height:400px; overflow-y:auto;">${escapeHtml(r.text || '')}</pre></div>`;
        html += `</div>`;
      }
      html += `</div>`;
    });
  }

  resultEl.innerHTML = html;
  // Store batch results for copy functions
  resultEl._batchResults = batchResults;
}

function showBatchCardView(idx, view) {
  const htmlEl = document.getElementById('bc-html-' + idx);
  const textEl = document.getElementById('bc-text-' + idx);
  const htmlBtn = document.getElementById('bc-html-btn-' + idx);
  const textBtn = document.getElementById('bc-text-btn-' + idx);
  if (view === 'html') {
    htmlEl.style.display = ''; textEl.style.display = 'none';
    htmlBtn.style.opacity = '1'; textBtn.style.opacity = '.5';
  } else {
    htmlEl.style.display = 'none'; textEl.style.display = '';
    htmlBtn.style.opacity = '.5'; textBtn.style.opacity = '1';
  }
}

function copyBatchHtml(idx) {
  const el = document.getElementById('digest-result');
  const artists = Object.keys(el._batchResults || {});
  const r = el._batchResults[artists[idx]];
  if (!r) return;
  if (navigator.clipboard && navigator.clipboard.write) {
    const blob = new Blob([r.html || ''], { type: 'text/html' });
    const textBlob = new Blob([r.text || ''], { type: 'text/plain' });
    navigator.clipboard.write([
      new ClipboardItem({ 'text/html': blob, 'text/plain': textBlob })
    ]).then(() => showToast('HTML copied!')).catch(() => {
      navigator.clipboard.writeText(r.html || '').then(() => showToast('HTML copied as text!'));
    });
  } else {
    navigator.clipboard.writeText(r.html || '').then(() => showToast('HTML copied!'));
  }
}

function copyBatchText(idx) {
  const el = document.getElementById('digest-result');
  const artists = Object.keys(el._batchResults || {});
  const r = el._batchResults[artists[idx]];
  if (!r) return;
  navigator.clipboard.writeText(r.text || '').then(() => showToast('Plain text copied!'));
}

// =====================================================================
// Outlet Discovery
// =====================================================================
document.getElementById('discovery-genre').addEventListener('change', function() {
  document.getElementById('discovery-custom-wrap').style.display = this.value === 'custom' ? '' : 'none';
});

// "All LATAM" checkbox logic — uncheck specifics when All is checked, and vice versa
document.querySelectorAll('input[name="discovery-country"]').forEach(cb => {
  cb.addEventListener('change', function() {
    if (this.value === 'All LATAM' && this.checked) {
      document.querySelectorAll('input[name="discovery-country"]').forEach(other => {
        if (other.value !== 'All LATAM') other.checked = false;
      });
    } else if (this.value !== 'All LATAM' && this.checked) {
      const allBox = document.querySelector('input[name="discovery-country"][value="All LATAM"]');
      if (allBox) allBox.checked = false;
    }
  });
});

async function runDiscovery() {
  const genre = document.getElementById('discovery-genre').value;
  const customQuery = document.getElementById('discovery-custom').value.trim();

  if (genre === 'custom' && !customQuery) {
    return showToast('Please enter a custom search query.');
  }

  const countryBoxes = document.querySelectorAll('input[name="discovery-country"]:checked');
  const countries = Array.from(countryBoxes).map(cb => cb.value);
  if (countries.length === 0) {
    return showToast('Please select at least one region.');
  }

  const useLlm = document.getElementById('discovery-llm').checked;

  const btn = document.getElementById('discovery-btn');
  const logEl = document.getElementById('discovery-log');
  const progressEl = document.getElementById('discovery-progress');
  const resultEl = document.getElementById('discovery-result');

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const resp = await fetch('/api/discovery/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        genre,
        countries,
        custom_query: genre === 'custom' ? customQuery : '',
        use_llm: useLlm,
      }),
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    pollJob(data.job_id, logEl, progressEl, resultEl, (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        renderDiscovery(result, data.job_id, resultEl);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

function renderDiscovery(result, jobId, resultEl) {
  const outlets = result.discovery_outlets || [];
  const discoveryHtml = result.discovery_html || '';

  let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Discovery complete!</strong></div>`;

  if (result.result) {
    html += `<div style="margin:12px 0 16px; font-size:14px; color:var(--text-secondary); line-height:1.8;">${escapeHtml(result.result)}</div>`;
  }

  if (outlets.length > 0) {
    // Outlet cards
    html += `<div style="margin:16px 0;">`;
    for (const o of outlets) {
      const countries = (o.countries || []).join(', ');
      html += `<div style="padding:14px 18px; border:1px solid var(--border); border-radius:var(--radius-sm); margin-bottom:10px; background:var(--bg-card);">`;
      html += `<div style="display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:4px;">`;
      html += `<strong style="font-size:15px;">${escapeHtml(o.name)}</strong>`;
      html += `<span style="font-size:12px; color:var(--text-tertiary);">${escapeHtml(o.domain)}</span>`;
      if (o.outlet_type) {
        html += `<span style="display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px; background:var(--bg-input); color:var(--text-secondary); border:1px solid var(--border); margin-left:8px;">${escapeHtml(o.outlet_type)}</span>`;
      }
      html += `</div>`;
      if (o.description) {
        html += `<p style="margin:6px 0 4px; font-size:13px; color:var(--text-secondary); line-height:1.5;">${escapeHtml(o.description)}</p>`;
      }
      html += `<div style="font-size:12px; color:var(--text-tertiary); margin-top:6px;">`;
      html += `Region: ${escapeHtml(countries)} &middot; Mentions: ${o.mentions || 1}`;
      if (o.sample_url) {
        html += ` &middot; <a href="${escapeAttr(o.sample_url)}" target="_blank" style="color:var(--accent);">Sample article</a>`;
      }
      html += `</div></div>`;
    }
    html += `</div>`;

    // Action buttons
    html += `<div class="result-actions">`;
    html += `<a class="btn btn-small" href="/api/discovery/csv/${jobId}" download>Download CSV (Notion Import)</a>`;
    html += `<button class="btn btn-small" onclick="copyDiscoveryHtml('${jobId}')">Copy HTML Summary</button>`;
    html += `</div>`;
  } else {
    html += `<p style="color:var(--text-tertiary); font-style:italic; margin:16px 0;">No new outlets discovered. The existing database may already have good coverage for this genre/region.</p>`;
  }

  resultEl.innerHTML = html;
  resultEl._discoveryHtml = discoveryHtml;
}

function copyDiscoveryHtml(jobId) {
  const el = document.getElementById('discovery-result');
  const html = el._discoveryHtml || '';
  if (navigator.clipboard && navigator.clipboard.write) {
    const blob = new Blob([html], { type: 'text/html' });
    const textBlob = new Blob([html.replace(/<[^>]*>/g, '')], { type: 'text/plain' });
    navigator.clipboard.write([
      new ClipboardItem({ 'text/html': blob, 'text/plain': textBlob })
    ]).then(() => showToast('HTML summary copied!')).catch(() => {
      navigator.clipboard.writeText(html).then(() => showToast('Copied as text!'));
    });
  } else {
    showToast('Copy not supported in this browser.');
  }
}

// =====================================================================
// Helpers
// =====================================================================
async function parseResponse(resp) {
  if (!resp.ok && resp.status >= 500) {
    throw new Error('Server error (' + resp.status + '). Please try again.');
  }
  try {
    return await resp.json();
  } catch (e) {
    throw new Error('Unexpected server response. Please try again.');
  }
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escapeAttr(s) {
  return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function copyText(btn) {
  const text = btn.getAttribute('data-text');
  navigator.clipboard.writeText(text).then(() => showToast('Copied to clipboard!'));
}

function toggleProofGrid(btn) {
  const grid = btn.closest('.proof-gallery').querySelector('.proof-grid');
  const hidden = grid.style.display === 'none';
  grid.style.display = hidden ? '' : 'none';
  btn.textContent = hidden ? 'Hide' : 'Show';
}

function parsePlatformCounts(reportText) {
  if (!reportText) return null;
  const m = { spotify: 0, deezer: 0, apple: 0, amazon: 0, claro: 0, ytmusic: 0 };
  for (const line of reportText.split('\n')) {
    if (!line.includes('Position #')) continue;
    if (line.includes('[Spotify]')) m.spotify++;
    else if (line.includes('[Deezer]')) m.deezer++;
    else if (line.includes('[Apple Music]')) m.apple++;
    else if (line.includes('[Amazon Music]')) m.amazon++;
    else if (line.includes('[Claro')) m.claro++;
    else if (line.includes('[YouTube Music]')) m.ytmusic++;
  }
  if (!m.spotify && !m.deezer && !m.apple && !m.amazon && !m.claro && !m.ytmusic) return null;
  return m;
}

function colorizeReport(html) {
  return html
    .replace(/\[Spotify\]/g, '<span style="color:#4ade80">[Spotify]</span>')
    .replace(/\[Deezer\]/g, '<span style="color:#c084fc">[Deezer]</span>')
    .replace(/\[Apple Music\]/g, '<span style="color:#fb7185">[Apple Music]</span>')
    .replace(/\[Amazon Music\]/g, '<span style="color:#22d3ee">[Amazon Music]</span>')
    .replace(/\[Claro Música\]/g, '<span style="color:#f59e0b">[Claro Música]</span>')
    .replace(/\[YouTube Music\]/g, '<span style="color:#f87171">[YouTube Music]</span>')
    .replace(/Position #(\d+)/g, 'Position <span style="color:#f87171;font-weight:600">#$1</span>')
    .replace(/^(={2,})/gm, '<span style="color:#4b5563">$1</span>')
    .replace(/^(-{2,})/gm, '<span style="color:#4b5563">$1</span>')
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" style="color:#93c5fd;text-decoration:underline">$1</a>');
}

function formatPressReport(html) {
  // Process line by line
  const lines = html.split('\n');
  let out = '';
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    // Title line: "Press Pickup — Artist"
    if (trimmed.startsWith('Press Pickup')) {
      out += `<span style="color:#c43030;font-weight:700">${line}</span>\n`;
    }
    // URL line
    else if (trimmed.match(/^https?:\/\//)) {
      const url = trimmed;
      let domain = '';
      try { domain = new URL(url).hostname; } catch(e) {}
      const favicon = domain ? `<img src="https://www.google.com/s2/favicons?domain=${domain}&sz=32" class="press-favicon" onerror="this.style.display='none'">` : '';
      out += `${favicon}<a href="${url}" target="_blank" style="color:#93c5fd;text-decoration:underline">${line}</a>\n`;
    }
    // Country header: all-caps line (e.g. "ARGENTINA", "BRAZIL", "LATAM / REGIONAL")
    else if (trimmed && /^[A-ZÁÉÍÓÚÑÜ\s\/\-]+$/.test(trimmed) && trimmed.length > 1) {
      out += `<span style="text-decoration:underline">${line}</span>\n`;
    }
    // Source breakdown line: "Sources: 12 from RSS feeds, 3 from Google News..."
    else if (trimmed.startsWith('Sources:')) {
      out += `<span style="color:#9ca3af;font-size:0.9em;font-style:italic">${line}</span>\n`;
    }
    // Media entry: "Media Name: description..."
    else if (trimmed.includes(': ')) {
      const colonIdx = line.indexOf(': ');
      const name = line.substring(0, colonIdx);
      const desc = line.substring(colonIdx);
      out += `<strong>${name}</strong>${desc}\n`;
    }
    else {
      out += line + '\n';
    }
  }
  return out;
}

// =====================================================================
// PR Translator
// =====================================================================
let prUploadedFile = null;

function prInputModeChanged() {
  const mode = document.querySelector('input[name="pr-input-mode"]:checked').value;
  document.getElementById('pr-paste-area').style.display = mode === 'paste' ? '' : 'none';
  document.getElementById('pr-upload-area').style.display = mode === 'upload' ? '' : 'none';
}

function handlePrFile(files) {
  if (!files || files.length === 0) return;
  const file = files[0];
  if (!file.name.endsWith('.docx')) {
    showToast('Please upload a .docx file.');
    return;
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    showToast(`File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum is ${MAX_UPLOAD_MB} MB.`);
    return;
  }
  prUploadedFile = file;
  const nameEl = document.getElementById('pr-file-name');
  nameEl.style.display = 'flex';
  nameEl.innerHTML = `<span>&#128196;</span> <strong>${escapeHtml(file.name)}</strong> <span style="color:var(--text-tertiary);">(${(file.size / 1024).toFixed(1)} KB)</span> <button onclick="clearPrFile()" style="background:none;border:none;color:var(--error);cursor:pointer;font-size:13px;">Remove</button>`;
}

function clearPrFile() {
  prUploadedFile = null;
  document.getElementById('pr-file-input').value = '';
  document.getElementById('pr-file-name').style.display = 'none';
  document.getElementById('pr-file-name').innerHTML = '';
}

async function runPrTranslate() {
  const mode = document.querySelector('input[name="pr-input-mode"]:checked').value;
  const text = document.getElementById('pr-text').value.trim();
  const targetEs = document.getElementById('pr-target-es').checked;
  const targetPt = document.getElementById('pr-target-pt').checked;
  const notes = document.getElementById('pr-notes') ? document.getElementById('pr-notes').value.trim() : '';

  if (mode === 'paste' && !text) return showToast('Please paste the press release text.');
  if (mode === 'upload' && !prUploadedFile) return showToast('Please upload a .docx file.');
  if (!targetEs && !targetPt) return showToast('Please select at least one target language.');

  const btn = document.getElementById('pr-btn');
  const logEl = document.getElementById('pr-log');
  const progressEl = document.getElementById('pr-progress');
  const resultEl = document.getElementById('pr-result');

  setLoading(btn, true);
  logEl.textContent = '';

  try {
    const useAi = document.getElementById('pr-use-ai').checked;

    const formData = new FormData();
    if (mode === 'paste') {
      formData.append('text', text);
    } else {
      formData.append('file', prUploadedFile);
    }
    formData.append('target_es', targetEs ? 'true' : 'false');
    formData.append('target_pt', targetPt ? 'true' : 'false');
    formData.append('use_ai', useAi ? 'true' : 'false');
    formData.append('notes', notes);

    const resp = await fetch('/api/pr/translate', {
      method: 'POST',
      body: formData,
    });
    const data = await parseResponse(resp);
    if (data.error) {
      setLoading(btn, false);
      showError(resultEl, data.error);
      return;
    }

    const prJobId = data.job_id;
    pollJob(prJobId, logEl, progressEl, resultEl, (result) => {
      setLoading(btn, false);
      resultEl.classList.add('visible');
      if (result.status === 'error') {
        showError(resultEl, result.error);
      } else {
        result._jobId = prJobId;
        renderPrTranslation(result, resultEl);
      }
    });
  } catch (e) {
    setLoading(btn, false);
    showError(resultEl, e.message || 'Could not connect to the server. Check your connection and try again.');
  }
}

function renderPrTranslation(result, resultEl) {
  const esText = result.pr_es_text || '';
  const ptText = result.pr_pt_text || '';
  const esHasDocx = result.pr_es_has_docx || false;
  const ptHasDocx = result.pr_pt_has_docx || false;
  const jobId = result._jobId || '';

  let html = `<div class="result-success"><span class="check-icon">${checkSvg}</span><strong>Translation complete!</strong></div>`;

  if (result.result) {
    html += `<div style="margin:12px 0 16px; font-size:14px; color:var(--text-secondary); line-height:1.8;">${escapeHtml(result.result)}</div>`;
  }

  // Download buttons for translated .docx files
  if (esHasDocx || ptHasDocx) {
    html += `<div style="margin:16px 0; display:flex; gap:10px; flex-wrap:wrap;">`;
    if (esHasDocx) {
      html += `<a href="/api/pr/download/${jobId}?lang=es" class="btn btn-small" style="text-decoration:none; display:inline-flex; align-items:center; gap:6px;">&#128196; Download Spanish .docx</a>`;
    }
    if (ptHasDocx) {
      html += `<a href="/api/pr/download/${jobId}?lang=pt" class="btn btn-small" style="text-decoration:none; display:inline-flex; align-items:center; gap:6px;">&#128196; Download Portuguese .docx</a>`;
    }
    html += `</div>`;
    if (esHasDocx || ptHasDocx) {
      html += `<div style="font-size:12px; color:var(--text-tertiary); margin-bottom:16px;">The .docx files preserve the original document's formatting (fonts, bold, italic, alignment, sizes).</div>`;
    }
  }

  // Build toggle buttons for text preview
  const views = [];
  if (esText) views.push({ id: 'es', label: 'Spanish' });
  if (ptText) views.push({ id: 'pt', label: 'Portuguese' });

  if (views.length > 0) {
    html += `<label style="font-size:13px; color:var(--text-secondary); margin-bottom:4px; display:block;">Text Preview</label>`;
  }

  if (views.length > 1) {
    html += `<div style="margin:4px 0 8px; display:flex; gap:8px;">`;
    views.forEach((v, i) => {
      html += `<button class="btn btn-small" onclick="showPrView('${v.id}')" id="pr-view-${v.id}-btn" style="opacity:${i === 0 ? '1' : '.5'};">${v.label}</button>`;
    });
    html += `</div>`;
  }

  // Spanish text preview
  if (esText) {
    html += `<div id="pr-view-es" style="margin:8px 0 16px;">`;
    html += `<pre style="background:var(--bg-input); border:1px solid var(--border); border-radius:var(--radius-sm); padding:16px; font-size:13px; line-height:1.7; white-space:pre-wrap; color:var(--text-primary); overflow-x:auto; max-height:400px;">${escapeHtml(esText)}</pre>`;
    html += `</div>`;
  }

  // Portuguese text preview (hidden if both exist)
  if (ptText) {
    html += `<div id="pr-view-pt" style="${esText ? 'display:none; ' : ''}margin:8px 0 16px;">`;
    html += `<pre style="background:var(--bg-input); border:1px solid var(--border); border-radius:var(--radius-sm); padding:16px; font-size:13px; line-height:1.7; white-space:pre-wrap; color:var(--text-primary); overflow-x:auto; max-height:400px;">${escapeHtml(ptText)}</pre>`;
    html += `</div>`;
  }

  // Copy button
  html += `<div class="result-actions">`;
  html += `<button class="btn btn-small" onclick="copyPrCurrent()">Copy Current View</button>`;
  html += `</div>`;

  resultEl.innerHTML = html;

  // Store for copy
  resultEl._prData = { esText, ptText };
  resultEl._prCurrentView = esText ? 'es' : 'pt';
}

function showPrView(view) {
  ['es', 'pt'].forEach(v => {
    const el = document.getElementById('pr-view-' + v);
    const btn = document.getElementById('pr-view-' + v + '-btn');
    if (el) el.style.display = v === view ? '' : 'none';
    if (btn) btn.style.opacity = v === view ? '1' : '.5';
  });
  const resultEl = document.getElementById('pr-result');
  if (resultEl) resultEl._prCurrentView = view;
}

function copyPrCurrent() {
  const resultEl = document.getElementById('pr-result');
  const data = resultEl._prData || {};
  const view = resultEl._prCurrentView || 'es';
  const content = view === 'es' ? (data.esText || '') : (data.ptText || '');
  navigator.clipboard.writeText(content).then(() => showToast('Copied to clipboard!'));
}

// Default week date to this Friday
(function() {
  const d = new Date();
  const day = d.getDay();
  const diff = (5 - day + 7) % 7;
  const friday = new Date(d);
  friday.setDate(d.getDate() + (diff === 0 && d.getHours() > 12 ? 7 : diff));
  document.getElementById('dsp-week').value = friday.toISOString().split('T')[0];

  // Default custom range dates: 28 days ago → today
  const today = new Date();
  const ago28 = new Date(today);
  ago28.setDate(today.getDate() - 28);
  document.getElementById('radio-end-date').value = today.toISOString().split('T')[0];
  document.getElementById('radio-start-date').value = ago28.toISOString().split('T')[0];
})();

// =====================================================================
// URL parameter handling (for calendar action buttons)
// =====================================================================
(function() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  const artist = params.get('artist');
  if (tab) {
    goToTool(tab);
    if (artist) {
      const inputMap = {
        radio: 'radio-artist',
        press: 'press-artist',
        dsp: 'dsp-artist',
        report: 'report-artist',
        proposal: 'proposal-artist',
        digest: 'digest-artist',
        pr: 'pr-artist',
      };
      const inputId = inputMap[tab];
      if (inputId) {
        const el = document.getElementById(inputId);
        if (el) el.value = decodeURIComponent(artist);
      }
    }
    // Clean URL
    window.history.replaceState({}, '', '/');
  }
})();

// =====================================================================
// Walkthrough
// =====================================================================
const walkthroughSteps = [
  { target: null, text: 'Welcome to DMM Tools! This quick tour shows you the core reporting workflow. Click Next to begin.' },
  { target: '.landing-grid', text: 'This is your toolkit. Each card is a tool \u2014 click any card to open it. The three most-used tools are Radio Report, Press Pickup, and DSP Pickup.', goLanding: true },
  { target: '#radio-artist', tab: 'radio', text: 'Start by typing an artist name. The tool searches Soundcharts for their airplay data across LATAM radio stations.' },
  { target: 'input[name="radio-range"]', tab: 'radio', text: 'Pick a time range \u2014 7 days, 28 days, up to 1 year, or a custom date range.', targetParent: true },
  { target: '#radio-fetch-btn', tab: 'radio', text: 'Click here to fetch songs. You\u2019ll then pick which songs to include and generate a downloadable Word report.' },
  { target: '#press-artist', tab: 'press', text: 'Press Pickup searches 7 sources (RSS feeds, sitemaps, Google News, Web Search, Serper, Tavily, DuckDuckGo) for press coverage across LATAM.' },
  { target: 'input[name="dsp-mode"]', tab: 'dsp', text: 'DSP Pickup checks 99+ editorial playlists across Spotify, Apple Music, Deezer, Amazon, Claro M\u00fasica, and YouTube Music.', targetParent: true },
  { target: null, text: 'You\u2019re all set! Use the \u2190 All Tools button to return to the homepage. Click ? at the bottom to replay this tour anytime.' },
];

let wtStep = 0;
let wtBackdrop = null;
let wtTooltip = null;
let wtPrevTarget = null;

function startWalkthrough() {
  wtStep = 0;
  goToLanding();
  // Create backdrop
  if (!wtBackdrop) {
    wtBackdrop = document.createElement('div');
    wtBackdrop.className = 'walkthrough-backdrop';
    document.body.appendChild(wtBackdrop);
  }
  // Create tooltip
  if (!wtTooltip) {
    wtTooltip = document.createElement('div');
    wtTooltip.className = 'walkthrough-tooltip';
    document.body.appendChild(wtTooltip);
  }
  // Show with transition
  requestAnimationFrame(() => {
    wtBackdrop.classList.add('visible');
    showWtStep();
  });
}

function showWtStep() {
  const step = walkthroughSteps[wtStep];
  const total = walkthroughSteps.length;
  const isLast = wtStep === total - 1;

  // Clear previous highlight
  if (wtPrevTarget) {
    wtPrevTarget.classList.remove('walkthrough-highlight');
    wtPrevTarget = null;
  }

  // Switch view if needed
  if (step.goLanding) goToLanding();
  else if (step.tab) goToTool(step.tab);

  // Build tooltip content
  wtTooltip.innerHTML = `
    <p>${step.text}</p>
    <div class="walkthrough-footer">
      <span class="walkthrough-counter">${wtStep + 1} of ${total}</span>
      <div class="walkthrough-actions">
        ${!isLast ? '<button class="walkthrough-skip" onclick="endWalkthrough()">Skip</button>' : ''}
        <button class="walkthrough-next" onclick="${isLast ? 'endWalkthrough()' : 'nextWtStep()'}">${isLast ? 'Done' : 'Next'}</button>
      </div>
    </div>`;

  // Position tooltip
  wtTooltip.classList.remove('visible', 'centered');

  if (!step.target) {
    // Centered card (welcome / done)
    wtTooltip.classList.add('centered');
    wtTooltip.style.top = '';
    wtTooltip.style.left = '';
    requestAnimationFrame(() => wtTooltip.classList.add('visible'));
  } else {
    let el = step.targetParent
      ? document.querySelector(step.target)?.closest('.radio-group')
      : document.querySelector(step.target);
    if (!el) { nextWtStep(); return; }

    el.classList.add('walkthrough-highlight');
    wtPrevTarget = el;

    positionTooltip(el);
    requestAnimationFrame(() => wtTooltip.classList.add('visible'));
  }
}

function positionTooltip(el) {
  const rect = el.getBoundingClientRect();
  const tt = wtTooltip;
  tt.style.transform = '';

  // Try below the element
  const spaceBelow = window.innerHeight - rect.bottom;
  const spaceAbove = rect.top;
  const gap = 14;

  if (spaceBelow > 160 || spaceBelow >= spaceAbove) {
    tt.style.top = (rect.bottom + gap) + 'px';
  } else {
    // Position above — use getBoundingClientRect after render to know height
    tt.style.top = '0px';
    tt.style.left = Math.max(20, Math.min(rect.left, window.innerWidth - 400)) + 'px';
    requestAnimationFrame(() => {
      const ttH = tt.getBoundingClientRect().height;
      tt.style.top = (rect.top - gap - ttH) + 'px';
    });
    return;
  }

  tt.style.left = Math.max(20, Math.min(rect.left, window.innerWidth - 400)) + 'px';
}

function nextWtStep() {
  wtStep++;
  if (wtStep >= walkthroughSteps.length) { endWalkthrough(); return; }
  wtTooltip.classList.remove('visible');
  setTimeout(() => showWtStep(), 150);
}

function endWalkthrough() {
  localStorage.setItem('dmm_walkthrough_done', '1');
  if (wtPrevTarget) {
    wtPrevTarget.classList.remove('walkthrough-highlight');
    wtPrevTarget = null;
  }
  if (wtTooltip) wtTooltip.classList.remove('visible');
  if (wtBackdrop) wtBackdrop.classList.remove('visible');
  setTimeout(() => {
    if (wtBackdrop) { wtBackdrop.remove(); wtBackdrop = null; }
    if (wtTooltip) { wtTooltip.remove(); wtTooltip = null; }
  }, 300);
  // Return to landing
  goToLanding();
}

// Auto-start on first visit
if (!localStorage.getItem('dmm_walkthrough_done')) {
  // Small delay so page renders first
  setTimeout(startWalkthrough, 600);
}

// =====================================================================
// Schedules
// =====================================================================
let schedulesLoaded = false;
let _schedulesCache = [];
let _schedArtistsWithData = [];
let _schedArtistsFromSchedule = [];
let _schedArtistsLoaded = false;

async function loadSchedules() {
  const container = document.getElementById('schedules-list');
  try {
    const resp = await fetch('/api/schedules');
    const data = await resp.json();
    _schedulesCache = data;
    if (!data.length) {
      container.innerHTML = '<div style="color:var(--text-tertiary); font-size:13px;">No schedules yet. Click "+ New Schedule" to create one.</div>';
      return;
    }
    let html = '<table style="width:100%; border-collapse:collapse; font-size:13px;">';
    html += '<tr style="text-align:left; color:var(--text-tertiary); font-size:11px; text-transform:uppercase; letter-spacing:.05em;">';
    html += '<th style="padding:6px 8px;">Name</th><th style="padding:6px 8px;">Cadence</th><th style="padding:6px 8px;">Artists</th>';
    html += '<th style="padding:6px 8px;">Last Run</th><th style="padding:6px 8px;">Next Run</th><th style="padding:6px 8px;">Status</th><th style="padding:6px 8px; text-align:right;">Actions</th></tr>';
    data.forEach(s => {
      const statusBadge = s.enabled
        ? '<span style="color:#4ade80; font-size:11px;">● Enabled</span>'
        : '<span style="color:var(--text-tertiary); font-size:11px;">○ Disabled</span>';
      const artistLabel = s.artist_source === 'manual'
        ? (s.artists.length + ' artist' + (s.artists.length !== 1 ? 's' : ''))
        : ({all_with_data: 'All Dashboard', all_schedule: 'All Schedule', all: 'All'}[s.artist_source] || s.artist_source);
      const lastRun = s.last_run_at ? new Date(s.last_run_at + 'Z').toLocaleDateString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
      const nextRun = s.next_run_time ? new Date(s.next_run_time).toLocaleDateString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
      const lastStatus = s.last_run_status ? _schedStatusBadge(s.last_run_status) : '';
      html += `<tr style="border-top:1px solid var(--border);">`;
      const gdocBadge = s.auto_append_gdocs ? ' <span style="font-size:10px; padding:1px 5px; border-radius:6px; background:#3b82f622; color:#3b82f6; font-weight:600;">GDocs</span>' : '';
      html += `<td style="padding:8px;">${escapeHtml(s.name)}${gdocBadge}<div style="font-size:11px;color:var(--text-tertiary);">${s.mode}</div></td>`;
      html += `<td style="padding:8px; font-family:monospace; font-size:12px;">${cronToHuman(s.cron_expression)}</td>`;
      html += `<td style="padding:8px;">${artistLabel}</td>`;
      html += `<td style="padding:8px;">${lastRun} ${lastStatus}</td>`;
      html += `<td style="padding:8px;">${nextRun}</td>`;
      html += `<td style="padding:8px;">${statusBadge}</td>`;
      html += `<td style="padding:8px; text-align:right; white-space:nowrap;">`;
      html += `<button class="btn btn-small" onclick="triggerSchedule(${s.id})" title="Run Now" style="margin-right:4px;">▶</button>`;
      html += `<button class="btn btn-small" onclick="showScheduleForm(${s.id})" title="Edit" style="margin-right:4px;">✎</button>`;
      html += `<button class="btn btn-small" onclick="toggleSchedule(${s.id}, ${!s.enabled})" title="${s.enabled ? 'Disable' : 'Enable'}" style="margin-right:4px;">${s.enabled ? '⏸' : '▶'}</button>`;
      html += `<button class="btn btn-small" onclick="deleteSchedule(${s.id})" title="Delete" style="color:var(--accent);">✕</button>`;
      html += `</td></tr>`;
    });
    html += '</table>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div style="color:var(--accent); font-size:13px;">Failed to load schedules.</div>';
  }
}

function _schedStatusBadge(status) {
  const colors = {success:'#4ade80', partial:'#facc15', error:'#f87171', interrupted:'#a78bfa', running:'#60a5fa'};
  const c = colors[status] || 'var(--text-tertiary)';
  return `<span style="font-size:10px; padding:1px 6px; border-radius:8px; background:${c}22; color:${c}; font-weight:600;">${status}</span>`;
}

async function loadScheduleHistory() {
  const container = document.getElementById('schedule-history');
  try {
    const resp = await fetch('/api/schedules/history');
    const runs = await resp.json();
    if (!runs.length) {
      container.innerHTML = '<div style="color:var(--text-tertiary);">No runs yet.</div>';
      return;
    }
    let html = '<table style="width:100%; border-collapse:collapse; font-size:13px;">';
    html += '<tr style="text-align:left; color:var(--text-tertiary); font-size:11px; text-transform:uppercase; letter-spacing:.05em;">';
    html += '<th style="padding:6px 8px;">Schedule</th><th style="padding:6px 8px;">Started</th><th style="padding:6px 8px;">Duration</th>';
    html += '<th style="padding:6px 8px;">Status</th><th style="padding:6px 8px;">Artists</th><th style="padding:6px 8px;">Details</th></tr>';
    runs.forEach(r => {
      const schedName = (_schedulesCache.find(s => s.id === r.schedule_id) || {}).name || `#${r.schedule_id}`;
      const started = new Date(r.started_at + 'Z').toLocaleDateString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
      const duration = r.duration_seconds ? r.duration_seconds.toFixed(0) + 's' : '—';
      const detailParts = [];
      if (r.artists_with_data) detailParts.push(`${r.artists_with_data} with data`);
      if (r.artists_failed) detailParts.push(`${r.artists_failed} failed`);
      const detailStr = detailParts.join(', ') || '—';
      html += `<tr style="border-top:1px solid var(--border);">`;
      html += `<td style="padding:8px;">${escapeHtml(schedName)}</td>`;
      html += `<td style="padding:8px;">${started}</td>`;
      html += `<td style="padding:8px;">${duration}</td>`;
      html += `<td style="padding:8px;">${_schedStatusBadge(r.status)}</td>`;
      html += `<td style="padding:8px;">${r.total_artists}</td>`;
      html += `<td style="padding:8px;">${detailStr}</td>`;
      html += `</tr>`;
    });
    html += '</table>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div style="color:var(--accent); font-size:13px;">Failed to load history.</div>';
  }
}

async function _loadScheduleArtists() {
  if (_schedArtistsLoaded) return;
  _schedArtistsLoaded = true;
  try {
    const resp = await fetch('/api/dashboard/artists');
    const data = await resp.json();
    _schedArtistsWithData = (data.with_data || []).map(a => a.name);
    _schedArtistsFromSchedule = data.from_schedule || [];
  } catch (e) { /* ignore */ }
  _renderScheduleArtists();
}

function _renderScheduleArtists() {
  const container = document.getElementById('schedule-artist-list');
  const filter = (document.getElementById('schedule-artist-filter').value || '').toLowerCase();
  let html = '';
  const makeCheckbox = (name) => {
    if (filter && !name.toLowerCase().includes(filter)) return '';
    const id = 'sched-a-' + name.replace(/[^a-zA-Z0-9]/g, '_');
    return `<div class="checkbox-row" style="padding:3px 0;"><input type="checkbox" id="${id}" class="sched-artist-cb" value="${escapeHtml(name)}"><label for="${id}" style="font-size:13px;">${escapeHtml(name)}</label></div>`;
  };
  if (_schedArtistsWithData.length) {
    html += '<div style="font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--text-tertiary); margin:4px 0 6px; font-weight:600;">With Dashboard Data</div>';
    _schedArtistsWithData.forEach(n => { html += makeCheckbox(n); });
  }
  if (_schedArtistsFromSchedule.length) {
    html += '<div style="font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--text-tertiary); margin:10px 0 6px; font-weight:600;">From Release Schedule</div>';
    _schedArtistsFromSchedule.forEach(n => { html += makeCheckbox(n); });
  }
  if (!html) html = '<div style="color:var(--text-tertiary); font-size:13px;">No artists found.</div>';
  container.innerHTML = html;
  _updateScheduleArtistCount();
}

function scheduleArtistSelectAll(select) {
  const filter = (document.getElementById('schedule-artist-filter').value || '').toLowerCase();
  document.querySelectorAll('.sched-artist-cb').forEach(cb => {
    if (!filter || cb.value.toLowerCase().includes(filter)) cb.checked = select;
  });
  _updateScheduleArtistCount();
}

function _updateScheduleArtistCount() {
  const count = document.querySelectorAll('.sched-artist-cb:checked').length;
  document.getElementById('schedule-artist-count').textContent = count + ' artist' + (count !== 1 ? 's' : '') + ' selected';
}

document.getElementById('schedule-artist-filter').addEventListener('input', function() {
  const checked = new Set();
  document.querySelectorAll('.sched-artist-cb:checked').forEach(cb => checked.add(cb.value));
  _renderScheduleArtists();
  document.querySelectorAll('.sched-artist-cb').forEach(cb => {
    if (checked.has(cb.value)) cb.checked = true;
  });
  _updateScheduleArtistCount();
});

function toggleScheduleArtistSource() {
  const source = document.querySelector('input[name="schedule-artist-source"]:checked').value;
  document.getElementById('schedule-artist-picker').style.display = source === 'manual' ? '' : 'none';
  if (source === 'manual') _loadScheduleArtists();
}

function toggleScheduleCron() {
  const val = document.querySelector('input[name="schedule-cadence"]:checked').value;
  document.getElementById('schedule-custom-cron').style.display = val === 'custom' ? '' : 'none';
  if (val !== 'custom') document.getElementById('cron-preview').style.display = 'none';
}

function updateCronPreview() {
  const input = document.getElementById('schedule-cron-input').value.trim();
  const previewEl = document.getElementById('cron-preview');
  if (!input) { previewEl.style.display = 'none'; return; }
  const cv = validateCron(input);
  if (cv.error) {
    previewEl.style.display = '';
    previewEl.innerHTML = `<span style="color:var(--error);">${escapeHtml(cv.error)}</span>`;
    return;
  }
  const runs = cronNextRuns(input, 3);
  if (runs.length) {
    previewEl.style.display = '';
    previewEl.innerHTML = '<strong>Next runs:</strong> ' + runs.map(d => d.toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})).join(' &rarr; ');
  } else {
    previewEl.style.display = 'none';
  }
}

function showScheduleForm(editId) {
  const form = document.getElementById('schedule-form');
  form.style.display = '';
  document.getElementById('schedule-edit-id').value = editId || '';
  document.getElementById('schedule-form-title').textContent = editId ? 'Edit Schedule' : 'New Schedule';

  if (editId) {
    const s = _schedulesCache.find(x => x.id === editId);
    if (!s) return;
    document.getElementById('schedule-name').value = s.name;
    document.querySelector(`input[name="schedule-artist-source"][value="${s.artist_source}"]`).checked = true;
    document.querySelector(`input[name="schedule-mode"][value="${s.mode}"]`).checked = true;
    document.querySelector(`input[name="schedule-region"][value="${s.radio_region}"]`).checked = true;
    document.querySelector(`input[name="schedule-time-range"][value="${s.radio_time_range}"]`).checked = true;
    document.getElementById('schedule-inc-radio').checked = s.include_radio;
    document.getElementById('schedule-inc-dsp').checked = s.include_dsp;
    document.getElementById('schedule-inc-press').checked = s.include_press;
    document.getElementById('schedule-auto-append').checked = s.auto_append_gdocs || false;
    // Set cadence
    const presets = ['0 18 * * *', '0 9 * * 1', '0 18 * * 5'];
    if (presets.includes(s.cron_expression)) {
      document.querySelector(`input[name="schedule-cadence"][value="${s.cron_expression}"]`).checked = true;
    } else {
      document.querySelector('input[name="schedule-cadence"][value="custom"]').checked = true;
      document.getElementById('schedule-cron-input').value = s.cron_expression;
    }
    toggleScheduleCron();
    toggleScheduleArtistSource();
    // Pre-check artists if manual
    if (s.artist_source === 'manual') {
      _loadScheduleArtists().then(() => {
        const set = new Set(s.artists);
        document.querySelectorAll('.sched-artist-cb').forEach(cb => { cb.checked = set.has(cb.value); });
        _updateScheduleArtistCount();
      });
    }
  } else {
    document.getElementById('schedule-name').value = '';
    document.querySelector('input[name="schedule-artist-source"][value="manual"]').checked = true;
    document.querySelector('input[name="schedule-mode"][value="snapshot"]').checked = true;
    document.querySelector('input[name="schedule-cadence"][value="0 18 * * *"]').checked = true;
    document.querySelector('input[name="schedule-region"][value="latam"]').checked = true;
    document.querySelector('input[name="schedule-time-range"][value="7d"]').checked = true;
    document.getElementById('schedule-inc-radio').checked = true;
    document.getElementById('schedule-inc-dsp').checked = true;
    document.getElementById('schedule-inc-press').checked = true;
    document.getElementById('schedule-auto-append').checked = false;
    document.getElementById('schedule-cron-input').value = '';
    toggleScheduleCron();
    toggleScheduleArtistSource();
    _loadScheduleArtists();
  }
}

function hideScheduleForm() {
  document.getElementById('schedule-form').style.display = 'none';
}

async function saveSchedule() {
  const editId = document.getElementById('schedule-edit-id').value;
  const name = document.getElementById('schedule-name').value.trim();
  if (!name) return showToast('Please enter a schedule name.');

  const artistSource = document.querySelector('input[name="schedule-artist-source"]:checked').value;
  let artists = [];
  if (artistSource === 'manual') {
    document.querySelectorAll('.sched-artist-cb:checked').forEach(cb => artists.push(cb.value));
    if (!artists.length) return showToast('Please select at least one artist.');
  }

  const cadenceVal = document.querySelector('input[name="schedule-cadence"]:checked').value;
  const cronExpression = cadenceVal === 'custom' ? document.getElementById('schedule-cron-input').value.trim() : cadenceVal;
  if (!cronExpression) return showToast('Please enter a cron expression.');
  if (cadenceVal === 'custom') {
    const cv = validateCron(cronExpression);
    if (cv.error) return showToast(cv.error);
  }

  const payload = {
    name,
    artist_source: artistSource,
    artists,
    mode: document.querySelector('input[name="schedule-mode"]:checked').value,
    cron_expression: cronExpression,
    radio_region: document.querySelector('input[name="schedule-region"]:checked').value,
    radio_time_range: document.querySelector('input[name="schedule-time-range"]:checked').value,
    include_radio: document.getElementById('schedule-inc-radio').checked,
    include_dsp: document.getElementById('schedule-inc-dsp').checked,
    include_press: document.getElementById('schedule-inc-press').checked,
    auto_append_gdocs: document.getElementById('schedule-auto-append').checked,
  };

  try {
    const url = editId ? `/api/schedules/${editId}` : '/api/schedules';
    const method = editId ? 'PUT' : 'POST';
    const resp = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await resp.json();
    if (!resp.ok) return showToast(data.error || 'Failed to save schedule.');
    hideScheduleForm();
    await loadSchedules();
    showToast(editId ? 'Schedule updated.' : 'Schedule created.');
  } catch (e) {
    showToast('Failed to save schedule.');
  }
}

async function deleteSchedule(id) {
  if (!confirm('Delete this schedule and all its run history?')) return;
  try {
    await fetch(`/api/schedules/${id}`, {method:'DELETE'});
    await loadSchedules();
    await loadScheduleHistory();
    showToast('Schedule deleted.');
  } catch (e) {
    showToast('Failed to delete schedule.');
  }
}

async function toggleSchedule(id, enabled) {
  try {
    await fetch(`/api/schedules/${id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled})});
    await loadSchedules();
  } catch (e) {
    showToast('Failed to update schedule.');
  }
}

async function triggerSchedule(id) {
  const logEl = document.getElementById('schedule-log');
  const progressEl = document.getElementById('schedule-progress');
  const resultEl = document.getElementById('schedule-result');
  logEl.textContent = '';
  resultEl.innerHTML = '';

  try {
    const resp = await fetch(`/api/schedules/${id}/run`, {method:'POST'});
    const data = await resp.json();
    if (!resp.ok) return showToast(data.error || 'Failed to trigger run.');

    pollJob(data.job_id, logEl, progressEl, resultEl, (result) => {
      if (result.status === 'done') {
        resultEl.classList.add('visible');
        resultEl.innerHTML = `<div class="result-success">${escapeHtml(result.result || 'Complete')}</div>`;
      } else {
        showError(resultEl, result.error || 'Failed');
      }
      loadSchedules();
      loadScheduleHistory();
    });
  } catch (e) {
    showToast('Failed to trigger schedule.');
  }
}

function cronToHuman(expr) {
  const map = {
    '0 18 * * *': 'Daily 6 PM',
    '0 9 * * 1': 'Mon 9 AM',
    '0 18 * * 5': 'Fri 6 PM',
    '*/5 * * * *': 'Every 5 min',
    '*/10 * * * *': 'Every 10 min',
    '*/30 * * * *': 'Every 30 min',
    '0 * * * *': 'Hourly',
    '0 0 * * *': 'Daily midnight',
    '0 12 * * *': 'Daily noon',
  };
  return map[expr] || expr;
}

/* ============================================================
   ACTIVE JOBS DRAWER LOGIC
   ============================================================ */
let activeJobs = new Map(); // jobId -> { title, progress, status, element }

function toggleJobDrawer() {
  document.getElementById('job-drawer').classList.toggle('active');
}

function updateJobBadge() {
  const badge = document.getElementById('job-badge');
  const count = activeJobs.size;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = 'flex';
  } else {
    badge.style.display = 'none';
  }
}

function getLatestJobLogLine(logLines) {
  if (!Array.isArray(logLines)) return '';
  for (let i = logLines.length - 1; i >= 0; i -= 1) {
    const line = String(logLines[i] || '').trim();
    if (line) return line;
  }
  return '';
}

function getJobPhaseLabel(data) {
  if (typeof data.current_step === 'string' && data.current_step.trim()) {
    return data.current_step.trim();
  }
  return getLatestJobLogLine(data.log) || 'Working...';
}

function getDeterminateJobProgress(data) {
  if (data?.determinate_progress !== true || !Number.isFinite(data.progress)) {
    return null;
  }
  return Math.max(0, Math.min(100, data.progress));
}

function renderDrawerJobActivity(item, data) {
  const progressWrap = item.querySelector('.job-item-progress');
  const bar = item.querySelector('.job-item-bar');
  const pct = item.querySelector('.job-item-pct');
  const status = item.querySelector('.job-item-status');
  const progress = getDeterminateJobProgress(data);
  const phaseLabel = getJobPhaseLabel(data);
  const hasDeterminateProgress = progress !== null;

  progressWrap.classList.toggle('is-indeterminate', !hasDeterminateProgress);
  status.classList.toggle('is-live', !hasDeterminateProgress && data.status === 'running');

  if (hasDeterminateProgress) {
    bar.style.width = `${progress}%`;
    pct.hidden = false;
    pct.textContent = `${Math.round(progress)}%`;
  } else {
    bar.style.removeProperty('width');
    pct.hidden = true;
    pct.textContent = '';
  }

  status.textContent = phaseLabel;
  status.title = phaseLabel;

  return { bar, pct, status, progressWrap };
}

function addJobToDrawer(jobId, title) {
  if (activeJobs.has(jobId)) return;

  const list = document.getElementById('job-list');
  const empty = list.querySelector('.job-empty');
  if (empty) empty.remove();

  const item = document.createElement('div');
  item.className = 'job-item';
  item.id = `job-${jobId}`;
  item.innerHTML = `
    <div class="job-item-title">
      <span>${title}</span>
      <span class="job-item-pct" hidden></span>
    </div>
    <div class="job-item-progress is-indeterminate">
      <div class="job-item-bar"></div>
    </div>
    <div class="job-item-status is-live">Starting...</div>
  `;
  list.prepend(item);

  activeJobs.set(jobId, { title, element: item });
  updateJobBadge();
  pollJobStatus(jobId);
}

async function pollJobStatus(jobId) {
  if (!activeJobs.has(jobId)) return;

  try {
    const resp = await fetch(`/api/status/${jobId}/summary`);
    if (resp.status === 401) {
      const job = activeJobs.get(jobId);
      if (job) {
        const statusEl = job.element.querySelector('.job-item-status');
        if (statusEl) {
          statusEl.textContent = 'Signed out: log in again to resume status updates';
          statusEl.title = statusEl.textContent;
          statusEl.style.color = 'var(--error)';
        }
      }
      setTimeout(() => {
        if (!activeJobs.has(jobId)) return;
        const job = activeJobs.get(jobId);
        if (job) job.element.remove();
        activeJobs.delete(jobId);
        updateJobBadge();
        if (activeJobs.size === 0) {
          document.getElementById('job-list').innerHTML = '<div class="job-empty">No active tasks</div>';
        }
      }, 8000);
      return;
    }
    
    // Handle stale jobs (server restart or expired)
    if (resp.status === 404) {
      const job = activeJobs.get(jobId);
      if (job) {
        job.element.remove();
        activeJobs.delete(jobId);
        updateJobBadge();
        if (activeJobs.size === 0) {
          document.getElementById('job-list').innerHTML = '<div class="job-empty">No active tasks</div>';
        }
      }
      return;
    }

    const data = await resp.json();

    const job = activeJobs.get(jobId);
    if (!job) return;

    const item = job.element;
    const { bar, pct, status, progressWrap } = renderDrawerJobActivity(item, data);

    if (data.status === 'done') {
      progressWrap.classList.remove('is-indeterminate');
      status.classList.remove('is-live');
      bar.style.width = '100%';
      pct.hidden = false;
      pct.textContent = '100%';
      status.textContent = 'Completed';
      status.title = 'Completed';
      status.style.color = 'var(--success)';
      
      // Remove from drawer after 5 seconds
      setTimeout(() => {
        item.style.opacity = '0';
        item.style.transform = 'translateX(20px)';
        setTimeout(() => {
          item.remove();
          activeJobs.delete(jobId);
          updateJobBadge();
          if (activeJobs.size === 0) {
            document.getElementById('job-list').innerHTML = '<div class="job-empty">No active tasks</div>';
          }
        }, 300);
      }, 5000);
      return;
    }

    if (data.status === 'error') {
      progressWrap.classList.remove('is-indeterminate');
      status.classList.remove('is-live');
      bar.style.removeProperty('width');
      pct.hidden = true;
      pct.textContent = '';
      status.textContent = 'Failed: ' + (data.error || 'Unknown error');
      status.title = status.textContent;
      status.style.color = 'var(--error)';
      setTimeout(() => {
        item.remove();
        activeJobs.delete(jobId);
        updateJobBadge();
        if (activeJobs.size === 0) {
          document.getElementById('job-list').innerHTML = '<div class="job-empty">No active tasks</div>';
        }
      }, 10000);
      return;
    }

    status.style.color = 'var(--text-secondary)';

    // Poll again
    setTimeout(() => pollJobStatus(jobId), 2000);

  } catch (err) {
    console.error('Job poll failed:', err);
    setTimeout(() => pollJobStatus(jobId), 5000);
  }
}

// Hook into existing job launchers
const originalFetch = window.fetch;
window.fetch = function() {
  return originalFetch.apply(this, arguments).then(async response => {
    // Check if it's a job start response (contains job_id)
    if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
      const clone = response.clone();
      try {
        const data = await clone.json();
        const startedJobId = data?.batch_id || data?.job_id;
        if (startedJobId) {
          // Identify tool from URL or data
          const url = arguments[0];
          let title = 'Automation Task';
          if (url.includes('radio')) title = 'Radio Report';
          else if (url.includes('press')) title = 'Press Pickup';
          else if (url.includes('dsp')) title = 'DSP Pickup';
          else if (url.includes('digest')) title = 'Weekly Digest';
          
          addJobToDrawer(startedJobId, title);
        }
      } catch (e) {}
    }
    return response;
  });
};

/* ============================================================
   CMD+K UNIFIED SEARCH LOGIC
   ============================================================ */
let searchData = {
  artists: [],
  tools: [
    { title: 'Radio Report', icon: '📻', id: 'radio', type: 'tool' },
    { title: 'Press Pickup', icon: '📰', id: 'press', type: 'tool' },
    { title: 'DSP Pickup', icon: '🎧', id: 'dsp', type: 'tool' },
    { title: 'Full Report Compiler', icon: '📊', id: 'report', type: 'tool' },
    { title: 'Proposal Generator', icon: '📝', id: 'proposal', type: 'tool' },
    { title: 'Weekly Digest', icon: '📬', id: 'digest', type: 'tool' },
    { title: 'Outlet Discovery', icon: '🔍', id: 'discovery', type: 'tool' },
    { title: 'PR Translator', icon: '🌐', id: 'pr', type: 'tool' },
    { title: 'Schedules', icon: '⏰', id: 'schedules', type: 'tool' },
    { title: 'Release Calendar', icon: '📅', url: '/calendar', type: 'page' },
    { title: 'Playlist Database', icon: '📂', url: '/playlists', type: 'page' },
    { title: 'Artist Dashboard', icon: '📈', url: '/dashboard', type: 'page' },
    { title: 'O.R.A.C.L.E.', icon: '🔮', url: '/oracle', type: 'page' }
  ]
};

let selectedSearchIdx = -1;
let currentSearchResults = [];

function toggleSearch(show) {
  const modal = document.getElementById('search-modal');
  const input = document.getElementById('search-input');
  
  if (show === undefined) show = !modal.classList.contains('active');
  
  if (show) {
    modal.classList.add('active');
    input.value = '';
    input.focus();
    renderSearchResults([]);
    if (searchData.artists.length === 0) fetchSearchData();
  } else {
    modal.classList.remove('active');
  }
}

async function fetchSearchData() {
  try {
    const resp = await fetch('/api/dashboard/artists');
    const data = await resp.json();
    const withData = (data.with_data || []).map(a => ({ title: a.name, meta: 'Artist Dashboard', url: `/dashboard?artist=${encodeURIComponent(a.name)}`, icon: '👤', type: 'artist' }));
    const fromSchedule = (data.from_schedule || []).map(a => ({ title: a, meta: 'From Release Schedule', id: a, icon: '👤', type: 'schedule' }));
    searchData.artists = [...withData, ...fromSchedule];
  } catch (e) {
    console.error('Failed to fetch search data:', e);
  }
}

function renderSearchResults(results) {
  const container = document.getElementById('search-results');
  currentSearchResults = results;
  selectedSearchIdx = results.length > 0 ? 0 : -1;
  
  if (results.length === 0) {
    container.innerHTML = document.getElementById('search-input').value 
      ? '<div class="search-empty">No results found</div>' 
      : '<div class="search-empty">Type to start searching...</div>';
    return;
  }
  
  let html = '';
  results.forEach((r, i) => {
    const isSelected = i === selectedSearchIdx ? 'selected' : '';
    html += `
      <div class="search-item ${isSelected}" onclick="executeSearchItem(${i})">
        <div class="search-item-icon">${r.icon}</div>
        <div class="search-item-info">
          <span class="search-item-title">${escapeHtml(r.title)}</span>
          ${r.meta ? `<span class="search-item-meta">${escapeHtml(r.meta)}</span>` : ''}
        </div>
      </div>
    `;
  });
  container.innerHTML = html;
}

function executeSearchItem(idx) {
  const item = currentSearchResults[idx];
  if (!item) return;
  
  toggleSearch(false);
  
  if (item.type === 'tool') {
    goToTool(item.id);
  } else if (item.type === 'page' || item.type === 'artist') {
    window.location.href = item.url;
  } else if (item.type === 'schedule') {
    // Jump to Radio and fill artist
    goToTool('radio');
    document.getElementById('radio-artist').value = item.id;
    // Also fill other tools just in case
    document.getElementById('press-artist').value = item.id;
    document.getElementById('dsp-artist').value = item.id;
  }
}

document.addEventListener('keydown', (e) => {
  // CMD+K or CTRL+K
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    toggleSearch();
  }
  
  const modal = document.getElementById('search-modal');
  if (!modal.classList.contains('active')) return;
  
  if (e.key === 'Escape') {
    toggleSearch(false);
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    selectedSearchIdx = Math.min(selectedSearchIdx + 1, currentSearchResults.length - 1);
    updateSearchSelection();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    selectedSearchIdx = Math.max(selectedSearchIdx - 1, 0);
    updateSearchSelection();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    executeSearchItem(selectedSearchIdx);
  }
});

function updateSearchSelection() {
  const items = document.querySelectorAll('.search-item');
  items.forEach((item, i) => {
    item.classList.toggle('selected', i === selectedSearchIdx);
    if (i === selectedSearchIdx) item.scrollIntoView({ block: 'nearest' });
  });
}

document.getElementById('search-input').addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase().trim();
  if (!q) {
    renderSearchResults([]);
    return;
  }
  
  const results = [
    ...searchData.tools.filter(t => t.title.toLowerCase().includes(q)),
    ...searchData.artists.filter(a => a.title.toLowerCase().includes(q))
  ].slice(0, 10);
  
  renderSearchResults(results);
});

// Close modal when clicking outside
document.getElementById('search-modal').addEventListener('click', (e) => {
  if (e.target.id === 'search-modal') toggleSearch(false);
});


// =====================================================================
// Google Docs Integration
// =====================================================================

async function loadGoogleStatus() {
  try {
    const resp = await fetch('/api/settings/google/status');
    return await resp.json();
  } catch { return { connected: false, email: null }; }
}

async function connectGoogle() {
  const statusEl = document.getElementById('google-status');
  statusEl.innerHTML = '<span style="color:var(--text-secondary)">Opening Google sign-in...</span>';
  try {
    const resp = await fetch('/api/settings/google/connect', { method: 'POST' });
    const data = await resp.json();
    if (data.ok) {
      // Open the auth URL in a new tab
      if (data.auth_url) window.open(data.auth_url, '_blank');
      statusEl.innerHTML = '<span style="color:var(--text-secondary)">Complete sign-in in the browser tab that just opened...</span>';
      // Poll for completion
      let polls = 0;
      const pollInterval = setInterval(async () => {
        polls++;
        if (polls > 90) { // stop after 3 min
          clearInterval(pollInterval);
          statusEl.innerHTML = '<span style="color:var(--accent)">Authorization timed out. Try again.</span>';
          return;
        }
        const s = await loadGoogleStatus();
        if (s.connected) {
          clearInterval(pollInterval);
          showToast('Google account connected!');
          refreshGoogleSettings();
        }
      }, 2000);
    } else {
      statusEl.innerHTML = `<span style="color:var(--accent)">${escapeHtml(data.error || 'Unknown error')}</span>`;
    }
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--accent)">Connection failed: ${escapeHtml(e.message)}</span>`;
  }
}

async function disconnectGoogle() {
  if (!confirm('Disconnect Google account? Linked docs will be preserved but appending will stop working.')) return;
  try {
    await fetch('/api/settings/google/disconnect', { method: 'POST' });
    showToast('Google account disconnected.');
    refreshGoogleSettings();
  } catch (e) { showToast('Failed to disconnect.'); }
}

function buildGoogleDocsSettingsActionsHtml() {
  let html = '';
  html += '<div style="margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card, var(--bg-secondary));">';
  html += '<div style="font-size:13px;font-weight:600;margin-bottom:4px;">Link Any Artist</div>';
  html += '<p style="font-size:12px;color:var(--text-secondary);margin:0 0 10px 0;">Add artists outside the current release schedule, including older releases that still need updates.</p>';
  html += '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">';
  html += '<input type="text" id="google-doc-manual-artist" placeholder="Artist name" style="flex:1;min-width:180px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--bg-primary);color:var(--text-primary);">';
  html += '<input type="text" id="google-doc-manual-url" placeholder="https://docs.google.com/document/d/..." style="flex:2;min-width:280px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--bg-primary);color:var(--text-primary);">';
  html += '<button class="btn btn-small" id="google-doc-manual-save" onclick="saveManualGoogleDocLink()">Link Artist</button>';
  html += '</div>';
  html += '<div id="google-doc-manual-result" style="margin-top:8px;font-size:12px;"></div>';
  html += '</div>';
  html += '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">';
  html += '<button class="btn btn-small btn-secondary" onclick="showBulkLinkUI()">Bulk Link Artists</button>';
  html += '</div>';
  return html;
}

async function saveManualGoogleDocLink() {
  const artistInput = document.getElementById('google-doc-manual-artist');
  const urlInput = document.getElementById('google-doc-manual-url');
  const saveBtn = document.getElementById('google-doc-manual-save');
  const resultEl = document.getElementById('google-doc-manual-result');
  if (!artistInput || !urlInput) return;

  const artistName = artistInput.value.trim();
  const docUrl = urlInput.value.trim();
  if (!artistName) return showToast('Please enter an artist name.');
  if (!docUrl) return showToast('Please paste a Google Doc URL.');
  if (!docUrl.includes('docs.google.com/document/d/')) {
    return showToast('Invalid Google Doc URL. Must contain docs.google.com/document/d/');
  }

  artistInput.disabled = true;
  urlInput.disabled = true;
  if (saveBtn) saveBtn.disabled = true;
  if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-secondary);">Linking artist...</span>';

  try {
    const resp = await fetch('/api/settings/google/docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist_name: artistName, doc_url: docUrl }),
    });
    const data = await resp.json();
    if (data.ok) {
      if (resultEl) {
        resultEl.innerHTML = `<span style="color:var(--success, #22c55e);">Linked ${escapeHtml(artistName)} to "${escapeHtml(data.doc_title || 'Google Doc')}".</span>`;
      }
      showToast(`Linked to "${data.doc_title}"`);
      await refreshGoogleSettings();
      return;
    }

    if (resultEl) {
      resultEl.innerHTML = `<span style="color:var(--accent);">${escapeHtml(data.error || 'Failed to link document.')}</span>`;
    }
    showToast(data.error || 'Failed to link document.');
  } catch (e) {
    if (resultEl) {
      resultEl.innerHTML = `<span style="color:var(--accent);">${escapeHtml(e.message)}</span>`;
    }
    showToast('Failed to link: ' + e.message);
  } finally {
    artistInput.disabled = false;
    urlInput.disabled = false;
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function refreshGoogleSettings() {
  const statusEl = document.getElementById('google-status');
  const docsEl = document.getElementById('google-linked-docs');
  if (!statusEl) return;

  const status = await loadGoogleStatus();
  if (status.connected) {
    statusEl.innerHTML = `<span style="color:var(--success, #22c55e)">Connected as ${escapeHtml(status.email || 'unknown')}</span>
      <button class="btn btn-small btn-secondary" onclick="disconnectGoogle()" style="margin-left:12px;">Disconnect</button>`;
  } else {
    statusEl.innerHTML = `<span style="color:var(--text-secondary)">Not connected</span>
      <button class="btn btn-small" onclick="connectGoogle()" style="margin-left:12px;">Connect Google Account</button>`;
  }

  // Load linked docs
  if (!docsEl) return;
  try {
    const resp = await fetch('/api/settings/google/docs');
    const docs = await resp.json();
    if (!docs.length) {
      docsEl.innerHTML = `<p style="color:var(--text-secondary);font-size:13px;">No Google Docs linked yet. Link docs from any tool's results page, add an artist manually below, or use bulk linking.</p>${buildGoogleDocsSettingsActionsHtml()}`;
      return;
    }
    let html = '<table style="width:100%;font-size:13px;border-collapse:collapse;">';
    html += '<tr style="text-align:left;color:var(--text-secondary);border-bottom:1px solid var(--border);"><th style="padding:6px 8px;">Artist</th><th style="padding:6px 8px;">Document</th><th style="padding:6px 8px;">Last Appended</th><th style="padding:6px 8px;">Status</th><th style="padding:6px 8px;"></th></tr>';
    for (const doc of docs) {
      const lastAppend = doc.last_appended_at ? new Date(doc.last_appended_at).toLocaleDateString() : 'Never';
      const statusBadge = doc.insertion_confirmed
        ? '<span style="color:var(--success, #22c55e);font-size:11px;">Ready</span>'
        : '<span style="color:var(--text-secondary);font-size:11px;">Needs setup</span>';
      html += `<tr style="border-bottom:1px solid var(--border);">
        <td style="padding:6px 8px;font-weight:500;">${escapeHtml(doc.artist_name)}</td>
        <td style="padding:6px 8px;"><a href="${escapeHtml(doc.doc_url)}" target="_blank" style="color:var(--link, #4a9eff);">Open Doc</a></td>
        <td style="padding:6px 8px;">${lastAppend}</td>
        <td style="padding:6px 8px;">${statusBadge}</td>
        <td style="padding:6px 8px;white-space:nowrap;">
          <button class="btn btn-small btn-secondary" onclick="undoGoogleDocAppend('${escapeAttr(doc.artist_name)}')" style="font-size:11px;padding:2px 6px;margin-right:4px;" title="Undo last append">Undo</button>
          <button class="btn btn-small btn-secondary" onclick="unlinkGoogleDoc('${escapeAttr(doc.artist_name)}')">Unlink</button>
        </td>
      </tr>`;
    }
    html += '</table>';
    html += buildGoogleDocsSettingsActionsHtml();
    docsEl.innerHTML = html;
  } catch { docsEl.innerHTML = '<p style="color:var(--accent)">Failed to load linked docs.</p>'; }
}

async function unlinkGoogleDoc(artistName) {
  if (!confirm(`Unlink Google Doc for "${artistName}"?`)) return;
  try {
    await fetch(`/api/settings/google/docs/${encodeURIComponent(artistName)}`, { method: 'DELETE' });
    showToast(`Unlinked doc for ${artistName}`);
    refreshGoogleSettings();
    // Also refresh inline doc section if visible
    const inlineEl = document.querySelector(`.gdoc-section[data-artist="${CSS.escape(artistName)}"]`);
    if (inlineEl) renderGoogleDocSection(inlineEl, artistName);
  } catch { showToast('Failed to unlink.'); }
}

async function undoGoogleDocAppend(artistName) {
  // Check if undo is available first
  try {
    const statusResp = await fetch(`/api/google/undo-status/${encodeURIComponent(artistName)}`);
    const status = await statusResp.json();
    if (!status.available) {
      showToast('No undo available (expired or no recent append).');
      return;
    }
  } catch { showToast('Could not check undo status.'); return; }

  if (!confirm(`Undo the last append for "${artistName}"? This will remove the most recently inserted report from the Google Doc.`)) return;

  try {
    const resp = await fetch(`/api/google/undo-append/${encodeURIComponent(artistName)}`, { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast(`Undo successful: ${data.characters_deleted} characters removed.`);
      refreshGoogleSettings();
    } else {
      showToast(data.error || 'Undo failed.');
    }
  } catch (e) { showToast('Undo failed: ' + e.message); }
}

async function showBulkLinkUI() {
  const docsEl = document.getElementById('google-linked-docs');
  if (!docsEl) return;

  // Also get already-linked docs
  let linkedDocs = {};
  try {
    const resp = await fetch('/api/settings/google/docs');
    const docs = await resp.json();
    for (const d of docs) linkedDocs[d.artist_name] = d.doc_url;
  } catch {}

  // Fetch artists from dashboard/history + release schedule, then merge linked docs.
  const artistMap = new Map();
  const addArtistOption = (artist) => {
    const rawName = typeof artist === 'string'
      ? artist
      : (artist && (artist.name || artist.artist_name || artist.artist));
    const name = (rawName || '').trim();
    if (!name) return;
    const key = name.toLowerCase();
    if (!artistMap.has(key)) artistMap.set(key, { name });
  };

  try {
    const resp = await fetch('/api/dashboard/artists');
    const data = await resp.json();
    for (const item of data.with_data || []) addArtistOption(item);
    for (const item of data.from_dashboard || []) addArtistOption(item);
    for (const item of data.from_schedule || []) addArtistOption(item);
    if (!artistMap.size) {
      for (const item of data.artists || (Array.isArray(data) ? data : [])) addArtistOption(item);
    }
  } catch {
    showToast('Could not load saved artist list.');
  }

  for (const name of Object.keys(linkedDocs)) addArtistOption(name);
  const artists = Array.from(artistMap.values()).sort((a, b) => a.name.localeCompare(b.name));

  let html = '<div style="margin-top:16px;padding:16px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card, var(--bg-secondary));">';
  html += '<h4 style="margin:0 0 12px 0;font-size:14px;">Bulk Link Google Docs</h4>';
  html += '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">Paste a Google Doc URL next to each artist. Already-linked artists are pre-filled, and artists from dashboard history are included alongside the release schedule.</p>';
  html += '<input type="text" id="bulk-link-search" placeholder="Filter artists..." oninput="filterBulkLinkTable()" style="width:100%;padding:6px 10px;margin-bottom:8px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--bg-primary);color:var(--text-primary);">';
  html += '<div style="max-height:400px;overflow-y:auto;border:1px solid var(--border);border-radius:4px;">';
  html += '<table id="bulk-link-table" style="width:100%;font-size:13px;border-collapse:collapse;">';
  html += '<tr style="text-align:left;color:var(--text-secondary);border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg-card, var(--bg-secondary));z-index:1;"><th style="padding:4px 8px;width:30%;">Artist</th><th style="padding:4px 8px;">Google Doc URL</th><th style="padding:4px 8px;width:60px;"></th></tr>';

  for (const a of artists) {
    const name = a.name || a.artist_name || a;
    const existing = linkedDocs[name] || '';
    html += `<tr class="bulk-link-row" data-artist-lower="${escapeAttr(name.toLowerCase())}" style="border-bottom:1px solid var(--border);">
      <td style="padding:4px 8px;font-weight:500;">${escapeHtml(name)}</td>
      <td style="padding:4px 8px;"><input type="text" class="bulk-link-url" data-artist="${escapeAttr(name)}" value="${escapeAttr(existing)}" placeholder="https://docs.google.com/document/d/..." style="width:100%;padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:12px;background:var(--bg-primary);color:var(--text-primary);"></td>
      <td style="padding:4px 8px;" class="bulk-link-status"></td>
    </tr>`;
  }
  html += '</table></div>';
  html += '<div style="margin-top:12px;display:flex;gap:8px;">';
  html += '<button class="btn btn-small" onclick="bulkValidateAll()">Validate All</button>';
  html += '<button class="btn btn-small" onclick="bulkSaveAll()">Save All</button>';
  html += '<button class="btn btn-small btn-secondary" onclick="refreshGoogleSettings()">Cancel</button>';
  html += '</div>';
  html += '<div id="bulk-link-result" style="margin-top:8px;font-size:13px;"></div>';
  html += '</div>';

  docsEl.innerHTML += html;
  document.getElementById('bulk-link-search').focus();
}

function filterBulkLinkTable() {
  const q = (document.getElementById('bulk-link-search').value || '').toLowerCase();
  for (const row of document.querySelectorAll('.bulk-link-row')) {
    row.style.display = row.dataset.artistLower.includes(q) ? '' : 'none';
  }
}

async function bulkValidateAll() {
  const rows = document.querySelectorAll('#bulk-link-table .bulk-link-url');
  for (const input of rows) {
    const statusTd = input.closest('tr').querySelector('.bulk-link-status');
    const url = input.value.trim();
    if (!url) { statusTd.innerHTML = ''; continue; }
    if (!url.includes('docs.google.com/document/d/')) {
      statusTd.innerHTML = '<span style="color:#f87171;font-size:11px;">\u2717</span>';
      continue;
    }
    statusTd.innerHTML = '<span style="color:var(--text-secondary);font-size:11px;">...</span>';
    try {
      const docId = url.split('/document/d/')[1].split('/')[0];
      const resp = await fetch(`/api/google/doc-info/${docId}`);
      const data = await resp.json();
      if (data.accessible) {
        statusTd.innerHTML = '<span style="color:#4ade80;font-size:11px;">\u2713</span>';
      } else {
        statusTd.innerHTML = '<span style="color:#f87171;font-size:11px;">\u2717</span>';
      }
    } catch {
      statusTd.innerHTML = '<span style="color:#f87171;font-size:11px;">\u2717</span>';
    }
  }
}

async function bulkSaveAll() {
  const rows = document.querySelectorAll('#bulk-link-table .bulk-link-url');
  const mappings = [];
  for (const input of rows) {
    const url = input.value.trim();
    if (!url || !url.includes('docs.google.com/document/d/')) continue;
    mappings.push({ artist_name: input.dataset.artist, doc_url: url });
  }

  if (!mappings.length) return showToast('No valid URLs to save.');

  const resultEl = document.getElementById('bulk-link-result');
  if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-secondary);">Saving & scanning...</span>';

  try {
    const resp = await fetch('/api/settings/google/docs/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mappings }),
    });
    const data = await resp.json();
    const results = data.results || [];
    const ok = results.filter(r => r.ok).length;
    const fail = results.filter(r => !r.ok).length;

    // Update status cells
    for (const r of results) {
      const input = document.querySelector(`#bulk-link-table .bulk-link-url[data-artist="${CSS.escape(r.artist_name)}"]`);
      if (!input) continue;
      const statusTd = input.closest('tr').querySelector('.bulk-link-status');
      if (r.ok) {
        statusTd.innerHTML = '<span style="color:#4ade80;font-size:11px;">\u2713</span>';
      } else {
        statusTd.innerHTML = `<span style="color:#f87171;font-size:11px;" title="${escapeAttr(r.error)}">\u2717</span>`;
      }
    }

    if (resultEl) resultEl.innerHTML = `<span style="color:var(--text-primary);">${ok} linked${fail ? `, ${fail} failed` : ''}.</span>`;
    showToast(`${ok} docs linked successfully.`);
    setTimeout(() => refreshGoogleSettings(), 2000);
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span style="color:#f87171;">Error: ${escapeHtml(e.message)}</span>`;
  }
}

async function renderGoogleDocSection(containerEl, artistName) {
  if (!artistName) { containerEl.innerHTML = ''; return; }
  containerEl.setAttribute('data-artist', artistName);

  try {
    const resp = await fetch(`/api/google/artist-doc/${encodeURIComponent(artistName)}`);
    const doc = await resp.json();

    if (doc && doc.doc_url) {
      const lastDate = doc.last_appended_at ? new Date(doc.last_appended_at).toLocaleDateString() : 'Never';
      const jobId = containerEl.getAttribute('data-job-id') || '';
      containerEl.innerHTML = `
        <div style="margin-top:16px;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card, var(--bg-secondary));">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-size:16px;">&#128196;</span>
            <span style="font-size:13px;"><strong>Linked to:</strong> <a href="${escapeHtml(doc.doc_url)}" target="_blank" style="color:var(--link, #4a9eff);">Google Doc</a></span>
            <span style="font-size:12px;color:var(--text-secondary);">Last updated: ${lastDate}</span>
            <button class="btn btn-small" id="gdoc-append-btn-${CSS.escape(artistName)}" onclick="appendToGoogleDoc('${escapeAttr(artistName)}')" style="margin-left:auto;">Append to Google Doc</button>
            <button class="btn btn-small btn-secondary" onclick="unlinkGoogleDoc('${escapeAttr(artistName)}')">Unlink</button>
          </div>
          <div id="gdoc-append-status-${CSS.escape(artistName)}" style="margin-top:8px;font-size:13px;display:none;"></div>
        </div>`;
    } else {
      containerEl.innerHTML = `
        <div style="margin-top:16px;padding:12px 16px;border:1px dashed var(--border);border-radius:8px;">
          <div style="font-size:13px;color:var(--text-secondary);margin-bottom:8px;">No Google Doc linked for <strong>${escapeHtml(artistName)}</strong></div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <input type="text" id="gdoc-url-${CSS.escape(artistName)}" placeholder="Paste Google Doc URL" style="flex:1;min-width:200px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--bg-primary);color:var(--text-primary);">
            <button class="btn btn-small" onclick="linkGoogleDoc('${escapeAttr(artistName)}')">Link & Save</button>
          </div>
        </div>`;
    }
  } catch {
    containerEl.innerHTML = '';
  }
}

async function linkGoogleDoc(artistName) {
  const input = document.getElementById(`gdoc-url-${CSS.escape(artistName)}`);
  if (!input) return;
  const url = input.value.trim();
  if (!url) return showToast('Please paste a Google Doc URL.');
  if (!url.includes('docs.google.com/document/d/')) return showToast('Invalid Google Doc URL. Must contain docs.google.com/document/d/');

  input.disabled = true;
  try {
    const resp = await fetch('/api/settings/google/docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist_name: artistName, doc_url: url }),
    });
    const data = await resp.json();
    if (data.ok) {
      showToast(`Linked to "${data.doc_title}"`);
      const container = input.closest('.gdoc-section') || input.closest('[data-artist]');
      if (container) renderGoogleDocSection(container, artistName);
      refreshGoogleSettings();
    } else {
      showToast(data.error || 'Failed to link document.');
      input.disabled = false;
    }
  } catch (e) {
    showToast('Failed to link: ' + e.message);
    input.disabled = false;
  }
}

function appendGoogleDocSectionToResults(resultEl, artistName, jobId) {
  if (!artistName) return;
  let gdocEl = resultEl.querySelector('.gdoc-section');
  if (!gdocEl) {
    gdocEl = document.createElement('div');
    gdocEl.className = 'gdoc-section';
    resultEl.appendChild(gdocEl);
  }
  if (jobId) gdocEl.setAttribute('data-job-id', jobId);
  renderGoogleDocSection(gdocEl, artistName);
}

async function appendToGoogleDoc(artistName) {
  const btn = document.getElementById(`gdoc-append-btn-${CSS.escape(artistName)}`);
  const statusEl = document.getElementById(`gdoc-append-status-${CSS.escape(artistName)}`);
  if (!btn || !statusEl) return;

  btn.disabled = true;
  btn.textContent = 'Appending...';
  statusEl.style.display = 'block';
  statusEl.innerHTML = '<span style="color:var(--text-secondary)">Appending report to Google Doc...</span>';

  // Find the job_id from the closest gdoc-section
  const gdocSection = btn.closest('.gdoc-section') || btn.closest('[data-job-id]');
  const jobId = gdocSection ? gdocSection.getAttribute('data-job-id') : null;

  try {
    let resp;
    if (jobId) {
      // Use append-from-job endpoint (has structured data)
      resp = await fetch(`/api/google/append-from-job/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artist_name: artistName }),
      });
    } else {
      // No job_id — can't append without data
      statusEl.innerHTML = '<span style="color:var(--warning, #e8a838)">No report data available to append. Run a report first.</span>';
      btn.disabled = false;
      btn.textContent = 'Append to Google Doc';
      return;
    }

    const data = await resp.json();
    if (data.success) {
      statusEl.innerHTML = `<span style="color:var(--success, #4caf50)">Report appended (${data.characters_inserted} chars). <a href="javascript:void(0)" onclick="const s=this.closest('.gdoc-section');if(s)renderGoogleDocSection(s,'${escapeAttr(artistName)}')" style="color:var(--link, #4a9eff);">Refresh</a></span>`;
      btn.textContent = 'Appended';
      showToast('Report appended to Google Doc');
    } else {
      statusEl.innerHTML = `<span style="color:var(--error, #ef5350)">${escapeHtml(data.error || 'Append failed')}. You can still download the .docx and paste manually.</span>`;
      btn.disabled = false;
      btn.textContent = 'Append to Google Doc';
    }
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--error, #ef5350)">Failed: ${escapeHtml(e.message)}</span>`;
    btn.disabled = false;
    btn.textContent = 'Append to Google Doc';
  }
}

// =====================================================================
// Settings — Admin Gate & Data Loading
// =====================================================================

window._adminUnlocked = false;

async function unlockSettings() {
  const input = document.getElementById('admin-pass-input');
  const errEl = document.getElementById('admin-gate-error');
  errEl.style.display = 'none';
  try {
    const resp = await fetch('/api/admin/auth', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: input.value})
    });
    const data = await resp.json();
    if (data.ok) {
      window._adminUnlocked = true;
      document.getElementById('settings-admin-gate').style.display = 'none';
      document.getElementById('settings-content').style.display = '';
      refreshGoogleSettings();
      loadSettingsCredentials();
      loadSettingsDataSources();
    } else {
      errEl.textContent = data.error || 'Wrong password.';
      errEl.style.display = '';
      input.value = '';
      input.focus();
    }
  } catch (e) {
    errEl.textContent = 'Connection error. Try again.';
    errEl.style.display = '';
  }
}

async function loadSettingsCredentials() {
  const container = document.getElementById('settings-credentials');
  try {
    const resp = await fetch('/api/settings/credentials');
    const data = await resp.json();
    if (!data.services || !data.services.length) {
      container.innerHTML = '<span style="color:var(--text-tertiary);font-size:13px;">No services configured.</span>';
      return;
    }
    let html = '';
    for (const svc of data.services) {
      const allConfigured = svc.fields.every(f => f.configured);
      html += `<div class="card">`;
      html += `<div style="display:flex;justify-content:space-between;align-items:flex-start;">`;
      html += `<div>`;
      html += `<div style="font-weight:600;font-size:15px;">${escapeHtml(svc.label)}</div>`;
      html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:2px;">${escapeHtml(svc.used_by)}</div>`;
      html += `</div>`;
      html += `<span class="cred-status ${allConfigured ? 'ok' : 'missing'}" title="${allConfigured ? 'Configured' : 'Not configured'}"></span>`;
      html += `</div>`;

      // Field values
      html += `<div style="margin-top:10px;font-size:13px;font-family:monospace;color:var(--text-secondary);">`;
      for (const f of svc.fields) {
        html += `<div>${escapeHtml(f.label)}: ${f.configured ? escapeHtml(f.masked) : '<span style="color:var(--error,#c43030);">Not set</span>'}</div>`;
      }
      html += `</div>`;

      // Test result area
      html += `<div id="cred-test-${svc.id}" style="margin-top:8px;font-size:12px;"></div>`;

      // Edit form (hidden)
      html += `<div id="cred-edit-${svc.id}" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);">`;
      for (const f of svc.fields) {
        const inputType = f.label.toLowerCase().includes('password') ? 'password' : 'text';
        html += `<div style="margin-bottom:8px;">`;
        html += `<label style="font-size:11px;font-weight:600;color:var(--text-tertiary);">${escapeHtml(f.label)}</label>`;
        if (f.textarea) {
          html += `<textarea class="cred-input" data-key="${f.key}" placeholder="Paste the full JSON contents here" rows="6" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-primary);font-family:monospace;font-size:12px;margin-top:2px;resize:vertical;"></textarea>`;
        } else {
          html += `<input type="${inputType}" class="cred-input" data-key="${f.key}" placeholder="Enter new ${escapeHtml(f.label.toLowerCase())}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-primary);font-family:monospace;font-size:13px;margin-top:2px;">`;
        }
        html += `</div>`;
      }
      html += `<div style="display:flex;gap:8px;">`;
      html += `<button class="btn btn-small" onclick="saveCredential('${svc.id}')">Save</button>`;
      html += `<button class="btn btn-small btn-secondary" onclick="document.getElementById('cred-edit-${svc.id}').style.display='none'">Cancel</button>`;
      html += `</div></div>`;

      // Action buttons
      html += `<div style="margin-top:12px;display:flex;gap:8px;">`;
      html += `<button class="btn btn-small btn-secondary" id="cred-test-btn-${svc.id}" onclick="testCredential('${svc.id}')">Test Connection</button>`;
      html += `<button class="btn btn-small btn-secondary" onclick="toggleCredentialEdit('${svc.id}')">Edit</button>`;
      html += `</div>`;

      html += `</div>`;
    }
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<span style="color:var(--error);">Failed to load credentials: ${escapeHtml(e.message)}</span>`;
  }
}

async function testCredential(serviceId) {
  const btn = document.getElementById(`cred-test-btn-${serviceId}`);
  const resultEl = document.getElementById(`cred-test-${serviceId}`);
  btn.disabled = true;
  btn.textContent = 'Testing...';
  resultEl.innerHTML = '';
  try {
    const resp = await fetch(`/api/settings/credentials/${serviceId}/test`, { method: 'POST' });
    const data = await resp.json();
    if (data.ok) {
      resultEl.innerHTML = `<span style="color:#2ea043;">${checkSvg} ${escapeHtml(data.message)}</span>`;
    } else {
      resultEl.innerHTML = `<span style="color:var(--error,#c43030);">${errorSvg} ${escapeHtml(data.error)}</span>`;
    }
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--error);">${errorSvg} ${escapeHtml(e.message)}</span>`;
  }
  btn.disabled = false;
  btn.textContent = 'Test Connection';
}

function toggleCredentialEdit(serviceId) {
  const el = document.getElementById(`cred-edit-${serviceId}`);
  el.style.display = el.style.display === 'none' ? '' : 'none';
}

async function saveCredential(serviceId) {
  const editEl = document.getElementById(`cred-edit-${serviceId}`);
  const inputs = editEl.querySelectorAll('.cred-input');
  const body = {};
  let empty = true;
  inputs.forEach(inp => {
    const val = inp.value.trim();
    if (val) { body[inp.dataset.key] = val; empty = false; }
  });
  if (empty) return showToast('Please fill in at least one field.');
  try {
    const resp = await fetch(`/api/settings/credentials/${serviceId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.ok) {
      showToast('Credentials saved.');
      editEl.style.display = 'none';
      loadSettingsCredentials();
    } else {
      showToast(data.error || 'Failed to save.');
    }
  } catch (e) {
    showToast('Failed to save credentials.');
  }
}

function formatDataDate(ts) {
  // Accept epoch seconds or ISO string
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d)) return null;
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function dataDaysAgo(ts) {
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d)) return null;
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}

function staleTag(days, label) {
  if (days === null) return '';
  if (days > 30) return `<div style="margin-top:4px;font-size:11px;color:var(--error,#c43030);">Updated ${days}d ago — re-scan recommended</div>`;
  return '';
}

async function loadSettingsDataSources() {
  const container = document.getElementById('settings-data-sources');
  try {
    const resp = await fetch('/api/settings/data-sources');
    const data = await resp.json();

    // Store for stale banners on other tabs
    window._dataFreshness = data;
    updateStaleBanners(data);

    let html = '<div class="settings-stats-grid">';

    // Press DB
    const pdb = data.press_db || {};
    html += `<div class="card"><div style="font-weight:600;font-size:13px;margin-bottom:4px;">Press Database</div>`;
    if (pdb.error) {
      html += `<div style="color:var(--error);font-size:12px;">${escapeHtml(pdb.error)}</div>`;
    } else {
      html += `<div style="font-size:24px;font-weight:700;">${(pdb.total || 0).toLocaleString()}</div>`;
      html += `<div style="font-size:11px;color:var(--text-tertiary);">${(pdb.with_url || 0).toLocaleString()} with URLs</div>`;
      if (pdb.updated) {
        html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px;">Updated: ${formatDataDate(pdb.updated)}</div>`;
        html += staleTag(dataDaysAgo(pdb.updated));
      }
    }
    html += `</div>`;

    // Playlists
    const pl = data.playlists || {};
    html += `<div class="card"><div style="font-weight:600;font-size:13px;margin-bottom:4px;">Playlist Database</div>`;
    if (pl.error) {
      html += `<div style="color:var(--error);font-size:12px;">${escapeHtml(pl.error)}</div>`;
    } else {
      html += `<div style="font-size:24px;font-weight:700;">${(pl.total || 0).toLocaleString()}</div>`;
      html += `<div style="font-size:11px;color:var(--text-tertiary);">editorial playlists</div>`;
      if (pl.updated) {
        html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px;">Updated: ${formatDataDate(pl.updated)}</div>`;
        html += staleTag(dataDaysAgo(pl.updated));
      }
    }
    html += `</div>`;

    // Feed Registry
    const fr = data.feed_registry || {};
    html += `<div class="card"><div style="font-weight:600;font-size:13px;margin-bottom:4px;">Feed Registry</div>`;
    if (fr.error) {
      html += `<div style="color:var(--error);font-size:12px;">${escapeHtml(fr.error)}</div>`;
    } else {
      html += `<div style="font-size:24px;font-weight:700;">${(fr.rss || 0) + (fr.wp || 0)}</div>`;
      html += `<div style="font-size:11px;color:var(--text-tertiary);">${fr.rss || 0} RSS + ${fr.wp || 0} WP of ${(fr.scanned || 0).toLocaleString()} scanned</div>`;
      if (fr.generated) {
        html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px;">Scanned: ${formatDataDate(fr.generated)}</div>`;
        html += staleTag(dataDaysAgo(fr.generated));
      }
    }
    html += `</div>`;

    // Social Handles
    const sh = data.social_handles || {};
    html += `<div class="card"><div style="font-weight:600;font-size:13px;margin-bottom:4px;">Social Handles</div>`;
    if (sh.error) {
      html += `<div style="color:var(--error);font-size:12px;">${escapeHtml(sh.error)}</div>`;
    } else {
      html += `<div style="font-size:24px;font-weight:700;">${(sh.with_handles || 0).toLocaleString()}</div>`;
      html += `<div style="font-size:11px;color:var(--text-tertiary);">of ${(sh.scanned || 0).toLocaleString()} outlets with social</div>`;
      if (sh.generated) {
        html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px;">Scanned: ${formatDataDate(sh.generated)}</div>`;
        html += staleTag(dataDaysAgo(sh.generated));
      }
    }
    html += `</div>`;

    // Release Schedule
    const rs = data.release_schedule || {};
    html += `<div class="card"><div style="font-weight:600;font-size:13px;margin-bottom:4px;">Release Schedule</div>`;
    if (rs.error) {
      html += `<div style="color:var(--error);font-size:12px;">${escapeHtml(rs.error)}</div>`;
    } else {
      html += `<div style="font-size:24px;font-weight:700;">${(rs.total || 0).toLocaleString()}</div>`;
      html += `<div style="font-size:11px;color:var(--text-tertiary);">releases (live from Google Sheets)</div>`;
    }
    html += `</div>`;

    html += '</div>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<span style="color:var(--error);">Failed to load data sources: ${escapeHtml(e.message)}</span>`;
  }
}

function updateStaleBanners(data) {
  const STALE_DAYS = 30;
  const banners = [
    { id: 'stale-banner-press', tab: 'tab-press', source: data.press_db, label: 'Press database', dateKey: 'updated' },
    { id: 'stale-banner-dsp', tab: 'tab-dsp', source: data.playlists, label: 'Playlist database', dateKey: 'updated' },
  ];
  for (const b of banners) {
    // Remove old banner if any
    const old = document.getElementById(b.id);
    if (old) old.remove();

    const src = b.source || {};
    const ts = src[b.dateKey] || src.generated;
    if (!ts) continue;
    const days = dataDaysAgo(ts);
    if (days === null || days <= STALE_DAYS) continue;

    const tabEl = document.getElementById(b.tab);
    if (!tabEl) continue;
    const banner = document.createElement('div');
    banner.id = b.id;
    banner.style.cssText = 'padding:10px 14px;margin-bottom:14px;border-radius:8px;font-size:12px;background:rgba(196,48,48,0.08);border:1px solid rgba(196,48,48,0.2);color:var(--text-secondary);';
    banner.innerHTML = `${b.label} hasn't been updated in <strong>${days} days</strong>. Some new entries may be missing. <a href="#" onclick="switchTab('settings');return false;" style="color:var(--accent);">Check Settings</a>`;
    tabEl.insertBefore(banner, tabEl.children[1]); // after tips
  }
}

// Fetch freshness data on page load (for stale banners)
fetch('/api/settings/data-sources').then(r => r.json()).then(data => {
  window._dataFreshness = data;
  updateStaleBanners(data);
}).catch(() => {});
