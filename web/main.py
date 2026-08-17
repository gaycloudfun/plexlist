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

PORN_ROOT         = "/other/Porn"
CATEGORIES_FOLDER = "CATEGORIES"
MIN_ITEMS         = 2
RECENT_DAYS       = 30

RESOLUTION_MAP = {
    "4k": "4K", "2160": "4K",
    "1080": "1080p",
    "720":  "720p",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

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


def upsert_playlist(plex, full_name: str, items: list, library_name: str):
    for pl in plex.playlists():
        if pl.title == full_name:
            pl.delete()
            break
    plex.createPlaylist(full_name, section=plex.library.section(library_name), items=items)


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


class DestroyRequest(BaseModel):
    prefix: str


@app.post("/api/destroy")
def destroy(req: DestroyRequest):
    plex = get_plex()
    targets = [pl for pl in plex.playlists() if pl.title.startswith(req.prefix)]
    for pl in targets:
        pl.delete()
    return {"destroyed": len(targets)}


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
):
    try:
        section   = plex.library.section(library)
        all_items = section.all()
        total     = len(all_items)
        cutoff    = datetime.now() - timedelta(days=RECENT_DAYS)

        q.put({"type": "start", "total": total})

        groups: dict[str, list] = defaultdict(list)

        for i, item in enumerate(all_items, 1):
            if mode == "quick":
                if "studio" in selected:
                    studio = getattr(item, "studio", None)
                    if studio:
                        groups[f"Studio: {studio}"].append(item)
                if "genre" in selected:
                    for g in getattr(item, "genres", []):
                        groups[f"Genre: {g.tag}"].append(item)
                if "director" in selected:
                    for d in getattr(item, "directors", []):
                        groups[f"Director: {d.tag}"].append(item)
                if "actor" in selected:
                    for role in getattr(item, "roles", []):
                        if not actor_filter or actor_filter in role.tag.lower():
                            groups[f"Actor: {role.tag}"].append(item)
                if "resolution" in selected:
                    lbl = resolution_label(item)
                    if lbl:
                        groups[f"Resolution: {lbl}"].append(item)
                if "recent" in selected:
                    added = getattr(item, "addedAt", None)
                    if added and added >= cutoff:
                        groups[f"Recently Added (Last {RECENT_DAYS} Days)"].append(item)
                if "folder" in selected:
                    try:
                        pg = parse_path_groups(item.media[0].parts[0].file)
                        if "studio"   in pg: groups[f"FLDR STU: {pg['studio']}"].append(item)
                        if "category" in pg: groups[f"FLDR Cat: {pg['category']}"].append(item)
                    except (IndexError, AttributeError):
                        pass
                if "duration" in selected:
                    ms = getattr(item, "duration", None)
                    if ms:
                        if   ms < 2  * 60_000: groups["Duration: Under 2 Min"].append(item)
                        elif ms < 5  * 60_000: groups["Duration: 2–5 Min"].append(item)
                        elif ms < 10 * 60_000: groups["Duration: 5–10 Min"].append(item)
                        elif ms > 60 * 60_000: groups["Duration: Over 1 Hour"].append(item)
            else:
                for rule in rules_list:
                    if item_matches_rule(item, rule):
                        groups[str(rule["id"])].append(item)

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
                upsert_playlist(plex, f"{prefix}{name}", items, library)
                created += 1
                q.put({"type": "playlist", "name": name, "count": len(items)})
            else:
                for item in items:
                    if item.ratingKey not in seen_ids:
                        misc.append(item)
                        seen_ids.add(item.ratingKey)

        if misc:
            upsert_playlist(plex, f"{prefix}Misc", misc, library)
            created += 1
            q.put({"type": "playlist", "name": "Misc", "count": len(misc)})

        q.put({"type": "done", "created": created, "total": total})

    except Exception as e:
        q.put({"type": "error", "msg": str(e)})
    finally:
        q.put(None)


@app.get("/api/build")
async def build(
    library: str,
    prefix: str  = "t ",
    mode: str    = "quick",
    types: str   = "",
    actor_filter: str = "",
    rules: str   = "[]",
):
    plex       = get_plex()
    selected   = set(types.split(",")) if types else set()
    rules_list = json.loads(rules)

    q = queue.Queue()
    threading.Thread(
        target=_build_worker,
        args=(plex, library, prefix, mode, selected, actor_filter.lower(), rules_list, q),
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
