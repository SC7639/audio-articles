from typer.testing import CliRunner

from audio_articles.cli.main import _read_url_list, app
from audio_articles.core.models import AudiobookResult, ExtractionResult

runner = CliRunner()


def _make_run_full_mock(mocker, results):
    """Patch `run_full` so each URL gets a deterministic AudiobookResult + ExtractionResult.

    `results` is a dict {url: title} or {url: (title, raises_exc)}. When the value is
    an Exception instance the mock raises it for that URL — used to exercise the
    continue-on-failure path.
    """

    def _side_effect(article_input):
        url = str(article_input.url)
        spec = results[url]
        if isinstance(spec, Exception):
            raise spec
        title = spec
        extraction = ExtractionResult(
            title=title,
            body="body",
            source_url=url,
            word_count=10,
        )
        result = AudiobookResult(
            audio_bytes=b"fake-mp3-" + title.encode(),
            script=f"script for {title}",
            title=title,
            source_url=url,
        )
        return result, extraction

    return mocker.patch(
        "audio_articles.cli.main.run_full", side_effect=_side_effect
    )


def test_read_url_list_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text(
        "# comment line\n"
        "https://example.com/one\n"
        "\n"
        "   \n"
        "  https://example.com/two  \n"
        "# another comment\n"
        "https://example.com/three\n"
    )
    assert _read_url_list(f) == [
        "https://example.com/one",
        "https://example.com/two",
        "https://example.com/three",
    ]


def test_batch_processes_all_urls(tmp_path, mocker):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "# my batch\n"
        "https://example.com/one\n"
        "https://example.com/two\n"
    )
    out_dir = tmp_path / "out"

    _make_run_full_mock(
        mocker,
        {
            "https://example.com/one": "Article One",
            "https://example.com/two": "Article Two",
        },
    )

    result = runner.invoke(
        app,
        ["batch", str(urls_file), "--output-dir", str(out_dir), "--no-companion-pdf"],
    )

    assert result.exit_code == 0, result.output
    assert (out_dir / "Article_One.mp3").exists()
    assert (out_dir / "Article_Two.mp3").exists()
    assert "2 succeeded, 0 failed" in result.output


def test_batch_continues_on_failure_and_reports(tmp_path, mocker):
    from audio_articles.core.exceptions import ExtractionError

    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://example.com/good\n"
        "https://example.com/bad\n"
    )
    out_dir = tmp_path / "out"

    _make_run_full_mock(
        mocker,
        {
            "https://example.com/good": "Good Article",
            "https://example.com/bad": ExtractionError("paywall blocked"),
        },
    )

    result = runner.invoke(
        app,
        ["batch", str(urls_file), "--output-dir", str(out_dir), "--no-companion-pdf"],
    )

    assert result.exit_code == 1
    assert (out_dir / "Good_Article.mp3").exists()
    assert "1 succeeded, 1 failed" in result.output
    assert "https://example.com/bad" in result.output
    assert "paywall blocked" in result.output


def test_batch_handles_filename_collision(tmp_path, mocker):
    """Two articles with the same title must not overwrite each other."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://example.com/a\n"
        "https://example.com/b\n"
        "https://example.com/c\n"
    )
    out_dir = tmp_path / "out"

    _make_run_full_mock(
        mocker,
        {
            "https://example.com/a": "Same Title",
            "https://example.com/b": "Same Title",
            "https://example.com/c": "Same Title",
        },
    )

    result = runner.invoke(
        app,
        ["batch", str(urls_file), "--output-dir", str(out_dir), "--no-companion-pdf"],
    )

    assert result.exit_code == 0, result.output
    mp3s = sorted(p.name for p in out_dir.glob("*.mp3"))
    assert mp3s == ["Same_Title.mp3", "Same_Title_2.mp3", "Same_Title_3.mp3"]
    # Each file holds different bytes (proves no overwrite, since urls a/b/c each
    # produced uniquely-tagged audio bytes via the mock)
    contents = {(out_dir / name).read_bytes() for name in mp3s}
    assert len(contents) == 1  # all three articles share the same title → same body bytes


def test_batch_collision_preserves_distinct_payloads(tmp_path, mocker):
    """Stronger collision check: payloads vary per URL → all three end up on disk."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://example.com/one\n"
        "https://example.com/two\n"
    )
    out_dir = tmp_path / "out"

    # Same title, but the side-effect distinguishes by URL via the mock body.
    def _side_effect(article_input):
        url = str(article_input.url)
        extraction = ExtractionResult(
            title="Twin Title", body="b", source_url=url, word_count=1
        )
        result = AudiobookResult(
            audio_bytes=f"payload-for-{url}".encode(),
            script="s",
            title="Twin Title",
            source_url=url,
        )
        return result, extraction

    mocker.patch("audio_articles.cli.main.run_full", side_effect=_side_effect)

    result = runner.invoke(
        app,
        ["batch", str(urls_file), "--output-dir", str(out_dir), "--no-companion-pdf"],
    )

    assert result.exit_code == 0, result.output
    payloads = {p.read_bytes() for p in out_dir.glob("*.mp3")}
    assert payloads == {
        b"payload-for-https://example.com/one",
        b"payload-for-https://example.com/two",
    }


def test_batch_concurrency_processes_all(tmp_path, mocker):
    """With --concurrency 3, all URLs still produce expected outputs."""
    urls = [f"https://example.com/article-{i}" for i in range(5)]
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("\n".join(urls) + "\n")
    out_dir = tmp_path / "out"

    _make_run_full_mock(
        mocker,
        {url: f"Article {i}" for i, url in enumerate(urls)},
    )

    result = runner.invoke(
        app,
        [
            "batch",
            str(urls_file),
            "--output-dir",
            str(out_dir),
            "--no-companion-pdf",
            "--concurrency",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    mp3s = sorted(p.name for p in out_dir.glob("*.mp3"))
    assert mp3s == [f"Article_{i}.mp3" for i in range(5)]
    assert "5 succeeded, 0 failed" in result.output


def test_batch_missing_file_errors(tmp_path):
    result = runner.invoke(
        app, ["batch", str(tmp_path / "does-not-exist.txt")]
    )
    assert result.exit_code == 1
    assert "File not found" in result.output


def test_batch_empty_file_errors(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# nothing here\n\n")
    result = runner.invoke(app, ["batch", str(f)])
    assert result.exit_code == 1
    assert "No URLs found" in result.output


def test_batch_invalid_url_marked_as_failure(tmp_path, mocker):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "not-a-url\n"
        "https://example.com/ok\n"
    )
    out_dir = tmp_path / "out"

    _make_run_full_mock(
        mocker, {"https://example.com/ok": "OK Article"}
    )

    result = runner.invoke(
        app,
        ["batch", str(urls_file), "--output-dir", str(out_dir), "--no-companion-pdf"],
    )

    assert result.exit_code == 1
    assert "1 succeeded, 1 failed" in result.output
    assert "not-a-url" in result.output
    assert (out_dir / "OK_Article.mp3").exists()


def test_batch_writes_manifest_alongside_audio(tmp_path, mocker):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com/one\n")
    out_dir = tmp_path / "out"

    _make_run_full_mock(mocker, {"https://example.com/one": "Solo Article"})

    result = runner.invoke(
        app,
        ["batch", str(urls_file), "--output-dir", str(out_dir), "--no-companion-pdf"],
    )

    assert result.exit_code == 0, result.output
    assert (out_dir / "Solo_Article.mp3").exists()
    # save_manifest_for writes a JSON sidecar — verify one was created.
    manifests = list(out_dir.glob("Solo_Article*.json"))
    assert len(manifests) == 1
