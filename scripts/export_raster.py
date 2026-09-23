#!/usr/bin/env python3
"""Export a .drawio to a .drawio.png within the D7 budget, embedding local icons.

Why this exists
---------------
The committed golden-example ``.drawio`` sources reference provider icons by a
**repo-relative file path** for the image-shape providers (GCP category icons
under ``assets/vendor/...``). draw.io *desktop* renders those fine, and keeping
a file path (not a base64 ``data:`` URI) in the committed source is required by
the linter — ``image=data:image/svg...`` trips the ``icon-resolved`` rule.

But the **headless draw.io CLI** refuses to load local files during export
(Electron: ``Blocked loading file from file://...``), so every ``assets/vendor``
file-path icon renders as the default placeholder glyph in the exported PNG.
(AWS uses built-in ``mxgraph.aws4.*`` stencils and OCI embeds its stencils, so
neither is affected; Azure uses draw.io-internal ``img/lib/azure2`` shapes that
ship inside draw.io itself, so it renders too. Only the GCP ``assets/vendor``
file paths are blocked.)

This script bridges that gap deterministically: it reads the source, rewrites
each ``image=<repo-relative asset path>`` into an inlined
``image=data:image/svg+xml,<base64>`` in a **temporary copy only**, and runs the
draw.io CLI on that copy to produce the final ``.drawio.png``. The committed
source keeps its lint-clean file paths; the exported raster shows the real
icons. Only ``assets/vendor/...`` paths are inlined — ``data:`` URIs,
draw.io-internal ``img/lib`` references, and URLs are left untouched.

Usage::

    python scripts/export_raster.py examples/gcp/01-gcp-vertex-pipeline.drawio
    python scripts/export_raster.py --all          # every examples/**/*.drawio

Requires the ``drawio`` CLI on PATH (draw.io desktop). Exports at
``--width 1200 --border 8 --theme light`` to meet the Raster Export Dimensions
budget (≤ 1200px wide, < 500KB, white background, 8px padding).
"""

from __future__ import annotations

import argparse
import base64
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

# image=<path> where <path> is a repo-relative asset file we must inline.
_ASSET_IMAGE_RE = re.compile(r"image=(assets/vendor/[^;\"]+)")

# Class-aware export width (matches the raster gate's class-aware budget). A
# ``flow`` diagram fits a doc column at 1200px; a ``landscape`` as-built needs a
# wider raster so 30-plus nodes stay legible (the reference detailed as-built
# exports at ~3400px). The class is read from the companion .diagram.md.
EXPORT_WIDTH = "1600"
LANDSCAPE_EXPORT_WIDTH = "3400"
EXPORT_BORDER = "8"
EXPORT_THEME = "light"


def _diagram_class_of(source: Path) -> str:
    """Return ``diagram_class`` from the .drawio's companion doc (default flow)."""
    companion = Path(str(source)[: -len(".drawio")] + ".diagram.md") if str(source).endswith(".drawio") else None
    if companion is None or not companion.is_file():
        return "flow"
    try:
        text = companion.read_text(encoding="utf-8")
    except OSError:
        return "flow"
    m = re.search(r"^diagram_class:\s*([A-Za-z_]+)\s*$", text, re.MULTILINE)
    return m.group(1).strip().lower() if m else "flow"


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix in (".png",):
        return "image/png"
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def inline_local_images(text: str, repo_root: Path = REPO_ROOT) -> str:
    """Rewrite every ``image=assets/vendor/...`` token to an inlined data URI.

    Non-asset image styles (draw.io ``img/lib`` internals, ``data:`` URIs, and
    URLs) do not match ``_ASSET_IMAGE_RE`` and are left unchanged. A referenced
    file that does not exist is left as-is so the export surfaces the problem
    rather than silently dropping the icon.
    """

    def repl(match: re.Match) -> str:
        rel = match.group(1)
        asset = repo_root / rel
        if not asset.is_file():
            return match.group(0)
        data = base64.b64encode(asset.read_bytes()).decode("ascii")
        return f"image=data:{_mime_for(asset)},{data}"

    return _ASSET_IMAGE_RE.sub(repl, text)


def export_one(
    source: str | Path,
    repo_root: Path = REPO_ROOT,
    drawio: str = "drawio",
) -> Path:
    """Export ``source`` (a .drawio) to ``source + '.png'`` with icons inlined.

    Returns the output PNG path. Raises ``subprocess.CalledProcessError`` if the
    draw.io CLI exits non-zero, and ``FileNotFoundError`` if the CLI is absent.
    """
    source = Path(source)
    out_png = Path(str(source) + ".png")
    original = source.read_text(encoding="utf-8")
    inlined = inline_local_images(original, repo_root)
    width = LANDSCAPE_EXPORT_WIDTH if _diagram_class_of(source) == "landscape" else EXPORT_WIDTH

    if inlined == original:
        # No local assets to inline (AWS/OCI/Azure): export the source directly.
        export_input = str(source)
        tmp: Optional[str] = None
    else:
        fd, tmp = tempfile.mkstemp(suffix=".drawio")
        os.close(fd)
        Path(tmp).write_text(inlined, encoding="utf-8")
        export_input = tmp

    try:
        subprocess.run(
            [
                drawio, "--export", "--format", "png",
                "--width", width,
                "--border", EXPORT_BORDER,
                "--theme", EXPORT_THEME,
                "--output", str(out_png),
                export_input,
            ],
            check=True,
        )
    finally:
        if tmp:
            os.unlink(tmp)
    return out_png


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export_raster",
        description="Export .drawio to .drawio.png with local icons inlined (D7 budget).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("sources", nargs="*", default=[],
                       help="one or more .drawio files to export")
    group.add_argument("--all", action="store_true",
                       help="export every examples/**/*.drawio")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--drawio", default="drawio",
                        help="path to the draw.io CLI (default: 'drawio' on PATH)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(args.repo_root)

    if shutil.which(args.drawio) is None and not Path(args.drawio).exists():
        print(f"error: draw.io CLI '{args.drawio}' not found on PATH", file=sys.stderr)
        return 2

    if args.all:
        sources: List[str] = sorted(
            glob.glob(str(repo_root / "examples" / "**" / "*.drawio"), recursive=True)
        )
    else:
        sources = args.sources

    if not sources:
        print("error: no .drawio sources to export", file=sys.stderr)
        return 2

    failures = 0
    for src in sources:
        try:
            out = export_one(src, repo_root, args.drawio)
            size_kb = out.stat().st_size // 1024
            print(f"OK: {os.path.relpath(out, repo_root)} ({size_kb}KB)")
        except subprocess.CalledProcessError as exc:
            failures += 1
            print(f"FAILED: {src} (drawio exit {exc.returncode})", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
