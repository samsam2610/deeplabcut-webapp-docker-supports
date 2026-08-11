from src import config


def test_identity_when_unset(monkeypatch):
    monkeypatch.delenv(config.PATH_MAP_ENV, raising=False)
    assert config.to_local("/user-data/x/y.avi") == "/user-data/x/y.avi"


def test_single_mapping(monkeypatch):
    monkeypatch.setenv(config.PATH_MAP_ENV, "/user-data/A=/mnt/a")
    assert config.to_local("/user-data/A/v.avi") == "/mnt/a/v.avi"


def test_unmapped_path_passes_through(monkeypatch):
    monkeypatch.setenv(config.PATH_MAP_ENV, "/user-data/A=/mnt/a")
    assert config.to_local("/elsewhere/v.avi") == "/elsewhere/v.avi"


def test_longest_prefix_wins(monkeypatch):
    # Declaration order must not decide the result: /user-data/A/B is more
    # specific than /user-data/A and has to win regardless of ordering.
    monkeypatch.setenv(config.PATH_MAP_ENV,
                       "/user-data/A=/mnt/a,/user-data/A/B=/mnt/b")
    assert config.to_local("/user-data/A/B/v.avi") == "/mnt/b/v.avi"
    assert config.to_local("/user-data/A/C/v.avi") == "/mnt/a/c/v.avi".replace("/c/", "/C/")


def test_malformed_entries_are_ignored(monkeypatch):
    monkeypatch.setenv(config.PATH_MAP_ENV, "garbage,,/user-data/A=/mnt/a,=")
    assert config.to_local("/user-data/A/v.avi") == "/mnt/a/v.avi"


def test_whitespace_is_tolerated(monkeypatch):
    monkeypatch.setenv(config.PATH_MAP_ENV, "  /user-data/A = /mnt/a  ")
    assert config.to_local("/user-data/A/v.avi") == "/mnt/a/v.avi"
