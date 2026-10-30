"""The /api/build endpoint is POST-only and streams SSE from the POST body."""
import json

import pytest
from fastapi.testclient import TestClient

from tests.test_adult_filter import FakeItem, FakePlex
import main
import settings_store


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def connected(monkeypatch):
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="RegularStudio") for i in range(3)]
    plex = FakePlex(items)
    monkeypatch.setattr(main, "_plex", plex)
    return plex


def parse_sse(text):
    """Same job the browser client does: split on blank lines, take `data: `."""
    events = []
    for chunk in text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_build_rejects_get(client, connected):
    # The static-file mount at "/" swallows the unmatched GET, so it 404s
    # rather than 405s — either way no build is started by a plain GET.
    res = client.get("/api/build", params={"library": "Library"})
    assert res.status_code in (404, 405)
    assert connected.created == []


def test_build_requires_connection(client, monkeypatch):
    monkeypatch.setattr(main, "_plex", None)
    res = client.post("/api/build", json={"library": "Library"})
    assert res.status_code == 503


def test_build_streams_sse_events_from_post_body(client, connected):
    res = client.post("/api/build", json={
        "library": "Library",
        "prefix": "t ",
        "mode": "quick",
        "types": "studio",
        "actor_filter": "",
        "rules": "[]",
        "dry_run": False,
    })
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(res.text)
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "progress" in types and "log" in types and types[-1] == "done"

    playlist = next(e for e in events if e["type"] == "playlist")
    assert playlist["name"] == "Studio: RegularStudio"
    assert playlist["count"] == 3
    assert connected.created == [("t Studio: RegularStudio", [i.ratingKey for i in
                                                              connected.library._section._items])]


def test_build_honours_dry_run_from_body(client, connected):
    res = client.post("/api/build", json={
        "library": "Library", "types": "studio", "dry_run": True,
    })
    events = parse_sse(res.text)
    done = next(e for e in events if e["type"] == "done")
    assert done["dry_run"] is True
    assert connected.created == []


def test_build_respects_adult_setting_from_store(client, monkeypatch):
    monkeypatch.setattr(main, "_plex", FakePlex([
        FakeItem("/other/Porn/StudioA/scene1.mp4", studio="StudioA"),
    ]))
    settings_store.save_settings(include_adult_content=False)
    res = client.post("/api/build", json={"library": "Library", "types": "studio"})
    done = next(e for e in parse_sse(res.text) if e["type"] == "done")
    assert done["skipped"] == 1


def test_build_requires_library(client, connected):
    assert client.post("/api/build", json={}).status_code == 422


def test_second_build_is_refused_while_one_runs(client, connected):
    assert main._build_lock.acquire(blocking=False)  # a build in progress
    try:
        assert client.post("/api/build", json={"library": "Library", "types": "studio"}).status_code == 409
    finally:
        main._build_lock.release()
    # Lock is free again after a finished build.
    assert client.post("/api/build", json={"library": "Library", "types": "studio"}).status_code == 200
    assert client.post("/api/build", json={"library": "Library", "types": "studio"}).status_code == 200
