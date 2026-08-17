import pytest

import settings_store


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / ".structly_settings.json")


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
