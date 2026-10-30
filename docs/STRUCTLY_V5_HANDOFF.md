# Structly v5 — Handoff (2026-10-24)

**Where:** `plex_playlist_builder/web_v2/` · branch `launch-fixes` · **nothing committed yet**

## What Structly v5 is

A Python program (FastAPI) that runs on your Mac and shows its screen in Chrome.
It is **not online** — it only listens on `127.0.0.1`, so only this Mac can open it.
It talks to Plex directly and uses Mac features (folder picker, Trash).

The older desktop window app (`app_v4.py`, CustomTkinter) is separate and has **none** of the v5 features.

## How to run it

```bash
cd plex_playlist_builder/web_v2
python3 -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Then open http://127.0.0.1:8765

## What changed today

### Look & layout
- Header shows the Structly logo; tab title and subtitle say **v5**.
- LOG card collapses/expands (button with screen-reader support); card shrinks when collapsed.
- Buttons, top to bottom:
  1. **Build Playlists** (full width, orange)
  2. **Archive to Computer** | **Restore from Archive**
  3. **Destroy Playlists** (full width, solid red)
- **Preview (Dry Run)** button removed. The server still supports dry runs, so it can come back easily.

### Prefix
- The prefix box now starts **empty** — type any 1–3 characters.
- Folder playlists are named `STU: …` / `Cat: …` (the old `FLDR ` tag is gone).
  The old `web/` app still uses `FLDR`; it was not touched.

### Destroy Playlists
- Opens a pop-up (no browser `confirm()`, which browsers can silently block after the first use — the likely reason Destroy only worked once).
- Pop-up options: **Archive to Computer**, **Destroy Playlists**, **Cancel**.
- Before deleting, Destroy **automatically archives** every matching playlist to your last-used archive folder. If that save fails, **nothing is deleted**.
- An empty prefix is refused (it would delete every playlist in Plex).

### Archive to Computer
- Opens a Mac folder picker every time, starting at the last folder you used (remembered in `~/.structly_settings.json` as `archive_dir`). Default: `~/Documents/Structly Archives`.
- Saves **one file per playlist**, named after the playlist, e.g. `t Genre: Drama.json`:
  ```json
  {
    "title": "t Genre: Drama",
    "items": [
      {"ratingKey": 12345, "title": "Example Movie"},
      {"ratingKey": 12346, "title": "Another Movie"}
    ]
  }
  ```
  `title` = video titles (readable by you); `ratingKey` = Plex's ID, used for restoring.
- **Same file name already there → the original is kept and the new copy goes to the Trash.**
  Note: this means an archive file is never updated. Emptying the Trash loses the newer copy.
- First time, macOS asks to let the app control Finder — click **Allow**.

### Restore from Archive
- Opens the folder picker, then recreates every archived playlist that starts with the current prefix, into the library selected in the dropdown.
- Videos no longer in Plex are skipped; broken files are listed in the log without stopping the rest.

## Tests
- 43 backend tests pass (`cd web_v2 && python3 -m pytest -q`), including `tests/test_archive.py` (new).
- Both frontend harnesses pass (`node tests/frontend/sse_harness.js`, `node tests/frontend/settings_harness.js`).

## Before committing
- `git add web_v2/static/structly_logo.png` — the logo file is **not tracked yet**; without it the header image breaks.
- The repo has **no remote**, so there is nowhere to push until one is added.

## Not verified yet
- Against your real Plex server.
- The real Mac folder picker and Trash (tests use stand-ins).

## Tell existing users
> Folder playlists are now named "STU: …" / "Cat: …" instead of "FLDR STU: …" / "FLDR Cat: …".
> To avoid duplicates, run **Destroy Playlists** on your prefix once, then rebuild.

## Open decision
Ship the **browser version** as v5 (recommended; can later be wrapped to open like a normal Mac app),
or port these features into the desktop **`app_v4.py`**.
