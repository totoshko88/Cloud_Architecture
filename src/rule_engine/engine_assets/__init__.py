"""Engine-bundled icon assets and asset-file helpers (1.10.12).

Vendor icon packs are fetched on demand into the git-ignored
``assets/vendor/`` tree and never committed. A small number of glyphs have no
vendor source at all — the provider-neutral ``education`` mortarboard is the
first (SEP feedback §2.1). Those are authored in this repository, released
under CC0 1.0, and ship inside the package here, so every workspace gets them
without hand-wiring its own SVG.

A mapping still references such an asset by its canonical workspace path
(``assets/vendor/education/mortarboard.svg``), exactly like a fetched vendor
icon. :func:`locate_asset` resolves that path: the workspace file when it
exists, else the bundled copy. Every reader of ``assets/vendor`` files (the
diagram builder's embedder, the raster exporter's inliner, the asset-path
guard) goes through it.

:func:`sniff_mime` returns the real image MIME of an asset from its bytes, so a
PNG brand mark is inlined as ``image/png`` rather than mislabelled
``image/svg+xml`` (which renders as a broken image).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Union

#: Directory holding the bundled assets (this package).
BUNDLED_ROOT = Path(__file__).resolve().parent

#: Canonical workspace path prefix → bundled directory.
BUNDLED_PREFIXES: Dict[str, Path] = {
    "assets/vendor/education/": BUNDLED_ROOT / "education",
}


def bundled_path(rel: str) -> Optional[Path]:
    """The bundled file a canonical ``assets/vendor/...`` path maps to, if any."""
    norm = rel.strip().replace("\\", "/")
    for prefix, root in BUNDLED_PREFIXES.items():
        if norm.startswith(prefix):
            tail = norm[len(prefix):]
            if not tail or ".." in tail.split("/"):
                return None
            cand = root / tail
            return cand if cand.is_file() else None
    return None


def locate_asset(rel: str, root: Union[str, Path, None] = None) -> Optional[Path]:
    """Resolve an ``assets/...`` path: ``root``/``rel`` if present, else the bundled copy.

    ``root`` defaults to the current working directory (the workspace root the
    builders and exporter read assets from). Returns ``None`` when neither
    exists.
    """
    base = Path(root) if root is not None else Path.cwd()
    cand = base / rel
    if cand.is_file():
        return cand
    return bundled_path(rel)


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def sniff_mime(data: bytes, name: str = "") -> str:
    """Return the image MIME type of ``data`` (content first, suffix fallback)."""
    head = data[:512]
    if head.startswith(_PNG_MAGIC):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    text = head.lstrip(b"\xef\xbb\xbf").lstrip().lower()
    if text.startswith((b"<svg", b"<?xml", b"<!--", b"<!doctype svg")) or b"<svg" in text:
        return "image/svg+xml"
    suffix = Path(name).suffix.lower()
    return {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix, "application/octet-stream")


__all__ = ["BUNDLED_ROOT", "BUNDLED_PREFIXES", "bundled_path", "locate_asset", "sniff_mime"]
