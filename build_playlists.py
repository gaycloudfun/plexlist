"""
build_playlists.py — Scan a Plex library, derive groupings from folder structure
                     and technical metadata (duration, resolution), then create
                     playlists in Plex automatically.

Folder structure assumed:
    /other/Porn/{Studio}/{optional sub-folders}/{file}
    /other/Porn/CATEGORIES/{Category}/{optional sub-folders}/{file}

Usage:
    python3 build_playlists.py "Other Videos"
"""

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from plexapi.server import PlexServer
from config import PLEX_URL, PLEX_TOKEN


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# The root folder that all porn files live under (trailing slash not needed)
PORN_ROOT = "/other/Porn"

# Folder name that signals category-based organization instead of studio
CATEGORIES_FOLDER = "CATEGORIES"

# Duration buckets (seconds)
DURATION_BUCKETS = {
    "Duration: Short (under 20 min)":  (0,        20 * 60),
    "Duration: Medium (20–60 min)":    (20 * 60,  60 * 60),
    "Duration: Long (over 60 min)":    (60 * 60,  float("inf")),
}

# Resolution buckets (height in pixels)
RESOLUTION_BUCKETS = {
    "Quality: SD (under 720p)":   (0,    720),
    "Quality: HD (720p–1079p)":   (720,  1080),
    "Quality: Full HD (1080p+)":  (1080, 2160),
    "Quality: 4K (2160p+)":       (2160, float("inf")),
}

# Prefix applied to every created playlist
PLAYLIST_PREFIX = "Auto: "

# Minimum items needed to bother creating a playlist
MIN_ITEMS = 2

# ---------------------------------------------------------------------------


def get_ffprobe_technical(file_path: str) -> dict:
    """Return duration (seconds) and video height from ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", file_path],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        info = {}
        try:
            info["duration"] = float(data["format"].get("duration", 0))
        except (KeyError, ValueError):
            info["duration"] = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["height"] = stream.get("height", 0)
                break
        return info
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {}


def parse_path_groups(file_path: str) -> dict[str, str]:
    """
    Extract studio / category from folder structure.

    Examples:
      /other/Porn/MuscleBearPorn/scene.mp4        → studio=MuscleBearPorn
      /other/Porn/CATEGORIES/AMATEUR/scene.mp4    → category=AMATEUR
      /other/Porn/BerlinStar/FANS SITES/xyz.mp4   → studio=BerlinStar
    """
    groups: dict[str, str] = {}
    try:
        rel = Path(file_path).relative_to(PORN_ROOT)
        parts = rel.parts  # e.g. ('MuscleBearPorn', 'scene.mp4')
        if not parts:
            return groups

        if parts[0].upper() == CATEGORIES_FOLDER.upper():
            # CATEGORIES / {Category} / ...
            if len(parts) >= 2:
                groups["category"] = parts[1].title()
        else:
            groups["studio"] = parts[0]

    except ValueError:
        pass  # file not under PORN_ROOT — skip path parsing
    return groups


def bucket_label(value: float, buckets: dict) -> str | None:
    for label, (lo, hi) in buckets.items():
        if lo <= value < hi:
            return label
    return None


def scan_library(plex: PlexServer, library_name: str):
    section = plex.library.section(library_name)
    all_items = section.all()
    total = len(all_items)
    print(f"Scanning {total} items in '{library_name}' ...")

    groups: dict[str, list] = defaultdict(list)

    for i, item in enumerate(all_items, 1):
        print(f"  [{i:>4}/{total}] {item.title[:60]:<60}", end="\r")
        try:
            file_path = item.media[0].parts[0].file
        except (IndexError, AttributeError):
            continue

        # Path-based grouping (fast, no subprocess)
        path_groups = parse_path_groups(file_path)
        if "studio" in path_groups:
            groups[f"Studio: {path_groups['studio']}"].append(item)
        if "category" in path_groups:
            groups[f"Category: {path_groups['category']}"].append(item)

        # Technical metadata (ffprobe — slower)
        tech = get_ffprobe_technical(file_path)
        if tech.get("duration"):
            label = bucket_label(tech["duration"], DURATION_BUCKETS)
            if label:
                groups[label].append(item)
        if tech.get("height"):
            label = bucket_label(tech["height"], RESOLUTION_BUCKETS)
            if label:
                groups[label].append(item)

    print(f"\nFound {len(groups)} potential playlist groups.")
    return groups


def upsert_playlist(plex: PlexServer, name: str, items: list, library_name: str):
    full_name = f"{PLAYLIST_PREFIX}{name}"
    for pl in plex.playlists():
        if pl.title == full_name:
            pl.delete()
            break
    plex.createPlaylist(full_name, section=plex.library.section(library_name), items=items)
    print(f"  {'Updated' if True else 'Created':7}  {full_name!r}  ({len(items)} items)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 build_playlists.py \"Other Videos\"")
        sys.exit(1)

    library_name = " ".join(sys.argv[1:])

    print(f"Connecting to Plex at {PLEX_URL} ...")
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print(f"Connected: {plex.friendlyName}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    groups = scan_library(plex, library_name)

    print("\nCreating playlists ...")
    created = 0
    skipped = 0
    for name, items in sorted(groups.items()):
        if len(items) >= MIN_ITEMS:
            upsert_playlist(plex, name, items, library_name)
            created += 1
        else:
            skipped += 1

    print(f"\nDone. {created} playlists created/updated, {skipped} groups skipped (< {MIN_ITEMS} items).")


if __name__ == "__main__":
    main()
