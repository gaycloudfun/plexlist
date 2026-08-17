import os
import stat

import pytest

import settings_store

# `isolated_settings` is an autouse fixture in conftest.py — every test in the
# suite gets a throwaway SETTINGS_PATH without opting in.


def test_load_settings_defaults_when_no_file():
    result = settings_store.load_settings()
    assert result == {"token": "", "include_adult_content": False}


def test_save_and_load_round_trip():
    settings_store.save_settings(token="abc123")
    result = settings_store.load_settings()
    assert result["token"] == "abc123"
    assert result["include_adult_content"] is False


def test_save_settings_merges_not_overwrites():
    settings_store.save_settings(token="abc123")
    settings_store.save_settings(include_adult_content=True)
    result = settings_store.load_settings()
    assert result["token"] == "abc123"
    assert result["include_adult_content"] is True


def test_load_settings_survives_corrupt_json():
    settings_store.SETTINGS_PATH.write_text("{not json")
    result = settings_store.load_settings()
    assert result == {"token": "", "include_adult_content": False}


@pytest.mark.parametrize("payload", ["null", "42", "[]"])
def test_load_settings_survives_non_dict_json(payload):
    settings_store.SETTINGS_PATH.write_text(payload)
    result = settings_store.load_settings()
    assert result == {"token": "", "include_adult_content": False}


# ── Permissions & atomicity ───────────────────────────────────────────────────

def test_save_settings_writes_0600():
    settings_store.save_settings(token="abc123")
    assert stat.S_IMODE(settings_store.SETTINGS_PATH.stat().st_mode) == 0o600


def test_save_settings_leaves_no_temp_files_behind():
    settings_store.save_settings(token="abc123")
    settings_store.save_settings(include_adult_content=True)
    siblings = list(settings_store.SETTINGS_PATH.parent.iterdir())
    assert siblings == [settings_store.SETTINGS_PATH]


def test_save_settings_replaces_file_atomically(monkeypatch):
    """The real path is only ever swapped in whole, never written in place."""
    settings_store.save_settings(token="original")
    replaced = {}

    real_replace = os.replace

    def spy(src, dst):
        replaced["src"] = str(src)
        replaced["dst"] = str(dst)
        return real_replace(src, dst)

    monkeypatch.setattr(settings_store.os, "replace", spy)
    settings_store.save_settings(token="updated")

    assert replaced["dst"] == str(settings_store.SETTINGS_PATH)
    assert replaced["src"] != str(settings_store.SETTINGS_PATH)
    assert settings_store.load_settings()["token"] == "updated"


def test_load_settings_repairs_loose_permissions():
    settings_store.SETTINGS_PATH.write_text('{"token": "abc123"}')
    settings_store.SETTINGS_PATH.chmod(0o644)
    settings_store.load_settings()
    assert stat.S_IMODE(settings_store.SETTINGS_PATH.stat().st_mode) == 0o600
