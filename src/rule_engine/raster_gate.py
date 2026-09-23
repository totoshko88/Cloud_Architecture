"""Raster gate — enforce the exported ``.drawio.png`` budget (REVIEW.md D7).

The diagram standards (``.kiro/steering/diagram-standards.md`` → *Raster Export
Dimensions*) define a budget for every exported ``NN-topic.drawio.png``:

* width  ≤ **1200px** (fits documentation columns without horizontal scroll),
* file size < **500KB** (fast page loads; avoids bloating the repo).

The linter deliberately evaluates the ``.drawio`` source and the companion
document, **not** the rendered PNG's pixel dimensions or byte size — so nothing
in the lint path catches a raster that was exported too wide or too heavy (for
example the OCI example that was once 3485px wide). This guard closes that gap:
it reads each PNG's real width from the file header and its size from the
filesystem and fails when either exceeds the budget.

Dependency-free by design: PNG width/height live in the IHDR chunk as two
big-endian uint32s right after the 8-byte signature and the ``IHDR`` length +
type, so the width is read directly from the first 24 bytes — no Pillow (the
engine keeps runtime deps to ``jsonschema`` + ``PyYAML``).

Fetch-/export-awareness:

* :func:`check_rasters` reports every ``.drawio`` whose ``.drawio.png`` is
  present together with its measured width and size. A ``.drawio`` with **no**
  matching ``.drawio.png`` is reported as a missing raster.
* The CLI exit policy mirrors ``asset_paths_guard``: a raster that breaches the
  width or size budget is a hard failure (exit 1); a ``.drawio`` with no
  exported PNG at all is reported and (by default) also fails, since the
  standards require the full artifact triple. ``--allow-missing`` downgrades a
  missing PNG to a skip (exit 0) for environments where the raster export step
  has not run yet.
"""

from __future__ import annotations

import argparse
import glob
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

# Budget from diagram-standards.md → Raster Export Dimensions.
MAX_WIDTH_PX = 1200
MAX_SIZE_BYTES = 500 * 1024  # 500KB

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE = 2


class RasterReadError(Exception):
    """Raised when a file is not a readable PNG (bad signature / truncated)."""


@dataclass
class RasterRef:
    """One exported raster measured against the budget."""

    source: str            # the .drawio source path, relative to repo root
    png: str               # the .drawio.png path, relative to repo root
    exists: bool           # whether the PNG file exists
    width: Optional[int]   # measured pixel width (None when absent/unreadable)
    size_bytes: Optional[int]  # file size in bytes (None when absent)

    @property
    def width_ok(self) -> bool:
        return self.width is not None and self.width <= MAX_WIDTH_PX

    @property
    def size_ok(self) -> bool:
        return self.size_bytes is not None and self.size_bytes <= MAX_SIZE_BYTES

    @property
    def within_budget(self) -> bool:
        return self.exists and self.width_ok and self.size_ok


def read_png_width(path: str | Path) -> int:
    """Return the pixel width of a PNG by reading its IHDR chunk.

    Raises :class:`RasterReadError` when the file does not start with the PNG
    signature or is too short to contain an IHDR width field.
    """
    path = Path(path)
    with path.open("rb") as fh:
        header = fh.read(24)
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE:
        raise RasterReadError(f"{path} is not a valid PNG (bad signature)")
    # Bytes 8..16 are the IHDR length (4) + chunk type "IHDR" (4); bytes 16..20
    # are the width as a big-endian unsigned 32-bit int.
    if header[12:16] != b"IHDR":
        raise RasterReadError(f"{path} has no IHDR chunk where expected")
    (width,) = struct.unpack(">I", header[16:20])
    return width


def check_rasters(
    examples_dir: str | Path,
    repo_root: str | Path = REPO_ROOT,
) -> List[RasterRef]:
    """Return a :class:`RasterRef` for every ``.drawio`` under ``examples_dir``.

    For each ``NN-topic.drawio`` the matching ``NN-topic.drawio.png`` is measured
    (width from the PNG header, size from the filesystem). A source with no
    exported PNG yields a ref with ``exists=False``.
    """
    examples_dir = Path(examples_dir)
    repo_root = Path(repo_root)
    refs: List[RasterRef] = []
    for src in sorted(glob.glob(str(examples_dir / "**" / "*.drawio"), recursive=True)):
        png = src + ".png"
        rel_src = os.path.relpath(src, repo_root)
        rel_png = os.path.relpath(png, repo_root)
        if not os.path.isfile(png):
            refs.append(RasterRef(rel_src, rel_png, False, None, None))
            continue
        size = os.path.getsize(png)
        try:
            width: Optional[int] = read_png_width(png)
        except RasterReadError:
            width = None
        refs.append(RasterRef(rel_src, rel_png, True, width, size))
    return refs


def _fmt(ref: RasterRef) -> str:
    w = "?" if ref.width is None else f"{ref.width}px"
    kb = "?" if ref.size_bytes is None else f"{ref.size_bytes // 1024}KB"
    return f"{ref.png} ({w}, {kb})"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for the CI raster gate.

    Usage::

        python -m rule_engine.raster_gate [--examples DIR] [--repo-root DIR]
                                           [--allow-missing]

    Exit codes:
      0  every exported raster is within the width/size budget (missing PNGs
         only tolerated with ``--allow-missing``).
      1  a raster breaches the width or size budget, or a PNG is missing
         (without ``--allow-missing``).
      2  usage error.
    """
    parser = argparse.ArgumentParser(
        prog="raster-gate",
        description="Enforce the exported .drawio.png width/size budget (D7).",
    )
    parser.add_argument("--examples", default=str(REPO_ROOT / "examples"))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="treat a .drawio with no exported .png as a skip, not a failure",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    refs = check_rasters(args.examples, args.repo_root)
    if not refs:
        print(f"raster-gate: no .drawio sources found under {args.examples}.")
        return EXIT_OK

    missing = [r for r in refs if not r.exists]
    present = [r for r in refs if r.exists]
    over_width = [r for r in present if not r.width_ok]
    over_size = [r for r in present if not r.size_ok]
    unreadable = [r for r in present if r.width is None]

    failed = False

    if over_width:
        failed = True
        print(
            f"BLOCKING: raster(s) exceed the {MAX_WIDTH_PX}px width budget:",
            file=sys.stderr,
        )
        for r in over_width:
            print(f"    - {_fmt(r)}", file=sys.stderr)

    if over_size:
        failed = True
        print(
            f"BLOCKING: raster(s) exceed the {MAX_SIZE_BYTES // 1024}KB size budget:",
            file=sys.stderr,
        )
        for r in over_size:
            print(f"    - {_fmt(r)}", file=sys.stderr)

    if unreadable:
        failed = True
        print("BLOCKING: raster(s) are not readable PNGs:", file=sys.stderr)
        for r in unreadable:
            print(f"    - {r.png}", file=sys.stderr)

    if missing:
        if args.allow_missing:
            for r in missing:
                print(
                    f"raster-gate: {r.source} has no exported {r.png}; "
                    "skipping (--allow-missing).",
                )
        else:
            failed = True
            print(
                "BLOCKING: .drawio source(s) have no exported .drawio.png "
                "(export the raster or pass --allow-missing):",
                file=sys.stderr,
            )
            for r in missing:
                print(f"    - {r.source} -> {r.png}", file=sys.stderr)

    if failed:
        print(
            "Re-export the raster within budget: "
            "drawio --export --format png --width 1200 --border 8 --theme light "
            "--output <file>.drawio.png <file>.drawio",
            file=sys.stderr,
        )
        return EXIT_OVER_BUDGET

    print(
        f"OK: all {len(present)} exported raster(s) are within the "
        f"{MAX_WIDTH_PX}px / {MAX_SIZE_BYTES // 1024}KB budget."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
