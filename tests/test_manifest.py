"""Tests for the article manifest sidecar JSON."""

from audio_articles.core.manifest import (
    ArticleManifest,
    now_iso,
    read_manifest,
    write_manifest,
)


def test_manifest_round_trip(tmp_path):
    manifest = ArticleManifest(
        title="Hello, World",
        source_url="https://example.com/post",
        audio_filename="Hello_World.mp3",
        pdf_filename="Hello_World.pdf",
        generated_at=now_iso(),
        word_count=1234,
    )
    path = write_manifest(manifest, tmp_path, "Hello_World")
    assert path.exists()
    assert path.suffix == ".json"

    loaded = read_manifest(tmp_path, "Hello_World")
    assert loaded == manifest


def test_manifest_missing_returns_none(tmp_path):
    assert read_manifest(tmp_path, "nope") is None


def test_manifest_pdf_filename_optional(tmp_path):
    manifest = ArticleManifest(
        title="Audio-only",
        source_url=None,
        audio_filename="Audio_only.mp3",
        pdf_filename=None,
        generated_at=now_iso(),
        word_count=42,
    )
    write_manifest(manifest, tmp_path, "Audio_only")
    loaded = read_manifest(tmp_path, "Audio_only")
    assert loaded is not None
    assert loaded.pdf_filename is None


def test_manifest_corrupt_json_returns_none(tmp_path):
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
    assert read_manifest(tmp_path, "broken") is None
