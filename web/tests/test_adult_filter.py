import queue
from types import SimpleNamespace

import main


class FakeMedia:
    def __init__(self, path, resolution="1080"):
        self.parts = [SimpleNamespace(file=path)]
        self.videoResolution = resolution


class FakeItem:
    def __init__(self, path, studio=None, rating_key=None):
        self.media = [FakeMedia(path)]
        self.studio = studio
        self.genres = []
        self.directors = []
        self.roles = []
        self.duration = None
        self.addedAt = None
        self.ratingKey = rating_key or path


class FakePlaylist:
    def __init__(self, title):
        self.title = title
        self.deleted = False

    def delete(self):
        self.deleted = True


class FakeSection:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeLibrary:
    def __init__(self, section):
        self._section = section

    def section(self, name):
        return self._section


class FakePlex:
    def __init__(self, items, existing_playlists=None):
        self.library = FakeLibrary(FakeSection(items))
        self._playlists = existing_playlists or []
        self.created = []

    def playlists(self):
        return self._playlists

    def createPlaylist(self, name, section, items):
        self.created.append((name, [i.ratingKey for i in items]))
        return FakePlaylist(name)


def drain(q):
    msgs = []
    while True:
        msg = q.get_nowait()
        if msg is None:
            break
        msgs.append(msg)
    return msgs


def test_is_adult_item_true_under_porn_root():
    item = FakeItem("/other/Porn/StudioA/scene1.mp4")
    assert main.is_adult_item(item) is True


def test_is_adult_item_false_outside_porn_root():
    item = FakeItem("/movies/Regular/movie.mp4")
    assert main.is_adult_item(item) is False


def test_adult_items_skipped_by_default():
    items = [
        FakeItem("/other/Porn/StudioA/scene1.mp4", studio="StudioA"),
        FakeItem("/movies/Regular/movie.mp4", studio="RegularStudio"),
    ]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, include_adult=False)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 1


def test_adult_items_included_when_opted_in():
    items = [FakeItem("/other/Porn/StudioA/scene1.mp4", studio="StudioA")]
    plex = FakePlex(items)
    q = queue.Queue()
    main._build_worker(plex, "Library", "t ", "quick", {"studio"}, "", [], q, include_adult=True)
    msgs = drain(q)
    done = next(m for m in msgs if m["type"] == "done")
    assert done["skipped"] == 0
