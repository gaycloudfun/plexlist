import pytest
from fastapi.testclient import TestClient

import main
import settings_store


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / ".structly_settings.json")
    monkeypatch.setattr(main, "_plex", None)


class FakeServer:
    friendlyName = "Test Server"


class FakeResource:
    product = "Plex Media Server"

    def connect(self):
        return FakeServer()


class FakeAccount:
    def __init__(self, token):
        self.token = token

    def resources(self):
        return [FakeResource()]


@pytest.fixture
def client():
    return TestClient(main.app)


def test_status_reports_disconnected_with_no_token(client):
    res = client.get("/api/status")
    assert res.json() == {"connected": False, "error": "No token configured"}


def test_connect_persists_token_and_connects(client, monkeypatch):
    monkeypatch.setattr(main, "MyPlexAccount", FakeAccount)
    res = client.post("/api/connect", json={"token": "secret-token"})
    assert res.status_code == 200
    assert res.json() == {"connected": True, "name": "Test Server"}
    assert settings_store.load_settings()["token"] == "secret-token"


def test_status_reconnects_from_persisted_token(client, monkeypatch):
    monkeypatch.setattr(main, "MyPlexAccount", FakeAccount)
    settings_store.save_settings(token="saved-token")
    res = client.get("/api/status")
    assert res.json() == {"connected": True, "name": "Test Server"}
