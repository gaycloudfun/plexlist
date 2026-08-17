# Structly Launch Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the security hole in `config.py`, give the web app a real first-run connect flow with persisted settings, add the adult-content opt-in from the approved spec, fix mobile layout clipping, and make the build worker report accurate skipped/replaced/dry-run data.

**Architecture:** All backend work lands in `plex_playlist_builder/web/main.py` plus a new shared `web/settings_store.py` module that persists to `~/.structly_settings.json` (same path already used by the desktop app in `app_v4.py`, so a token saved by one is visible to the other). Frontend work is vanilla HTML/CSS/JS in `web/static/` — no build step, no new toolchain. `config.py` and the older CLI scripts (`app.py`, `app_v3.py`, `app_v4.py`, `discover.py`, `build_playlists.py`) keep working via `from config import PLEX_URL, PLEX_TOKEN`, but that import now yields empty strings unless the developer sets env vars — no more real secret shipped in the file.

**Tech Stack:** Python 3.13, FastAPI + Starlette `TestClient` (httpx already installed), `pytest` (needs installing), plexapi, vanilla JS/CSS on the frontend.

## Global Constraints

- `PORN_ROOT = "/other/Porn"` (existing constant in `web/main.py`) is the adult-content path prefix — do not change its value.
- `include_adult_content` defaults to `false` and must be enforced **server-side** (filtered before data leaves the backend), per the approved spec (`docs/superpowers/specs/2026-07-07-web-ui-design.md`).
- Settings persist to `SETTINGS_PATH = Path.home() / ".structly_settings.json"` — this path is already load-bearing for `app_v4.py`; new code must only ever *add* keys to that JSON, never rename/remove the existing `"token"` key.
- Item 5 from the original request ("Make destructive actions safer" / typed confirmation on Destroy) is **explicitly out of scope** per user instruction — do not touch `confirmDestroy()` behavior beyond what's needed for unrelated changes.
- Run all backend tests from the `web/` directory (`cd web && python3 -m pytest tests/ -v`) — `main.py` mounts `StaticFiles(directory="static", ...)` relative to cwd at import time, so importing `main` from anywhere else raises at collection time.

---

## ⚠️ Manual prerequisite (not a code task — do this yourself before or alongside Task 1)

`config.py` currently contains a **live, real** Plex token (`-N1F5…[REDACTED]`) and your home server URL. Task 1 removes it from the file, but deleting text on disk does not invalidate the token itself — if it was ever screenshotted, pasted into a chat, zipped up, or committed anywhere outside this untracked local file, it's still valid until you revoke it.

**Rotate it now:** go to `plex.tv` → Account → Authorized Devices (or Settings → Devices), find the app/session using this token, and remove it. Then generate a fresh token and put it into the app the normal way (via the web UI's Connect Plex modal, once Task 6 ships — or immediately via `~/.structly_settings.json` / the desktop app's settings). I can't do this step for you — it's an account action on Plex's side, not a file edit.

---

### Task 1: Strip hardcoded credentials from `config.py`

**Files:**
- Modify: `config.py`
- Create: `config.example.py`
- Create: `.gitignore`

**Interfaces:**
- Produces: `config.PLEX_URL: str`, `config.PLEX_TOKEN: str` (env-var-backed, empty by default) — unchanged names, so `app.py`, `app_v3.py`, `app_v4.py`, `discover.py`, `build_playlists.py` need no edits.

- [ ] **Step 1: Rewrite `config.py` to read from environment instead of hardcoding**

```python
"""
Structly — local Plex connection config (NOT checked into git).

Copy config.example.py to config.py and fill in your own values, or set
PLEX_URL / PLEX_TOKEN as environment variables. Never commit a real token —
see .gitignore.
"""
import os

PLEX_URL = os.environ.get("PLEX_URL", "")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "")
```

- [ ] **Step 2: Add the checked-in template so other devs know the shape**

Create `config.example.py`:

```python
"""
Copy this file to config.py and fill in your own Plex server details, or
set PLEX_URL / PLEX_TOKEN as environment variables instead — config.py
already falls back to those if you leave this file's defaults blank.
"""
import os

PLEX_URL = os.environ.get("PLEX_URL", "http://your-plex-ip:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "your_plex_token_here")
```

- [ ] **Step 3: Add `.gitignore` so `config.py` (and other local-only files) can never be committed**

Create `.gitignore`:

```
__pycache__/
*.pyc
.DS_Store
config.py
web/.env
.venv/
venv/
*.egg-info/
```

- [ ] **Step 4: Verify no hardcoded secret remains anywhere in the repo**

Run: `grep -rn "<the leaked token>\|<your home server IP>" --include="*.py" .`
Expected: no output (zero matches).

Run: `python3 -c "import config; print(repr(config.PLEX_URL), repr(config.PLEX_TOKEN))"`
Expected: `'' ''` (empty strings, since no env vars are set in this shell).

- [ ] **Step 5: Commit**

```bash
git add config.py config.example.py .gitignore
git commit -m "security: remove hardcoded Plex credentials from config.py"
```

---

### Task 2: `settings_store.py` — shared persisted settings

**Files:**
- Create: `web/settings_store.py`
- Create: `web/tests/conftest.py`
- Create: `web/tests/test_settings_store.py`
- Create: `web/requirements-dev.txt`

**Interfaces:**
- Produces: `settings_store.SETTINGS_PATH: Path`, `settings_store.load_settings() -> dict`, `settings_store.save_settings(**updates) -> dict`. Return shape: `{"token": str, "include_adult_content": bool}`.
- Consumes: nothing (leaf module).

- [ ] **Step 1: Install test tooling**

Create `web/requirements-dev.txt`:

```
pytest>=8.0.0
httpx>=0.27.0
```

Run: `pip3 install -r web/requirements-dev.txt`
Expected: installs cleanly (httpx may already be satisfied).

- [ ] **Step 2: Add `web/tests/conftest.py` so tests can `import settings_store` / `import main`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 3: Write the failing tests**

Create `web/tests/test_settings_store.py`:

```python
import pytest

import settings_store


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / ".structly_settings.json")


def test_load_settings_defaults_when_no_file():
    result = settings_store.load_settings()
    assert result == {"token": "", "include_adult_content": False}


def test_save_and_load_round_trip():
    settings_store.save_settings(token="abc123")
    result = settings_store.load_settings()
    assert result["token"] == "abc123"
    assert result["include_adult_content"] is False


def test_save_settings_merges_not_overwrites():
    settings_store.save_settings(token="abc123")
    settings_store.save_settings(include_adult_content=True)
    result = settings_store.load_settings()
    assert result["token"] == "abc123"
    assert result["include_adult_content"] is True


def test_load_settings_survives_corrupt_json():
    settings_store.SETTINGS_PATH.write_text("{not json")
    result = settings_store.load_settings()
    assert result == {"token": "", "include_adult_content": False}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd web && python3 -m pytest tests/test_settings_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'settings_store'`

- [ ] **Step 5: Implement `settings_store.py`**

Create `web/settings_store.py`:

```python
"""
Structly — persisted local settings (~/.structly_settings.json).

Shared with the desktop app (app_v4.py), which already reads/writes the
"token" key at this same path. This module additionally manages
"include_adult_content" without disturbing that compatibility — never
rename or drop the "token" key.
"""
import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".structly_settings.json"

DEFAULTS = {
    "token": "",
    "include_adult_content": False,
}


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
            return {**DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def save_settings(**updates) -> dict:
    data = load_settings()
    data.update(updates)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))
    try:
        SETTINGS_PATH.chmod(0o600)
    except OSError:
        pass
    return data
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && python3 -m pytest tests/test_settings_store.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add web/settings_store.py web/tests/conftest.py web/tests/test_settings_store.py web/requirements-dev.txt
git commit -m "feat: add shared settings_store for token + adult-content persistence"
```

---

### Task 3: Wire `/api/status` and `/api/connect` to `settings_store`

Replaces the in-memory `_token = os.environ.get("PLEX_TOKEN", "")` (lost on every restart, and a leftover env-var path we no longer want) with the persisted store from Task 2.

**Files:**
- Modify: `web/main.py:1-30` (imports/state), `web/main.py:113-156` (`/api/status`, `/api/connect`)
- Create: `web/tests/test_connect_status.py`

**Interfaces:**
- Consumes: `settings_store.load_settings()`, `settings_store.save_settings()` (Task 2).
- Produces: `main._try_connect(token: str) -> Optional[PlexServer]` — used again in Task 5's `/api/build`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/test_connect_status.py`:

```python
import pytest
from fastapi.testclient import TestClient

import main
import settings_store


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / ".structly_settings.json")
    monkeypatch.setattr(main, "_plex", None)


class FakeServer:
    friendlyName = "Test Server"


class FakeResource:
    product = "Plex Media Server"

    def connect(self):
        return FakeServer()


class FakeAccount:
    def __init__(self, token):
        self.token = token

    def resources(self):
        return [FakeResource()]


@pytest.fixture
def client():
    return TestClient(main.app)


def test_status_reports_disconnected_with_no_token(client):
    res = client.get("/api/status")
    assert res.json() == {"connected": False, "error": "No token configured"}


def test_connect_persists_token_and_connects(client, monkeypatch):
    monkeypatch.setattr(main, "MyPlexAccount", FakeAccount)
    res = client.post("/api/connect", json={"token": "secret-token"})
    assert res.status_code == 200
    assert res.json() == {"connected": True, "name": "Test Server"}
    assert settings_store.load_settings()["token"] == "secret-token"


def test_status_reconnects_from_persisted_token(client, monkeypatch):
    monkeypatch.setattr(main, "MyPlexAccount", FakeAccount)
    settings_store.save_settings(token="saved-token")
    res = client.get("/api/status")
    assert res.json() == {"connected": True, "name": "Test Server"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && python3 -m pytest tests/test_connect_status.py -v`
Expected: FAIL — `test_status_reconnects_from_persisted_token` fails because `/api/status` doesn't yet read `settings_store`.

- [ ] **Step 3: Update `web/main.py` imports and state**

Replace lines 1-27 (through `_token: str = os.environ.get("PLEX_TOKEN", "")`) with:

```python
"""
Structly — Plex Playlist Builder  (web backend)
"""

import asyncio
import json
import queue
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from settings_store import load_settings, save_settings

app = FastAPI()

# ── State ─────────────────────────────────────────────────────────────────────

_plex: Optional[PlexServer] = None
```

(This drops the `os` import since it's no longer used directly in this file, and drops the old `_token` global entirely — the persisted store is now the single source of truth.)

- [ ] **Step 4: Add `_try_connect` helper and rewrite `/api/status` + `/api/connect`**

Replace the existing `/api/status`, `/api/connect` block (original lines 113-156) with:

```python
def _try_connect(token: str) -> Optional[PlexServer]:
    if not token:
        return None
    account = MyPlexAccount(token=token)
    servers = [r for r in account.resources() if r.product == "Plex Media Server"]
    if not servers:
        return None
    return servers[0].connect()


@app.get("/api/status")
def status():
    global _plex
    if _plex:
        return {"connected": True, "name": _plex.friendlyName}
    token = load_settings().get("token", "")
    if not token:
        return {"connected": False, "error": "No token configured"}
    try:
        plex = _try_connect(token)
        if plex is None:
            return {"connected": False, "error": "No Plex Media Server found"}
        _plex = plex
        return {"connected": True, "name": _plex.friendlyName}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.get("/api/libraries")
def libraries():
    plex = get_plex()
    sections = [s.title for s in plex.library.sections() if s.type in ("movie", "show")]
    return {"libraries": sections}


class ConnectRequest(BaseModel):
    token: str


@app.post("/api/connect")
def connect(req: ConnectRequest):
    global _plex
    try:
        plex = _try_connect(req.token)
        if plex is None:
            raise HTTPException(400, "No Plex Media Server found on this account")
        _plex = plex
        save_settings(token=req.token)
        return {"connected": True, "name": _plex.friendlyName}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))
```

(`/api/libraries` is reproduced unchanged here only to show where it sits relative to the edited block — no logic change.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && python3 -m pytest tests/test_connect_status.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add web/main.py web/tests/test_connect_status.py
git commit -m "feat: persist Plex token via settings_store instead of env var"
```

---

### Task 4: Server-side adult-content filter + `/api/settings` endpoint

**Files:**
- Modify: `web/main.py` (add `is_adult_item`, add `/api/settings`, thread `include_adult` into `_build_worker`)
- Create: `web/tests/test_adult_filter.py`

**Interfaces:**
- Produces: `main.is_adult_item(item) -> bool`; `GET /api/settings -> {"include_adult_content": bool}`; `POST /api/settings {"include_adult_content": bool} -> {"include_adult_content": bool}`.
- Consumes: `PORN_ROOT` (existing constant), `settings_store.load_settings/save_settings` (Task 2).

- [ ] **Step 1: Add `web/tests/test_adult_filter.py` fixtures and failing test**

```python
import queue
from types import SimpleNamespace

import main


class FakeMedia:
    def __init__(self, path, resolution="1080"):
        self.parts = [SimpleNamespace(file=path)]
        self.videoResolution = resolution


class FakeItem:
    def __init__(self, path, studio=None, rating_key=None):
        self.media = [FakeMedia(path)]
        self.studio = studio
        self.genres = []
        self.directors = []
        self.roles = []
        self.duration = None
        self.addedAt = None
        self.ratingKey = rating_key or path


class FakePlaylist:
    def __init__(self, title):
        self.title = title
        self.deleted = False

    def delete(self):
        self.deleted = True


class FakeSection:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeLibrary:
    def __init__(self, section):
        self._section = section

    def section(self, name):
        return self._section


class FakePlex:
    def __init__(self, items, existing_playlists=None):
        self.library = FakeLibrary(FakeSection(items))
        self._playlists = existing_playlists or []
        self.created = []

    def playlists(self):
        return self._playlists

    def createPlaylist(self, name, section, items):
        self.created.append((name, [i.ratingKey for i in items]))
        return FakePlaylist(name)


def drain(q):
    msgs = []
    while True:
        msg = q.get_nowait()
        if msg is None:
            break
        msgs.append(msg)
    return msgs


def test_is_adult_item_true_under_porn_root():
    item = FakeItem("/other/Porn/StudioA/scene1.mp4")
    assert main.is_adult_item(item) is True


def test_is_adult_item_false_outside_porn_root():
    item = FakeItem("/movies/Regular/movie.mp4")
    assert main.is_adult_item(item) is False


def test_adult_items_skipped_by_default():
    items = [
        FakeItem("/other/Porn/StudioA/scene1.mp4", studio="StudioA"),
        FakeItem("/movies/Regular/movie.mp4", studio="RegularStudio"),
    ]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, include_adult=False)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 1


def test_adult_items_included_when_opted_in():
    items = [FakeItem("/other/Porn/StudioA/scene1.mp4", studio="StudioA")]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, include_adult=True)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && python3 -m pytest tests/test_adult_filter.py -v`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'is_adult_item'`, and `_build_worker` doesn't accept `include_adult`.

- [ ] **Step 3: Add `is_adult_item` next to the other helpers**

Insert after `resolution_label` (originally lines 59-64) in `web/main.py`:

```python
def is_adult_item(item) -> bool:
    try:
        path = item.media[0].parts[0].file
    except (IndexError, AttributeError):
        return False
    try:
        Path(path).relative_to(PORN_ROOT)
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Thread `include_adult` through `_build_worker`'s signature and skip loop**

Change the `_build_worker` signature (originally lines 174-183) to:

```python
def _build_worker(
    plex,
    library: str,
    prefix: str,
    mode: str,
    selected: set,
    actor_filter: str,
    rules_list: list,
    q: queue.Queue,
    include_adult: bool = False,
):
```

Inside the `for i, item in enumerate(all_items, 1):` loop, immediately after the loop opens (before the `if mode == "quick":` branch), add:

```python
            if not include_adult and is_adult_item(item):
                if i % 10 == 0 or i == total:
                    q.put({"type": "progress", "current": i, "total": total})
                continue
```

(The `skipped` counter itself is added in Task 5, along with the `matched` tracking this filter interacts with — this step only adds the exclusion.)

- [ ] **Step 5: Add `/api/settings` endpoints**

Add after `/api/connect` (before the `DestroyRequest` block):

```python
class SettingsRequest(BaseModel):
    include_adult_content: bool


@app.get("/api/settings")
def get_settings():
    return {"include_adult_content": load_settings().get("include_adult_content", False)}


@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    data = save_settings(include_adult_content=req.include_adult_content)
    return {"include_adult_content": data["include_adult_content"]}
```

- [ ] **Step 6: Update `/api/build` to pass `include_adult` from the persisted setting**

In the `build` route handler (originally lines 281-299), change the thread-start line:

```python
    include_adult = load_settings().get("include_adult_content", False)

    q = queue.Queue()
    threading.Thread(
        target=_build_worker,
        args=(plex, library, prefix, mode, selected, actor_filter.lower(), rules_list, q),
        kwargs={"include_adult": include_adult},
        daemon=True,
    ).start()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd web && python3 -m pytest tests/test_adult_filter.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add web/main.py web/tests/test_adult_filter.py
git commit -m "feat: enforce adult-content opt-out server-side, add /api/settings"
```

---

### Task 5: Accurate `skipped` count, `replaced` reporting, and dry-run support

**Files:**
- Modify: `web/main.py` (`upsert_playlist`, `_build_worker` body, `/api/build`)
- Create: `web/tests/test_build_reporting.py`

**Interfaces:**
- Produces: `main.upsert_playlist(plex, full_name, items, library_name, dry_run=False) -> bool` (returns whether a same-named playlist was replaced); `_build_worker(..., include_adult=False, dry_run=False)`; SSE `"playlist"` messages now include `replaced` and `dry_run`; SSE `"done"` messages now include real `skipped`.
- Consumes: `is_adult_item`, `_build_worker` signature from Task 4 (extends it further).

- [ ] **Step 1: Write the failing tests**

Create `web/tests/test_build_reporting.py`:

```python
import queue

from tests.test_adult_filter import FakeItem, FakePlaylist, FakePlex, drain
import main


def test_never_matched_items_count_as_skipped():
    items = [FakeItem("/movies/Regular/unmatched.mp4")]  # no studio set
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 1


def test_single_match_lands_in_misc_not_skipped():
    items = [FakeItem("/movies/Regular/one.mp4", studio="LonelyStudio")]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 0
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["name"] == "Misc"


def test_dry_run_makes_no_plex_mutations():
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="RegularStudio") for i in range(3)]
    existing = FakePlaylist("t Studio: RegularStudio")
    plex = FakePlex(items, existing_playlists=[existing])
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, dry_run=True)
    msgs = drain(q)
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["replaced"] is True
    assert playlist_msg["dry_run"] is True
    assert plex.created == []
    assert existing.deleted is False


def test_real_run_reports_replaced_and_mutates():
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="RegularStudio") for i in range(3)]
    existing = FakePlaylist("t Studio: RegularStudio")
    plex = FakePlex(items, existing_playlists=[existing])
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, dry_run=False)
    msgs = drain(q)
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["replaced"] is True
    assert playlist_msg["dry_run"] is False
    assert existing.deleted is True
    assert plex.created == [
        ("t Studio: RegularStudio", [i.ratingKey for i in items])
    ]


def test_new_playlist_reports_replaced_false():
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="NewStudio") for i in range(3)]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q)
    msgs = drain(q)
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["replaced"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && python3 -m pytest tests/test_build_reporting.py -v`
Expected: FAIL — `upsert_playlist()` doesn't return a value / doesn't accept `dry_run`, `_build_worker` doesn't accept `dry_run`, `"skipped"`/`"replaced"` keys missing from messages.

- [ ] **Step 3: Rewrite `upsert_playlist` to report replacement and honor dry-run**

Replace the existing `upsert_playlist` (originally lines 98-103):

```python
def upsert_playlist(plex, full_name: str, items: list, library_name: str, dry_run: bool = False) -> bool:
    replaced = False
    for pl in plex.playlists():
        if pl.title == full_name:
            replaced = True
            if not dry_run:
                pl.delete()
            break
    if not dry_run:
        plex.createPlaylist(full_name, section=plex.library.section(library_name), items=items)
    return replaced
```

- [ ] **Step 4: Rewrite `_build_worker` body — add `matched`/`skipped` tracking and `dry_run` threading**

Replace the full `_build_worker` function body with:

```python
def _build_worker(
    plex,
    library: str,
    prefix: str,
    mode: str,
    selected: set,
    actor_filter: str,
    rules_list: list,
    q: queue.Queue,
    include_adult: bool = False,
    dry_run: bool = False,
):
    try:
        section   = plex.library.section(library)
        all_items = section.all()
        total     = len(all_items)
        cutoff    = datetime.now() - timedelta(days=RECENT_DAYS)

        q.put({"type": "start", "total": total})

        groups: dict[str, list] = defaultdict(list)
        skipped = 0

        for i, item in enumerate(all_items, 1):
            if not include_adult and is_adult_item(item):
                skipped += 1
                if i % 10 == 0 or i == total:
                    q.put({"type": "progress", "current": i, "total": total})
                continue

            matched = False

            if mode == "quick":
                if "studio" in selected:
                    studio = getattr(item, "studio", None)
                    if studio:
                        groups[f"Studio: {studio}"].append(item)
                        matched = True
                if "genre" in selected:
                    for g in getattr(item, "genres", []):
                        groups[f"Genre: {g.tag}"].append(item)
                        matched = True
                if "director" in selected:
                    for d in getattr(item, "directors", []):
                        groups[f"Director: {d.tag}"].append(item)
                        matched = True
                if "actor" in selected:
                    for role in getattr(item, "roles", []):
                        if not actor_filter or actor_filter in role.tag.lower():
                            groups[f"Actor: {role.tag}"].append(item)
                            matched = True
                if "resolution" in selected:
                    lbl = resolution_label(item)
                    if lbl:
                        groups[f"Resolution: {lbl}"].append(item)
                        matched = True
                if "recent" in selected:
                    added = getattr(item, "addedAt", None)
                    if added and added >= cutoff:
                        groups[f"Recently Added (Last {RECENT_DAYS} Days)"].append(item)
                        matched = True
                if "folder" in selected:
                    try:
                        pg = parse_path_groups(item.media[0].parts[0].file)
                        if "studio" in pg:
                            groups[f"FLDR STU: {pg['studio']}"].append(item)
                            matched = True
                        if "category" in pg:
                            groups[f"FLDR Cat: {pg['category']}"].append(item)
                            matched = True
                    except (IndexError, AttributeError):
                        pass
                if "duration" in selected:
                    ms = getattr(item, "duration", None)
                    if ms:
                        if ms < 2 * 60_000:
                            groups["Duration: Under 2 Min"].append(item)
                            matched = True
                        elif ms < 5 * 60_000:
                            groups["Duration: 2–5 Min"].append(item)
                            matched = True
                        elif ms < 10 * 60_000:
                            groups["Duration: 5–10 Min"].append(item)
                            matched = True
                        elif ms > 60 * 60_000:
                            groups["Duration: Over 1 Hour"].append(item)
                            matched = True
            else:
                for rule in rules_list:
                    if item_matches_rule(item, rule):
                        groups[str(rule["id"])].append(item)
                        matched = True

            if not matched:
                skipped += 1

            if i % 10 == 0 or i == total:
                q.put({"type": "progress", "current": i, "total": total})

        q.put({"type": "log", "msg": f"Building playlists from {len(groups)} groups…"})

        created  = 0
        misc     = []
        seen_ids = set()

        if mode == "quick":
            pairs = sorted(groups.items())
        else:
            pairs = [(str(r["id"]), groups[str(r["id"])]) for r in rules_list]

        for key, items in pairs:
            if mode == "custom":
                rule = next((r for r in rules_list if str(r["id"]) == key), None)
                name = (rule.get("custom_name") or "").strip() or auto_name(rule or {})
            else:
                name = key

            if len(items) >= MIN_ITEMS:
                replaced = upsert_playlist(plex, f"{prefix}{name}", items, library, dry_run=dry_run)
                created += 1
                q.put({
                    "type": "playlist", "name": name, "count": len(items),
                    "replaced": replaced, "dry_run": dry_run,
                })
            else:
                for item in items:
                    if item.ratingKey not in seen_ids:
                        misc.append(item)
                        seen_ids.add(item.ratingKey)

        if misc:
            replaced = upsert_playlist(plex, f"{prefix}Misc", misc, library, dry_run=dry_run)
            created += 1
            q.put({
                "type": "playlist", "name": "Misc", "count": len(misc),
                "replaced": replaced, "dry_run": dry_run,
            })

        q.put({"type": "done", "created": created, "total": total, "skipped": skipped, "dry_run": dry_run})

    except Exception as e:
        q.put({"type": "error", "msg": str(e)})
    finally:
        q.put(None)
```

- [ ] **Step 5: Add `dry_run` to the `/api/build` route and pass it through**

Update the `build` route (already touched in Task 4 Step 6) to:

```python
@app.get("/api/build")
async def build(
    library: str,
    prefix: str  = "t ",
    mode: str    = "quick",
    types: str   = "",
    actor_filter: str = "",
    rules: str   = "[]",
    dry_run: bool = False,
):
    plex       = get_plex()
    selected   = set(types.split(",")) if types else set()
    rules_list = json.loads(rules)
    include_adult = load_settings().get("include_adult_content", False)

    q = queue.Queue()
    threading.Thread(
        target=_build_worker,
        args=(plex, library, prefix, mode, selected, actor_filter.lower(), rules_list, q),
        kwargs={"include_adult": include_adult, "dry_run": dry_run},
        daemon=True,
    ).start()

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, q.get)
            if msg is None:
                break
            yield f"data: {json.dumps(msg)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd web && python3 -m pytest tests/ -v`
Expected: all tests pass (Tasks 2–5 combined).

- [ ] **Step 7: Commit**

```bash
git add web/main.py web/tests/test_build_reporting.py
git commit -m "feat: report accurate skipped count, playlist replacement, and dry-run mode"
```

---

### Task 6: Frontend — auto-open Connect Plex modal + adult-content toggle

**Files:**
- Modify: `web/static/index.html` (settings modal)
- Modify: `web/static/app.js` (`init`, modal open/close, `saveSettings`)

**Interfaces:**
- Consumes: `GET/POST /api/settings` (Task 4).

- [ ] **Step 1: Add the adult-content checkbox to the settings modal**

In `web/static/index.html`, replace the modal body (originally lines 152-165):

```html
  <!-- Settings modal -->
  <div class="modal-overlay hidden" id="modal-overlay" onclick="onOverlayClick(event)">
    <div class="modal">
      <div class="modal-title">Plex Settings</div>
      <div class="field-label">Plex Token</div>
      <div class="muted" style="font-size:12px; margin-bottom:8px;">
        Connects via Plex cloud — works from anywhere.
      </div>
      <input type="password" id="token-input" class="text-input" placeholder="Your Plex token">

      <label class="toggle-item" style="margin-top:16px;">
        <input type="checkbox" id="adult-content-toggle">
        <span class="toggle-track"></span><span>Include adult-content library items</span>
      </label>

      <button class="btn-primary" onclick="saveSettings()" style="margin-top:16px;">
        Save &amp; Reconnect
      </button>
      <button class="btn-cancel" onclick="closeModal()">Cancel</button>
    </div>
  </div>
```

- [ ] **Step 2: Auto-open the modal on disconnect and load the current adult-content setting whenever it opens**

In `web/static/app.js`, replace `init()` (originally lines 9-21):

```js
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
```

Replace the settings-button wiring and modal helpers (originally lines 54-65):

```js
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
```

- [ ] **Step 3: Save the adult-content toggle alongside the token**

Replace `saveSettings()` (originally lines 71-90):

```js
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
```

- [ ] **Step 4: Manual verification**

Run: `cd web && uvicorn main:app --reload`
Open `http://localhost:8000` in a browser with no `~/.structly_settings.json` present (rename it aside if you have one).
Expected: the Connect Plex modal opens automatically on load — no need to find the gear icon. Toggle "Include adult-content library items", enter a token, save; reopen the modal (gear icon) and confirm the checkbox reflects the saved state.

- [ ] **Step 5: Commit**

```bash
git add web/static/index.html web/static/app.js
git commit -m "feat: auto-open Connect Plex modal, add adult-content toggle UI"
```

---

### Task 7: Frontend — Preview (dry run) button + skipped/replaced reporting

**Files:**
- Modify: `web/static/index.html` (add Preview button)
- Modify: `web/static/app.js` (`startBuild`, `resetBtn`, `appendPlaylistLog`, library-load button wiring)
- Modify: `web/static/style.css` (`.btn-row`, `.btn-secondary`)

**Interfaces:**
- Consumes: `dry_run` query param and `replaced`/`skipped` SSE fields from Task 5.

- [ ] **Step 1: Add the Preview button next to Build**

In `web/static/index.html`, replace the buttons block (originally lines 137-141):

```html
    <!-- Buttons -->
    <div class="btn-row">
      <button class="btn-primary" id="build-btn" disabled onclick="startBuild(false)">Build Playlists</button>
      <button class="btn-secondary" id="preview-btn" disabled onclick="startBuild(true)">Preview (Dry Run)</button>
    </div>
    <button class="btn-danger" id="destroy-btn" disabled onclick="confirmDestroy()">
      Destroy All Matching Playlists
    </button>
```

- [ ] **Step 2: Style the new button row**

In `web/static/style.css`, add after the `.btn-primary` rules (originally ending around line 384):

```css
.btn-row { display: flex; gap: 10px; }
.btn-row .btn-primary { flex: 2; }

.btn-secondary {
  flex: 1;
  background: transparent;
  color: var(--orange);
  border: 1px solid var(--orange);
  border-radius: 14px;
  padding: 16px;
  font-family: 'Inter', sans-serif;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-secondary:hover:not(:disabled) { background: rgba(240,100,40,.1); }
.btn-secondary:disabled { opacity: 0.45; cursor: default; }
```

- [ ] **Step 3: Enable the Preview button wherever Build gets enabled**

In `web/static/app.js`, in `loadLibraries()` (originally lines 23-36), add the new line:

```js
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
```

- [ ] **Step 4: Make `startBuild` accept a `dryRun` flag and report skipped/replaced**

Replace `startBuild` through `resetBtn` (originally lines 163-244):

```js
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
```

- [ ] **Step 5: Show replaced/created and dry-run state in the per-playlist log line**

Replace `appendPlaylistLog` (originally lines 296-304):

```js
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
```

- [ ] **Step 6: Manual verification**

Run: `cd web && uvicorn main:app --reload`, connect to a real Plex server, pick a library.
Click **Preview (Dry Run)**: confirm the log shows `would create`/`would replace` lines and the stats update, then check in Plex that no playlists were actually added or changed.
Click **Build Playlists**: confirm real playlists appear/update in Plex, and the "Skipped" stat is a real number (not always `0`) — e.g. temporarily uncheck all Quick toggle types except one narrow one to produce items with no match, and confirm Skipped reflects them.

- [ ] **Step 7: Commit**

```bash
git add web/static/index.html web/static/app.js web/static/style.css
git commit -m "feat: add dry-run preview and accurate skipped/replaced reporting to UI"
```

---

### Task 8: Frontend — fix mobile clipping at 390px

**Files:**
- Modify: `web/static/style.css` (add a `max-width: 480px` media query — no existing media queries in this file)

**Interfaces:** none (pure CSS).

- [ ] **Step 1: Add the responsive block**

Append to the end of `web/static/style.css`, after the scrollbar rules (originally lines 463-467):

```css
/* ── Responsive (mobile) ─────────────────────────────────────────────────── */

@media (max-width: 480px) {
  .container { padding: 20px 14px 36px; gap: 12px; }

  .header {
    flex-wrap: wrap;
    row-gap: 10px;
  }
  .brand-name { font-size: 24px; }
  .header-right { flex-wrap: wrap; }

  .badge { max-width: 100%; }
  .badge-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 160px;
  }

  .toggle-row { flex-wrap: wrap; row-gap: 10px; }
  .toggle-item {
    flex: 1 1 45%;
    min-width: 130px;
  }
  .toggle-item > span:last-child {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .stats-row { gap: 8px; }
  .stat-tile { padding: 10px 6px; }
  .stat-value { font-size: 21px; }
  .stat-label { font-size: 11px; }

  .btn-row { flex-direction: column; }

  .rule-fields { flex-direction: column; }
  .rule-field { min-width: 0; }
}
```

- [ ] **Step 2: Manual verification**

Run: `cd web && uvicorn main:app --reload`
Open Chrome DevTools → device toolbar → iPhone 12/13 preset (390×844).
Expected: no horizontal scrollbar anywhere on the page; the connection badge text truncates with `…` instead of overflowing; the three Playlist Types toggle rows wrap to two columns instead of clipping; the Scanned/Playlists/Skipped stat row stays inside the viewport; Build/Preview/Destroy buttons remain full-width and legible.

- [ ] **Step 3: Commit**

```bash
git add web/static/style.css
git commit -m "fix: responsive layout for mobile widths, stop horizontal clipping"
```

---

## Summary of what's deliberately NOT in this plan

- Item 5 (typed confirmation before Destroy) — excluded per explicit user instruction ("ignore step 5").
- Rotating the actual leaked Plex token — that's a manual Plex-account action called out above; no code task can do it.
- Refactoring `app_v4.py`'s own inline `load_settings()`/`save_settings()` (desktop CTk app) to share `web/settings_store.py` — both already read/write the same `~/.structly_settings.json` file compatibly, so behavior is unified even though the code isn't; de-duplicating that is a reasonable future cleanup but wasn't asked for here.
