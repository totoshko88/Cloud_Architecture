"""Tests for the raster gate (rule_engine.raster_gate).

Covers the exported ``.drawio.png`` budget check: PNG width read from the file
header, the width/size budget, missing rasters (with and without
``--allow-missing``), and the CLI exit policy.
"""

from __future__ import annotations

import os
import struct

from rule_engine.raster_gate import (
    LANDSCAPE_MAX_WIDTH_PX,
    MAX_SIZE_BYTES,
    MAX_WIDTH_PX,
    RasterReadError,
    check_rasters,
    main,
    read_png_width,
)

import pytest

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_bytes(width: int, height: int = 100, pad: int = 0) -> bytes:
    """A minimal but valid PNG header with the given width, optionally padded.

    Only the 8-byte signature + IHDR length/type/width/height are meaningful to
    the header reader; ``pad`` appends filler bytes so the file size can be
    driven independently of the width for the size-budget test.
    """
    ihdr_len = struct.pack(">I", 13)
    ihdr_type = b"IHDR"
    dims = struct.pack(">II", width, height)
    rest = b"\x08\x02\x00\x00\x00"  # bit depth, color type, etc. (not parsed)
    return _PNG_SIGNATURE + ihdr_len + ihdr_type + dims + rest + (b"\x00" * pad)


def _write_bytes(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _write_text(path, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# --- read_png_width --------------------------------------------------------


def test_read_png_width_reads_header(tmp_path):
    p = tmp_path / "a.png"
    _write_bytes(str(p), _png_bytes(1200, 566))
    assert read_png_width(p) == 1200


def test_read_png_width_rejects_non_png(tmp_path):
    p = tmp_path / "a.png"
    _write_bytes(str(p), b"not a png at all, just text padding........")
    with pytest.raises(RasterReadError):
        read_png_width(p)


# --- check_rasters + CLI ---------------------------------------------------


def test_within_budget_passes(tmp_path):
    repo = tmp_path
    _write_text(str(repo / "examples/aws/01.drawio"), "<mxfile/>")
    _write_bytes(str(repo / "examples/aws/01.drawio.png"), _png_bytes(1200))

    refs = check_rasters(repo / "examples", repo)
    assert len(refs) == 1
    assert refs[0].within_budget is True
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 0


def test_over_width_fails(tmp_path):
    repo = tmp_path
    _write_text(str(repo / "examples/oci/01.drawio"), "<mxfile/>")
    # 3485px like the OCI raster that motivated the gate.
    _write_bytes(str(repo / "examples/oci/01.drawio.png"), _png_bytes(3485))

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].width == 3485
    assert refs[0].width_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_over_size_fails(tmp_path):
    repo = tmp_path
    _write_text(str(repo / "examples/gcp/01.drawio"), "<mxfile/>")
    # width fine, but pad the file past the 500KB size budget.
    _write_bytes(
        str(repo / "examples/gcp/01.drawio.png"),
        _png_bytes(1000, pad=MAX_SIZE_BYTES + 1),
    )

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].width_ok is True
    assert refs[0].size_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_missing_png_fails_by_default(tmp_path):
    repo = tmp_path
    _write_text(str(repo / "examples/azure/01.drawio"), "<mxfile/>")
    # no .drawio.png exported

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].exists is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_missing_png_skipped_with_allow_missing(tmp_path):
    repo = tmp_path
    _write_text(str(repo / "examples/azure/01.drawio"), "<mxfile/>")

    rc = main([
        "--examples", str(repo / "examples"),
        "--repo-root", str(repo),
        "--allow-missing",
    ])
    assert rc == 0


def test_no_sources_is_ok(tmp_path):
    repo = tmp_path
    os.makedirs(str(repo / "examples"), exist_ok=True)
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 0


def test_repo_examples_within_budget():
    """The shipped golden-example rasters must be within their class budget."""
    refs = check_rasters(os.path.join(os.getcwd(), "examples"))
    present = [r for r in refs if r.exists]
    # All shipped .drawio have an exported PNG within their class width/size budget.
    assert present, "expected shipped .drawio.png rasters"
    for r in present:
        assert r.width_ok, f"{r.png} width {r.width} exceeds {r.max_width}px ({r.diagram_class})"
        assert r.size_ok, f"{r.png} size {r.size_bytes} exceeds {r.max_size} ({r.diagram_class})"


# --- class-aware budget (v1.3.x) -------------------------------------------


def test_landscape_companion_raises_the_budget(tmp_path):
    """A .drawio whose companion declares diagram_class: landscape gets the wide
    budget — a 3000px raster that would fail as flow passes as landscape."""
    repo = tmp_path
    _write_text(str(repo / "examples/aws/02-x-landscape.drawio"), "<mxfile/>")
    _write_text(
        str(repo / "examples/aws/02-x-landscape.diagram.md"),
        "---\ndiagram_class: landscape\nsummary_of: 02-x-summary\n---\n# x\n",
    )
    _write_bytes(str(repo / "examples/aws/02-x-landscape.drawio.png"), _png_bytes(3000))

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].diagram_class == "landscape"
    assert refs[0].max_width == LANDSCAPE_MAX_WIDTH_PX
    assert refs[0].width_ok is True  # 3000 <= 3600 landscape budget
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 0


def test_quoted_and_commented_diagram_class_parsed_as_landscape(tmp_path):
    """A quoted ``diagram_class`` value with a trailing comment must still be read
    as landscape (a bare regex would miss it and wrongly apply the flow budget,
    failing a legitimately-wide as-built)."""
    repo = tmp_path
    _write_text(str(repo / "examples/aws/02-q-landscape.drawio"), "<mxfile/>")
    _write_text(
        str(repo / "examples/aws/02-q-landscape.diagram.md"),
        '---\ndiagram_class: "landscape"   # as-built\nsummary_of: 02-q-summary\n---\n# x\n',
    )
    _write_bytes(str(repo / "examples/aws/02-q-landscape.drawio.png"), _png_bytes(3000))

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].diagram_class == "landscape"
    assert refs[0].width_ok is True  # 3000 <= 3600 landscape budget


def test_landscape_still_capped_at_its_wider_limit(tmp_path):
    """Even a landscape has a ceiling — 4000px exceeds the 3600px landscape budget."""
    repo = tmp_path
    _write_text(str(repo / "examples/aws/02-x-landscape.drawio"), "<mxfile/>")
    _write_text(
        str(repo / "examples/aws/02-x-landscape.diagram.md"),
        "---\ndiagram_class: landscape\nsummary_of: 02-x-summary\n---\n# x\n",
    )
    _write_bytes(str(repo / "examples/aws/02-x-landscape.drawio.png"), _png_bytes(4000))

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].width_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_flow_default_keeps_narrow_budget(tmp_path):
    """A .drawio with no companion (or a flow companion) keeps the 1200px budget:
    a 3000px flow raster fails."""
    repo = tmp_path
    _write_text(str(repo / "examples/aws/02-x-summary.drawio"), "<mxfile/>")
    _write_bytes(str(repo / "examples/aws/02-x-summary.drawio.png"), _png_bytes(3000))

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].diagram_class == "flow"
    assert refs[0].max_width == MAX_WIDTH_PX
    assert refs[0].width_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1
