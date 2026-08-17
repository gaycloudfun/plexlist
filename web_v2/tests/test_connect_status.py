import pytest
from fastapi.testclient import TestClient

import main
import settings_store


# Settings isolation comes from conftest.py's autouse `isolated_settings`.
@pytest.fixture(autouse=True)
def reset_plex(monkeypatch):
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


# ── Token redaction in relayed error text ─────────────────────────────────────

LEAKY_MESSAGE = (
    "(401) unauthorized; https://plex.tv/api/v2/resources"
    "?X-Plex-Token=supersecrettoken&includeHttps=1"
)


def leaky_account(token):
    raise RuntimeError(LEAKY_MESSAGE)


def test_redact_token_scrubs_query_string():
    assert main.redact_token(LEAKY_MESSAGE) == (
        "(401) unauthorized; https://plex.tv/api/v2/resources"
        "?X-Plex-Token=[REDACTED]&includeHttps=1"
    )


def test_redact_token_leaves_unrelated_text_alone():
    assert main.redact_token("plain failure") == "plain failure"


def test_status_error_does_not_leak_token(client, monkeypatch):
    monkeypatch.setattr(main, "MyPlexAccount", leaky_account)
    settings_store.save_settings(token="saved-token")
    body = client.get("/api/status").json()
    assert body["connected"] is False
    assert "supersecrettoken" not in body["error"]
    assert "X-Plex-Token=[REDACTED]" in body["error"]


def test_connect_error_does_not_leak_token(client, monkeypatch):
    monkeypatch.setattr(main, "MyPlexAccount", leaky_account)
    res = client.post("/api/connect", json={"token": "supersecrettoken"})
    assert res.status_code == 400
    assert "supersecrettoken" not in res.json()["detail"]
    assert "X-Plex-Token=[REDACTED]" in res.json()["detail"]
