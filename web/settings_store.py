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
            if isinstance(data, dict):
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
