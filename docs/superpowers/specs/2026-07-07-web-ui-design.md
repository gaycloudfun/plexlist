# Design: Structly Web UI — Local Browser Rewrite

Date: 2026-07-07
Repo: jason_pka / plex_playlist_builder
Status: APPROVED (pending user review of this written spec)

## Purpose

Test whether a browser-based UI reduces adoption friction for lay Plex users
compared to the current native `.dmg` desktop app (customtkinter), as part of
the broader lay-user test approved earlier today
(`.gstack/projects/jason_pka/jasonmcguire-unknown-design-20260707-182854.md`).

This is a UI-layer rewrite, not new product scope. Everything still runs
locally on the user's machine against their own Plex server — no hosted
multi-tenant service, no Plex OAuth, no new infrastructure cost.

Scope:
- Full feature parity with `app_v4.py`: Quick/Auto mode (group by studio,
  genre, director, resolution) and Rule builder mode (custom rules by studio,
  genre, director, actor).
- One new feature: an opt-in adult-content include/exclude toggle.
- A proper first-run credentials setup flow, replacing the hardcoded-token
  fallback currently in `config.py`.

## Architecture

- **Backend:** FastAPI (Python), running locally on `localhost:<port>`.
  Reuses `discover.py` and `build_playlists.py` logic largely unchanged —
  same `plexapi` calls, same folder-path parsing (`parse_path_groups`) for
  studio/adult-content detection. Business logic moves into FastAPI route
  handlers instead of tkinter button callbacks.
- **Frontend:** React + Vite (TypeScript). Talks to the FastAPI backend over
  local HTTP (REST endpoints: list libraries, list rule presets, build
  playlists, stream progress/log). No auth/session needed — single local
  user, single local process.
- **Progress/log streaming:** replicate the desktop app's live log/status
  panel (`PRODUCT.md`'s "status is everything" principle) via Server-Sent
  Events (SSE) from FastAPI — simpler than WebSockets for one-directional
  progress updates.
- **Settings/credentials:** new `/setup` flow. On first run, if
  `~/.structly_settings.json` doesn't exist, the UI prompts for Plex URL +
  token before anything else loads. In dev only, an untracked `.env` file
  (gitignored, stripped from the packaged build) may pre-fill the founder's
  own token for convenience — this must never be bundled into the shipped
  app.
- **Packaging:** same PyInstaller → `.dmg` pipeline as today. The bundled
  binary starts the FastAPI server on a local port and opens the user's
  default browser to it, replacing the CTk window launch.

## Adult-Content Toggle

A single setting, persisted in `~/.structly_settings.json`:
`include_adult_content: bool`, default `false`.

- When `false`: the backend excludes any item whose path falls under
  `PORN_ROOT` (`/other/Porn`) from both Quick/Auto grouping and Rule-builder
  results. Filtering happens server-side — excluded items are never sent to
  the frontend, not just hidden in the UI.
- When `true`: current automatic studio-parsing behavior applies as-is
  (folder name → studio, e.g. `/other/Porn/MuscleBearPorn/scene.mp4` →
  studio=MuscleBearPorn).

## Credentials Handling (Security Fix)

**Existing problem:** `config.py` hardcodes the founder's personal Plex
server URL and auth token in plaintext. `app_v4.py`'s `load_settings()` uses
that token as the default fallback for any user without a
`~/.structly_settings.json` file. If shipped as-is to strangers, the
founder's own Plex credentials go out embedded in the binary.

**Fix:**
- The packaged build ships with no hardcoded token or URL at all.
- First run always checks for `~/.structly_settings.json`; if absent, the UI
  blocks on the setup screen until the user enters their own Plex URL +
  token.
- For local development only, a `.env` file (excluded from version control
  and from the PyInstaller build) may supply the founder's own token as a
  fallback so `npm run dev` / local testing doesn't require re-entering
  credentials every time.

## Testing Approach

Per the active test-driven-development skill: write the failing test first,
watch it fail, then write minimal code to pass.

- **Backend** (`parse_path_groups`, playlist-building, the new adult-content
  filter, the setup/settings flow): full pytest coverage, test-first. This is
  pure Python, easy to isolate from live Plex/network calls (mock
  `PlexServer`/`plexapi` responses).
- **Frontend:** lighter coverage — the React UI is thin and mostly
  presentational. TDD rigor concentrates on the backend engine, where
  correctness actually matters.

## Success Criteria

Same two top-line numbers as the approved broader plan — this rewrite adds
no new metrics, it tests whether the web-UI variant moves those same numbers
relative to the existing `.dmg`:

- Unique non-founder installs from the broad test.
- At least one paid conversion from someone outside the founder's direct
  network.

## Open Questions

- Final distribution mechanism for testers wasn't fully decided during
  brainstorming (kept as same `.dmg`-launches-local-server approach per the
  architecture above — revisit if packaging FastAPI + a Vite-built React
  frontend into PyInstaller proves heavier than expected).
- Whether the local port should be fixed or dynamically chosen (avoid
  conflicts with other local services) — default to picking a free port at
  startup unless there's a reason to fix one.

## Dependencies

- New Python deps: `fastapi`, `uvicorn` (or similar ASGI server).
- New frontend toolchain: Node/npm, React, Vite, TypeScript — needs to be
  built and bundled into the PyInstaller `.dmg` (build step: `npm run build`
  → static assets served by FastAPI).
- Existing deps unchanged: `plexapi`, `Pillow` (if any image handling
  carries over to the web UI, e.g. logo/branding assets).
