import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import settings_store  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point the settings store at a throwaway path for every test.

    Autouse and shared here on purpose: any test that touches settings would
    otherwise read/write the developer's real ~/.structly_settings.json.
    """
    path = tmp_path / ".structly_settings.json"
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", path)
    return path
