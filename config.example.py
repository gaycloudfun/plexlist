"""
Copy this file to config.py and fill in your own Plex server details, or
set PLEX_URL / PLEX_TOKEN as environment variables instead — config.py
already falls back to those if you leave this file's defaults blank.
"""
import os

PLEX_URL = os.environ.get("PLEX_URL", "http://your-plex-ip:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "your_plex_token_here")
