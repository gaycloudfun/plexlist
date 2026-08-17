/**
 * Harness for the settings modal in static/app.js: saving settings without a
 * token, and the Folder checkbox tracking the adult-content setting.
 *
 * Run with:  node tests/frontend/settings_harness.js   (from web_v2/)
 * No dependencies — plain node + a hand-rolled fake DOM.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const NEW = path.resolve(__dirname, '..', '..', 'static', 'app.js');
const src = fs.readFileSync(NEW, 'utf8');

function build({includeAdult = false, token = '', adultToggle = false, connectFails = false}) {
  const ops = [];
  const calls = [];
  const rec = s => ops.push(s);

  class FakeEl {
    constructor(id) {
      this.id = id; this._t = ''; this._h = ''; this._d = false;
      this.checked = false; this.value = ''; this.title = '';
      this.style = {}; this.dataset = {}; this.scrollTop = 0; this.scrollHeight = 0;
      this._c = '';
      this.classList = {
        add: c => rec(`class+:${id}=${c}`),
        remove: c => rec(`class-:${id}=${c}`),
        toggle: (c, on) => rec(`class~:${id}=${c}:${on}`),
      };
    }
    set textContent(v) { this._t = v; rec(`text:${this.id}=${v}`); }
    get textContent() { return this._t; }
    set innerHTML(v) { this._h = v; rec(`html:${this.id}=${v}`); }
    get innerHTML() { return this._h; }
    set disabled(v) { this._d = v; rec(`disabled:${this.id}=${v}`); }
    get disabled() { return this._d; }
    set className(v) { this._c = v; rec(`className:${this.id}=${v}`); }
    get className() { return this._c; }
    addEventListener() {} appendChild() {} focus() {}
    closest() { return folderLabel; }
  }

  const els = new Map();
  const getEl = id => { if (!els.has(id)) els.set(id, new FakeEl(id)); return els.get(id); };
  const folderCb = new FakeEl('folder-cb');
  folderCb.checked = true;              // as shipped: checked by default in index.html
  const folderLabel = new FakeEl('folder-label');

  getEl('token-input').value = token;
  getEl('adult-content-toggle').checked = adultToggle;
  getEl('library-select').value = 'Lib';
  getEl('prefix-input').value = 't ';

  const document = {
    getElementById: getEl,
    createElement: () => new FakeEl('div'),
    addEventListener() {},
    querySelector: sel => (sel.includes('folder') ? folderCb : null),
    querySelectorAll: () => [],
  };

  const fetchImpl = async (url, opts = {}) => {
    calls.push({url, method: opts.method || 'GET', body: opts.body});
    if (url === '/api/settings' && (opts.method || 'GET') === 'GET') {
      return {ok: true, json: async () => ({include_adult_content: includeAdult})};
    }
    if (url === '/api/settings') {
      const sent = JSON.parse(opts.body);
      return {ok: true, json: async () => ({include_adult_content: sent.include_adult_content})};
    }
    if (url === '/api/status') return {ok: true, json: async () => ({connected: true, name: 'Srv'})};
    if (url === '/api/libraries') return {ok: true, json: async () => ({libraries: ['Lib']})};
    if (url === '/api/connect') {
      if (connectFails) return {ok: false, status: 400, json: async () => ({detail: 'bad token'})};
      return {ok: true, json: async () => ({connected: true, name: 'Srv'})};
    }
    return {ok: true, json: async () => ({})};
  };

  const sandbox = {
    document, console, fetch: fetchImpl, TextDecoder, TextEncoder,
    URLSearchParams, AbortController, setTimeout, confirm: () => false, EventSource: null,
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  return {sandbox, ops, calls, folderCb, folderLabel, getEl};
}

const settle = async (n = 15) => { for (let i = 0; i < n; i++) await new Promise(r => setImmediate(r)); };

(async () => {
  let failures = 0;
  const check = (name, ok, detail = '') => {
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : '\n' + detail}`);
    if (!ok) failures++;
  };

  // Finding #6 — page load with adult content OFF (the default)
  {
    const h = build({includeAdult: false});
    await settle();
    check('load w/ adult OFF: Folder checkbox disabled and unchecked',
      h.folderCb.disabled === true && h.folderCb.checked === false,
      `  disabled=${h.folderCb.disabled} checked=${h.folderCb.checked}`);
    check('load w/ adult OFF: label gets .disabled + explanatory title',
      h.ops.includes('class~:folder-label=disabled:true') && h.folderLabel.title.length > 0);
  }

  // Finding #6 — page load with adult content ON
  {
    const h = build({includeAdult: true});
    await settle();
    check('load w/ adult ON: Folder checkbox enabled, stays checked',
      h.folderCb.disabled === false && h.folderCb.checked === true);
  }

  // Finding #6 — settings endpoint unreachable => safe default
  {
    const h = build({includeAdult: false});
    h.sandbox.fetch = async () => { throw new TypeError('down'); };
    await settle();
    check('load w/ settings unreachable: Folder still disabled (safe default)',
      h.folderCb.disabled === true);
  }

  // Finding #3 — save with NO token: settings saved, modal closed, no connect
  {
    const h = build({includeAdult: false, token: '', adultToggle: true});
    await settle();
    h.ops.length = 0; h.calls.length = 0;
    await h.sandbox.saveSettings();
    await settle();
    const settingsPost = h.calls.find(c => c.url === '/api/settings' && c.method === 'POST');
    check('no token: POST /api/settings still happens',
      !!settingsPost && JSON.parse(settingsPost.body).include_adult_content === true,
      '  calls=' + JSON.stringify(h.calls));
    check('no token: /api/connect NOT called', !h.calls.some(c => c.url === '/api/connect'),
      '  calls=' + JSON.stringify(h.calls));
    check('no token: modal closed', h.ops.includes('class+:modal-overlay=hidden'));
    check('no token: badge left alone (no "Connecting…")',
      !h.ops.some(s => s.includes('Connecting…')), '  ' + JSON.stringify(h.ops));
    check('no token: build/destroy buttons not disabled',
      !h.ops.includes('disabled:build-btn=true') && !h.ops.includes('disabled:destroy-btn=true'),
      '  ' + JSON.stringify(h.ops));
    check('no token: turning adult ON re-enables the Folder checkbox',
      h.folderCb.disabled === false);
  }

  // Finding #3 — save WITH a token: settings + connect, badge, libraries
  {
    const h = build({includeAdult: false, token: 'tok-123', adultToggle: false});
    await settle();
    h.ops.length = 0; h.calls.length = 0;
    await h.sandbox.saveSettings();
    await settle();
    check('with token: both /api/settings and /api/connect called',
      h.calls.some(c => c.url === '/api/settings' && c.method === 'POST') &&
      h.calls.some(c => c.url === '/api/connect'), '  calls=' + JSON.stringify(h.calls));
    check('with token: shows Connecting… then Connected',
      h.ops.some(s => s.includes('Connecting…')) && h.ops.some(s => s.includes('Connected · Srv')),
      '  ' + JSON.stringify(h.ops));
    check('with token: libraries reloaded (build btn re-enabled)',
      h.ops.includes('disabled:build-btn=false'));
    check('with token + adult OFF: Folder disabled again', h.folderCb.disabled === true);
  }

  // Finding #3 — connect failure path still reports
  {
    const h = build({token: 'bad', connectFails: true});
    await settle();
    h.ops.length = 0;
    await h.sandbox.saveSettings();
    await settle();
    check('connect failure: red badge + logged error',
      h.ops.some(s => s.includes('Connection failed')) &&
      h.ops.some(s => s.includes('bad token')), '  ' + JSON.stringify(h.ops));
  }

  // openModal reflects stored value and re-applies the folder state
  {
    const h = build({includeAdult: true});
    await settle();
    h.folderCb.disabled = true;
    await h.sandbox.openModal();
    await settle();
    check('openModal: toggle reflects stored value and Folder re-enabled',
      h.getEl('adult-content-toggle').checked === true && h.folderCb.disabled === false);
  }

  console.log(failures ? `\n${failures} FAILURE(S)` : '\nAll harness checks passed.');
  process.exit(failures ? 1 : 0);
})();
