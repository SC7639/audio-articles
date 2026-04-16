import json
from pathlib import Path

import pytest

from audio_articles.core.auth import SessionStore


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def store(session_dir: Path) -> SessionStore:
    return SessionStore(session_dir=session_dir)


def test_save_and_load_round_trip(store: SessionStore, session_dir: Path):
    cookies = [{"name": "sid", "value": "abc123", "domain": ".substack.com"}]
    store.save("substack", cookies)
    loaded = store.load("substack")
    assert loaded == cookies


def test_load_returns_none_when_no_file(store: SessionStore):
    assert store.load("substack") is None


def test_load_returns_none_on_corrupt_file(store: SessionStore, session_dir: Path):
    session_dir.mkdir(parents=True)
    (session_dir / "substack.json").write_text("not json", encoding="utf-8")
    assert store.load("substack") is None


def test_delete_removes_file(store: SessionStore, session_dir: Path):
    store.save("substack", [{"name": "x", "value": "y", "domain": ".substack.com"}])
    assert (session_dir / "substack.json").exists()
    store.delete("substack")
    assert not (session_dir / "substack.json").exists()


def test_delete_noop_when_no_file(store: SessionStore):
    store.delete("substack")  # should not raise


def test_delete_all_removes_all_json_files(store: SessionStore, session_dir: Path):
    store.save("substack", [{"name": "a", "value": "1", "domain": ".substack.com"}])
    store.save("medium", [{"name": "b", "value": "2", "domain": ".medium.com"}])
    store.delete_all()
    assert not list(session_dir.glob("*.json"))


def test_delete_all_noop_when_dir_missing(session_dir: Path):
    store = SessionStore(session_dir=session_dir / "nonexistent")
    store.delete_all()  # should not raise
