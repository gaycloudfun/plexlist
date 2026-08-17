/**
 * Fidelity harness for the fetch-based build stream in static/app.js.
 *
 * Run with:  node tests/frontend/sse_harness.js   (from web_v2/)
 *
 * No dependencies — plain node + a hand-rolled fake DOM. It drives
 * startBuild() through a simulated text/event-stream response and asserts the
 * exact sequence of DOM effects, including byte-level chunk reassembly and
 * every failure path (non-2xx, network drop, truncated stream).
 *
 * If the pre-rewrite tree (../web/static/app.js, EventSource-based) is still
 * present, it is also loaded and driven with the identical event sequence so
 * the two implementations' DOM effects can be diffed directly. Those
 * comparison checks are skipped when that tree is gone.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HERE = __dirname;                                   // web_v2/tests/frontend
const WEB_V2 = path.resolve(HERE, '..', '..');            // web_v2
const REPO = path.resolve(WEB_V2, '..');
const OLD = path.join(REPO, 'web', 'static', 'app.js');   // optional baseline
const NEW = path.join(WEB_V2, 'static', 'app.js');
const HAS_OLD = fs.existsSync(OLD);

function makeSandbox({fetchImpl, ops}) {
  const rec = s => ops.push(s);

  class FakeEl {
    constructor(id) {
      this.id = id;
      this._textContent = '';
      this._innerHTML = '';
      this._disabled = false;
      this.checked = false;
      this.value = '';
      this.style = new Proxy({}, {set: (t, k, v) => { t[k] = v; rec(`style:${id}.${k}=${v}`); return true; }});
      this.dataset = {};
      this.children = [];
      this.scrollTop = 0;
      this.scrollHeight = 0;
      this._className = '';
      this.title = '';
      this.classList = {
        add: c => rec(`class+:${id}=${c}`),
        remove: c => rec(`class-:${id}=${c}`),
        toggle: (c, on) => rec(`class~:${id}=${c}:${on}`),
      };
    }
    set textContent(v) { this._textContent = v; rec(`text:${this.id}=${v}`); }
    get textContent() { return this._textContent; }
    set innerHTML(v) { this._innerHTML = v; rec(`html:${this.id}=${v}`); }
    get innerHTML() { return this._innerHTML; }
    set disabled(v) { this._disabled = v; rec(`disabled:${this.id}=${v}`); }
    get disabled() { return this._disabled; }
    set className(v) { this._className = v; rec(`className:${this.id}=${v}`); }
    get className() { return this._className; }
    addEventListener() {}
    appendChild(child) {
      this.children.push(child);
      // Log lines are the user-visible output — record content, not identity.
      rec(`append:${this.id}=[${child._className}] ${child._textContent || child._innerHTML}`);
    }
    focus() {}
    querySelector() { return null; }
    querySelectorAll() { return []; }
    closest() { return new FakeEl('closest'); }
  }

  const els = new Map();
  const getEl = id => {
    if (!els.has(id)) els.set(id, new FakeEl(id));
    return els.get(id);
  };

  getEl('library-select').value = 'MyLibrary';
  getEl('prefix-input').value = 't ';
  getEl('actor-filter').value = '';
  getEl('token-input').value = '';

  const document = {
    getElementById: getEl,
    createElement: tag => new FakeEl(`new:${tag}`),
    addEventListener() {},
    querySelector: sel => (sel.includes('folder') ? getEl('folder-cb') : null),
    querySelectorAll: sel => {
      if (sel.includes('ptype')) return [{value: 'studio'}, {value: 'genre'}];
      if (sel.includes('rule-card')) return [];
      return [];
    },
  };

  const sandbox = {
    document,
    console,
    fetch: fetchImpl,
    TextDecoder,
    TextEncoder,
    URLSearchParams,
    AbortController,
    ReadableStream,
    setTimeout,
    confirm: () => false,
    EventSource: null,
    __ops: ops,
    __els: els,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  return sandbox;
}

// ── Fake EventSource for the ORIGINAL implementation ──────────────────────────
function makeFakeEventSource(holder) {
  const ES = function (url) {
    this.url = url;
    this.readyState = 1;
    this.onmessage = null;
    this.onerror = null;
    holder.instance = this;
  };
  ES.prototype.close = function () { this.readyState = 2; };
  ES.CONNECTING = 0; ES.OPEN = 1; ES.CLOSED = 2;
  return ES;
}

const tick = () => new Promise(r => setImmediate(r));
async function settle(n = 12) { for (let i = 0; i < n; i++) await tick(); }

const EVENTS = [
  {type: 'start', total: 10},
  {type: 'progress', current: 5, total: 10},
  {type: 'log', msg: 'Building playlists from 2 groups…'},
  {type: 'playlist', name: 'Studio: A', count: 4, replaced: false, dry_run: false},
  {type: 'playlist', name: 'Genre: B', count: 3, replaced: true, dry_run: false},
  {type: 'progress', current: 10, total: 10},
  {type: 'done', created: 2, total: 10, skipped: 1, dry_run: false},
];

function sseText(events) {
  return events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('');
}

// ── Run the OLD implementation ────────────────────────────────────────────────
async function runOld(events, {dryRun = false, mode = 'events'} = {}) {
  const ops = [];
  const holder = {};
  const sandbox = makeSandbox({
    fetchImpl: async () => ({ok: true, json: async () => ({connected: false, error: 'x'})}),
    ops,
  });
  sandbox.EventSource = makeFakeEventSource(holder);
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(OLD, 'utf8'), sandbox);
  await settle();
  ops.length = 0;

  sandbox.startBuild(dryRun);
  const es = holder.instance;
  if (mode === 'events') {
    for (const e of events) es.onmessage({data: JSON.stringify(e)});
  } else if (mode === 'http-error') {
    // A non-2xx response makes a real EventSource fail and close.
    es.readyState = 2;
    es.onerror();
  } else if (mode === 'network-drop') {
    es.readyState = 0; // CONNECTING (retrying)
    es.onerror();
  }
  await settle();
  return {ops, url: es.url};
}

// ── Run the NEW implementation ────────────────────────────────────────────────
async function runNew(events, {dryRun = false, mode = 'events', chunkSize = null} = {}) {
  const ops = [];
  let captured = null;
  const fetchImpl = async (url, opts = {}) => {
    if (url === '/api/settings' || url === '/api/status') {
      return {ok: true, json: async () => ({include_adult_content: false, connected: false, error: 'x'})};
    }
    captured = {url, opts};
    if (mode === 'network-drop') throw new TypeError('Failed to fetch');
    if (mode === 'http-error') {
      return {ok: false, status: 503, json: async () => ({detail: 'Not connected to Plex'})};
    }
    let text = sseText(events);
    if (mode === 'truncated') text = text.slice(0, text.length - 40); // clipped mid-stream
    const bytes = new TextEncoder().encode(text);
    const size = chunkSize || bytes.length;
    let pos = 0;
    return {
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            if (pos >= bytes.length) return {done: true, value: undefined};
            const slice = bytes.slice(pos, pos + size);
            pos += size;
            return {done: false, value: slice};
          },
          cancel: async () => {},
        }),
      },
    };
  };

  const sandbox = makeSandbox({fetchImpl, ops});
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(NEW, 'utf8'), sandbox);
  await settle();
  ops.length = 0;

  await sandbox.startBuild(dryRun);
  await settle();
  return {ops, captured};
}

function diff(a, b) {
  const out = [];
  const n = Math.max(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) out.push(`  [${i}] old=${a[i]}  new=${b[i]}`);
  return out;
}

(async () => {
  let failures = 0;
  const check = (name, ok, detail = '') => {
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '\n' + detail : ''}`);
    if (!ok) failures++;
  };
  const skip = name => console.log(`SKIP  ${name} (../web/static/app.js not present)`);

  // 1. Happy path, one chunk
  {
    const n = await runNew(EVENTS);
    if (HAS_OLD) {
      const o = await runOld(EVENTS);
      const d = diff(o.ops, n.ops);
      check('happy path (real run): DOM effects identical to EventSource version',
        d.length === 0, d.join('\n'));
      check('old URL for reference: ' + o.url, true);
    } else {
      skip('happy path (real run): DOM effects identical to EventSource version');
      const expected = [
        "append:log=[log-line orange] Scanning 10 items in 'MyLibrary' …",
        'append:log=[log-line orange] Building playlists from 2 groups…',
        'text:stat-scanned=10', 'text:stat-playlists=2', 'text:stat-skipped=1',
        'text:progress-label=Complete', 'disabled:build-btn=false',
        'text:build-btn=Build Playlists',
      ];
      const missing = expected.filter(e => !n.ops.includes(e));
      check('happy path (real run): every message type reaches the DOM',
        missing.length === 0, '  missing: ' + JSON.stringify(missing));
    }
    check('POST /api/build with JSON body',
      n.captured.url === '/api/build' && n.captured.opts.method === 'POST' &&
      n.captured.opts.headers['Content-Type'] === 'application/json');
    const body = JSON.parse(n.captured.opts.body);
    check('body carries the same param names/values as the old query string',
      body.library === 'MyLibrary' && body.prefix === 't ' && body.mode === 'quick' &&
      body.types === 'studio,genre' && body.actor_filter === '' && body.dry_run === false,
      '  body=' + JSON.stringify(body));
  }

  // 2. Byte-boundary robustness: every chunk size from 1 byte up
  {
    const base = (await runNew(EVENTS)).ops;
    let bad = null;
    for (const size of [1, 2, 3, 7, 13, 31, 64, 128, 512]) {
      const r = await runNew(EVENTS, {chunkSize: size});
      const d = diff(base, r.ops);
      if (d.length) { bad = `chunk=${size}\n` + d.join('\n'); break; }
    }
    check('stream reassembly identical at chunk sizes 1..512 bytes', !bad, bad || '');
  }

  // 3. Dry run
  {
    const dryEvents = EVENTS.map(e =>
      e.type === 'playlist' || e.type === 'done' ? {...e, dry_run: true} : e);
    const n = await runNew(dryEvents, {dryRun: true});
    if (HAS_OLD) {
      const o = await runOld(dryEvents, {dryRun: true});
      const d = diff(o.ops, n.ops);
      const onlyLabel = d.length === 1 &&
        d[0].includes('old=text:build-btn=Build Playlists') &&
        d[0].includes('new=text:build-btn=Previewing…');
      check('dry run: only difference is the Finding #13 busy label', onlyLabel, d.join('\n'));
    } else {
      skip('dry run: only difference is the Finding #13 busy label');
    }
    check('dry run: busy label + preview wording',
      n.ops.includes('text:build-btn=Previewing…') &&
      n.ops.includes('text:progress-label=Preview complete') &&
      n.ops.some(s => s.includes('would create')),
      '  ' + JSON.stringify(n.ops));
  }

  // 4. Server-side 'error' message
  {
    const errEvents = [{type: 'start', total: 3}, {type: 'error', msg: 'boom'}];
    const n = await runNew(errEvents);
    if (HAS_OLD) {
      const o = await runOld(errEvents);
      const d = diff(o.ops, n.ops);
      check("server 'error' event: identical handling", d.length === 0, d.join('\n'));
    } else {
      skip("server 'error' event: identical handling");
    }
    check("server 'error' event: logged red + resetBtn",
      n.ops.some(s => s.includes('[log-line red] Error: boom')) &&
      n.ops.includes('disabled:build-btn=false'), '  ' + JSON.stringify(n.ops));
  }

  // 5. Non-2xx (Finding #5 — old code silently stuck, new must recover)
  {
    const n = await runNew([], {mode: 'http-error'});
    const o = HAS_OLD ? await runOld([], {mode: 'http-error'}) : null;
    // The old code left the UI on 'Building…' with the buttons disabled and
    // nothing logged: no reset, no error surfaced.
    const oldStuck = o && !o.ops.includes('disabled:build-btn=false') &&
      !o.ops.some(s => s.startsWith('append:log')) &&
      o.ops.includes('text:build-btn=Building…');
    const newRecovers =
      n.ops.some(s => s.includes('Not connected to Plex')) &&
      n.ops.includes('disabled:build-btn=false') &&
      n.ops.includes('disabled:preview-btn=false') &&
      n.ops.includes('text:build-btn=Build Playlists');
    if (o) {
      check('503: old code did nothing (the bug)', oldStuck, '  old ops: ' + JSON.stringify(o.ops));
    } else {
      skip('503: old code did nothing (the bug)');
    }
    check('503: new code logs the detail and re-enables the buttons', newRecovers,
      '  new ops: ' + JSON.stringify(n.ops));
  }

  // 6. Network failure
  {
    const n = await runNew([], {mode: 'network-drop'});
    const ok = n.ops.some(s => s.includes('Failed to fetch')) &&
      n.ops.includes('disabled:build-btn=false') &&
      n.ops.includes('text:build-btn=Build Playlists');
    check('network failure: logs error and calls resetBtn()', ok, '  ' + JSON.stringify(n.ops));
  }

  // 7. Stream truncated before 'done'
  {
    const n = await runNew(EVENTS, {mode: 'truncated', chunkSize: 16});
    const ok = n.ops.some(s => s.includes('Stream connection lost.')) &&
      n.ops.includes('disabled:build-btn=false');
    check('truncated stream: reports loss and calls resetBtn()', ok, '  ' + JSON.stringify(n.ops));
  }

  // 8. Custom mode payload
  {
    const ops = [];
    const sandbox = makeSandbox({
      fetchImpl: async () => ({ok: true, json: async () => ({include_adult_content: false, connected: false})}),
      ops,
    });
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(NEW, 'utf8'), sandbox);
    await settle();
    sandbox.setMode('custom');
    let captured = null;
    sandbox.fetch = async (url, opts) => { captured = {url, opts}; throw new TypeError('stop'); };
    // No rules defined -> must bail out early and reset the buttons.
    ops.length = 0;
    await sandbox.startBuild(false);
    const bailed = captured === null &&
      ops.some(s => s.includes('No rules defined.')) &&
      ops.includes('disabled:build-btn=false');
    check('custom mode with no rules: early bail + resetBtn, no request', bailed,
      '  ' + JSON.stringify(ops));
  }

  console.log(failures ? `\n${failures} FAILURE(S)` : '\nAll harness checks passed.');
  process.exit(failures ? 1 : 0);
})();
