"""Sidecar JSON written next to every generated audio file.

Pairs an MP3 with its companion PDF (when one was generated) and records the
source URL so the library page can show provenance. Existence is optional —
older files without a manifest still appear in the library, just without
extra metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class ArticleManifest(BaseModel):
    title: str
    source_url: str | None = None
    audio_filename: str
    pdf_filename: str | None = None
    generated_at: str
    word_count: int


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def manifest_path_for_stem(output_dir: Path, stem: str) -> Path:
    return output_dir / f"{stem}.json"


def write_manifest(manifest: ArticleManifest, output_dir: Path, stem: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path_for_stem(output_dir, stem)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_manifest(output_dir: Path, stem: str) -> ArticleManifest | None:
    path = manifest_path_for_stem(output_dir, stem)
    if not path.exists():
        return None
    try:
        return ArticleManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — manifest is best-effort metadata
        return None
