'use strict';

let currentMode = 'quick';
let ruleSeq     = 0;
let eventSource = null;

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  try {
    const res = await apiFetch('/api/status');
    if (res.connected) {
      setConnected(res.name);
      await loadLibraries();
    } else {
      setBadge('red', res.error || 'Not connected');
      openModal();
    }
  } catch {
    setBadge('red', 'Server unreachable');
    openModal();
  }
}

async function loadLibraries() {
  const res = await apiFetch('/api/libraries');
  const sel = document.getElementById('library-select');
  sel.innerHTML = '';
  res.libraries.forEach(lib => {
    const opt = document.createElement('option');
    opt.value = lib;
    opt.textContent = lib;
    sel.appendChild(opt);
  });
  sel.disabled = false;
  document.getElementById('build-btn').disabled   = false;
  document.getElementById('preview-btn').disabled = false;
  document.getElementById('destroy-btn').disabled = false;
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function setConnected(name) {
  setBadge('green', `Connected · ${name}`);
}

function setBadge(color, text) {
  const dot = document.getElementById('badge-dot');
  const txt = document.getElementById('badge-text');
  dot.className = `badge-dot ${color}`;
  txt.className = 'badge-text' + (color === 'green' ? ' connected' : '');
  txt.textContent = text;
}

// ── Settings modal ────────────────────────────────────────────────────────────

document.getElementById('settings-btn').addEventListener('click', openModal);

async function openModal() {
  try {
    const res = await apiFetch('/api/settings');
    document.getElementById('adult-content-toggle').checked = res.include_adult_content;
  } catch {
    // Not connected yet — leave the toggle at its default (unchecked).
  }
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('token-input').focus();
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

function onOverlayClick(e) {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

async function saveSettings() {
  const token = document.getElementById('token-input').value.trim();
  const includeAdult = document.getElementById('adult-content-toggle').checked;
  if (!token) return;
  setBadge('muted', 'Connecting…');
  document.getElementById('build-btn').disabled   = true;
  document.getElementById('destroy-btn').disabled = true;
  closeModal();
  try {
    const res = await apiFetch('/api/connect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token}),
    });
    await apiFetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({include_adult_content: includeAdult}),
    });
    setConnected(res.name);
    await loadLibraries();
  } catch (e) {
    setBadge('red', 'Connection failed');
    appendLog(`Error: ${e.message}`, 'red');
  }
}

// ── Mode ──────────────────────────────────────────────────────────────────────

function setMode(m) {
  currentMode = m;
  document.getElementById('mode-quick').classList.toggle('active', m === 'quick');
  document.getElementById('mode-custom').classList.toggle('active', m === 'custom');
  document.getElementById('quick-panel').classList.toggle('hidden', m !== 'quick');
  document.getElementById('custom-panel').classList.toggle('hidden', m !== 'custom');
}

// ── Actor toggle ──────────────────────────────────────────────────────────────

document.getElementById('actor-toggle').addEventListener('change', e => {
  document.getElementById('actor-entry-row').style.display = e.target.checked ? '' : 'none';
});

// ── Custom rules ──────────────────────────────────────────────────────────────

function addRule() {
  const id   = ruleSeq++;
  const card = document.createElement('div');
  card.className  = 'rule-card';
  card.dataset.id = id;
  card.innerHTML  = `
    <div class="rule-top">
      <input type="text" class="rule-name" placeholder="Playlist name (auto-generated if blank)"
             data-key="custom_name">
      <button class="remove-btn" onclick="removeRule(${id})">×</button>
    </div>
    <div class="rule-fields">
      <input type="text" class="rule-field" placeholder="Studio"   data-key="studio">
      <input type="text" class="rule-field" placeholder="Genre"    data-key="genre">
      <input type="text" class="rule-field" placeholder="Director" data-key="director">
      <input type="text" class="rule-field" placeholder="Actor"    data-key="actor">
    </div>
    <div class="dur-row">
      <label>Duration</label>
      <select class="dur-select" data-key="duration">
        <option>Any</option>
        <option>&lt; 2 min</option>
        <option>2–5 min</option>
        <option>5–10 min</option>
        <option>&gt; 1 hour</option>
      </select>
    </div>
  `;
  document.getElementById('rules-list').appendChild(card);
  card.querySelector('.rule-name').focus();
}

function removeRule(id) {
  const card = document.querySelector(`.rule-card[data-id="${id}"]`);
  if (card) card.remove();
}

function getRulesData() {
  return Array.from(document.querySelectorAll('.rule-card')).map(card => {
    const id   = parseInt(card.dataset.id);
    const data = {id};
    card.querySelectorAll('[data-key]').forEach(el => {
      data[el.dataset.key] = el.value.trim();
    });
    return data;
  }).filter(r => {
    const {custom_name, duration, id, ...fields} = r;
    return Object.values(fields).some(v => v) || duration !== 'Any';
  });
}

// ── Build ─────────────────────────────────────────────────────────────────────

function startBuild(dryRun) {
  if (eventSource) { eventSource.close(); eventSource = null; }

  const library = document.getElementById('library-select').value;
  const prefix  = document.getElementById('prefix-input').value;

  resetStats();
  clearLog();
  setProgress(0, dryRun ? 'Previewing…' : 'Starting…');
  document.getElementById('build-btn').disabled   = true;
  document.getElementById('preview-btn').disabled = true;
  document.getElementById('build-btn').textContent =
    dryRun ? 'Build Playlists' : 'Building…';

  let params;
  if (currentMode === 'quick') {
    const selected = Array.from(document.querySelectorAll('input[name="ptype"]:checked'))
      .map(cb => cb.value).join(',');
    if (!selected) { appendLog('No playlist types selected.', 'red'); resetBtn(); return; }
    const actorFilter = document.getElementById('actor-filter').value.trim();
    params = new URLSearchParams({
      library, prefix, mode: 'quick', types: selected, actor_filter: actorFilter, dry_run: dryRun,
    });
  } else {
    const rules = getRulesData();
    if (!rules.length) { appendLog('No rules defined.', 'red'); resetBtn(); return; }
    params = new URLSearchParams({
      library, prefix, mode: 'custom', rules: JSON.stringify(rules), dry_run: dryRun,
    });
  }

  let playlistCount = 0;
  eventSource = new EventSource(`/api/build?${params}`);

  eventSource.onmessage = e => {
    const msg = JSON.parse(e.data);
    switch (msg.type) {
      case 'start':
        appendLog(`${dryRun ? 'Previewing' : 'Scanning'} ${msg.total} items in '${library}' …`, 'orange');
        break;

      case 'progress': {
        const pct = msg.total > 0 ? msg.current / msg.total * 100 : 0;
        setProgress(pct, `Scanning ${msg.current} of ${msg.total}`);
        document.getElementById('stat-scanned').textContent = msg.current;
        break;
      }

      case 'log':
        appendLog(msg.msg, 'orange');
        break;

      case 'playlist':
        appendPlaylistLog(prefix, msg.name, msg.count, msg.replaced, msg.dry_run);
        playlistCount++;
        document.getElementById('stat-playlists').textContent = playlistCount;
        break;

      case 'done':
        setProgress(100, dryRun ? 'Preview complete' : 'Complete');
        document.getElementById('stat-scanned').textContent   = msg.total;
        document.getElementById('stat-playlists').textContent = msg.created;
        document.getElementById('stat-skipped').textContent   = msg.skipped;
        appendLog(
          `\n${dryRun ? 'Preview' : 'Done'} — ${msg.created} playlist(s), ${msg.skipped} item(s) skipped.`,
          'orange'
        );
        resetBtn();
        eventSource.close();
        break;

      case 'error':
        appendLog(`Error: ${msg.msg}`, 'red');
        resetBtn();
        eventSource.close();
        break;
    }
  };

  eventSource.onerror = () => {
    if (eventSource.readyState === EventSource.CLOSED) return;
    appendLog('Stream connection lost.', 'red');
    resetBtn();
    eventSource.close();
  };
}

function resetBtn() {
  document.getElementById('build-btn').disabled    = false;
  document.getElementById('preview-btn').disabled  = false;
  document.getElementById('build-btn').textContent = 'Build Playlists';
}

// ── Destroy ───────────────────────────────────────────────────────────────────

async function confirmDestroy() {
  const prefix = document.getElementById('prefix-input').value;
  if (!confirm(`Delete ALL Plex playlists starting with '${prefix}'?\n\nThis cannot be undone.`)) return;

  document.getElementById('destroy-btn').disabled = true;
  clearLog();
  appendLog(`Destroying playlists with prefix '${prefix}' …`);

  try {
    const res = await apiFetch('/api/destroy', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prefix}),
    });
    appendLog(`Done — ${res.destroyed} playlist(s) destroyed.`, 'orange');
  } catch (e) {
    appendLog(`Error: ${e.message}`, 'red');
  } finally {
    document.getElementById('destroy-btn').disabled = false;
  }
}

// ── Progress ──────────────────────────────────────────────────────────────────

function setProgress(pct, label) {
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-label').textContent = label;
  document.getElementById('progress-label').className =
    'progress-label' + (pct === 0 || label === 'Ready' ? ' muted' : '');
}

function resetStats() {
  document.getElementById('stat-scanned').textContent   = '—';
  document.getElementById('stat-playlists').textContent = '—';
  document.getElementById('stat-skipped').textContent   = '—';
}

// ── Log ───────────────────────────────────────────────────────────────────────

function appendLog(msg, cls = '') {
  const logEl = document.getElementById('log');
  const line  = document.createElement('div');
  line.className   = 'log-line' + (cls ? ' ' + cls : '');
  line.textContent = msg;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

function appendPlaylistLog(prefix, name, count, replaced, dryRun) {
  const logEl = document.getElementById('log');
  const line  = document.createElement('div');
  line.className = 'log-line';
  const icon = dryRun ? '○' : (replaced ? '↻' : '✓');
  const verb = dryRun ? (replaced ? 'would replace' : 'would create') : (replaced ? 'replaced' : 'created');
  line.innerHTML =
    `  ${icon}  <span class="accent">${esc(prefix)}</span>${esc(name)}  (${count} items, ${verb})`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() { document.getElementById('log').innerHTML = ''; }

function esc(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Fetch wrapper ─────────────────────────────────────────────────────────────

async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Boot ──────────────────────────────────────────────────────────────────────

init();
