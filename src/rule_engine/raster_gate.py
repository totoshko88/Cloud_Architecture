"""Raster gate — enforce the exported ``.drawio.png`` budget (REVIEW.md D7).

The diagram standards (``.kiro/steering/diagram-standards.md`` → *Raster Export
Dimensions*) define a budget for every exported ``NN-topic.drawio.png``:

* width  ≤ **1600px** for a ``flow`` diagram / ≤ **3600px** for a ``landscape``,
* file size < **500KB** (flow) / < **2MB** (landscape); fast page loads.

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
import hashlib
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The tEXt chunk keyword the exporter writes and the checker verifies. Its value
#: is the hex sha256 of the source ``.drawio`` bytes at export time, so a raster
#: exported from a since-edited source is caught as ``stale-raster`` (R8.2).
PROVENANCE_KEY = "rule-engine:source-sha256"


def _default_workspace_root() -> Path:
    """Return the workspace root whose ``examples/`` this gate should check (v1.5.1).

    The raster gate operates on a WORKSPACE's exported diagrams, not on package
    data. On a pip/Power install ``parents[2]`` is NOT the repo root, so prefer
    the current directory when it looks like a workspace (it has an ``examples/``
    tree); otherwise fall back to ``REPO_ROOT`` (the dev / repo-checkout case).
    """
    cwd = Path.cwd()
    if (cwd / "examples").is_dir():
        return cwd
    return REPO_ROOT


# Budget from diagram-standards.md → Raster Export Dimensions.
#
# Class-aware (v1.3.x). A ``flow`` diagram fits a documentation column, so its
# raster stays small (≤ 1600px / < 500KB). A ``landscape`` as-built exists to
# show a whole system on one canvas; forcing it into the flow width shrinks 30-plus
# nodes until the icons are illegible (the exact defect the audit surfaced —
# the reference detailed as-built exports at ~3400px). The landscape budget is
# therefore wider and heavier, matching the reference; readability at that width
# is held by the container/padding/overlap/direction rules, not by a narrow cap.
# The flow width (1600px) is a touch wider than a single doc column so a wide
# summary (DNS fan-out across two regions) stays legible; a landscape needs far
# more room still.
MAX_WIDTH_PX = 1600
MAX_SIZE_BYTES = 500 * 1024  # 500KB

LANDSCAPE_MAX_WIDTH_PX = 3600
LANDSCAPE_MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2MB

# Height ceiling per class (R8.3). The class height ceiling mirrors the width
# ceiling — flow 1600px, landscape 3600px — so an export that is within its
# width budget but ran away vertically is still caught.
MAX_HEIGHT_PX = 1600
LANDSCAPE_MAX_HEIGHT_PX = 3600

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _diagram_class_of(source: str | Path) -> str:
    """Return the diagram class declared in a ``.drawio``'s companion doc.

    Reads ``diagram_class`` from the sibling ``NN-topic.diagram.md`` YAML
    frontmatter; defaults to ``"flow"`` when the companion or the key is absent,
    so every pre-1.3.0 artifact keeps the narrow flow budget."""
    src = Path(source)
    companion = Path(str(src)[: -len(".drawio")] + ".diagram.md") if str(src).endswith(".drawio") else None
    if companion is None or not companion.is_file():
        return "flow"
    try:
        text = companion.read_text(encoding="utf-8")
    except OSError:
        return "flow"
    # Tolerate a quoted value (``diagram_class: "landscape"`` / ``'landscape'``)
    # and a trailing ``# comment`` — a bare ``[A-Za-z_]+`` match would miss the
    # quoted form and silently fall back to the flow budget, then wrongly fail a
    # legitimately-wide landscape. Kept as a small regex so the gate stays
    # dependency-free (stdlib only, no PyYAML).
    m = re.search(
        r"""^diagram_class:\s*['"]?([A-Za-z_]+)['"]?\s*(?:\#.*)?$""",
        text,
        re.MULTILINE,
    )
    return m.group(1).strip().lower() if m else "flow"

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE = 2


class RasterReadError(Exception):
    """Raised when a file is not a readable PNG (bad signature / truncated)."""


@dataclass
class RasterRef:
    """One exported raster measured against its class-aware budget."""

    source: str            # the .drawio source path, relative to repo root
    png: str               # the .drawio.png path, relative to repo root
    exists: bool           # whether the PNG file exists
    width: Optional[int]   # measured pixel width (None when absent/unreadable)
    size_bytes: Optional[int]  # file size in bytes (None when absent)
    diagram_class: str = "flow"  # "flow" (narrow budget) or "landscape" (wide)
    height: Optional[int] = None       # measured pixel height (None when absent)
    color_type: Optional[int] = None   # PNG colour type from IHDR
    has_trns: bool = False             # a tRNS (transparency) chunk is present
    provenance: Optional[str] = None   # source sha256 recorded in the PNG tEXt
    source_sha256: Optional[str] = None  # sha256 of the current source .drawio
    row0_all_white: Optional[bool] = None  # first row opaque white (None: unknown)

    @property
    def max_width(self) -> int:
        return LANDSCAPE_MAX_WIDTH_PX if self.diagram_class == "landscape" else MAX_WIDTH_PX

    @property
    def max_size(self) -> int:
        return LANDSCAPE_MAX_SIZE_BYTES if self.diagram_class == "landscape" else MAX_SIZE_BYTES

    @property
    def max_height(self) -> int:
        return LANDSCAPE_MAX_HEIGHT_PX if self.diagram_class == "landscape" else MAX_HEIGHT_PX

    @property
    def width_ok(self) -> bool:
        return self.width is not None and self.width <= self.max_width

    @property
    def size_ok(self) -> bool:
        return self.size_bytes is not None and self.size_bytes <= self.max_size

    @property
    def height_ok(self) -> bool:
        return self.height is not None and self.height <= self.max_height

    @property
    def provenance_ok(self) -> bool:
        """True when the recorded provenance matches the current source sha256.

        A missing provenance chunk (None) or a mismatch is a stale raster: the
        PNG was exported from a source that has since changed (or from no
        recorded source at all), so it may not reflect the committed ``.drawio``.
        """
        return (
            self.provenance is not None
            and self.source_sha256 is not None
            and self.provenance == self.source_sha256
        )

    @property
    def background_ok(self) -> bool:
        """True when the raster is an opaque white-background PNG.

        Requires colour type 0 (grayscale) or 2 (truecolour) — i.e. no alpha
        channel — with no ``tRNS`` chunk, and a first scanline that is entirely
        white. ``row0_all_white is None`` means the row could not be
        reconstructed, which is treated as not-OK (fail closed)."""
        return (
            self.color_type in (0, 2)
            and not self.has_trns
            and self.row0_all_white is True
        )

    @property
    def within_budget(self) -> bool:
        return (
            self.exists
            and self.width_ok
            and self.size_ok
            and self.height_ok
            and self.provenance_ok
            and self.background_ok
        )


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


# --------------------------------------------------------------------------- #
# PNG chunk parsing + provenance                                              #
# --------------------------------------------------------------------------- #
#
# The gate needs more than the width now (R8.2/R8.3): the tEXt provenance chunk
# (source sha256), the IHDR height and colour type, whether a tRNS chunk is
# present, and the reconstructed first scanline for the white-background check.
# All of it comes from parsing the chunk stream directly — still dependency-free
# (no Pillow), stdlib ``struct`` + ``zlib`` only.


def _iter_png_chunks(data: bytes) -> List[Tuple[bytes, bytes]]:
    """Return ``[(type, data), …]`` for every chunk in ``data``.

    Raises :class:`RasterReadError` on a bad signature or a truncated chunk.
    """
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        raise RasterReadError("not a valid PNG (bad signature)")
    chunks: List[Tuple[bytes, bytes]] = []
    pos = 8
    n = len(data)
    while pos + 8 <= n:
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        start = pos + 8
        end = start + length
        if end + 4 > n:
            raise RasterReadError(f"truncated PNG chunk {ctype!r}")
        chunks.append((ctype, data[start:end]))
        pos = end + 4  # skip the 4-byte CRC
        if ctype == b"IEND":
            break
    return chunks


def insert_provenance(png_bytes: bytes, digest: str) -> bytes:
    """Return ``png_bytes`` with a ``rule-engine:source-sha256`` tEXt chunk.

    The chunk is inserted immediately before ``IEND`` (any existing provenance
    chunk with the same keyword is dropped first, so re-inserting is
    idempotent). ``digest`` is the hex sha256 of the source ``.drawio``. This is
    the single writer of the provenance chunk, shared by the exporter
    (``scripts/export_raster.py``) and used symmetrically by the checker below,
    so the two never disagree on the chunk layout.
    """
    chunks = _iter_png_chunks(png_bytes)
    text = PROVENANCE_KEY.encode("latin-1") + b"\x00" + digest.encode("latin-1")
    prov = _png_chunk(b"tEXt", text)
    out = bytearray(_PNG_SIGNATURE)
    inserted = False
    for ctype, cdata in chunks:
        if ctype == b"tEXt" and cdata.split(b"\x00", 1)[0] == PROVENANCE_KEY.encode("latin-1"):
            continue  # drop a stale provenance chunk; we rewrite it
        if ctype == b"IEND" and not inserted:
            out += prov
            inserted = True
        out += _png_chunk(ctype, cdata)
    if not inserted:
        # No IEND encountered (malformed input); append provenance then IEND.
        out += prov
        out += _png_chunk(b"IEND", b"")
    return bytes(out)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    """Serialize one PNG chunk: length + type + data + CRC32(type+data)."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def read_provenance(png_bytes: bytes) -> Optional[str]:
    """Return the source sha256 from the provenance tEXt chunk, or None."""
    key = PROVENANCE_KEY.encode("latin-1")
    for ctype, cdata in _iter_png_chunks(png_bytes):
        if ctype == b"tEXt":
            k, _, v = cdata.partition(b"\x00")
            if k == key:
                return v.decode("latin-1")
    return None


def _paeth(a: int, b: int, c: int) -> int:
    """PNG Paeth predictor."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _reconstruct_row0(idat: bytes, width: int, channels: int) -> Optional[bytes]:
    """Reconstruct the first scanline's raw samples from the IDAT stream.

    Row 0 has no previous row, so the Up/Average/Paeth predictors reference an
    all-zero row. Returns the ``width * channels`` reconstructed sample bytes, or
    None when the stream is too short / undecodable.
    """
    try:
        raw = zlib.decompress(idat)
    except zlib.error:
        return None
    stride = width * channels
    if len(raw) < 1 + stride:
        return None
    filter_byte = raw[0]
    row = raw[1 : 1 + stride]
    out = bytearray(stride)
    for i in range(stride):
        x = row[i]
        a = out[i - channels] if i >= channels else 0  # left
        b = 0  # up (previous row is all zero for row 0)
        c = 0  # upper-left
        if filter_byte == 0:      # None
            out[i] = x & 0xFF
        elif filter_byte == 1:    # Sub
            out[i] = (x + a) & 0xFF
        elif filter_byte == 2:    # Up
            out[i] = (x + b) & 0xFF
        elif filter_byte == 3:    # Average
            out[i] = (x + ((a + b) >> 1)) & 0xFF
        elif filter_byte == 4:    # Paeth
            out[i] = (x + _paeth(a, b, c)) & 0xFF
        else:
            return None
    return bytes(out)


@dataclass
class RasterFacts:
    """Everything the gate needs from a PNG beyond width (R8.2/R8.3)."""

    height: Optional[int] = None
    color_type: Optional[int] = None
    has_trns: bool = False
    provenance: Optional[str] = None       # source sha256 recorded in the PNG
    row0_all_white: Optional[bool] = None  # None when it could not be reconstructed


def read_png_facts(path: str | Path) -> RasterFacts:
    """Parse ``path`` and return its height, colour type, tRNS, provenance and
    a reconstructed-first-row white-background verdict.

    Raises :class:`RasterReadError` on a non-PNG / truncated file.
    """
    data = Path(path).read_bytes()
    chunks = _iter_png_chunks(data)
    facts = RasterFacts()
    idat = bytearray()
    width = 0
    for ctype, cdata in chunks:
        if ctype == b"IHDR":
            if len(cdata) < 10:
                raise RasterReadError("truncated IHDR")
            width, height = struct.unpack(">II", cdata[:8])
            facts.height = height
            facts.color_type = cdata[9]
        elif ctype == b"tRNS":
            facts.has_trns = True
        elif ctype == b"tEXt":
            k, _, v = cdata.partition(b"\x00")
            if k == PROVENANCE_KEY.encode("latin-1"):
                facts.provenance = v.decode("latin-1")
        elif ctype == b"IDAT":
            idat += cdata
    if facts.color_type is not None and idat and width:
        channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(facts.color_type)
        if channels is not None:
            row0 = _reconstruct_row0(bytes(idat), width, channels)
            if row0 is not None:
                # Opaque white: every colour sample of the first pixel is 0xFF.
                # (For gray colour types one sample; for RGB three.) We check the
                # whole first pixel's colour channels.
                colour_channels = {0: 1, 2: 3, 4: 1, 6: 3}[facts.color_type]
                facts.row0_all_white = all(
                    b == 0xFF for b in row0[:colour_channels]
                )
    return facts


def source_sha256(path: str | Path) -> str:
    """Return the hex sha256 of a source ``.drawio`` file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    # Scratch/editor duplicates ("… копія", "… copy", "… (2)") are working
    # drafts, not publishable artifacts — the linter's discover_artifacts skips
    # them, and the raster gate uses the same exclusion so a hand-edited copy
    # does not fail the triple/PNG check.
    # Preserved ``-reference`` snapshots (frozen comparison baselines) are
    # likewise excluded from the raster gate: like scratch copies, they are not
    # publishable golden artifacts, so a reference triple must not fail the
    # triple/PNG budget check nor be treated as a diagram to regenerate.
    from rule_engine.cli import _is_reference_artifact, _is_scratch_copy
    for src in sorted(glob.glob(str(examples_dir / "**" / "*.drawio"), recursive=True)):
        base = os.path.basename(src)
        if _is_scratch_copy(base) or _is_reference_artifact(base):
            continue
        png = src + ".png"
        rel_src = os.path.relpath(src, repo_root)
        rel_png = os.path.relpath(png, repo_root)
        dclass = _diagram_class_of(src)
        if not os.path.isfile(png):
            refs.append(RasterRef(rel_src, rel_png, False, None, None, dclass))
            continue
        size = os.path.getsize(png)
        try:
            width: Optional[int] = read_png_width(png)
        except RasterReadError:
            width = None
        try:
            facts = read_png_facts(png)
        except RasterReadError:
            facts = RasterFacts()
        # The source sha256 the raster's provenance must match: hash the current
        # .drawio bytes. A missing/unreadable source leaves it None (a mismatch,
        # so the raster is reported stale).
        try:
            cur_sha: Optional[str] = source_sha256(src)
        except OSError:
            cur_sha = None
        refs.append(
            RasterRef(
                rel_src,
                rel_png,
                True,
                width,
                size,
                dclass,
                height=facts.height,
                color_type=facts.color_type,
                has_trns=facts.has_trns,
                provenance=facts.provenance,
                source_sha256=cur_sha,
                row0_all_white=facts.row0_all_white,
            )
        )
    return refs


def _fmt(ref: RasterRef) -> str:
    w = "?" if ref.width is None else f"{ref.width}px"
    kb = "?" if ref.size_bytes is None else f"{ref.size_bytes // 1024}KB"
    budget = f"{ref.diagram_class} budget {ref.max_width}px/{ref.max_size // 1024}KB"
    return f"{ref.png} ({w}, {kb}; {budget})"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for the CI raster gate.

    Usage::

        python -m rule_engine.raster_gate [--examples DIR] [--repo-root DIR]
                                           [--allow-missing]

    Exit codes:
      0  every exported raster is within budget: width, size, height, an opaque
         white background, and a provenance chunk matching the current source
         (missing PNGs only tolerated with ``--allow-missing``).
      1  a raster breaches the width/size/height budget, is stale (its
         provenance chunk is missing or does not match the source .drawio), is
         not an opaque white-background PNG, or a PNG is missing (without
         ``--allow-missing``).
      2  no ``.drawio`` source was found under ``--examples`` (the "no silent
         zero" rule — an empty run in CI is a configuration error, not a pass),
         or a usage error.
    """
    parser = argparse.ArgumentParser(
        prog="raster-gate",
        description="Enforce the exported .drawio.png width/size budget (D7).",
    )
    default_root = _default_workspace_root()
    parser.add_argument("--examples", default=str(default_root / "examples"))
    parser.add_argument("--repo-root", default=str(default_root))
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="treat a .drawio with no exported .png as a skip, not a failure",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    refs = check_rasters(args.examples, args.repo_root)
    if not refs:
        # No silent zero (R8.3): an empty run in CI means the gate was pointed
        # at the wrong tree or the examples were never generated — that is a
        # configuration failure, not a clean pass. Exit non-zero.
        print(
            f"BLOCKING: no .drawio sources found under {args.examples} "
            "(nothing to check — refusing to report a silent pass).",
            file=sys.stderr,
        )
        return EXIT_USAGE

    missing = [r for r in refs if not r.exists]
    present = [r for r in refs if r.exists]
    over_width = [r for r in present if not r.width_ok]
    over_size = [r for r in present if not r.size_ok]
    over_height = [r for r in present if not r.height_ok]
    unreadable = [r for r in present if r.width is None]
    stale = [r for r in present if r.width is not None and not r.provenance_ok]
    bad_bg = [r for r in present if r.width is not None and not r.background_ok]

    failed = False

    if over_width:
        failed = True
        print(
            "BLOCKING: raster(s) exceed their class width budget:",
            file=sys.stderr,
        )
        for r in over_width:
            print(f"    - {_fmt(r)}", file=sys.stderr)

    if over_size:
        failed = True
        print(
            "BLOCKING: raster(s) exceed their class size budget:",
            file=sys.stderr,
        )
        for r in over_size:
            print(f"    - {_fmt(r)}", file=sys.stderr)

    if over_height:
        failed = True
        print(
            "BLOCKING: raster(s) exceed their class height budget:",
            file=sys.stderr,
        )
        for r in over_height:
            h = "?" if r.height is None else f"{r.height}px"
            print(
                f"    - {r.png} (height {h}; {r.diagram_class} budget "
                f"{r.max_height}px)",
                file=sys.stderr,
            )

    if unreadable:
        failed = True
        print("BLOCKING: raster(s) are not readable PNGs:", file=sys.stderr)
        for r in unreadable:
            print(f"    - {r.png}", file=sys.stderr)

    if stale:
        failed = True
        print(
            "BLOCKING: stale-raster — provenance chunk missing or does not "
            "match the source .drawio (re-export):",
            file=sys.stderr,
        )
        for r in stale:
            got = r.provenance or "<none>"
            print(
                f"    - {r.png} (recorded {got[:12]}…, source "
                f"{(r.source_sha256 or '<none>')[:12]}…)",
                file=sys.stderr,
            )

    if bad_bg:
        failed = True
        print(
            "BLOCKING: raster(s) are not opaque white-background PNGs "
            "(need colour type 0/2, no tRNS, a white first row):",
            file=sys.stderr,
        )
        for r in bad_bg:
            reason = []
            if r.color_type not in (0, 2):
                reason.append(f"colour-type {r.color_type}")
            if r.has_trns:
                reason.append("tRNS present")
            if r.row0_all_white is not True:
                reason.append("first row not white")
            print(f"    - {r.png} ({', '.join(reason) or 'not white'})", file=sys.stderr)

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
            "Re-export the raster within its class budget "
            f"(flow ≤ {MAX_WIDTH_PX}px/{MAX_SIZE_BYTES // 1024}KB, "
            f"landscape ≤ {LANDSCAPE_MAX_WIDTH_PX}px/{LANDSCAPE_MAX_SIZE_BYTES // 1024}KB): "
            "python scripts/export_raster.py <file>.drawio",
            file=sys.stderr,
        )
        return EXIT_OVER_BUDGET

    print(
        f"OK: all {len(present)} exported raster(s) are within their "
        f"class budget (flow ≤ {MAX_WIDTH_PX}px, landscape ≤ {LANDSCAPE_MAX_WIDTH_PX}px)."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
