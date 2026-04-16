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
    # Verify the file is not world-readable (credentials must be user-only)
    import stat
    file_mode = (session_dir / "substack.json").stat().st_mode
    assert not (file_mode & stat.S_IRGRP), "File must not be group-readable"
    assert not (file_mode & stat.S_IROTH), "File must not be world-readable"


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


from audio_articles.core.auth import MEDIUM_CUSTOM_DOMAINS, get_cookies_for_url, get_medium_cookies


# ── get_cookies_for_url ───────────────────────────────────────────────────

def test_substack_url_returns_substack_cookies(session_dir: Path):
    store = SessionStore(session_dir=session_dir)
    cookies = [{"name": "substack.sid", "value": "tok", "domain": ".substack.com"}]
    store.save("substack", cookies)
    result = get_cookies_for_url("https://foo.substack.com/p/article", session_dir=session_dir)
    assert result == {"substack.sid": "tok"}


def test_medium_url_returns_medium_cookies(session_dir: Path):
    store = SessionStore(session_dir=session_dir)
    cookies = [{"name": "uid", "value": "123", "domain": ".medium.com"}]
    store.save("medium", cookies)
    result = get_cookies_for_url("https://medium.com/@user/article", session_dir=session_dir)
    assert result == {"uid": "123"}


def test_medium_subdomain_returns_medium_cookies(session_dir: Path):
    store = SessionStore(session_dir=session_dir)
    cookies = [{"name": "uid", "value": "456", "domain": ".medium.com"}]
    store.save("medium", cookies)
    result = get_cookies_for_url("https://pub.medium.com/some-article", session_dir=session_dir)
    assert result == {"uid": "456"}


def test_custom_medium_domain_returns_medium_cookies(session_dir: Path):
    store = SessionStore(session_dir=session_dir)
    cookies = [{"name": "uid", "value": "789", "domain": ".medium.com"}]
    store.save("medium", cookies)
    result = get_cookies_for_url("https://towardsdatascience.com/article", session_dir=session_dir)
    assert result == {"uid": "789"}


def test_unknown_url_returns_none(session_dir: Path):
    result = get_cookies_for_url("https://example.com/article", session_dir=session_dir)
    assert result is None


def test_returns_none_when_no_session_saved(session_dir: Path):
    result = get_cookies_for_url("https://foo.substack.com/p/article", session_dir=session_dir)
    assert result is None


def test_cookies_missing_name_or_value_are_excluded(session_dir: Path):
    store = SessionStore(session_dir=session_dir)
    cookies = [
        {"name": "good", "value": "val", "domain": ".substack.com"},
        {"domain": ".substack.com"},  # missing name + value
        {"name": "novalue", "domain": ".substack.com"},  # missing value
    ]
    store.save("substack", cookies)
    result = get_cookies_for_url("https://foo.substack.com/p/x", session_dir=session_dir)
    assert result == {"good": "val"}


def test_lookalike_substack_domain_returns_none(session_dir: Path):
    SessionStore(session_dir=session_dir).save(
        "substack", [{"name": "sid", "value": "tok", "domain": ".substack.com"}]
    )
    assert get_cookies_for_url(
        "https://foo.substack.com.attacker.example/p/x", session_dir=session_dir
    ) is None


def test_lookalike_medium_domain_returns_none(session_dir: Path):
    SessionStore(session_dir=session_dir).save(
        "medium", [{"name": "uid", "value": "tok", "domain": ".medium.com"}]
    )
    assert get_cookies_for_url(
        "https://medium.com.attacker.example/article", session_dir=session_dir
    ) is None


# ── get_medium_cookies ────────────────────────────────────────────────────

def test_get_medium_cookies_returns_dict(session_dir: Path):
    store = SessionStore(session_dir=session_dir)
    store.save("medium", [{"name": "uid", "value": "abc", "domain": ".medium.com"}])
    result = get_medium_cookies(session_dir=session_dir)
    assert result == {"uid": "abc"}


def test_get_medium_cookies_returns_none_when_no_session(session_dir: Path):
    assert get_medium_cookies(session_dir=session_dir) is None


# ── MEDIUM_CUSTOM_DOMAINS ─────────────────────────────────────────────────

def test_medium_custom_domains_is_frozenset():
    assert isinstance(MEDIUM_CUSTOM_DOMAINS, frozenset)
    assert "towardsdatascience.com" in MEDIUM_CUSTOM_DOMAINS
    assert "betterprogramming.pub" in MEDIUM_CUSTOM_DOMAINS


from audio_articles.core.auth import login_interactive
from audio_articles.core.exceptions import LoginError


def test_login_raises_for_unknown_platform(session_dir: Path):
    with pytest.raises(LoginError, match="Unknown platform"):
        login_interactive("twitter", session_dir=session_dir)


def test_login_raises_when_playwright_not_installed(mocker, session_dir: Path):
    # Patch the already-bound module-level name rather than sys.modules,
    # since the import runs at module load time and would be too late to intercept.
    mocker.patch("audio_articles.core.auth.sync_playwright", None)
    with pytest.raises(LoginError, match="Playwright is not installed"):
        login_interactive("substack", session_dir=session_dir)


def test_login_raises_on_timeout(mocker, session_dir: Path):
    mock_page = mocker.MagicMock()
    mock_context = mocker.MagicMock()
    mock_context.new_page.return_value = mock_page
    # cookies() never returns substack.sid — session never established
    mock_context.cookies.return_value = []
    mock_browser = mocker.MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_playwright_ctx = mocker.MagicMock()
    mock_playwright_ctx.__enter__ = lambda s: mock_playwright_ctx
    mock_playwright_ctx.__exit__ = mocker.MagicMock(return_value=False)
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    mocker.patch("audio_articles.core.auth.sync_playwright", return_value=mock_playwright_ctx)
    # timeout=0 means deadline expires before the loop body runs — no sleep mock needed

    with pytest.raises(LoginError, match="timed out"):
        login_interactive("substack", session_dir=session_dir, timeout=0)


def test_login_saves_cookies_on_success(mocker, session_dir: Path):
    saved_cookies = [{"name": "substack.sid", "value": "tok", "domain": ".substack.com"}]
    mock_page = mocker.MagicMock()
    mock_context = mocker.MagicMock()
    mock_context.new_page.return_value = mock_page
    # cookies() returns the session cookie — login detected immediately
    mock_context.cookies.return_value = saved_cookies
    mock_browser = mocker.MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_playwright_ctx = mocker.MagicMock()
    mock_playwright_ctx.__enter__ = lambda s: mock_playwright_ctx
    mock_playwright_ctx.__exit__ = mocker.MagicMock(return_value=False)
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    mocker.patch("audio_articles.core.auth.sync_playwright", return_value=mock_playwright_ctx)
    mocker.patch("audio_articles.core.auth.time.sleep")

    login_interactive("substack", session_dir=session_dir, timeout=60)

    store = SessionStore(session_dir=session_dir)
    assert store.load("substack") == saved_cookies
