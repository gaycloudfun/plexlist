# Structly Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, browser-based rewrite of Structly (FastAPI backend + React/Vite/TypeScript frontend) that reproduces `app_v4.py`'s Quick/Auto and Rule-builder playlist modes, adds an opt-in adult-content toggle, and fixes the hardcoded-credential fallback — packaged into the same `.dmg` distribution as today.

**Architecture:** A `webapp/backend` FastAPI app exposes REST + SSE endpoints. Business logic (path parsing, adult-content filtering, grouping, rule matching) lives in plain-Python modules that operate on a `MediaItem` dataclass — not raw `plexapi` objects — so it's fully unit-testable without a live Plex server. A thin adapter (`plex_client.py`) converts real `plexapi` objects to `MediaItem`s. The `webapp/frontend` React app talks to the backend over local HTTP/SSE. Settings (Plex URL, token, adult-content toggle) persist to `~/.structly_settings.json`; no credentials are hardcoded in the packaged build.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, plexapi 4.18, pytest, httpx (for `TestClient`), python-dotenv (dev-only credential fallback). Node 22, React 18, Vite, TypeScript, Vitest + React Testing Library.

## Global Constraints

- Settings persist to `~/.structly_settings.json` with keys: `plex_url` (str), `plex_token` (str), `include_adult_content` (bool, default `false`).
- No hardcoded Plex URL/token may ship in the packaged build. Dev-only fallback reads `STRUCTLY_DEV_PLEX_URL` / `STRUCTLY_DEV_PLEX_TOKEN` from an untracked `.env` file, loaded via `python-dotenv`, and only applies when no settings file exists.
- Adult-content root path is `/other/Porn` (matches existing `PORN_ROOT` constant in `app_v4.py`/`build_playlists.py`).
- All new backend logic goes under `plex_playlist_builder/webapp/backend/`; all new frontend code under `plex_playlist_builder/webapp/frontend/`. The existing `web/` and `app_v4.py` directories/files are left untouched.
- Every backend module: write the failing test first, watch it fail, then implement (per the active test-driven-development skill).

---

### Task 1: Backend scaffold + settings/credentials module

**Files:**
- Create: `webapp/backend/__init__.py`
- Create: `webapp/backend/settings.py`
- Create: `webapp/requirements.txt`
- Create: `webapp/requirements-dev.txt`
- Create: `webapp/.env.example`
- Create: `webapp/.gitignore`
- Test: `webapp/tests/__init__.py`
- Test: `webapp/tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` (TypedDict: `plex_url: str`, `plex_token: str`, `include_adult_content: bool`), `load_settings() -> Settings`, `save_settings(settings: Settings) -> None`, `is_configured() -> bool`, `SETTINGS_PATH: Path` (module-level, monkeypatchable by tests).

- [ ] **Step 1: Create directories and empty package files**

```bash
mkdir -p webapp/backend webapp/tests
touch webapp/backend/__init__.py webapp/tests/__init__.py
```

- [ ] **Step 2: Write dependency and env files**

`webapp/requirements.txt`:
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
plexapi>=4.15.0
python-dotenv>=1.0.0
```

`webapp/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0.0
httpx>=0.27.0
```

`webapp/.env.example`:
```
STRUCTLY_DEV_PLEX_URL=http://your-plex-server-ip:32400
STRUCTLY_DEV_PLEX_TOKEN=your_dev_token_here
```

`webapp/.gitignore`:
```
.env
__pycache__/
*.pyc
node_modules/
dist/
frontend/dist/
```

- [ ] **Step 3: Install dependencies**

```bash
cd webapp && pip3 install -r requirements-dev.txt
```

- [ ] **Step 4: Write the failing test for default settings**

`webapp/tests/test_settings.py`:
```python
import json

import pytest

from backend import settings as settings_module


@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "structly_settings.json")
    monkeypatch.delenv("STRUCTLY_DEV_PLEX_URL", raising=False)
    monkeypatch.delenv("STRUCTLY_DEV_PLEX_TOKEN", raising=False)


def test_load_settings_returns_defaults_when_no_file_and_no_dev_env():
    result = settings_module.load_settings()

    assert result == {
        "plex_url": "",
        "plex_token": "",
        "include_adult_content": False,
    }
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend'` (module doesn't exist yet)

- [ ] **Step 6: Write minimal settings.py to pass**

`webapp/backend/settings.py`:
```python
import json
import os
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

load_dotenv()

SETTINGS_PATH = Path.home() / ".structly_settings.json"


class Settings(TypedDict):
    plex_url: str
    plex_token: str
    include_adult_content: bool


DEFAULT_SETTINGS: Settings = {
    "plex_url": "",
    "plex_token": "",
    "include_adult_content": False,
}


def load_settings() -> Settings:
    if SETTINGS_PATH.exists():
        data = json.loads(SETTINGS_PATH.read_text())
        return {
            "plex_url": data.get("plex_url", ""),
            "plex_token": data.get("plex_token", ""),
            "include_adult_content": bool(data.get("include_adult_content", False)),
        }
    return dict(DEFAULT_SETTINGS)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 8: Write the failing test for save/load roundtrip**

Add to `webapp/tests/test_settings.py`:
```python
def test_save_and_load_settings_roundtrip():
    settings_module.save_settings({
        "plex_url": "http://192.168.1.5:32400",
        "plex_token": "abc123",
        "include_adult_content": True,
    })

    result = settings_module.load_settings()

    assert result == {
        "plex_url": "http://192.168.1.5:32400",
        "plex_token": "abc123",
        "include_adult_content": True,
    }
```

- [ ] **Step 9: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: FAIL with `AttributeError: module 'backend.settings' has no attribute 'save_settings'`

- [ ] **Step 10: Add save_settings to pass**

Append to `webapp/backend/settings.py`:
```python
def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
```

- [ ] **Step 11: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 12: Write the failing test for dev-env fallback**

Add to `webapp/tests/test_settings.py`:
```python
def test_load_settings_uses_dev_env_fallback_when_no_file(monkeypatch):
    monkeypatch.setenv("STRUCTLY_DEV_PLEX_URL", "http://dev.local:32400")
    monkeypatch.setenv("STRUCTLY_DEV_PLEX_TOKEN", "dev-token")

    result = settings_module.load_settings()

    assert result == {
        "plex_url": "http://dev.local:32400",
        "plex_token": "dev-token",
        "include_adult_content": False,
    }


def test_load_settings_ignores_dev_env_when_settings_file_exists():
    settings_module.save_settings({
        "plex_url": "http://saved:32400",
        "plex_token": "saved-token",
        "include_adult_content": True,
    })

    result = settings_module.load_settings()

    assert result["plex_url"] == "http://saved:32400"
```

- [ ] **Step 13: Run tests to verify the new one fails**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: `test_load_settings_uses_dev_env_fallback_when_no_file` FAILS (returns empty strings, not the env values); `test_load_settings_ignores_dev_env_when_settings_file_exists` passes already

- [ ] **Step 14: Add dev-env fallback to pass**

Replace `load_settings` in `webapp/backend/settings.py`:
```python
def _dev_fallback() -> Settings:
    return {
        "plex_url": os.environ.get("STRUCTLY_DEV_PLEX_URL", ""),
        "plex_token": os.environ.get("STRUCTLY_DEV_PLEX_TOKEN", ""),
        "include_adult_content": False,
    }


def load_settings() -> Settings:
    if SETTINGS_PATH.exists():
        data = json.loads(SETTINGS_PATH.read_text())
        return {
            "plex_url": data.get("plex_url", ""),
            "plex_token": data.get("plex_token", ""),
            "include_adult_content": bool(data.get("include_adult_content", False)),
        }
    fallback = _dev_fallback()
    if fallback["plex_url"] and fallback["plex_token"]:
        return fallback
    return dict(DEFAULT_SETTINGS)
```

- [ ] **Step 15: Run tests to verify all pass**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: PASS (4 tests)

- [ ] **Step 16: Write the failing test for is_configured**

Add to `webapp/tests/test_settings.py`:
```python
def test_is_configured_false_when_no_settings():
    assert settings_module.is_configured() is False


def test_is_configured_true_when_url_and_token_present():
    settings_module.save_settings({
        "plex_url": "http://x:32400",
        "plex_token": "tok",
        "include_adult_content": False,
    })

    assert settings_module.is_configured() is True
```

- [ ] **Step 17: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: FAIL with `AttributeError: module 'backend.settings' has no attribute 'is_configured'`

- [ ] **Step 18: Add is_configured to pass**

Append to `webapp/backend/settings.py`:
```python
def is_configured() -> bool:
    current = load_settings()
    return bool(current["plex_url"] and current["plex_token"])
```

- [ ] **Step 19: Run full test suite to verify all pass**

Run: `cd webapp && python3 -m pytest tests/test_settings.py -v`
Expected: PASS (6 tests), no errors or warnings

- [ ] **Step 20: Commit**

```bash
git add webapp/backend/__init__.py webapp/backend/settings.py webapp/requirements.txt webapp/requirements-dev.txt webapp/.env.example webapp/.gitignore webapp/tests/__init__.py webapp/tests/test_settings.py
git commit -m "feat(webapp): add settings module with dev-only credential fallback"
```

---

### Task 2: Plex client wrapper

**Files:**
- Create: `webapp/backend/plex_client.py`
- Test: `webapp/tests/test_plex_client.py`

**Interfaces:**
- Produces: `MediaItem` (dataclass), `connect_to_plex(url: str, token: str) -> PlexServer`, `list_libraries(plex) -> list[str]`, `fetch_items(plex, library: str) -> list[MediaItem]`, `upsert_playlist(plex, name: str, items: list, library: str) -> None`, `destroy_playlists(plex, prefix: str) -> int`.

Note: `MediaItem` is defined here (not in Task 3) because `plex_client.py` needs it to type its adapter function. Task 3 imports `MediaItem` from this module.

- [ ] **Step 1: Write the failing test for connect_to_plex passthrough**

`webapp/tests/test_plex_client.py`:
```python
from dataclasses import dataclass

from backend import plex_client


@dataclass
class FakeSection:
    title: str
    type: str


class FakeLibrary:
    def __init__(self, sections):
        self._sections = sections

    def sections(self):
        return self._sections

    def section(self, name):
        return next(s for s in self._sections if s.title == name)


class FakePlex:
    def __init__(self, sections=None, items=None, playlists=None):
        self.library = FakeLibrary(sections or [])
        self._items = items or []
        self._playlists = playlists or []
        self.created = []

    def playlists(self):
        return self._playlists

    def createPlaylist(self, name, section, items):
        self.created.append((name, section, items))


def test_connect_to_plex_passes_url_and_token(monkeypatch):
    captured = {}

    class FakePlexServer:
        def __init__(self, url, token):
            captured["url"] = url
            captured["token"] = token

    monkeypatch.setattr(plex_client, "PlexServer", FakePlexServer)

    plex_client.connect_to_plex("http://192.168.1.5:32400", "tok123")

    assert captured == {"url": "http://192.168.1.5:32400", "token": "tok123"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.plex_client'`

- [ ] **Step 3: Write plex_client.py with MediaItem and connect_to_plex**

`webapp/backend/plex_client.py`:
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from plexapi.server import PlexServer


@dataclass
class MediaItem:
    id: str
    title: str
    studio: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    resolution: Optional[str] = None
    duration_ms: Optional[int] = None
    added_at: Optional[datetime] = None
    file_path: Optional[str] = None


def connect_to_plex(url: str, token: str) -> PlexServer:
    return PlexServer(url, token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for list_libraries filtering**

Add to `webapp/tests/test_plex_client.py`:
```python
def test_list_libraries_filters_to_movie_and_show_types():
    fake_plex = FakePlex(sections=[
        FakeSection(title="Movies", type="movie"),
        FakeSection(title="TV Shows", type="show"),
        FakeSection(title="Music", type="artist"),
    ])

    result = plex_client.list_libraries(fake_plex)

    assert result == ["Movies", "TV Shows"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: FAIL with `AttributeError: module 'backend.plex_client' has no attribute 'list_libraries'`

- [ ] **Step 7: Add list_libraries to pass**

Append to `webapp/backend/plex_client.py`:
```python
def list_libraries(plex: PlexServer) -> list[str]:
    return [s.title for s in plex.library.sections() if s.type in ("movie", "show")]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Write the failing test for fetch_items adapting raw plex items**

Add to `webapp/tests/test_plex_client.py`:
```python
from dataclasses import dataclass as _dc
from datetime import datetime


@_dc
class FakeTag:
    tag: str


@_dc
class FakePart:
    file: str


@_dc
class FakeMedia:
    parts: list
    videoResolution: str = "1080"


class FakeItem:
    def __init__(self, rating_key, title, studio=None, genres=None, directors=None,
                 actors=None, duration=None, added_at=None, file_path="/movies/x.mp4"):
        self.ratingKey = rating_key
        self.title = title
        self.studio = studio
        self.genres = [FakeTag(g) for g in (genres or [])]
        self.directors = [FakeTag(d) for d in (directors or [])]
        self.roles = [FakeTag(a) for a in (actors or [])]
        self.duration = duration
        self.addedAt = added_at
        self.media = [FakeMedia(parts=[FakePart(file=file_path)])]


def test_fetch_items_adapts_raw_plex_items_to_media_items():
    added = datetime(2026, 1, 1)
    fake_item = FakeItem(
        rating_key=42, title="Some Movie", studio="Warner",
        genres=["Action"], directors=["Jane Doe"], actors=["John Roe"],
        duration=120_000, added_at=added, file_path="/movies/some.mp4",
    )
    fake_plex = FakePlex(sections=[FakeSection(title="Movies", type="movie")])
    fake_section = fake_plex.library.section("Movies")
    fake_section.all = lambda: [fake_item]

    result = plex_client.fetch_items(fake_plex, "Movies")

    assert result == [plex_client.MediaItem(
        id="42",
        title="Some Movie",
        studio="Warner",
        genres=["Action"],
        directors=["Jane Doe"],
        actors=["John Roe"],
        resolution="1080",
        duration_ms=120_000,
        added_at=added,
        file_path="/movies/some.mp4",
    )]
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: FAIL with `AttributeError: module 'backend.plex_client' has no attribute 'fetch_items'`

- [ ] **Step 11: Add fetch_items and adapter to pass**

Append to `webapp/backend/plex_client.py`:
```python
def fetch_items(plex: PlexServer, library: str) -> list[MediaItem]:
    section = plex.library.section(library)
    return [_to_media_item(item) for item in section.all()]


def _to_media_item(item) -> MediaItem:
    try:
        file_path = item.media[0].parts[0].file
    except (IndexError, AttributeError):
        file_path = None
    try:
        resolution = item.media[0].videoResolution
    except (IndexError, AttributeError):
        resolution = None
    return MediaItem(
        id=str(item.ratingKey),
        title=item.title,
        studio=getattr(item, "studio", None),
        genres=[g.tag for g in getattr(item, "genres", [])],
        directors=[d.tag for d in getattr(item, "directors", [])],
        actors=[r.tag for r in getattr(item, "roles", [])],
        resolution=resolution,
        duration_ms=getattr(item, "duration", None),
        added_at=getattr(item, "addedAt", None),
        file_path=file_path,
    )
```

- [ ] **Step 12: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 13: Write the failing test for upsert_playlist replacing an existing playlist**

Add to `webapp/tests/test_plex_client.py`:
```python
class FakePlaylist:
    def __init__(self, title):
        self.title = title
        self.deleted = False

    def delete(self):
        self.deleted = True


def test_upsert_playlist_deletes_existing_then_creates():
    existing = FakePlaylist("t Studio: Warner")
    fake_plex = FakePlex(
        sections=[FakeSection(title="Movies", type="movie")],
        playlists=[existing],
    )

    plex_client.upsert_playlist(fake_plex, "t Studio: Warner", ["item1", "item2"], "Movies")

    assert existing.deleted is True
    assert fake_plex.created == [("t Studio: Warner", fake_plex.library.section("Movies"), ["item1", "item2"])]
```

- [ ] **Step 14: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: FAIL with `AttributeError: module 'backend.plex_client' has no attribute 'upsert_playlist'`

- [ ] **Step 15: Add upsert_playlist to pass**

Append to `webapp/backend/plex_client.py`:
```python
def upsert_playlist(plex: PlexServer, name: str, items: list, library: str) -> None:
    for pl in plex.playlists():
        if pl.title == name:
            pl.delete()
            break
    plex.createPlaylist(name, section=plex.library.section(library), items=items)
```

- [ ] **Step 16: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 17: Write the failing test for destroy_playlists**

Add to `webapp/tests/test_plex_client.py`:
```python
def test_destroy_playlists_removes_matching_prefix_only():
    match1 = FakePlaylist("t Studio: Warner")
    match2 = FakePlaylist("t Genre: Action")
    other = FakePlaylist("Keep Me")
    fake_plex = FakePlex(playlists=[match1, match2, other])

    count = plex_client.destroy_playlists(fake_plex, "t ")

    assert count == 2
    assert match1.deleted is True
    assert match2.deleted is True
    assert other.deleted is False
```

- [ ] **Step 18: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: FAIL with `AttributeError: module 'backend.plex_client' has no attribute 'destroy_playlists'`

- [ ] **Step 19: Add destroy_playlists to pass**

Append to `webapp/backend/plex_client.py`:
```python
def destroy_playlists(plex: PlexServer, prefix: str) -> int:
    targets = [pl for pl in plex.playlists() if pl.title.startswith(prefix)]
    for pl in targets:
        pl.delete()
    return len(targets)
```

- [ ] **Step 20: Run full test suite to verify all pass**

Run: `cd webapp && python3 -m pytest tests/test_plex_client.py -v`
Expected: PASS (5 tests), no errors or warnings

- [ ] **Step 21: Commit**

```bash
git add webapp/backend/plex_client.py webapp/tests/test_plex_client.py
git commit -m "feat(webapp): add plex_client wrapper with MediaItem adapter"
```

---

### Task 3: Playlist engine — path parsing and adult-content filter

**Files:**
- Create: `webapp/backend/playlist_engine.py`
- Test: `webapp/tests/test_playlist_engine.py`

**Interfaces:**
- Consumes: `MediaItem` from `backend.plex_client` (Task 2).
- Produces: `PORN_ROOT: str`, `parse_path_groups(file_path: str, porn_root: str = PORN_ROOT) -> dict`, `is_adult_item(item: MediaItem, porn_root: str = PORN_ROOT) -> bool`, `filter_adult_content(items: list[MediaItem], include_adult: bool, porn_root: str = PORN_ROOT) -> list[MediaItem]`, `resolution_label(resolution: str | None) -> str | None`.

- [ ] **Step 1: Write the failing test for parse_path_groups with a studio folder**

`webapp/tests/test_playlist_engine.py`:
```python
import pytest

from backend import playlist_engine
from backend.plex_client import MediaItem


def test_parse_path_groups_extracts_studio_from_folder_name():
    result = playlist_engine.parse_path_groups("/other/Porn/MuscleBearPorn/scene.mp4")

    assert result == {"studio": "MuscleBearPorn"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.playlist_engine'`

- [ ] **Step 3: Write playlist_engine.py with parse_path_groups**

`webapp/backend/playlist_engine.py`:
```python
from pathlib import Path

from backend.plex_client import MediaItem

PORN_ROOT = "/other/Porn"
CATEGORIES_FOLDER = "CATEGORIES"

RESOLUTION_MAP = {
    "4k": "4K", "2160": "4K",
    "1080": "1080p",
    "720": "720p",
}


def parse_path_groups(file_path: str, porn_root: str = PORN_ROOT) -> dict:
    groups = {}
    try:
        rel = Path(file_path).relative_to(porn_root)
        parts = rel.parts
        if not parts:
            return groups
        if parts[0].upper() == CATEGORIES_FOLDER.upper():
            if len(parts) >= 2:
                groups["category"] = parts[1].title()
        else:
            groups["studio"] = parts[0]
    except ValueError:
        pass
    return groups
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for parse_path_groups with a categories folder and a non-matching path**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_parse_path_groups_extracts_category_from_categories_folder():
    result = playlist_engine.parse_path_groups("/other/Porn/CATEGORIES/fetish/scene.mp4")

    assert result == {"category": "Fetish"}


def test_parse_path_groups_returns_empty_for_path_outside_porn_root():
    result = playlist_engine.parse_path_groups("/movies/some_movie.mp4")

    assert result == {}
```

- [ ] **Step 6: Run tests to verify they pass already (regression check) or fail correctly**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (all 3) — this confirms the Step 3 implementation already handles these cases; if either fails, fix `parse_path_groups` before continuing.

- [ ] **Step 7: Write the failing test for is_adult_item**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_is_adult_item_true_for_path_under_porn_root():
    item = MediaItem(id="1", title="x", file_path="/other/Porn/Studio/scene.mp4")

    assert playlist_engine.is_adult_item(item) is True


def test_is_adult_item_false_for_path_outside_porn_root():
    item = MediaItem(id="1", title="x", file_path="/movies/x.mp4")

    assert playlist_engine.is_adult_item(item) is False


def test_is_adult_item_false_when_no_file_path():
    item = MediaItem(id="1", title="x", file_path=None)

    assert playlist_engine.is_adult_item(item) is False
```

- [ ] **Step 8: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'is_adult_item'`

- [ ] **Step 9: Add is_adult_item to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
def is_adult_item(item: MediaItem, porn_root: str = PORN_ROOT) -> bool:
    if not item.file_path:
        return False
    try:
        Path(item.file_path).relative_to(porn_root)
        return True
    except ValueError:
        return False
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (6 tests)

- [ ] **Step 11: Write the failing test for filter_adult_content**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_filter_adult_content_excludes_adult_items_when_not_included():
    regular = MediaItem(id="1", title="Movie", file_path="/movies/x.mp4")
    adult = MediaItem(id="2", title="Scene", file_path="/other/Porn/Studio/scene.mp4")

    result = playlist_engine.filter_adult_content([regular, adult], include_adult=False)

    assert result == [regular]


def test_filter_adult_content_includes_all_items_when_included():
    regular = MediaItem(id="1", title="Movie", file_path="/movies/x.mp4")
    adult = MediaItem(id="2", title="Scene", file_path="/other/Porn/Studio/scene.mp4")

    result = playlist_engine.filter_adult_content([regular, adult], include_adult=True)

    assert result == [regular, adult]
```

- [ ] **Step 12: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'filter_adult_content'`

- [ ] **Step 13: Add filter_adult_content to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
def filter_adult_content(
    items: list[MediaItem], include_adult: bool, porn_root: str = PORN_ROOT
) -> list[MediaItem]:
    if include_adult:
        return items
    return [item for item in items if not is_adult_item(item, porn_root)]
```

- [ ] **Step 14: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (8 tests)

- [ ] **Step 15: Write the failing test for resolution_label**

Add to `webapp/tests/test_playlist_engine.py`:
```python
@pytest.mark.parametrize("raw,expected", [
    ("4k", "4K"),
    ("2160", "4K"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("480", "SD"),
    (None, None),
])
def test_resolution_label_maps_known_and_unknown_resolutions(raw, expected):
    assert playlist_engine.resolution_label(raw) == expected
```

- [ ] **Step 16: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'resolution_label'`

- [ ] **Step 17: Add resolution_label to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
def resolution_label(resolution: str | None) -> str | None:
    if not resolution:
        return None
    return RESOLUTION_MAP.get(str(resolution).lower(), "SD")
```

- [ ] **Step 18: Run full test suite to verify all pass**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (14 tests), no errors or warnings

- [ ] **Step 19: Commit**

```bash
git add webapp/backend/playlist_engine.py webapp/tests/test_playlist_engine.py
git commit -m "feat(webapp): add path parsing, adult-content filter, resolution labeling"
```

---

### Task 4: Playlist engine — quick-mode grouping and rule-based custom mode

**Files:**
- Modify: `webapp/backend/playlist_engine.py`
- Modify: `webapp/tests/test_playlist_engine.py`

**Interfaces:**
- Consumes: `MediaItem`, `parse_path_groups`, `resolution_label` (all from this task/Task 3, same file).
- Produces: `item_matches_rule(item: MediaItem, rule: dict) -> bool`, `auto_name(rule: dict) -> str`, `group_quick_mode(items: list[MediaItem], selected: set[str], actor_filter: str = "", recent_days: int = 30, porn_root: str = PORN_ROOT) -> dict[str, list[MediaItem]]`, `group_custom_mode(items: list[MediaItem], rules: list[dict]) -> dict[str, list[MediaItem]]`.

- [ ] **Step 1: Write the failing test for item_matches_rule with a studio filter**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_item_matches_rule_by_studio_case_insensitive_substring():
    item = MediaItem(id="1", title="x", studio="Warner Bros")

    assert playlist_engine.item_matches_rule(item, {"studio": "warner"}) is True
    assert playlist_engine.item_matches_rule(item, {"studio": "Universal"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'item_matches_rule'`

- [ ] **Step 3: Add item_matches_rule (studio-only) to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
def item_matches_rule(item: MediaItem, rule: dict) -> bool:
    if rule.get("studio"):
        if rule["studio"].lower() not in (item.studio or "").lower():
            return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for genre, director, actor, and duration matching**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_item_matches_rule_by_genre_director_actor():
    item = MediaItem(
        id="1", title="x",
        genres=["Action", "Comedy"], directors=["Jane Doe"], actors=["John Roe"],
    )

    assert playlist_engine.item_matches_rule(item, {"genre": "comedy"}) is True
    assert playlist_engine.item_matches_rule(item, {"genre": "horror"}) is False
    assert playlist_engine.item_matches_rule(item, {"director": "jane"}) is True
    assert playlist_engine.item_matches_rule(item, {"actor": "john"}) is True
    assert playlist_engine.item_matches_rule(item, {"actor": "nobody"}) is False


@pytest.mark.parametrize("duration_label,ms,expected", [
    ("< 2 min", 60_000, True),
    ("< 2 min", 180_000, False),
    ("2–5 min", 3 * 60_000, True),
    ("5–10 min", 7 * 60_000, True),
    ("> 1 hour", 90 * 60_000, True),
    ("> 1 hour", 30 * 60_000, False),
    ("Any", 1, True),
])
def test_item_matches_rule_by_duration(duration_label, ms, expected):
    item = MediaItem(id="1", title="x", duration_ms=ms)

    assert playlist_engine.item_matches_rule(item, {"duration": duration_label}) is expected
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL — genre/director/actor/duration assertions return `True` incorrectly (current implementation ignores those rule keys)

- [ ] **Step 7: Complete item_matches_rule to pass**

Replace `item_matches_rule` in `webapp/backend/playlist_engine.py`:
```python
def item_matches_rule(item: MediaItem, rule: dict) -> bool:
    if rule.get("studio"):
        if rule["studio"].lower() not in (item.studio or "").lower():
            return False
    if rule.get("genre"):
        if not any(rule["genre"].lower() in g.lower() for g in item.genres):
            return False
    if rule.get("director"):
        if not any(rule["director"].lower() in d.lower() for d in item.directors):
            return False
    if rule.get("actor"):
        if not any(rule["actor"].lower() in a.lower() for a in item.actors):
            return False
    duration = rule.get("duration", "Any")
    if duration != "Any":
        ms = item.duration_ms or 0
        if duration == "< 2 min" and not ms < 2 * 60_000:
            return False
        if duration == "2–5 min" and not 2 * 60_000 <= ms < 5 * 60_000:
            return False
        if duration == "5–10 min" and not 5 * 60_000 <= ms < 10 * 60_000:
            return False
        if duration == "> 1 hour" and not ms > 60 * 60_000:
            return False
    return True
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 9: Write the failing test for auto_name**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_auto_name_joins_present_fields_title_cased():
    result = playlist_engine.auto_name({"studio": "warner", "actor": "john roe"})

    assert result == "Warner · John Roe"


def test_auto_name_returns_custom_when_no_fields_present():
    assert playlist_engine.auto_name({}) == "Custom"
```

- [ ] **Step 10: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'auto_name'`

- [ ] **Step 11: Add auto_name to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
def auto_name(rule: dict) -> str:
    parts = [rule[k].title() for k in ("studio", "genre", "director", "actor") if rule.get(k)]
    return " · ".join(parts) or "Custom"
```

- [ ] **Step 12: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS

- [ ] **Step 13: Write the failing test for group_quick_mode by studio and genre**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_group_quick_mode_groups_by_studio_and_genre():
    item1 = MediaItem(id="1", title="A", studio="Warner", genres=["Action"])
    item2 = MediaItem(id="2", title="B", studio="Warner", genres=["Comedy"])

    result = playlist_engine.group_quick_mode([item1, item2], selected={"studio", "genre"})

    assert result["Studio: Warner"] == [item1, item2]
    assert result["Genre: Action"] == [item1]
    assert result["Genre: Comedy"] == [item2]
```

- [ ] **Step 14: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'group_quick_mode'`

- [ ] **Step 15: Add group_quick_mode (studio + genre only) to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
from collections import defaultdict
from datetime import datetime, timedelta


def group_quick_mode(
    items: list[MediaItem],
    selected: set[str],
    actor_filter: str = "",
    recent_days: int = 30,
    porn_root: str = PORN_ROOT,
) -> dict[str, list[MediaItem]]:
    groups: dict[str, list[MediaItem]] = defaultdict(list)

    for item in items:
        if "studio" in selected and item.studio:
            groups[f"Studio: {item.studio}"].append(item)
        if "genre" in selected:
            for g in item.genres:
                groups[f"Genre: {g}"].append(item)

    return dict(groups)
```

- [ ] **Step 16: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS

- [ ] **Step 17: Write the failing test for the remaining quick-mode groupings**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_group_quick_mode_groups_by_director_actor_resolution_folder_duration_recent():
    now = datetime.now()
    item = MediaItem(
        id="1", title="A",
        directors=["Jane Doe"], actors=["John Roe"], resolution="1080",
        duration_ms=3 * 60_000, added_at=now, file_path="/other/Porn/StudioX/scene.mp4",
    )

    result = playlist_engine.group_quick_mode(
        [item],
        selected={"director", "actor", "resolution", "folder", "duration", "recent"},
    )

    assert result["Director: Jane Doe"] == [item]
    assert result["Actor: John Roe"] == [item]
    assert result["Resolution: 1080p"] == [item]
    assert result["FLDR STU: StudioX"] == [item]
    assert result["Duration: 2–5 Min"] == [item]
    assert result["Recently Added (Last 30 Days)"] == [item]


def test_group_quick_mode_actor_filter_excludes_non_matching_actors():
    item = MediaItem(id="1", title="A", actors=["John Roe", "Jane Smith"])

    result = playlist_engine.group_quick_mode([item], selected={"actor"}, actor_filter="jane")

    assert "Actor: Jane Smith" in result
    assert "Actor: John Roe" not in result
```

- [ ] **Step 18: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL — director/actor/resolution/folder/duration/recent groups are missing (current implementation only handles studio/genre)

- [ ] **Step 19: Complete group_quick_mode to pass**

Replace `group_quick_mode` in `webapp/backend/playlist_engine.py`:
```python
def group_quick_mode(
    items: list[MediaItem],
    selected: set[str],
    actor_filter: str = "",
    recent_days: int = 30,
    porn_root: str = PORN_ROOT,
) -> dict[str, list[MediaItem]]:
    groups: dict[str, list[MediaItem]] = defaultdict(list)
    cutoff = datetime.now() - timedelta(days=recent_days)

    for item in items:
        if "studio" in selected and item.studio:
            groups[f"Studio: {item.studio}"].append(item)
        if "genre" in selected:
            for g in item.genres:
                groups[f"Genre: {g}"].append(item)
        if "director" in selected:
            for d in item.directors:
                groups[f"Director: {d}"].append(item)
        if "actor" in selected:
            for a in item.actors:
                if not actor_filter or actor_filter.lower() in a.lower():
                    groups[f"Actor: {a}"].append(item)
        if "resolution" in selected:
            lbl = resolution_label(item.resolution)
            if lbl:
                groups[f"Resolution: {lbl}"].append(item)
        if "recent" in selected and item.added_at and item.added_at >= cutoff:
            groups[f"Recently Added (Last {recent_days} Days)"].append(item)
        if "folder" in selected and item.file_path:
            pg = parse_path_groups(item.file_path, porn_root)
            if "studio" in pg:
                groups[f"FLDR STU: {pg['studio']}"].append(item)
            if "category" in pg:
                groups[f"FLDR Cat: {pg['category']}"].append(item)
        if "duration" in selected and item.duration_ms:
            ms = item.duration_ms
            if ms < 2 * 60_000:
                groups["Duration: Under 2 Min"].append(item)
            elif ms < 5 * 60_000:
                groups["Duration: 2–5 Min"].append(item)
            elif ms < 10 * 60_000:
                groups["Duration: 5–10 Min"].append(item)
            elif ms > 60 * 60_000:
                groups["Duration: Over 1 Hour"].append(item)

    return dict(groups)
```

- [ ] **Step 20: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (all tests)

- [ ] **Step 21: Write the failing test for group_custom_mode**

Add to `webapp/tests/test_playlist_engine.py`:
```python
def test_group_custom_mode_groups_items_by_matching_rule_id():
    item1 = MediaItem(id="1", title="A", studio="Warner")
    item2 = MediaItem(id="2", title="B", studio="Universal")
    rules = [{"id": 0, "studio": "warner"}, {"id": 1, "studio": "universal"}]

    result = playlist_engine.group_custom_mode([item1, item2], rules)

    assert result["0"] == [item1]
    assert result["1"] == [item2]
```

- [ ] **Step 22: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: FAIL with `AttributeError: module 'backend.playlist_engine' has no attribute 'group_custom_mode'`

- [ ] **Step 23: Add group_custom_mode to pass**

Append to `webapp/backend/playlist_engine.py`:
```python
def group_custom_mode(items: list[MediaItem], rules: list[dict]) -> dict[str, list[MediaItem]]:
    groups: dict[str, list[MediaItem]] = defaultdict(list)
    for item in items:
        for rule in rules:
            if item_matches_rule(item, rule):
                groups[str(rule["id"])].append(item)
    return dict(groups)
```

- [ ] **Step 24: Run full test suite to verify all pass**

Run: `cd webapp && python3 -m pytest tests/test_playlist_engine.py -v`
Expected: PASS (all tests), no errors or warnings

- [ ] **Step 25: Commit**

```bash
git add webapp/backend/playlist_engine.py webapp/tests/test_playlist_engine.py
git commit -m "feat(webapp): add quick-mode grouping and rule-based custom mode"
```

---

### Task 5: Build orchestrator + FastAPI routes

**Files:**
- Create: `webapp/backend/build_orchestrator.py`
- Create: `webapp/backend/main.py`
- Test: `webapp/tests/test_build_orchestrator.py`
- Test: `webapp/tests/test_main.py`

**Interfaces:**
- Consumes: everything from `settings.py` (Task 1), `plex_client.py` (Task 2), `playlist_engine.py` (Tasks 3–4).
- Produces: `run_build(plex, library, prefix, mode, params, include_adult, on_event) -> None` (orchestrator); FastAPI app `app` with routes `GET/POST /api/setup`, `GET /api/libraries`, `GET /api/build` (SSE), `POST /api/destroy`.

- [ ] **Step 1: Write the failing test for run_build in quick mode**

`webapp/tests/test_build_orchestrator.py`:
```python
from dataclasses import dataclass, field

from backend import build_orchestrator


class FakeSection:
    def __init__(self, name, raw_items):
        self.name = name
        self._raw_items = raw_items

    def all(self):
        return self._raw_items


class FakeLibrary:
    def __init__(self, sections):
        self._sections = {s.name: s for s in sections}

    def section(self, name):
        return self._sections[name]


class FakePlaylist:
    def __init__(self, title):
        self.title = title
        self.deleted = False

    def delete(self):
        self.deleted = True


class FakePlex:
    def __init__(self, sections):
        self.library = FakeLibrary(sections)
        self._playlists = []
        self.created = []

    def playlists(self):
        return self._playlists

    def createPlaylist(self, name, section, items):
        self.created.append((name, [i for i in items]))


@dataclass
class FakeRawItem:
    ratingKey: int
    title: str
    studio: str = None
    genres: list = field(default_factory=list)
    directors: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    duration: int = None
    addedAt: object = None
    media: list = field(default_factory=list)


def test_run_build_quick_mode_creates_playlists_and_emits_events():
    raw_item = FakeRawItem(ratingKey=1, title="Movie", studio="Warner", media=[])
    section = FakeSection("Movies", [raw_item])
    fake_plex = FakePlex([section])
    events = []

    build_orchestrator.run_build(
        plex=fake_plex,
        library="Movies",
        prefix="t ",
        mode="quick",
        params={"selected": {"studio"}, "actor_filter": ""},
        include_adult=True,
        on_event=events.append,
    )

    assert {"type": "start", "total": 1} in events
    assert any(e["type"] == "playlist" and e["name"] == "Studio: Warner" for e in events)
    assert any(e["type"] == "done" for e in events)
    assert fake_plex.created == [("t Studio: Warner", [raw_item])]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_build_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.build_orchestrator'`

- [ ] **Step 3: Write build_orchestrator.py**

`webapp/backend/build_orchestrator.py`:
```python
from typing import Callable

from backend.plex_client import _to_media_item, upsert_playlist
from backend.playlist_engine import filter_adult_content, group_custom_mode, group_quick_mode, auto_name

MIN_ITEMS = 2


def run_build(
    plex,
    library: str,
    prefix: str,
    mode: str,
    params: dict,
    include_adult: bool,
    on_event: Callable[[dict], None],
) -> None:
    try:
        section = plex.library.section(library)
        raw_items = section.all()
        total = len(raw_items)
        on_event({"type": "start", "total": total})

        media_items = [_to_media_item(ri) for ri in raw_items]
        raw_by_id = {str(ri.ratingKey): ri for ri in raw_items}

        filtered = filter_adult_content(media_items, include_adult)

        if mode == "quick":
            groups = group_quick_mode(
                filtered,
                selected=params.get("selected", set()),
                actor_filter=params.get("actor_filter", ""),
            )
        else:
            groups = group_custom_mode(filtered, params.get("rules", []))

        on_event({"type": "log", "msg": f"Building playlists from {len(groups)} groups…"})

        created = 0
        misc: list = []
        seen_ids: set = set()

        if mode == "quick":
            pairs = sorted(groups.items())
        else:
            rules = params.get("rules", [])
            pairs = [(str(r["id"]), groups.get(str(r["id"]), [])) for r in rules]

        for key, group_items in pairs:
            if mode == "custom":
                rule = next((r for r in params.get("rules", []) if str(r["id"]) == key), None)
                name = (rule.get("custom_name") or "").strip() or auto_name(rule or {})
            else:
                name = key

            raw_group_items = [raw_by_id[mi.id] for mi in group_items]

            if len(group_items) >= MIN_ITEMS:
                upsert_playlist(plex, f"{prefix}{name}", raw_group_items, library)
                created += 1
                on_event({"type": "playlist", "name": name, "count": len(group_items)})
            else:
                for mi, raw in zip(group_items, raw_group_items):
                    if mi.id not in seen_ids:
                        misc.append(raw)
                        seen_ids.add(mi.id)

        if misc:
            upsert_playlist(plex, f"{prefix}Misc", misc, library)
            created += 1
            on_event({"type": "playlist", "name": "Misc", "count": len(misc)})

        on_event({"type": "done", "created": created, "total": total})

    except Exception as e:
        on_event({"type": "error", "msg": str(e)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_build_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for the adult-content filter being applied in run_build**

Add to `webapp/tests/test_build_orchestrator.py`:
```python
def test_run_build_excludes_adult_items_when_include_adult_is_false():
    adult_item = FakeRawItem(
        ratingKey=1, title="Scene", studio="AdultStudio",
        media=[type("M", (), {"parts": [type("P", (), {"file": "/other/Porn/AdultStudio/x.mp4"})()]})()],
    )
    regular_item = FakeRawItem(ratingKey=2, title="Movie", studio="Warner", media=[])
    section = FakeSection("Movies", [adult_item, regular_item])
    fake_plex = FakePlex([section])
    events = []

    build_orchestrator.run_build(
        plex=fake_plex,
        library="Movies",
        prefix="t ",
        mode="quick",
        params={"selected": {"studio"}, "actor_filter": ""},
        include_adult=False,
        on_event=events.append,
    )

    playlist_events = [e for e in events if e["type"] == "playlist"]
    assert all("AdultStudio" not in e["name"] for e in playlist_events)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_build_orchestrator.py -v`
Expected: PASS (the `filter_adult_content` call already wired in Step 3 should make this pass without further changes — if it fails, the filter call is misplaced and must be fixed before continuing)

- [ ] **Step 7: Commit build_orchestrator**

```bash
git add webapp/backend/build_orchestrator.py webapp/tests/test_build_orchestrator.py
git commit -m "feat(webapp): add build orchestrator wiring settings, engine, and Plex client"
```

- [ ] **Step 8: Write the failing test for GET /api/setup when unconfigured**

`webapp/tests/test_main.py`:
```python
import pytest
from fastapi.testclient import TestClient

from backend import main as main_module
from backend import settings as settings_module


@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "structly_settings.json")
    monkeypatch.setattr(main_module, "_plex", None)


@pytest.fixture
def client():
    return TestClient(main_module.app)


def test_get_setup_returns_not_configured_when_no_settings_saved(client):
    response = client.get("/api/setup")

    assert response.status_code == 200
    assert response.json()["configured"] is False
```

- [ ] **Step 9: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.main'`

- [ ] **Step 10: Write main.py with GET /api/setup**

`webapp/backend/main.py`:
```python
from fastapi import FastAPI

from backend import settings as settings_module

app = FastAPI()

_plex = None


@app.get("/api/setup")
def get_setup():
    return {
        "configured": settings_module.is_configured(),
        "settings": settings_module.load_settings(),
    }
```

- [ ] **Step 11: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 12: Write the failing test for POST /api/setup connecting and saving**

Add to `webapp/tests/test_main.py`:
```python
class FakePlexServer:
    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.friendlyName = "My Plex Server"

    class library:
        @staticmethod
        def sections():
            return []


def test_post_setup_connects_and_persists_settings(client, monkeypatch):
    monkeypatch.setattr(main_module, "connect_to_plex", lambda url, token: FakePlexServer(url, token))

    response = client.post("/api/setup", json={
        "plex_url": "http://192.168.1.5:32400",
        "plex_token": "tok123",
        "include_adult_content": True,
    })

    assert response.status_code == 200
    assert response.json() == {"connected": True, "name": "My Plex Server"}
    assert settings_module.load_settings()["plex_url"] == "http://192.168.1.5:32400"


def test_post_setup_returns_400_when_connection_fails(client, monkeypatch):
    def raise_error(url, token):
        raise Exception("bad token")

    monkeypatch.setattr(main_module, "connect_to_plex", raise_error)

    response = client.post("/api/setup", json={
        "plex_url": "http://x:32400", "plex_token": "bad", "include_adult_content": False,
    })

    assert response.status_code == 400
```

- [ ] **Step 13: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: FAIL with `405 Method Not Allowed` (no POST handler yet)

- [ ] **Step 14: Add POST /api/setup to pass**

Append to `webapp/backend/main.py`:
```python
from fastapi import HTTPException
from pydantic import BaseModel

from backend.plex_client import connect_to_plex, list_libraries, destroy_playlists


class SettingsIn(BaseModel):
    plex_url: str
    plex_token: str
    include_adult_content: bool = False


@app.post("/api/setup")
def post_setup(body: SettingsIn):
    global _plex
    try:
        _plex = connect_to_plex(body.plex_url, body.plex_token)
        _plex.library.sections()
    except Exception as e:
        raise HTTPException(400, f"Could not connect to Plex: {e}")
    settings_module.save_settings({
        "plex_url": body.plex_url,
        "plex_token": body.plex_token,
        "include_adult_content": body.include_adult_content,
    })
    return {"connected": True, "name": _plex.friendlyName}
```

- [ ] **Step 15: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: PASS (all tests)

- [ ] **Step 16: Write the failing test for GET /api/libraries**

Add to `webapp/tests/test_main.py`:
```python
def test_get_libraries_returns_503_when_not_connected(client):
    response = client.get("/api/libraries")

    assert response.status_code == 503


def test_get_libraries_returns_list_when_connected(client, monkeypatch):
    class Section:
        def __init__(self, title, type_):
            self.title = title
            self.type = type_

    class ConnectedPlex:
        class library:
            @staticmethod
            def sections():
                return [Section("Movies", "movie")]

    monkeypatch.setattr(main_module, "_plex", ConnectedPlex())

    response = client.get("/api/libraries")

    assert response.status_code == 200
    assert response.json() == {"libraries": ["Movies"]}
```

- [ ] **Step 17: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: FAIL with `404 Not Found` (route doesn't exist yet)

- [ ] **Step 18: Add GET /api/libraries to pass**

Append to `webapp/backend/main.py`:
```python
@app.get("/api/libraries")
def get_libraries():
    if _plex is None:
        raise HTTPException(503, "Not connected to Plex")
    return {"libraries": list_libraries(_plex)}
```

- [ ] **Step 19: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: PASS (all tests)

- [ ] **Step 20: Write the failing test for POST /api/destroy**

Add to `webapp/tests/test_main.py`:
```python
def test_post_destroy_returns_503_when_not_connected(client):
    response = client.post("/api/destroy", json={"prefix": "t "})

    assert response.status_code == 503


def test_post_destroy_returns_count_when_connected(client, monkeypatch):
    class ConnectedPlex:
        def playlists(self):
            return []

    monkeypatch.setattr(main_module, "_plex", ConnectedPlex())
    monkeypatch.setattr(main_module, "destroy_playlists", lambda plex, prefix: 3)

    response = client.post("/api/destroy", json={"prefix": "t "})

    assert response.status_code == 200
    assert response.json() == {"destroyed": 3}
```

- [ ] **Step 21: Run test to verify it fails**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: FAIL with `404 Not Found`

- [ ] **Step 22: Add POST /api/destroy to pass**

Append to `webapp/backend/main.py`:
```python
class DestroyIn(BaseModel):
    prefix: str


@app.post("/api/destroy")
def post_destroy(body: DestroyIn):
    if _plex is None:
        raise HTTPException(503, "Not connected to Plex")
    count = destroy_playlists(_plex, body.prefix)
    return {"destroyed": count}
```

- [ ] **Step 23: Run test to verify it passes**

Run: `cd webapp && python3 -m pytest tests/test_main.py -v`
Expected: PASS (all tests)

- [ ] **Step 24: Add GET /api/build SSE endpoint (manual verification, no new pytest — streaming endpoints are covered by the orchestrator's own tests from Step 1–6)**

Append to `webapp/backend/main.py`:
```python
import json
import queue
import threading

from fastapi.responses import StreamingResponse

from backend.build_orchestrator import run_build


@app.get("/api/build")
async def get_build(
    library: str,
    prefix: str = "t ",
    mode: str = "quick",
    types: str = "",
    actor_filter: str = "",
    rules: str = "[]",
):
    if _plex is None:
        raise HTTPException(503, "Not connected to Plex")

    current_settings = settings_module.load_settings()
    selected = set(types.split(",")) if types else set()
    params = {
        "selected": selected,
        "actor_filter": actor_filter.lower(),
        "rules": json.loads(rules),
    }

    q: queue.Queue = queue.Queue()

    def on_event(event: dict) -> None:
        q.put(event)

    def worker() -> None:
        run_build(
            _plex, library, prefix, mode, params,
            current_settings["include_adult_content"], on_event,
        )
        q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        import asyncio
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

- [ ] **Step 25: Manually verify the SSE endpoint starts without error**

Run: `cd webapp && python3 -c "from backend.main import app; print('OK:', [r.path for r in app.routes])"`
Expected: prints `OK:` followed by a list including `/api/setup`, `/api/libraries`, `/api/build`, `/api/destroy`

- [ ] **Step 26: Run full backend test suite to verify everything passes together**

Run: `cd webapp && python3 -m pytest tests/ -v`
Expected: PASS (all tests across all files), no errors or warnings

- [ ] **Step 27: Commit**

```bash
git add webapp/backend/main.py webapp/tests/test_main.py
git commit -m "feat(webapp): add FastAPI routes for setup, libraries, build (SSE), and destroy"
```

---

### Task 6: Frontend scaffold + Setup screen

**Files:**
- Create: `webapp/frontend/` (via Vite scaffold)
- Create: `webapp/frontend/src/api.ts`
- Create: `webapp/frontend/src/SetupForm.tsx`
- Create: `webapp/frontend/src/SetupForm.test.tsx`

**Interfaces:**
- Consumes: `GET /api/setup`, `POST /api/setup` (Task 5).
- Produces: `<SetupForm onConnected={(name: string) => void} />` React component.

- [ ] **Step 1: Scaffold the Vite React+TS app**

```bash
cd webapp && npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Configure Vitest**

Replace `webapp/frontend/vite.config.ts` contents:
```typescript
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
```

Add to `webapp/frontend/package.json` scripts:
```json
"test": "vitest run"
```

- [ ] **Step 3: Write the api.ts fetch helper**

`webapp/frontend/src/api.ts`:
```typescript
export async function apiFetch<T>(url: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(url, opts)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export interface SetupStatus {
  configured: boolean
  settings: {
    plex_url: string
    plex_token: string
    include_adult_content: boolean
  }
}

export function getSetup(): Promise<SetupStatus> {
  return apiFetch<SetupStatus>('/api/setup')
}

export function postSetup(data: {
  plex_url: string
  plex_token: string
  include_adult_content: boolean
}): Promise<{ connected: boolean; name: string }> {
  return apiFetch('/api/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}
```

- [ ] **Step 4: Write the failing test for SetupForm submit behavior**

`webapp/frontend/src/SetupForm.test.tsx`:
```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect } from 'vitest'
import { SetupForm } from './SetupForm'
import * as api from './api'

describe('SetupForm', () => {
  it('calls onConnected with the server name after a successful submit', async () => {
    vi.spyOn(api, 'postSetup').mockResolvedValue({ connected: true, name: 'My Plex Server' })
    const onConnected = vi.fn()

    render(<SetupForm onConnected={onConnected} />)

    fireEvent.change(screen.getByLabelText(/plex url/i), { target: { value: 'http://x:32400' } })
    fireEvent.change(screen.getByLabelText(/plex token/i), { target: { value: 'tok123' } })
    fireEvent.click(screen.getByRole('button', { name: /connect/i }))

    await waitFor(() => expect(onConnected).toHaveBeenCalledWith('My Plex Server'))
  })

  it('shows an error message when the connection fails', async () => {
    vi.spyOn(api, 'postSetup').mockRejectedValue(new Error('Could not connect to Plex: bad token'))

    render(<SetupForm onConnected={vi.fn()} />)

    fireEvent.change(screen.getByLabelText(/plex url/i), { target: { value: 'http://x:32400' } })
    fireEvent.change(screen.getByLabelText(/plex token/i), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: /connect/i }))

    await waitFor(() => expect(screen.getByText(/could not connect to plex/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd webapp/frontend && npm test`
Expected: FAIL — `Cannot find module './SetupForm'`

- [ ] **Step 6: Write SetupForm.tsx to pass**

`webapp/frontend/src/SetupForm.tsx`:
```tsx
import { useState } from 'react'
import { postSetup } from './api'

interface Props {
  onConnected: (name: string) => void
}

export function SetupForm({ onConnected }: Props) {
  const [plexUrl, setPlexUrl] = useState('')
  const [plexToken, setPlexToken] = useState('')
  const [includeAdult, setIncludeAdult] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setConnecting(true)
    try {
      const result = await postSetup({
        plex_url: plexUrl,
        plex_token: plexToken,
        include_adult_content: includeAdult,
      })
      onConnected(result.name)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed')
    } finally {
      setConnecting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <label htmlFor="plex-url">Plex URL</label>
      <input
        id="plex-url"
        value={plexUrl}
        onChange={(e) => setPlexUrl(e.target.value)}
      />

      <label htmlFor="plex-token">Plex Token</label>
      <input
        id="plex-token"
        type="password"
        value={plexToken}
        onChange={(e) => setPlexToken(e.target.value)}
      />

      <label htmlFor="include-adult">
        <input
          id="include-adult"
          type="checkbox"
          checked={includeAdult}
          onChange={(e) => setIncludeAdult(e.target.checked)}
        />
        Include adult content
      </label>

      <button type="submit" disabled={connecting}>
        {connecting ? 'Connecting…' : 'Connect'}
      </button>

      {error && <p role="alert">{error}</p>}
    </form>
  )
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd webapp/frontend && npm test`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend
git commit -m "feat(webapp): scaffold Vite React frontend with Setup screen"
```

---

### Task 7: Frontend Builder screen

**Files:**
- Create: `webapp/frontend/src/Builder.tsx`
- Create: `webapp/frontend/src/Builder.test.tsx`
- Modify: `webapp/frontend/src/api.ts`
- Modify: `webapp/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/libraries`, `GET /api/build` (SSE) (Task 5); `SetupForm` (Task 6).
- Produces: `<Builder />` React component; `<App />` wiring `SetupForm` → `Builder`.

- [ ] **Step 1: Add getLibraries and buildEventSourceUrl to api.ts**

Append to `webapp/frontend/src/api.ts`:
```typescript
export function getLibraries(): Promise<{ libraries: string[] }> {
  return apiFetch('/api/libraries')
}

export function buildEventSourceUrl(params: {
  library: string
  prefix: string
  mode: 'quick' | 'custom'
  types?: string
  actorFilter?: string
  rules?: string
}): string {
  const q = new URLSearchParams({
    library: params.library,
    prefix: params.prefix,
    mode: params.mode,
    types: params.types ?? '',
    actor_filter: params.actorFilter ?? '',
    rules: params.rules ?? '[]',
  })
  return `/api/build?${q}`
}
```

- [ ] **Step 2: Write the failing test for Builder loading libraries on mount**

`webapp/frontend/src/Builder.test.tsx`:
```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { vi, describe, it, expect } from 'vitest'
import { Builder } from './Builder'
import * as api from './api'

describe('Builder', () => {
  it('loads and displays libraries on mount', async () => {
    vi.spyOn(api, 'getLibraries').mockResolvedValue({ libraries: ['Movies', 'TV Shows'] })

    render(<Builder />)

    await waitFor(() => expect(screen.getByRole('option', { name: 'Movies' })).toBeInTheDocument())
    expect(screen.getByRole('option', { name: 'TV Shows' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd webapp/frontend && npm test`
Expected: FAIL — `Cannot find module './Builder'`

- [ ] **Step 4: Write Builder.tsx to pass**

`webapp/frontend/src/Builder.tsx`:
```tsx
import { useEffect, useRef, useState } from 'react'
import { getLibraries, buildEventSourceUrl } from './api'

type Mode = 'quick' | 'custom'

export function Builder() {
  const [libraries, setLibraries] = useState<string[]>([])
  const [library, setLibrary] = useState('')
  const [prefix, setPrefix] = useState('t ')
  const [mode] = useState<Mode>('quick')
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set(['studio']))
  const [log, setLog] = useState<string[]>([])
  const [building, setBuilding] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    getLibraries().then((res) => {
      setLibraries(res.libraries)
      if (res.libraries.length > 0) setLibrary(res.libraries[0])
    })
  }, [])

  function toggleType(type: string) {
    setSelectedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  function appendLog(msg: string) {
    setLog((prev) => [...prev, msg])
  }

  function startBuild() {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }
    setLog([])
    setBuilding(true)

    const url = buildEventSourceUrl({
      library,
      prefix,
      mode,
      types: Array.from(selectedTypes).join(','),
    })
    const es = new EventSource(url)
    eventSourceRef.current = es

    es.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'start') appendLog(`Scanning ${msg.total} items…`)
      if (msg.type === 'log') appendLog(msg.msg)
      if (msg.type === 'playlist') appendLog(`✓ ${msg.name} (${msg.count} items)`)
      if (msg.type === 'done') {
        appendLog(`Done — ${msg.created} playlists created.`)
        setBuilding(false)
        es.close()
      }
      if (msg.type === 'error') {
        appendLog(`Error: ${msg.msg}`)
        setBuilding(false)
        es.close()
      }
    }
  }

  return (
    <div>
      <select
        aria-label="Library"
        value={library}
        onChange={(e) => setLibrary(e.target.value)}
      >
        {libraries.map((lib) => (
          <option key={lib} value={lib}>{lib}</option>
        ))}
      </select>

      <label htmlFor="prefix">Prefix</label>
      <input id="prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} />

      <fieldset>
        <legend>Quick mode groupings</legend>
        {['studio', 'genre', 'director', 'actor', 'resolution', 'folder', 'duration', 'recent'].map((t) => (
          <label key={t}>
            <input
              type="checkbox"
              checked={selectedTypes.has(t)}
              onChange={() => toggleType(t)}
            />
            {t}
          </label>
        ))}
      </fieldset>

      <button onClick={startBuild} disabled={building || !library}>
        {building ? 'Building…' : 'Build Playlists'}
      </button>

      <div role="log">
        {log.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd webapp/frontend && npm test`
Expected: PASS

- [ ] **Step 6: Wire App.tsx to switch between SetupForm and Builder**

Replace `webapp/frontend/src/App.tsx` contents:
```tsx
import { useEffect, useState } from 'react'
import { SetupForm } from './SetupForm'
import { Builder } from './Builder'
import { getSetup } from './api'

function App() {
  const [connected, setConnected] = useState<boolean | null>(null)

  useEffect(() => {
    getSetup().then((status) => setConnected(status.configured))
  }, [])

  if (connected === null) return <p>Loading…</p>

  return connected ? <Builder /> : <SetupForm onConnected={() => setConnected(true)} />
}

export default App
```

- [ ] **Step 7: Manually verify the dev server runs**

```bash
cd webapp/frontend && npm run dev
```
Expected: Vite prints a local dev server URL (e.g. `http://localhost:5173`) with no build errors

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend
git commit -m "feat(webapp): add Builder screen with live SSE build log"
```

---

### Task 8: Packaging — local launch + PyInstaller bundle

**Files:**
- Create: `webapp/launch.py`
- Modify: `webapp/backend/main.py` (mount built frontend static assets)
- Create: `webapp/structly_web.spec`

**Interfaces:**
- Consumes: `app` from `backend/main.py` (Task 5); built assets from `webapp/frontend/dist` (Task 7, after `npm run build`).
- Produces: a runnable local launcher that starts the API server and opens the user's browser.

- [ ] **Step 1: Mount built frontend assets as static files**

Append to `webapp/backend/main.py` (must be the last route registration, after all `/api/*` routes):
```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
```

- [ ] **Step 2: Write launch.py**

`webapp/launch.py`:
```python
import socket
import threading
import webbrowser

import uvicorn

from backend.main import app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Build the frontend for production**

```bash
cd webapp/frontend && npm run build
```

Expected: creates `webapp/frontend/dist/` with `index.html` and bundled assets

- [ ] **Step 4: Manually verify launch.py serves both API and frontend**

```bash
cd webapp && python3 launch.py
```

Expected: terminal shows uvicorn startup log, default browser opens to the app, Setup screen (or Builder, if already configured) renders with no console errors

- [ ] **Step 5: Write the PyInstaller spec**

`webapp/structly_web.spec`:
```python
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['launch.py'],
    pathex=['.'],
    datas=[('frontend/dist', 'frontend/dist')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name='StructlyWeb',
    console=False,
)
```

- [ ] **Step 6: Manually verify the PyInstaller build produces a runnable binary**

```bash
cd webapp && pip3 install pyinstaller && pyinstaller structly_web.spec
./dist/StructlyWeb/StructlyWeb
```

Expected: binary launches, browser opens, app is usable end-to-end (connect to Plex, list libraries, build a playlist)

- [ ] **Step 7: Commit**

```bash
git add webapp/launch.py webapp/structly_web.spec webapp/backend/main.py webapp/frontend/.gitignore
git commit -m "feat(webapp): add local launcher and PyInstaller packaging"
```

---

## Self-Review Notes

- **Spec coverage:** Overview/scope → Tasks 1–8 collectively. Architecture (FastAPI + React, SSE, local-only) → Tasks 5–8. Adult-content toggle → Task 3 (`filter_adult_content`) + Task 5 (`run_build` applies it) + Task 6 (setup form checkbox). Credentials handling/security fix → Task 1 (`settings.py`, no hardcoded fallback in packaged build) + Task 5 (`/api/setup` requires real connection). Testing approach → pytest-first throughout Tasks 1–5, lighter Vitest coverage in Tasks 6–7 matching the spec's explicit "frontend gets lighter coverage" call. Success criteria (installs/conversions) are business metrics tracked outside this codebase, not implementation tasks. Packaging → Task 8.
- **Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code or an exact command with expected output.
- **Type consistency:** `MediaItem` defined once in `plex_client.py` (Task 2) and imported consistently in `playlist_engine.py` (Tasks 3–4) and `build_orchestrator.py` (Task 5). `run_build`'s `on_event` callback signature (`Callable[[dict], None]`) matches its usage in `main.py`'s SSE endpoint (Task 5, Step 24) and in the Task 5 orchestrator tests.
