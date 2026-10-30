"""
Structly — Plex Playlist Builder  (web backend)
"""

import asyncio
import json
import queue
import re
import subprocess
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from plexapi.exceptions import BadRequest, NotFound
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from settings_store import load_settings, save_settings

app = FastAPI(title="Structly", version="5.0")


@app.middleware("http")
async def no_cache(request, call_next):
    # Make Chrome re-check files on every load, so a normal refresh shows the latest UI.
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response

# ── State ─────────────────────────────────────────────────────────────────────

_plex: Optional[PlexServer] = None

PORN_ROOT         = "/other/Porn"
CATEGORIES_FOLDER = "CATEGORIES"
MIN_ITEMS         = 2
RECENT_DAYS       = 30
ARCHIVE_DIR       = Path.home() / "Documents" / "Structly Archives"

RESOLUTION_MAP = {
    "4k": "4K", "2160": "4K",
    "1080": "1080p",
    "720":  "720p",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

_PLEX_TOKEN_RE = re.compile(r"X-Plex-Token=[^&\s]*")


def redact_token(message) -> str:
    """Strip any X-Plex-Token=... value out of text bound for the browser.

    plexapi exception messages routinely embed the request URL, token and all.
    """
    return _PLEX_TOKEN_RE.sub("X-Plex-Token=[REDACTED]", str(message))


def parse_path_groups(file_path: str) -> dict:
    groups = {}
    try:
        rel   = Path(file_path).relative_to(PORN_ROOT)
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


def resolution_label(item) -> str | None:
    try:
        res = str(item.media[0].videoResolution).lower()
        return RESOLUTION_MAP.get(res, "SD")
    except (IndexError, AttributeError):
        return None


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


def item_matches_rule(item, rule: dict) -> bool:
    if rule.get("studio"):
        if rule["studio"].lower() not in (getattr(item, "studio", "") or "").lower():
            return False
    if rule.get("genre"):
        genres = [g.tag.lower() for g in getattr(item, "genres", [])]
        if not any(rule["genre"].lower() in g for g in genres):
            return False
    if rule.get("director"):
        dirs = [d.tag.lower() for d in getattr(item, "directors", [])]
        if not any(rule["director"].lower() in d for d in dirs):
            return False
    if rule.get("actor"):
        actors = [r.tag.lower() for r in getattr(item, "roles", [])]
        if not any(rule["actor"].lower() in a for a in actors):
            return False
    dur = rule.get("duration", "Any")
    if dur != "Any":
        ms = getattr(item, "duration", None) or 0
        if dur == "< 2 min"  and not ms < 2 * 60_000:           return False
        if dur == "2–5 min"  and not 2 * 60_000 <= ms < 5 * 60_000:  return False
        if dur == "5–10 min" and not 5 * 60_000 <= ms < 10 * 60_000: return False
        if dur == "> 1 hour" and not ms > 60 * 60_000:          return False
    return True


def auto_name(rule: dict) -> str:
    parts = [rule[k].title() for k in ("studio", "genre", "director", "actor") if rule.get(k)]
    return " · ".join(parts) or "Custom"


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


def get_plex() -> PlexServer:
    if _plex is None:
        raise HTTPException(503, "Not connected to Plex")
    return _plex

# ── API ───────────────────────────────────────────────────────────────────────

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
        return {"connected": False, "error": redact_token(e)}


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
        raise HTTPException(400, redact_token(e))


class SettingsRequest(BaseModel):
    include_adult_content: bool


@app.get("/api/settings")
def get_settings():
    return {"include_adult_content": load_settings().get("include_adult_content", False)}


@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    data = save_settings(include_adult_content=req.include_adult_content)
    return {"include_adult_content": data["include_adult_content"]}


class PrefixRequest(BaseModel):
    prefix: str


class RestoreRequest(BaseModel):
    prefix: str
    library: str


@app.post("/api/destroy")
def destroy(req: PrefixRequest):
    # An empty prefix matches every playlist on the server, not just ours.
    if not req.prefix.strip():
        raise HTTPException(400, "Prefix is empty — refusing to delete every playlist")
    plex = get_plex()
    archived = archive_playlists(plex, req.prefix, last_archive_dir())
    # A playlist that didn't save would be lost for good if we deleted it now.
    if archived["errors"]:
        failed = ", ".join(e["title"] for e in archived["errors"])
        raise HTTPException(500, f"Archive failed for {failed} — nothing was deleted")
    targets = [pl for pl in plex.playlists() if pl.title.startswith(req.prefix)]
    for pl in targets:
        pl.delete()
    return {"destroyed": len(targets), "archive": archived}


@app.get("/api/playlists")
def playlists(prefix: str):
    """Titles Destroy would delete, so the user sees them before confirming."""
    return {"titles": [pl.title for pl in get_plex().playlists() if pl.title.startswith(prefix)]}


# ── Archive / Restore ─────────────────────────────────────────────────────────

def archive_path(folder: Path, title: str) -> Path:
    return folder / (title.replace("/", "_") + ".json")


def last_archive_dir() -> Path:
    return Path(load_settings().get("archive_dir") or ARCHIVE_DIR)


def choose_folder(start: Path) -> Optional[Path]:
    """Native Mac folder picker, opened in front of the browser. None if cancelled."""
    start.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["osascript", "-e", "on run argv",
         "-e", "tell application (path to frontmost application as text) to POSIX path of "
               '(choose folder with prompt "Choose the Structly archive folder" '
               "default location (POSIX file (item 1 of argv)))",
         "-e", "end run", str(start)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:  # user hit Cancel
        return None
    folder = Path(res.stdout.strip())
    save_settings(archive_dir=str(folder))
    return folder


def move_to_trash(path: Path) -> None:
    # Path goes in argv, not the script text, so quotes in a title can't inject AppleScript.
    subprocess.run(
        ["osascript", "-e", "on run argv",
         "-e", 'tell application "Finder" to delete POSIX file (item 1 of argv)',
         "-e", "end run", str(path)],
        check=True, capture_output=True, timeout=15,
    )


@app.post("/api/archive")
def archive(req: PrefixRequest):
    plex   = get_plex()
    folder = choose_folder(last_archive_dir())
    if folder is None:
        return {"cancelled": True}
    return archive_playlists(plex, req.prefix, folder)


def archive_playlists(plex, prefix: str, folder: Path) -> dict:
    # A failed write raises, so destroy() never deletes a playlist that wasn't archived.
    folder.mkdir(parents=True, exist_ok=True)
    saved, duplicates, errors = [], [], []
    for pl in plex.playlists():
        if not pl.title.startswith(prefix):
            continue
        items = [{"ratingKey": i.ratingKey, "title": getattr(i, "title", "")} for i in pl.items()]
        body  = json.dumps({"title": pl.title, "items": items}, indent=2, ensure_ascii=False)
        path = archive_path(folder, pl.title)
        if not path.exists():
            path.write_text(body)
            saved.append(pl.title)
            continue
        # Same name already archived: the original stays, the new copy goes to the Trash.
        dup = path.with_name(f"{path.stem} (duplicate {datetime.now():%Y-%m-%d %H%M%S}).json")
        dup.write_text(body)
        try:
            move_to_trash(dup)
            duplicates.append(pl.title)
        except (subprocess.SubprocessError, OSError) as e:
            dup.unlink(missing_ok=True)
            errors.append({"title": pl.title, "reason": f"could not move duplicate to Trash: {e}"})
    return {"folder": str(folder), "saved": saved, "duplicates": duplicates, "errors": errors}


@app.post("/api/restore")
def restore(req: RestoreRequest):
    plex   = get_plex()
    folder = choose_folder(last_archive_dir())
    if folder is None:
        return {"cancelled": True}
    restored, errors = [], []
    for path in sorted(folder.glob("*.json")):
        try:
            data  = json.loads(path.read_text())
            title = data["title"]
            if not title.startswith(req.prefix):
                continue
            keys  = ",".join(str(i["ratingKey"]) for i in data["items"])
            items = plex.fetchItems(f"/library/metadata/{keys}") if keys else []
            if not items:
                errors.append({"title": title, "reason": "none of its videos are in Plex anymore"})
                continue
            upsert_playlist(plex, title, items, req.library)
            restored.append({"title": title, "count": len(items)})
        except (json.JSONDecodeError, KeyError, TypeError, OSError, NotFound, BadRequest) as e:
            errors.append({"title": path.stem, "reason": str(e)})
    return {"folder": str(folder), "restored": restored, "errors": errors}


# ── Build (SSE) ───────────────────────────────────────────────────────────────

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
    on_done=None,
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
                            groups[pg['studio']].append(item)
                            matched = True
                        if "category" in pg:
                            groups[f"Cat: {pg['category']}"].append(item)
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
        # Before the end-of-stream marker, so a build started right after this one isn't refused.
        if on_done:
            on_done()
        q.put(None)


# Two builds at once would both miss an existing playlist and create duplicates.
_build_lock = threading.Lock()


class BuildRequest(BaseModel):
    library: str
    prefix: str  = ""
    mode: str    = "quick"
    types: str   = ""
    actor_filter: str = ""
    rules: str   = "[]"
    dry_run: bool = False


# POST (not GET): starting a build mutates Plex, and a state-mutating GET is
# trivially triggerable cross-origin. The client reads the SSE body manually
# via fetch(), since EventSource cannot issue a POST.
@app.post("/api/build")
async def build(req: BuildRequest):
    plex       = get_plex()
    selected   = set(req.types.split(",")) if req.types else set()
    rules_list = json.loads(req.rules)
    include_adult = load_settings().get("include_adult_content", False)
    if not _build_lock.acquire(blocking=False):
        raise HTTPException(409, "A build is already running — wait for it to finish")

    q = queue.Queue()
    threading.Thread(
        target=_build_worker,
        args=(plex, req.library, req.prefix, req.mode, selected,
              req.actor_filter.lower(), rules_list, q),
        kwargs={"include_adult": include_adult, "dry_run": req.dry_run,
                "on_done": _build_lock.release},
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


# ── Static files (must be last) ───────────────────────────────────────────────

app.mount("/", StaticFiles(directory="static", html=True), name="static")
