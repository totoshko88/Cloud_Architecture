"""Tests for the raster gate (rule_engine.raster_gate).

Covers the exported ``.drawio.png`` budget check: PNG width read from the file
header, the width/size budget, missing rasters (with and without
``--allow-missing``), and the CLI exit policy.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

from rule_engine.raster_gate import (
    LANDSCAPE_MAX_WIDTH_PX,
    MAX_SIZE_BYTES,
    MAX_WIDTH_PX,
    RasterReadError,
    check_rasters,
    insert_provenance,
    main,
    read_png_width,
    source_sha256,
)

import pytest

# ``tests/strategies.py`` is a sibling module, imported by path like the rest of
# the honest-gates property suite.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategies import PngModel, encode_png  # noqa: E402

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


def _conforming_png(width: int, height: int = 100, pad: int = 0) -> bytes:
    """A fully conforming PNG body sans provenance: RGB, no tRNS, white row 0.

    Callers add provenance with :func:`insert_provenance` once the source
    ``.drawio`` sha256 is known. ``pad`` is appended after ``IEND`` so the file
    size can be driven independently of the pixels for the size-budget test.
    """
    body = encode_png(
        PngModel(
            width=width,
            height=height,
            color_type=2,          # RGB (no alpha)
            row0_filter=0,
            first_pixel_white=True,
            trns=False,
        )
    )
    return body + (b"\x00" * pad)


def _write_conforming(png_path, src_path, width: int, height: int = 100, pad: int = 0):
    """Write a conforming PNG whose provenance matches ``src_path``'s sha256."""
    body = insert_provenance(_conforming_png(width, height), source_sha256(src_path))
    body += b"\x00" * pad
    _write_bytes(str(png_path), body)


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
    src = repo / "examples/aws/01.drawio"
    _write_text(str(src), "<mxfile/>")
    _write_conforming(repo / "examples/aws/01.drawio.png", src, 1200)

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


def test_no_sources_is_non_zero(tmp_path):
    """No .drawio under --examples is exit 2, not a silent 0 (R8.3)."""
    repo = tmp_path
    os.makedirs(str(repo / "examples"), exist_ok=True)
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 2


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
    src = repo / "examples/aws/02-x-landscape.drawio"
    _write_text(str(src), "<mxfile/>")
    _write_text(
        str(repo / "examples/aws/02-x-landscape.diagram.md"),
        "---\ndiagram_class: landscape\nsummary_of: 02-x-summary\n---\n# x\n",
    )
    _write_conforming(repo / "examples/aws/02-x-landscape.drawio.png", src, 3000)

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


# --- provenance, height, background (R8.2 / R8.3, task 17.2) ---------------


def test_provenance_round_trip():
    """insert_provenance/read_provenance is a round trip and idempotent."""
    from rule_engine.raster_gate import read_provenance

    body = _conforming_png(64, 64)
    digest = "a" * 64
    stamped = insert_provenance(body, digest)
    assert read_provenance(stamped) == digest
    # Re-stamping replaces (not duplicates) the chunk.
    restamped = insert_provenance(stamped, "b" * 64)
    assert read_provenance(restamped) == "b" * 64
    assert restamped.count(b"rule-engine:source-sha256") == 1


def test_matching_provenance_passes(tmp_path):
    repo = tmp_path
    src = repo / "examples/aws/p.drawio"
    _write_text(str(src), "<mxfile>fresh</mxfile>")
    _write_conforming(repo / "examples/aws/p.drawio.png", src, 800)

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].provenance_ok is True
    assert refs[0].within_budget is True
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 0


def test_stale_raster_fails_when_source_changed(tmp_path):
    """A PNG stamped for an old source is stale after the .drawio is edited."""
    repo = tmp_path
    src = repo / "examples/aws/s.drawio"
    _write_text(str(src), "<mxfile>v1</mxfile>")
    _write_conforming(repo / "examples/aws/s.drawio.png", src, 800)
    # Edit the source after export: the recorded sha no longer matches.
    _write_text(str(src), "<mxfile>v2-edited</mxfile>")

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].provenance_ok is False
    assert refs[0].within_budget is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_missing_provenance_is_stale(tmp_path):
    """A PNG with no provenance chunk at all is treated as stale."""
    repo = tmp_path
    src = repo / "examples/aws/n.drawio"
    _write_text(str(src), "<mxfile/>")
    _write_bytes(str(repo / "examples/aws/n.drawio.png"), _conforming_png(800))  # no provenance

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].provenance is None
    assert refs[0].provenance_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_over_height_fails(tmp_path):
    """A flow PNG within width but taller than 1600px breaches the height ceiling."""
    repo = tmp_path
    src = repo / "examples/aws/h.drawio"
    _write_text(str(src), "<mxfile/>")
    _write_conforming(repo / "examples/aws/h.drawio.png", src, 800, height=1700)

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].height == 1700
    assert refs[0].height_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_alpha_background_fails(tmp_path):
    """An RGBA (colour type 6) PNG is not an opaque white-background raster."""
    repo = tmp_path
    src = repo / "examples/aws/a.drawio"
    _write_text(str(src), "<mxfile/>")
    body = encode_png(
        PngModel(width=800, height=100, color_type=6, first_pixel_white=True)
    )
    _write_bytes(
        str(repo / "examples/aws/a.drawio.png"),
        insert_provenance(body, source_sha256(src)),
    )

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].color_type == 6
    assert refs[0].background_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_trns_background_fails(tmp_path):
    """A tRNS chunk (transparency) disqualifies an otherwise-white RGB raster."""
    repo = tmp_path
    src = repo / "examples/aws/t.drawio"
    _write_text(str(src), "<mxfile/>")
    body = encode_png(
        PngModel(width=800, height=100, color_type=2, first_pixel_white=True, trns=True)
    )
    _write_bytes(
        str(repo / "examples/aws/t.drawio.png"),
        insert_provenance(body, source_sha256(src)),
    )

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].has_trns is True
    assert refs[0].background_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_non_white_first_row_fails(tmp_path):
    """A raster whose first pixel is black fails the white-background check,
    across every row-0 filter (the gate reconstructs row 0 from its filter)."""
    from rule_engine.raster_gate import read_png_facts

    for filt in range(5):
        body = encode_png(
            PngModel(
                width=8, height=8, color_type=2,
                row0_filter=filt, first_pixel_white=False,
            )
        )
        p = tmp_path / f"blk-{filt}.png"
        with open(p, "wb") as fh:
            fh.write(body)
        facts = read_png_facts(p)
        assert facts.row0_all_white is False, f"filter {filt} should read non-white"


# --- raster_background mode (v1.10.0, Part D) ------------------------------


def test_transparent_companion_requires_alpha(tmp_path):
    """A companion declaring raster_background: transparent accepts an RGBA PNG
    with a transparent first pixel, and the gate passes."""
    repo = tmp_path
    src = repo / "examples/aws/01-t.drawio"
    _write_text(str(src), "<mxfile/>")
    _write_text(
        str(repo / "examples/aws/01-t.diagram.md"),
        "---\nraster_background: transparent\n---\n# x\n",
    )
    body = encode_png(
        PngModel(width=800, height=100, color_type=6, first_pixel_white=False)
    )
    _write_bytes(
        str(repo / "examples/aws/01-t.drawio.png"),
        insert_provenance(body, source_sha256(src)),
    )

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].raster_background == "transparent"
    assert refs[0].color_type == 6
    assert refs[0].row0_transparent is True
    assert refs[0].background_ok is True
    assert refs[0].within_budget is True
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 0


def test_transparent_companion_rejects_opaque_white(tmp_path):
    """An opaque white RGB raster fails the gate when the companion asks for
    transparent (it has no alpha channel)."""
    repo = tmp_path
    src = repo / "examples/aws/01-tw.drawio"
    _write_text(str(src), "<mxfile/>")
    _write_text(
        str(repo / "examples/aws/01-tw.diagram.md"),
        "---\nraster_background: transparent\n---\n# x\n",
    )
    _write_conforming(repo / "examples/aws/01-tw.drawio.png", src, 800)

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].raster_background == "transparent"
    assert refs[0].color_type == 2  # RGB, no alpha
    assert refs[0].background_ok is False
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_white_companion_rejects_transparent_png(tmp_path):
    """A transparent RGBA raster fails the gate in the default white mode
    (the pre-1.10.0 opaque-white check is unchanged for white/absent)."""
    repo = tmp_path
    src = repo / "examples/aws/01-wt.drawio"
    _write_text(str(src), "<mxfile/>")
    # No companion at all -> background defaults to white.
    body = encode_png(
        PngModel(width=800, height=100, color_type=6, first_pixel_white=False)
    )
    _write_bytes(
        str(repo / "examples/aws/01-wt.drawio.png"),
        insert_provenance(body, source_sha256(src)),
    )

    refs = check_rasters(repo / "examples", repo)
    assert refs[0].raster_background == "white"
    assert refs[0].background_ok is False  # alpha colour type fails the white check
    assert main(["--examples", str(repo / "examples"), "--repo-root", str(repo)]) == 1


def test_check_rasters_excludes_vendor_and_build_dirs(tmp_path):
    """v1.9.3: a .drawio under assets/vendor/ (e.g. the OCI style guide) or any
    excluded build dir is NOT a publishable artifact, so check_rasters skips it —
    the same _EXCLUDED_DIRS the linter's --all scan uses. Before this fix the gate
    globbed **/*.drawio and forced --allow-missing on a workspace that kept its
    diagrams beside assets/."""
    # A real diagram at the workspace root must be discovered.
    (tmp_path / "01-real.drawio").write_text("<mxfile/>", encoding="utf-8")
    # Vendor + build .drawio inputs must be ignored.
    for rel in ("assets/vendor/oci-style/OCI Library.drawio",
                ".build-tools/export-tmp/x.inlined.drawio",
                "build/lib/whatever.drawio"):
        d = tmp_path / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text("<mxfile/>", encoding="utf-8")
    found = {os.path.basename(r.source) for r in check_rasters(tmp_path, tmp_path)}
    assert "01-real.drawio" in found
    assert "OCI Library.drawio" not in found
    assert "x.inlined.drawio" not in found
    assert "whatever.drawio" not in found
