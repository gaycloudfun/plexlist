"""
discover.py — Connect to Plex, list libraries, and show what embedded
              metadata tags are available in your video files.

Usage:
    python discover.py
"""

import json
import subprocess
import sys
from plexapi.server import PlexServer
from config import PLEX_URL, PLEX_TOKEN


def get_ffprobe_tags(file_path: str) -> dict:
    """Extract embedded metadata tags from a file using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        # Normalize keys to lowercase
        return {k.lower(): v for k, v in tags.items()}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {}


def list_libraries(plex: PlexServer):
    print("\n=== Plex Libraries ===")
    for section in plex.library.sections():
        print(f"  [{section.key}] {section.title!r}  (type: {section.type})")
    print()


def sample_metadata(plex: PlexServer, library_name: str, sample_size: int = 10):
    """Sample a few items from a library and show available embedded tags."""
    section = plex.library.section(library_name)
    items = section.all()

    print(f"\n=== Sampling {sample_size} items from '{library_name}' ===")
    all_tag_keys: set = set()

    for item in items[:sample_size]:
        # Get the actual file path from the first media part
        try:
            file_path = item.media[0].parts[0].file
        except (IndexError, AttributeError):
            continue

        tags = get_ffprobe_tags(file_path)
        if tags:
            all_tag_keys.update(tags.keys())
            print(f"\n  {item.title}")
            print(f"    File: {file_path}")
            for k, v in sorted(tags.items()):
                print(f"    {k}: {v}")
        else:
            print(f"\n  {item.title}")
            print(f"    File: {file_path}")
            print(f"    (no embedded tags found)")

    if all_tag_keys:
        print(f"\n=== Tag keys found across sample ===")
        for key in sorted(all_tag_keys):
            print(f"  {key}")
    else:
        print("\n  No embedded tags found in sample — playlists will use technical metadata (duration, resolution, codec).")


def main():
    print(f"Connecting to Plex at {PLEX_URL} ...")
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print(f"Connected: {plex.friendlyName}")
    except Exception as e:
        print(f"ERROR: Could not connect to Plex — {e}")
        sys.exit(1)

    list_libraries(plex)

    if len(sys.argv) > 1:
        library_name = " ".join(sys.argv[1:])
        sample_metadata(plex, library_name)
    else:
        print("To sample metadata from a library, run:")
        print('  python discover.py "Your Library Name"')


if __name__ == "__main__":
    main()
