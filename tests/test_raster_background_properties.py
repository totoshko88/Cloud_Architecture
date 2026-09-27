"""Property tests for the ``raster_background`` companion mode (Part D).

Feature: provider-diagram-conventions (release 1.10.0), task 4.

Property 4 (design.md -> *Correctness Properties*): the raster mode is
backward-compatible. With ``raster_background`` absent or ``white`` the gate's
background verdict is **byte-for-byte the pre-1.10.0 check** (an opaque
white-background PNG: colour type 0/2, no tRNS, a white first row); only
``transparent`` changes the check, and there it requires an **alpha** channel
(colour type 4/6) with a transparent first pixel.

**Validates: Requirements 4.2, 4.4**
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.raster_gate import (
    check_rasters,
    insert_provenance,
    source_sha256,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests.strategies import PngModel, encode_png, fs_settings, png_models  # noqa: E402


def _legacy_white_background_ok(color_type, has_trns, row0_all_white) -> bool:
    """The pre-1.10.0 opaque-white predicate, reproduced verbatim.

    This is the exact expression ``RasterRef.background_ok`` used before the
    ``raster_background`` branch existed; Property 4 asserts the gate still
    matches it byte-for-byte in white/absent mode.
    """
    return color_type in (0, 2) and not has_trns and row0_all_white is True


def _write_triple(examples: Path, png_bytes: bytes, *, background: str | None) -> None:
    """Write a ``01.drawio`` + optional companion + stamped ``01.drawio.png``."""
    examples.mkdir(parents=True, exist_ok=True)
    src = examples / "01.drawio"
    src.write_bytes(b"<mxfile></mxfile>")
    if background is not None:
        (examples / "01.diagram.md").write_text(
            f"---\nraster_background: {background}\n---\n", encoding="utf-8"
        )
    stamped = insert_provenance(png_bytes, source_sha256(src))
    (examples / "01.drawio.png").write_bytes(stamped)


# Feature: provider-diagram-conventions, Property 4: raster mode is backward-compatible
@settings(fs_settings)
@given(model=png_models(), declare_white=st.booleans())
def test_white_or_absent_is_the_legacy_check(tmp_path_factory, model, declare_white):
    """White/absent background verdict == the pre-1.10.0 opaque-white predicate.

    Whether the companion declares ``raster_background: white`` explicitly or
    omits the key entirely, the gate's ``background_ok`` equals the exact legacy
    conjunction (colour type 0/2, no tRNS, white first row) for every synthetic
    PNG — colour type, tRNS presence, row-0 filter and first pixel all varied.
    """
    repo = tmp_path_factory.mktemp("white")
    background = "white" if declare_white else None
    _write_triple(repo / "examples" / "aws", encode_png(model), background=background)

    refs = check_rasters(repo / "examples", repo)
    assert len(refs) == 1
    ref = refs[0]

    assert ref.raster_background == "white"
    assert ref.background_ok is _legacy_white_background_ok(
        ref.color_type, ref.has_trns, ref.row0_all_white
    )


# Feature: provider-diagram-conventions, Property 4: transparent requires alpha
@settings(fs_settings)
@given(model=png_models())
def test_transparent_requires_alpha_and_transparent_first_pixel(tmp_path_factory, model):
    """Transparent background verdict == (alpha colour type AND transparent pixel).

    In ``transparent`` mode the check flips: it requires an alpha channel
    (colour type 4 gray+alpha or 6 RGBA) and a transparent first pixel
    (alpha == 0), and is independent of the opaque-white verdict.
    """
    repo = tmp_path_factory.mktemp("transparent")
    _write_triple(repo / "examples" / "aws", encode_png(model), background="transparent")

    refs = check_rasters(repo / "examples", repo)
    assert len(refs) == 1
    ref = refs[0]

    assert ref.raster_background == "transparent"
    assert ref.background_ok is (
        ref.color_type in (4, 6) and ref.row0_transparent is True
    )


# Feature: provider-diagram-conventions, Property 4: bad value falls back to white
@settings(fs_settings)
@given(model=png_models(), bogus=st.sampled_from(["opaque", "clear", "White", "TRANSPARENT", "none"]))
def test_unknown_value_falls_back_to_white(tmp_path_factory, model, bogus):
    """Any value other than the literal ``transparent`` uses the white check.

    A typo or an unexpected token (including a differently-cased ``TRANSPARENT``
    read as-is) must not silently drop the opaque-white check — it falls back to
    ``white`` so the default safety holds.
    """
    repo = tmp_path_factory.mktemp("bogus")
    # Only the exact lowercase literal "transparent" selects the alpha check.
    expect_white = bogus.lower() != "transparent"
    _write_triple(repo / "examples" / "aws", encode_png(model), background=bogus)

    refs = check_rasters(repo / "examples", repo)
    ref = refs[0]
    if expect_white:
        assert ref.raster_background == "white"
        assert ref.background_ok is _legacy_white_background_ok(
            ref.color_type, ref.has_trns, ref.row0_all_white
        )
    else:
        assert ref.raster_background == "transparent"
