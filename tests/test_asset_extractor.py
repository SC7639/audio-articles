"""Tests for asset_extractor — code/figure capture and reference-marker injection."""

import base64
import io

from PIL import Image

from audio_articles.core.asset_extractor import extract_assets


def _png_bytes(width: int = 300, height: int = 300, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_code_blocks_captured_with_language(tmp_path):
    html = """
    <article>
      <p>Intro paragraph.</p>
      <pre><code class="language-python">def foo():\n    return 42</code></pre>
      <p>Middle.</p>
      <pre><code class="lang-bash">echo hello</code></pre>
      <p>End.</p>
    </article>
    """
    assets, marker_html = extract_assets(html, base_url="https://example.com", output_dir=tmp_path)

    assert [b.language for b in assets.code_blocks] == ["python", "bash"]
    assert "def foo()" in assets.code_blocks[0].content
    assert "echo hello" in assets.code_blocks[1].content
    assert "(See code block 1 in the companion PDF.)" in marker_html
    assert "(See code block 2 in the companion PDF.)" in marker_html
    assert "<pre>" not in marker_html


def test_pre_without_language_class(tmp_path):
    html = "<article><pre>plain text</pre></article>"
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.code_blocks) == 1
    assert assets.code_blocks[0].language is None
    assert "(See code block 1 in the companion PDF.)" in marker_html


def test_figure_with_image_and_caption(tmp_path, mocker):
    mocker.patch(
        "audio_articles.core.asset_extractor._fetch_image_bytes",
        return_value=_png_bytes(),
    )
    html = """
    <article>
      <figure>
        <img src="/assets/diagram.png" alt="A test diagram">
        <figcaption>System overview</figcaption>
      </figure>
    </article>
    """
    assets, marker_html = extract_assets(
        html, base_url="https://example.com/post", output_dir=tmp_path
    )
    assert len(assets.images) == 1
    img = assets.images[0]
    assert img.alt_text == "A test diagram"
    assert img.caption == "System overview"
    assert (tmp_path / img.local_filename).exists()
    assert "(See figure 1 in the companion PDF.)" in marker_html
    assert "<figure>" not in marker_html


def test_standalone_image(tmp_path, mocker):
    mocker.patch(
        "audio_articles.core.asset_extractor._fetch_image_bytes",
        return_value=_png_bytes(),
    )
    html = (
        '<article><p>Before.</p>'
        '<img src="https://cdn.example.com/x.png" alt="loose"/>'
        '<p>After.</p></article>'
    )
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.images) == 1
    assert assets.images[0].alt_text == "loose"
    assert "(See figure 1 in the companion PDF.)" in marker_html


def test_small_image_is_skipped(tmp_path, mocker):
    mocker.patch(
        "audio_articles.core.asset_extractor._fetch_image_bytes",
        return_value=_png_bytes(width=50, height=50),
    )
    html = '<article><img src="bug.png"/></article>'
    assets, marker_html = extract_assets(
        html, base_url="https://example.com", output_dir=tmp_path
    )
    assert len(assets.images) == 0
    assert "<img" not in marker_html
    assert "See figure" not in marker_html


def test_failed_image_fetch_drops_silently(tmp_path, mocker):
    mocker.patch(
        "audio_articles.core.asset_extractor._fetch_image_bytes",
        return_value=None,
    )
    html = '<article><img src="dead-link.png"/></article>'
    assets, marker_html = extract_assets(
        html, base_url="https://example.com", output_dir=tmp_path
    )
    assert assets.images == []
    assert "<img" not in marker_html


def test_data_uri_image_decoded_inline(tmp_path):
    png = _png_bytes()
    data_uri = "data:image/png;base64," + base64.b64encode(png).decode()
    html = f'<article><img src="{data_uri}" alt="inline"/></article>'
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.images) == 1
    assert assets.images[0].alt_text == "inline"
    assert (tmp_path / assets.images[0].local_filename).exists()
    assert "(See figure 1 in the companion PDF.)" in marker_html


def test_inline_svg_preserved_as_file(tmp_path):
    html = (
        '<article><svg width="300" height="300" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="50" cy="50" r="40" fill="blue"/></svg></article>'
    )
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.images) == 1
    assert assets.images[0].is_svg is True
    saved = tmp_path / assets.images[0].local_filename
    assert saved.exists()
    assert "<circle" in saved.read_text()
    assert "(See figure 1 in the companion PDF.)" in marker_html


def test_figure_prefers_img_over_decorative_svg_icon(tmp_path, mocker):
    """Substack wraps each image in <figure> with the real <img> alongside tiny
    <svg> toolbar icons. The <img> must win — the icon must not become the asset."""
    mocker.patch(
        "audio_articles.core.asset_extractor._fetch_image_bytes",
        return_value=_png_bytes(),
    )
    html = """
    <article>
      <figure>
        <a href="https://cdn.example.com/diagram.png">
          <img src="https://cdn.example.com/diagram.png" alt="The actual diagram"/>
        </a>
        <svg width="20" height="20" role="img"><path d="M0 0"/></svg>
        <svg width="20" height="20" role="img"><path d="M0 0"/></svg>
        <figcaption>Real diagram caption</figcaption>
      </figure>
    </article>
    """
    assets, marker_html = extract_assets(
        html, base_url="https://example.com/post", output_dir=tmp_path
    )
    assert len(assets.images) == 1
    img = assets.images[0]
    assert img.is_svg is False  # the <img>, not the icon
    assert img.alt_text == "The actual diagram"
    assert img.caption == "Real diagram caption"
    assert "(See figure 1 in the companion PDF.)" in marker_html


def test_standalone_tiny_svg_is_filtered(tmp_path):
    """20×20 SVG icons floating outside <figure> shouldn't become 'figures' either."""
    html = (
        '<article>'
        '<svg width="20" height="20" role="img"><path d="M0 0"/></svg>'
        '<p>Real text content.</p>'
        '<svg width="600" height="400"><rect width="100%" height="100%"/></svg>'
        '</article>'
    )
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    # Only the 600×400 SVG survives the size filter
    assert len(assets.images) == 1
    assert assets.images[0].is_svg is True
    # Exactly one figure marker present, not two
    assert marker_html.count("(See figure 1 in the companion PDF.)") == 1
    assert "(See figure 2" not in marker_html


def test_svg_without_dimensions_is_kept(tmp_path):
    """A real diagram SVG using viewBox only (no width/height attrs) shouldn't be filtered."""
    html = (
        '<article><svg viewBox="0 0 800 600"><circle cx="400" cy="300" r="100"/></svg></article>'
    )
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.images) == 1


def test_figure_with_svg_and_caption(tmp_path):
    html = """
    <article>
      <figure>
        <svg width="300" height="300"><rect width="100%" height="100%"/></svg>
        <figcaption>Block diagram</figcaption>
      </figure>
    </article>
    """
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.images) == 1
    assert assets.images[0].is_svg is True
    assert assets.images[0].caption == "Block diagram"
    assert "(See figure 1 in the companion PDF.)" in marker_html


def test_marker_numbering_is_per_kind_and_in_order(tmp_path, mocker):
    mocker.patch(
        "audio_articles.core.asset_extractor._fetch_image_bytes",
        return_value=_png_bytes(),
    )
    html = """
    <article>
      <pre><code>code A</code></pre>
      <img src="/a.png" alt="img A"/>
      <pre><code>code B</code></pre>
      <img src="/b.png" alt="img B"/>
    </article>
    """
    assets, marker_html = extract_assets(
        html, base_url="https://example.com", output_dir=tmp_path
    )
    assert [b.content for b in assets.code_blocks] == ["code A", "code B"]
    assert [i.alt_text for i in assets.images] == ["img A", "img B"]
    for n in (1, 2):
        assert f"(See code block {n} in the companion PDF.)" in marker_html
        assert f"(See figure {n} in the companion PDF.)" in marker_html


def test_empty_pre_is_ignored(tmp_path):
    html = "<article><pre></pre><pre><code>real code</code></pre></article>"
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert len(assets.code_blocks) == 1
    assert assets.code_blocks[0].content == "real code"


def test_no_assets_returns_empty(tmp_path):
    html = "<article><p>Just text. No code or images.</p></article>"
    assets, marker_html = extract_assets(html, base_url=None, output_dir=tmp_path)
    assert assets.is_empty
    assert "Just text" in marker_html
