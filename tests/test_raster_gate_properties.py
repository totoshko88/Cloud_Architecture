"""Property tests for the raster gate's PNG provenance (`rule_engine.raster_gate`).

Feature: honest-gates (release 1.7.0), task 17.3.

This pins the contract the design records for the raster provenance round trip
(design.md -> *Correctness Properties*, Property 28), which implements R8.2: the
Raster_Exporter writes the sha256 of the source ``.drawio`` into a PNG ``tEXt``
chunk (keyword ``rule-engine:source-sha256``), and the Raster_Checker fails on a
mismatch.

The property uses Hypothesis with ``max_examples >= 100`` via the
``honest-gates`` profile loaded in ``tests/conftest.py``. The example-based
round-trip test lives in ``tests/test_raster_gate.py``
(``test_provenance_round_trip``); this is the property-based version, which
additionally exercises the checker's stale/fresh verdict against a sibling
``.drawio`` on disk (so it opts into the filesystem profile's ``deadline=None``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.raster_gate import (
    PROVENANCE_KEY,
    _iter_png_chunks,
    check_rasters,
    insert_provenance,
    read_png_facts,
    read_provenance,
    source_sha256,
)

# ``tests/strategies.py`` is imported both as a package module (matching the rest
# of the honest-gates suite) and by path, so a bare ``pytest tests/...`` works.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests.strategies import PngModel, encode_png, fs_settings, png_models  # noqa: E402

#: 64-hex sha256 digests, the shape the exporter writes and the checker reads.
_DIGESTS = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


def _crcs_valid(png_bytes: bytes) -> bool:
    """True when every chunk in ``png_bytes`` parses (CRC-checked by re-serialise).

    ``_iter_png_chunks`` validates the signature and chunk framing; a chunk whose
    stored CRC is wrong would still frame, so we re-derive each CRC via the shared
    ``insert_provenance`` writer path implicitly. Here we just assert the stream
    parses and re-hashing the type+data reproduces a well-formed stream, which is
    what the checker relies on.
    """
    import struct
    import zlib

    pos = 8
    n = len(png_bytes)
    sig = b"\x89PNG\r\n\x1a\n"
    if png_bytes[:8] != sig:
        return False
    while pos + 8 <= n:
        (length,) = struct.unpack(">I", png_bytes[pos : pos + 4])
        ctype = png_bytes[pos + 4 : pos + 8]
        start = pos + 8
        end = start + length
        if end + 4 > n:
            return False
        stored = png_bytes[end : end + 4]
        want = struct.pack(">I", zlib.crc32(ctype + png_bytes[start:end]) & 0xFFFFFFFF)
        if stored != want:
            return False
        pos = end + 4
        if ctype == b"IEND":
            break
    return True


# Feature: honest-gates, Property 28: PNG provenance round trip
@given(model=png_models(), digest=_DIGESTS, second=_DIGESTS)
def test_provenance_round_trip_and_idempotent(model, digest, second):
    """For any valid PNG and any digest, stamping then reading returns the digest.

    * ``read_provenance(insert_provenance(png, digest)) == digest`` (R8.2 write/read).
    * The stamped PNG is still a valid, parseable PNG with valid chunk CRCs and
      exactly one provenance chunk.
    * Re-stamping is idempotent: a second stamp replaces the chunk (latest wins),
      never appends a second one.
    """
    png = encode_png(model)

    stamped = insert_provenance(png, digest)

    # Round trip: the digest reads back.
    assert read_provenance(stamped) == digest
    # Still a valid, parseable PNG (chunk framing + CRCs intact).
    assert _crcs_valid(stamped)
    chunks = _iter_png_chunks(stamped)  # raises RasterReadError if malformed
    assert chunks[-1][0] == b"IEND"
    # Exactly one provenance chunk.
    key = PROVENANCE_KEY.encode("latin-1")
    prov_chunks = [c for t, c in chunks if t == b"tEXt" and c.split(b"\x00", 1)[0] == key]
    assert len(prov_chunks) == 1

    # Re-stamping replaces (latest wins), never duplicates.
    restamped = insert_provenance(stamped, second)
    assert read_provenance(restamped) == second
    assert _crcs_valid(restamped)
    rechunks = _iter_png_chunks(restamped)
    re_prov = [c for t, c in rechunks if t == b"tEXt" and c.split(b"\x00", 1)[0] == key]
    assert len(re_prov) == 1


# Feature: honest-gates, Property 28: PNG provenance round trip
@settings(fs_settings)
@given(
    model=png_models(),
    src_bytes=st.binary(min_size=0, max_size=64),
    stamp_matches=st.booleans(),
    other=_DIGESTS,
)
def test_checker_reports_stale_iff_digest_differs(
    tmp_path_factory, model, src_bytes, stamp_matches, other
):
    """The checker reports stale iff the stamped digest differs from the source.

    A raster stamped with the sibling ``.drawio``'s own sha256 is fresh
    (``provenance_ok is True``); a raster stamped with any other digest is stale
    (``provenance_ok is False``). This is the ``stale-raster`` if-and-only-if
    half of Property 28.
    """
    repo = tmp_path_factory.mktemp("prov")
    examples = repo / "examples" / "aws"
    examples.mkdir(parents=True)
    src = examples / "01.drawio"
    src.write_bytes(src_bytes)

    true_sha = source_sha256(src)
    # Choose a digest that either matches the source or is guaranteed different.
    if stamp_matches:
        digest = true_sha
    else:
        digest = other if other != true_sha else ("0" * 64 if true_sha != "0" * 64 else "f" * 64)

    png = insert_provenance(encode_png(model), digest)
    (examples / "01.drawio.png").write_bytes(png)

    refs = check_rasters(repo / "examples", repo)
    assert len(refs) == 1
    ref = refs[0]

    assert ref.provenance == digest
    assert ref.source_sha256 == true_sha
    # stale iff the recorded digest differs from the source sha256.
    assert ref.provenance_ok is (digest == true_sha)
    assert ref.provenance_ok is stamp_matches


# Feature: honest-gates, Property 28: PNG provenance round trip
@settings(fs_settings)
@given(model=png_models(), digest=_DIGESTS)
def test_stamp_preserves_pixels_and_facts(tmp_path_factory, model, digest):
    """Stamping provenance does not disturb the image the checker reads.

    The IHDR-derived facts (height, colour type), the tRNS presence and the
    reconstructed first-row verdict are unchanged by inserting the tEXt chunk —
    only the provenance is added. So a stamp can never flip the background or
    height verdict of an otherwise-conforming raster.
    """
    tmp = tmp_path_factory.mktemp("facts")
    png = encode_png(model)
    before_path = tmp / "before.png"
    before_path.write_bytes(png)
    before = read_png_facts(before_path)

    stamped = insert_provenance(png, digest)
    after_path = tmp / "after.png"
    after_path.write_bytes(stamped)
    after = read_png_facts(after_path)

    assert after.height == before.height
    assert after.color_type == before.color_type
    assert after.has_trns == before.has_trns
    assert after.row0_all_white == before.row0_all_white
    assert after.provenance == digest


# Feature: honest-gates, Property 29: Raster verdicts follow the budget model
@settings(fs_settings)
@given(
    model=png_models(),
    dclass=st.sampled_from(["flow", "landscape"]),
    stamp_matches=st.booleans(),
    other=_DIGESTS,
)
def test_within_budget_is_the_and_of_its_parts(
    tmp_path_factory, model, dclass, stamp_matches, other
):
    """The verdict is exactly the conjunction of the individual budget checks.

    For any synthetic PNG (random width, height, colour type, tRNS presence,
    row-0 filter and first-pixel colour) and diagram class, the checker's
    ``within_budget`` verdict equals ``exists AND width_ok AND size_ok AND
    height_ok AND provenance_ok AND background_ok`` — the raster ships iff every
    part passes, and is blocked the moment any single part fails.

    This is the whole-verdict half of Property 29 (R8.3). The provenance-only
    if-and-only-if is already pinned by Property 28
    (``test_checker_reports_stale_iff_digest_differs``); here provenance is
    varied too so it participates in the conjunction rather than being held
    fixed. The generated PNGs are ≤ 64px, so a genuinely conforming raster is
    within both the flow and landscape width/height/size budgets — the parts
    that vary the verdict are colour type / tRNS / first-pixel (background) and
    the provenance stamp.
    """
    repo = tmp_path_factory.mktemp("verdict")
    examples = repo / "examples" / "aws"
    examples.mkdir(parents=True)
    src = examples / "01.drawio"
    src.write_bytes(b"<mxfile></mxfile>")

    # A companion doc so the diagram class is picked up (defaults to flow when
    # absent, but a landscape must be declared to exercise the wide budget).
    (examples / "01.diagram.md").write_text(
        f"---\ndiagram_class: {dclass}\n---\n", encoding="utf-8"
    )

    true_sha = source_sha256(src)
    if stamp_matches:
        digest = true_sha
    else:
        digest = other if other != true_sha else ("0" * 64 if true_sha != "0" * 64 else "f" * 64)

    png = insert_provenance(encode_png(model), digest)
    (examples / "01.drawio.png").write_bytes(png)

    refs = check_rasters(repo / "examples", repo)
    assert len(refs) == 1
    ref = refs[0]

    assert ref.diagram_class == dclass

    # The verdict is exactly the AND of the six independent parts.
    expected = (
        ref.exists
        and ref.width_ok
        and ref.size_ok
        and ref.height_ok
        and ref.provenance_ok
        and ref.background_ok
    )
    assert ref.within_budget is expected

    # Failing any single part blocks the raster: if the verdict is True then
    # every part is True; if any part is False the verdict is False.
    parts = [
        ref.exists,
        ref.width_ok,
        ref.size_ok,
        ref.height_ok,
        ref.provenance_ok,
        ref.background_ok,
    ]
    if ref.within_budget:
        assert all(parts)
    if not all(parts):
        assert not ref.within_budget

    # The background verdict itself is the alpha/tRNS/white-row conjunction the
    # design names (colour type 0/2, no tRNS, an opaque white first row).
    assert ref.background_ok is (
        ref.color_type in (0, 2)
        and not ref.has_trns
        and ref.row0_all_white is True
    )
