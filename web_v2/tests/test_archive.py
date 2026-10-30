"""Archive keeps the original on a name clash and trashes the copy; restore rebuilds from files."""
import json

import pytest
from fastapi.testclient import TestClient

from tests.test_adult_filter import FakeItem, FakePlaylist, FakePlex
import main


class ArchivePlaylist(FakePlaylist):
    def __init__(self, title, items):
        super().__init__(title)
        self._items = items

    def items(self):
        return self._items


class ArchivePlex(FakePlex):
    def fetchItems(self, ekey):
        keys = ekey.rsplit("/", 1)[1].split(",")
        return [FakeItem(f"/m/{k}.mp4", rating_key=k) for k in keys]


@pytest.fixture
def env(tmp_path, monkeypatch):
    trashed = []
    monkeypatch.setattr(main, "ARCHIVE_DIR", tmp_path / "archives")
    monkeypatch.setattr(main, "choose_folder", lambda start: start)
    monkeypatch.setattr(main, "move_to_trash", lambda p: trashed.append(p) or p.unlink())
    a, b = FakeItem("/a", rating_key="1"), FakeItem("/b", rating_key="2")
    a.title, b.title = "A", "B"
    pls = [
        ArchivePlaylist("t Genre: Drama", [a, b]),
        ArchivePlaylist("Other list", [FakeItem("/c", rating_key="3")]),
    ]
    plex = ArchivePlex([], existing_playlists=pls)
    monkeypatch.setattr(main, "_plex", plex)
    return TestClient(main.app), plex, tmp_path / "archives", trashed


def test_archive_saves_only_prefixed_playlists(env):
    client, _, folder, trashed = env
    res = client.post("/api/archive", json={"prefix": "t "}).json()
    assert res["saved"] == ["t Genre: Drama"]
    items = json.loads((folder / "t Genre: Drama.json").read_text())["items"]
    assert [i["ratingKey"] for i in items] == ["1", "2"]
    assert [i["title"] for i in items] == ["A", "B"]
    assert not trashed


def test_archive_same_name_keeps_original_and_trashes_copy(env):
    client, plex, folder, trashed = env
    client.post("/api/archive", json={"prefix": "t "})
    original = (folder / "t Genre: Drama.json").read_text()
    plex._playlists[0]._items = [FakeItem("/z", rating_key="99")]

    res = client.post("/api/archive", json={"prefix": "t "}).json()

    assert res["duplicates"] == ["t Genre: Drama"] and res["saved"] == []
    assert (folder / "t Genre: Drama.json").read_text() == original
    assert len(trashed) == 1 and list(folder.iterdir()) == [folder / "t Genre: Drama.json"]


def test_archive_trash_failure_reports_and_leaves_no_stray_file(env, monkeypatch):
    client, _, folder, _ = env
    client.post("/api/archive", json={"prefix": "t "})
    def boom(p):
        raise OSError("no Finder")
    monkeypatch.setattr(main, "move_to_trash", boom)

    res = client.post("/api/archive", json={"prefix": "t "}).json()

    assert res["errors"][0]["title"] == "t Genre: Drama"
    assert list(folder.iterdir()) == [folder / "t Genre: Drama.json"]


def test_restore_recreates_prefixed_playlists_and_skips_bad_files(env):
    client, plex, folder, _ = env
    client.post("/api/archive", json={"prefix": "t "})
    (folder / "broken.json").write_text("{not json")

    res = client.post("/api/restore", json={"prefix": "t ", "library": "Movies"}).json()

    assert res["restored"] == [{"title": "t Genre: Drama", "count": 2}]
    assert plex.created == [("t Genre: Drama", ["1", "2"])]
    assert res["errors"][0]["title"] == "broken"


def test_cancelled_folder_picker_does_nothing(env, monkeypatch):
    client, plex, folder, _ = env
    monkeypatch.setattr(main, "choose_folder", lambda start: None)
    assert client.post("/api/archive", json={"prefix": "t "}).json() == {"cancelled": True}
    assert client.post("/api/restore", json={"prefix": "t ", "library": "M"}).json() == {"cancelled": True}
    assert not folder.exists() and plex.created == []


def test_destroy_archives_into_last_chosen_folder(env, tmp_path):
    client, _, _, _ = env
    main.save_settings(archive_dir=str(tmp_path / "picked"))
    client.post("/api/destroy", json={"prefix": "t "})
    assert (tmp_path / "picked" / "t Genre: Drama.json").exists()


def test_destroy_refuses_empty_prefix(env):
    client, plex, _, _ = env
    assert client.post("/api/destroy", json={"prefix": "  "}).status_code == 400
    assert not any(pl.deleted for pl in plex._playlists)


def test_destroy_works_repeatedly(env):
    client, _, _, _ = env
    assert client.post("/api/destroy", json={"prefix": "t "}).json()["destroyed"] == 1
    assert client.post("/api/destroy", json={"prefix": "t "}).status_code == 200


def test_destroy_archives_titles_before_deleting(env):
    client, plex, folder, _ = env
    res = client.post("/api/destroy", json={"prefix": "t "}).json()
    assert res["archive"]["saved"] == ["t Genre: Drama"]
    assert "A" in (folder / "t Genre: Drama.json").read_text()
    assert plex._playlists[0].deleted and not plex._playlists[1].deleted


def test_destroy_deletes_nothing_if_archive_write_fails(env, monkeypatch):
    client, plex, _, _ = env
    monkeypatch.setattr(main.Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        client.post("/api/destroy", json={"prefix": "t "})
    assert not any(pl.deleted for pl in plex._playlists)


def test_destroy_deletes_nothing_when_an_archive_fails(env, monkeypatch):
    client, plex, _, _ = env
    client.post("/api/archive", json={"prefix": "t "})  # first copy exists, so the next save is a duplicate
    def boom(p):
        raise OSError("no Finder")
    monkeypatch.setattr(main, "move_to_trash", boom)

    res = client.post("/api/destroy", json={"prefix": "t "})

    assert res.status_code == 500 and "nothing was deleted" in res.json()["detail"]
    assert [pl.title for pl in plex.playlists()] == ["t Genre: Drama", "Other list"]


def test_playlists_lists_only_prefixed_titles(env):
    client, _, _, _ = env
    assert client.get("/api/playlists", params={"prefix": "t "}).json() == {"titles": ["t Genre: Drama"]}
