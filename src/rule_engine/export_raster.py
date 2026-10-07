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

    rule-engine-export-raster examples/gcp/01-gcp-vertex-pipeline.drawio
    rule-engine-export-raster --all          # every examples/**/*.drawio

This is the packaged form of the exporter (console script
``rule-engine-export-raster``); ``scripts/export_raster.py`` is a thin shim
that calls :func:`main` here, so both entry points share one implementation.

Requires the ``drawio`` CLI on PATH (draw.io desktop).

Export at scale ≥ 1 (R8.4, D8)
------------------------------
The exporter never downscales. It parses the page, measures the natural canvas
width ``W`` (the union of every vertex box), and exports at ``--scale`` clamped
to at least 1 (never below), computed as ``clamp(target / W, 1, max_width / W)``
with ``target`` 1600px (flow) / 3400px (landscape) and ``max_width`` the class
budget (1600 flow / 3600 landscape). When the canvas cannot fit its class budget
even at scale 1 (``W + 2*border > max_width``), the export **fails** with a clear
"split the diagram" error and writes no PNG — the exporter refuses to silently
downscale a too-wide diagram (D8 tightens those layouts rather than raising the
budget).

Hygiene (R8.5)
--------------
* ``subprocess.run`` is called with ``timeout=180`` so a hung draw.io CLI is
  killed rather than hanging the whole run forever; a ``TimeoutExpired`` is a
  failure, never a silent OK.
* The inlined temp copy is written to ``.build-tools/export-tmp`` (repo-local,
  so a snap/AppArmor-confined draw.io CLI can still read it — it cannot read
  ``/tmp`` — but **outside** ``examples/``) and removed in a ``finally`` block.
* A referenced ``assets/vendor`` asset that does not exist is a failure: the
  exporter raises listing the missing paths instead of exporting a broken image
  and reporting "OK".
"""

from __future__ import annotations

import argparse
import base64
import glob
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# The asset root defaults to the CURRENT WORKING DIRECTORY (the workspace a
# user runs the exporter in), NOT a repo path — the packaged console script
# has no repo checkout. ``image=assets/vendor/...`` tokens are resolved under
# this root; ``--repo-root`` / the ``repo_root`` argument override it.
ASSET_ROOT = Path.cwd()

# image=<path> where <path> is a workspace-relative asset file we must inline.
_ASSET_IMAGE_RE = re.compile(r"image=(assets/vendor/[^;\"]+)")

# Class-aware export targets and budgets (match the raster gate's class-aware
# budget in rule_engine.raster_gate). A ``flow`` diagram fits a doc column at
# 1600px; a ``landscape`` as-built needs a wider raster so 30-plus nodes stay
# legible (the reference detailed as-built exports at ~3400px). The class is
# read from the companion .diagram.md.
FLOW_TARGET_WIDTH = 1600
LANDSCAPE_TARGET_WIDTH = 3400
FLOW_MAX_WIDTH = 1600
LANDSCAPE_MAX_WIDTH = 3600

EXPORT_BORDER = "8"
EXPORT_THEME = "light"

#: Seconds before a hung draw.io CLI export is killed (R8.5).
EXPORT_TIMEOUT = 180

#: Sub-path (under the asset root) for inlined temp copies — repo-local so a
#: snap/AppArmor-confined draw.io CLI can read it (it cannot read /tmp), yet
#: OUTSIDE examples/ (R8.5).
EXPORT_TMP_SUBDIR = ".build-tools/export-tmp"


class MissingAssetError(RuntimeError):
    """Raised when a source references ``assets/vendor`` files that do not exist.

    Rather than silently leaving the broken ``image=<path>`` in place and
    exporting a placeholder glyph (then reporting "OK"), the exporter fails and
    names every missing asset (R8.5)."""

    def __init__(self, source: Path, missing: Sequence[str]) -> None:
        self.source = source
        self.missing = list(missing)
        listed = ", ".join(self.missing)
        super().__init__(f"{source}: missing referenced asset(s): {listed}")


class CanvasTooWideError(RuntimeError):
    """Raised when a diagram cannot fit its class budget at scale >= 1 (R8.4/D8).

    This is the "split the diagram" signal: the exporter refuses to downscale a
    canvas that is wider than its class budget, and writes no PNG."""

    def __init__(self, source: Path, width: float, diagram_class: str, max_width: int) -> None:
        self.source = source
        self.width = width
        self.diagram_class = diagram_class
        self.max_width = max_width
        super().__init__(
            f"{source}: canvas {int(round(width))}px exceeds the "
            f"{diagram_class} budget at scale 1 — split the diagram"
        )


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


def _diagram_background_of(source: Path) -> str:
    """Return ``raster_background`` from the .drawio's companion doc (default white).

    Any value other than ``transparent`` falls back to ``"white"`` (the safe
    default), matching the raster gate's :func:`raster_gate._diagram_background_of`
    so the exporter and the checker never disagree on the mode (Requirement 4,
    item D)."""
    companion = Path(str(source)[: -len(".drawio")] + ".diagram.md") if str(source).endswith(".drawio") else None
    if companion is None or not companion.is_file():
        return "white"
    try:
        text = companion.read_text(encoding="utf-8")
    except OSError:
        return "white"
    m = re.search(r"""^raster_background:\s*['"]?([A-Za-z_]+)['"]?\s*(?:\#.*)?$""", text, re.MULTILINE)
    if not m:
        return "white"
    return "transparent" if m.group(1).strip().lower() == "transparent" else "white"


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix in (".png",):
        return "image/png"
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def missing_assets(text: str, repo_root: Path = ASSET_ROOT) -> List[str]:
    """Return the ``assets/vendor`` paths referenced by ``text`` that do not exist.

    Every ``image=assets/vendor/...`` token whose target file is absent under
    ``repo_root`` is collected (de-duplicated, in first-seen order). An empty
    list means every referenced asset resolves."""
    seen: List[str] = []
    for match in _ASSET_IMAGE_RE.finditer(text):
        rel = match.group(1)
        if rel in seen:
            continue
        if not (repo_root / rel).is_file():
            seen.append(rel)
    return seen


def inline_local_images(text: str, repo_root: Path = ASSET_ROOT) -> str:
    """Rewrite every ``image=assets/vendor/...`` token to an inlined data URI.

    Non-asset image styles (draw.io ``img/lib`` internals, ``data:`` URIs, and
    URLs) do not match ``_ASSET_IMAGE_RE`` and are left unchanged. A referenced
    file that does not exist is left as-is here; callers detect that with
    :func:`missing_assets` and fail before export (R8.5), rather than silently
    dropping the icon.
    """

    def repl(match: re.Match) -> str:
        rel = match.group(1)
        asset = repo_root / rel
        if not asset.is_file():
            return match.group(0)
        data = base64.b64encode(asset.read_bytes()).decode("ascii")
        return f"image=data:{_mime_for(asset)},{data}"

    return _ASSET_IMAGE_RE.sub(repl, text)


def _canvas_width(source: Path) -> float:
    """Return the natural canvas width ``W`` of ``source``: the rightmost
    rendered extent, plus any extent that overflows LEFT of ``x = 0``.

    draw.io crops the export to the bounding box of everything it draws, and a
    node's caption is part of that box. Each vertex's horizontal extent is
    therefore estimated from what it renders (1.10.7, M5):

    * a cell with ``verticalLabelPosition=bottom`` and a non-empty label spans
      its centre ± ``max(w, longest_line × 7.0) / 2`` — the caption may be wider
      than the icon (``geometry.node_caption_box``'s estimator);
    * a ``text;`` cell without ``whiteSpace=wrap`` spans
      ``x .. max(x + w, x + longest_line × 7.0 × fontSize / 12)`` — unwrapped text
      runs past its box;
    * any other vertex spans ``x .. x + w``.

    ``W = max_right − min(0, min_left)``. Before 1.10.7 only the vertex boxes'
    right edge was measured, so a wide caption on a node at the left margin
    (the quick summary: caption from x = −22) grew the real export past the
    computed width and the PNG came out 1610px — over the 1600px flow budget.
    Parsed with :mod:`rule_engine.drawio_model` so this matches the geometry the
    linter and layout engine use. A page with no vertices yields 0.0.
    """
    from rule_engine.drawio_model import DrawioParseError, absolute_origin, parse_drawio
    from rule_engine.geometry import _CAPTION_TEXT_CHAR_W, caption_lines

    try:
        pages = parse_drawio(source.read_bytes(), path=str(source))
    except DrawioParseError:
        # A source we cannot parse cannot be measured. Return 0.0 so the caller
        # exports at scale 1 (never downscaling) rather than crashing — a real
        # golden always parses; this only spares degenerate/placeholder inputs.
        return 0.0
    max_right = 0.0
    min_left = 0.0
    for page in pages:
        for cell in page.cells.values():
            if not cell.vertex or cell.geom is None:
                continue
            x, _y = absolute_origin(page, cell.id)
            w = cell.geom.w or 0.0
            left, right = x, x + w
            style = cell.style_map
            longest = max((len(ln) for ln in caption_lines(cell.label)), default=0)
            if longest and style.get("verticalLabelPosition") == "bottom":
                half = max(w, longest * _CAPTION_TEXT_CHAR_W) / 2.0
                left, right = x + w / 2.0 - half, x + w / 2.0 + half
            elif longest and "text" in style and style.get("whiteSpace") != "wrap":
                try:
                    font = float(style.get("fontSize") or 12)
                except ValueError:
                    font = 12.0
                right = max(right, x + longest * _CAPTION_TEXT_CHAR_W * font / 12.0)
            max_right = max(max_right, right)
            min_left = min(min_left, left)
    return max_right - min(0.0, min_left)


def compute_scale(source: Path, diagram_class: Optional[str] = None) -> Tuple[float, float]:
    """Return ``(scale, width)`` for exporting ``source`` at scale >= 1 (R8.4).

    ``width`` is the natural canvas width ``W``. ``scale`` is
    ``clamp(target / W, 1, max_width / W)`` — never below 1, so the exporter
    never downscales. Raises :class:`CanvasTooWideError` when the canvas plus its
    two borders cannot fit the class budget at scale 1 (the "split the diagram"
    signal): in that case downscaling would be the only way to fit, which the
    exporter refuses.
    """
    dclass = diagram_class or _diagram_class_of(source)
    is_landscape = dclass == "landscape"
    target = LANDSCAPE_TARGET_WIDTH if is_landscape else FLOW_TARGET_WIDTH
    max_width = LANDSCAPE_MAX_WIDTH if is_landscape else FLOW_MAX_WIDTH

    width = _canvas_width(source)
    border = int(EXPORT_BORDER) * 2
    if width + border > max_width:
        raise CanvasTooWideError(source, width, dclass, max_width)

    if width <= 0:
        # Degenerate/empty canvas: nothing to scale up or down.
        return (1.0, width)

    # Never below 1 (no downscaling); never so large the scaled width + borders
    # exceeds the class budget.
    upper = (max_width - border) / width
    scale = max(1.0, min(target / width, upper))
    return (scale, width)


def export_one(
    source: str | Path,
    repo_root: Path = ASSET_ROOT,
    drawio: str = "drawio",
) -> Path:
    """Export ``source`` (a .drawio) to ``source + '.png'`` with icons inlined.

    Returns the output PNG path. Raises:

    * :class:`MissingAssetError` when the source references an ``assets/vendor``
      file that does not exist (R8.5) — fail rather than export a broken image;
    * :class:`CanvasTooWideError` when the canvas cannot fit its class budget at
      scale 1 (R8.4) — the "split the diagram" signal;
    * ``subprocess.CalledProcessError`` if the draw.io CLI exits non-zero;
    * ``subprocess.TimeoutExpired`` if the CLI hangs past ``EXPORT_TIMEOUT``;
    * ``FileNotFoundError`` if the CLI is absent.
    """
    source = Path(source)
    out_png = Path(str(source) + ".png")
    original = source.read_text(encoding="utf-8")

    # Fail-honest on a missing referenced asset instead of exporting a broken
    # image and reporting OK (R8.5).
    missing = missing_assets(original, repo_root)
    if missing:
        raise MissingAssetError(source, missing)

    # Scale >= 1 or refuse (R8.4/D8). Computed before touching the CLI so a
    # too-wide canvas fails without spawning draw.io or writing a temp copy.
    dclass = _diagram_class_of(source)
    scale, _width = compute_scale(source, dclass)

    inlined = inline_local_images(original, repo_root)

    tmp_dir: Optional[str] = None
    if inlined == original:
        # No local assets to inline (AWS/OCI/Azure): export the source directly.
        export_input = str(source)
    else:
        # Write the inlined copy under .build-tools/export-tmp (R8.5): repo-local
        # so a snap/AppArmor-confined draw.io CLI can read it (it cannot read
        # /tmp), yet OUTSIDE examples/ so no transient copy ever appears among
        # the published artifacts. Cleaned up in the finally block below.
        export_tmp_dir = repo_root / EXPORT_TMP_SUBDIR
        export_tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(dir=str(export_tmp_dir))
        tmp_copy = Path(tmp_dir) / f"{source.stem}.inlined.drawio"
        tmp_copy.write_text(inlined, encoding="utf-8")
        export_input = str(tmp_copy)

    # Background mode (Requirement 4, item D): a "transparent" companion exports
    # a dark/light-safe raster (alpha channel, no forced white); "white"/absent
    # keeps the existing opaque-white export unchanged (AC 4.3, 4.4).
    background = _diagram_background_of(source)
    cmd = [
        drawio, "--export", "--format", "png",
        "--scale", _format_scale(scale),
        "--border", EXPORT_BORDER,
        "--theme", EXPORT_THEME,
    ]
    if background == "transparent":
        cmd.append("--transparent")
    cmd += ["--output", str(out_png), export_input]

    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=EXPORT_TIMEOUT,
        )
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Stamp the raster with the sha256 of the *source* .drawio bytes so the
    # raster gate can detect a PNG exported from a since-edited source
    # (stale-raster, R8.2). Provenance is written with the shared helper in
    # rule_engine.raster_gate, so the exporter and checker never disagree on the
    # chunk layout.
    _stamp_provenance(out_png, source)
    return out_png


def _format_scale(scale: float) -> str:
    """Format a scale for the draw.io CLI: an integer when whole, else 3 dp."""
    if math.isclose(scale, round(scale)):
        return str(int(round(scale)))
    return f"{scale:.3f}"


def _stamp_provenance(png: Path, source: Path) -> None:
    """Insert the source .drawio sha256 into the exported PNG's tEXt chunk."""
    # Import lazily so the script still runs from a bare checkout that has not
    # installed the package on the path yet (the CLI-not-found path exits first).
    from rule_engine.raster_gate import insert_provenance, source_sha256

    digest = source_sha256(source)
    stamped = insert_provenance(png.read_bytes(), digest)
    png.write_bytes(stamped)


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
    parser.add_argument("--repo-root", default=str(ASSET_ROOT),
                        help="root under which image=assets/vendor/... paths resolve (default: CWD)")
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
        except subprocess.TimeoutExpired:
            failures += 1
            print(f"FAILED: {src} (drawio timed out after {EXPORT_TIMEOUT}s)", file=sys.stderr)
        except CanvasTooWideError as exc:
            failures += 1
            print(f"FAILED: {exc}", file=sys.stderr)
        except MissingAssetError as exc:
            failures += 1
            print(f"FAILED: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
