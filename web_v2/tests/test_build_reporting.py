import queue

from tests.test_adult_filter import FakeItem, FakePlaylist, FakePlex, drain
import main


def test_never_matched_items_count_as_skipped():
    items = [FakeItem("/movies/Regular/unmatched.mp4")]  # no studio set
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 1


def test_single_match_lands_in_misc_not_skipped():
    items = [FakeItem("/movies/Regular/one.mp4", studio="LonelyStudio")]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 0
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["name"] == "Misc"


def test_dry_run_makes_no_plex_mutations():
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="RegularStudio") for i in range(3)]
    existing = FakePlaylist("t Studio: RegularStudio")
    plex = FakePlex(items, existing_playlists=[existing])
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, dry_run=True)
    msgs = drain(q)
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["replaced"] is True
    assert playlist_msg["dry_run"] is True
    assert plex.created == []
    assert existing.deleted is False


def test_real_run_reports_replaced_and_mutates():
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="RegularStudio") for i in range(3)]
    existing = FakePlaylist("t Studio: RegularStudio")
    plex = FakePlex(items, existing_playlists=[existing])
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, dry_run=False)
    msgs = drain(q)
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["replaced"] is True
    assert playlist_msg["dry_run"] is False
    assert existing.deleted is True
    assert plex.created == [
        ("t Studio: RegularStudio", [i.ratingKey for i in items])
    ]


def test_new_playlist_reports_replaced_false():
    items = [FakeItem(f"/movies/Regular/m{i}.mp4", studio="NewStudio") for i in range(3)]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q)
    msgs = drain(q)
    playlist_msg = next(m for m in msgs if m["type"] == "playlist")
    assert playlist_msg["replaced"] is False
