"""
Structly — persisted local settings (~/.structly_settings.json).

Shared with the desktop app (app_v4.py), which already reads/writes the
"token" key at this same path. This module additionally manages
"include_adult_content" without disturbing that compatibility — never
rename or drop the "token" key.
"""
import json
import os
import tempfile
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
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULTS)
        # Repair permissions on files written before 0600 hardening (or by
        # the desktop app, which never chmods) — any read tightens them.
        try:
            SETTINGS_PATH.chmod(0o600)
        except OSError:
            pass
        if isinstance(data, dict):
            return {**DEFAULTS, **data}
    return dict(DEFAULTS)


def save_settings(**updates) -> dict:
    data = load_settings()
    data.update(updates)
    # Write to a temp file in the same directory, lock it down, then swap it
    # into place: os.replace is atomic on POSIX, so a crash mid-write can
    # never leave a truncated settings file, and the real path is never
    # briefly readable at default permissions.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(SETTINGS_PATH.parent), prefix=SETTINGS_PATH.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(data, indent=2))
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, SETTINGS_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return data
