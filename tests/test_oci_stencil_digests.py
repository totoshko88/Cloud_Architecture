"""Tests for the committed OCI stencil digest manifest (honest-gates R4.1, task 5.3).

``rule-engine-build-icon-sets`` writes ``mappings/oci-stencil-digests.json`` next
to ``aws4-icons.json``. The manifest binds each OCI stencil slug to the sha256 an
OCI node built from that stencil renders — the digest of its ``shape=stencil(...)``
payloads, computed by :func:`rule_engine.icon_refs.oci_glyph_digest`. It holds
hashes only (no vendor content) and is covered by ``--check``.
"""

from __future__ import annotations

import json
from pathlib import Path

from rule_engine import build_icon_sets_cli as bics
from rule_engine import icon_refs


def _write_stencils(root: Path, entries: dict) -> Path:
    """Write a minimal decoded stencils.json under the OCI pack path."""
    sten = root / "oci-stencils" / "stencils.json"
    sten.parent.mkdir(parents=True, exist_ok=True)
    sten.write_text(json.dumps(entries), encoding="utf-8")
    return sten


# --------------------------------------------------------------------------- #
# build_oci_digests
# --------------------------------------------------------------------------- #


def test_digest_matches_the_glyph_digest_a_diagram_produces(tmp_path):
    """Each slug's digest equals oci_glyph_digest of its embedded payloads."""
    xml = (
        '<mxGraphModel><root>'
        '<mxCell id="2" style="group"/>'
        '<mxCell id="3" style="shape=stencil(AAAA);html=1"/>'
        '<mxCell id="4" style="shape=stencil(BBBB);html=1"/>'
        '</root></mxGraphModel>'
    )
    sten = _write_stencils(tmp_path, {"functions": {"w": 84, "h": 84, "xml": xml}})
    digests = bics.build_oci_digests(sten)
    assert set(digests) == {"functions"}
    assert digests["functions"] == icon_refs.oci_glyph_digest(["AAAA", "BBBB"])


def test_a_stencil_with_no_embedded_payload_still_gets_a_stable_digest(tmp_path):
    """A drawn-shape stencil (no shape=stencil payloads) hashes the empty join."""
    sten = _write_stencils(
        tmp_path, {"plain": {"w": 10, "h": 10, "xml": "<mxGraphModel/>"}}
    )
    digests = bics.build_oci_digests(sten)
    assert digests["plain"] == icon_refs.oci_glyph_digest([])


def test_manifest_holds_hashes_only_no_vendor_content(tmp_path):
    """No stencil XML/payload leaks into the manifest text — hashes only."""
    xml = '<mxCell id="3" style="shape=stencil(SECRETPAYLOAD);html=1"/>'
    sten = _write_stencils(tmp_path, {"vault": {"w": 84, "h": 84, "xml": xml}})
    digests = bics.build_oci_digests(sten)
    text = bics.oci_digests_to_json(digests)
    assert "SECRETPAYLOAD" not in text
    assert "shape=stencil" not in text
    assert "mxCell" not in text


def test_serialisation_is_deterministic_and_sorted(tmp_path):
    sten = _write_stencils(
        tmp_path,
        {
            "zeta": {"xml": '<mxCell style="shape=stencil(Z)"/>'},
            "alpha": {"xml": '<mxCell style="shape=stencil(A)"/>'},
        },
    )
    digests = bics.build_oci_digests(sten)
    text = bics.oci_digests_to_json(digests)
    assert text == bics.oci_digests_to_json(bics.build_oci_digests(sten))
    payload = json.loads(text)
    assert list(payload["digests"]) == ["alpha", "zeta"]  # sorted
    assert payload["count"] == 2


def test_absent_stencils_pack_yields_none(tmp_path):
    assert bics.build_oci_digests(tmp_path / "missing.json") is None


def test_manifest_is_consumable_by_icon_refs(tmp_path):
    """A written manifest resolves an oci-slug and an oci-glyph ref (round trip)."""
    xml = '<mxCell id="3" style="shape=stencil(GLYPH);html=1"/>'
    sten = _write_stencils(tmp_path, {"streaming": {"xml": xml}})
    digests = bics.build_oci_digests(sten)

    ws = tmp_path / "ws"
    (ws / "mappings").mkdir(parents=True)
    (ws / "mappings" / "oci-stencil-digests.json").write_text(
        bics.oci_digests_to_json(digests), encoding="utf-8"
    )
    loaded = icon_refs._load_oci_digests(ws)
    assert loaded == digests

    sources = icon_refs.IconSources(
        aws4=None, azure2=None, oci_digests=loaded,
        oci_stencils=None, workspace_root=ws,
    )
    slug_status, _ = icon_refs.resolve(
        icon_refs.IconRef("c1", "oci-slug", "streaming"), sources
    )
    glyph_status, _ = icon_refs.resolve(
        icon_refs.IconRef("c1", "oci-glyph", digests["streaming"]), sources
    )
    assert slug_status == icon_refs.RESOLVED
    assert glyph_status == icon_refs.RESOLVED


# --------------------------------------------------------------------------- #
# --check covers the digest manifest
# --------------------------------------------------------------------------- #


def _packs_with_oci(asset_root: Path, stencils: dict) -> None:
    """Populate a fake asset root: non-empty dirs for every non-OCI pack plus
    a real decoded OCI stencils.json, so build_icon_sets passes the missing-pack
    gate and reaches the digest logic."""
    for key, rel in bics._PACK_ROOTS.items():
        target = asset_root / rel
        if target.suffix:  # oci-stencils/stencils.json
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(stencils), encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "icon.svg").write_text("<svg/>", encoding="utf-8")


def test_check_flags_a_stale_digest_manifest(tmp_path, monkeypatch):
    asset_root = tmp_path / "packs"
    _packs_with_oci(asset_root, {"functions": {"xml": '<mxCell style="shape=stencil(A)"/>'}})
    # Keep the icon-index build cheap and current so only the digest check bites.
    monkeypatch.setattr(
        bics, "build_icon_index", lambda roots, full_packs=False, pack_pins=None: {"roles": {}, "pack_summary": {}}
    )
    out = tmp_path / "icon-index.json"
    out.write_text(bics.icon_index_to_json({"roles": {}, "pack_summary": {}}) + "\n", encoding="utf-8")
    digests_path = out.parent / "oci-stencil-digests.json"

    base = ["--check", "--no-fetch", "--asset-root", str(asset_root), "--out", str(out)]

    # No committed digest manifest yet -> STALE.
    assert bics.main(base) == bics.EXIT_FAIL

    # Write the current manifest -> check passes.
    fresh = bics.build_oci_digests(asset_root / bics._PACK_ROOTS["oci"])
    digests_path.write_text(bics.oci_digests_to_json(fresh), encoding="utf-8")
    assert bics.main(base) == bics.EXIT_OK


def test_build_writes_the_digest_manifest_next_to_the_index(tmp_path, monkeypatch):
    asset_root = tmp_path / "packs"
    _packs_with_oci(asset_root, {"vault": {"xml": '<mxCell style="shape=stencil(V)"/>'}})
    monkeypatch.setattr(
        bics, "build_icon_index", lambda roots, full_packs=False, pack_pins=None: {"roles": {}, "pack_summary": {}}
    )
    out = tmp_path / "icon-index.json"
    rc = bics.main(["--no-fetch", "--asset-root", str(asset_root), "--out", str(out)])
    assert rc == bics.EXIT_OK
    digests_path = out.parent / "oci-stencil-digests.json"
    assert digests_path.is_file()
    payload = json.loads(digests_path.read_text(encoding="utf-8"))
    assert set(payload["digests"]) == {"vault"}
