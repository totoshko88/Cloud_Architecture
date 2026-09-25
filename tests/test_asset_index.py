"""Tests for the Asset Index & Icon Fallback (rule_engine.asset_index).

These tests use a small synthetic asset tree written to a tmp dir, so they run
without the large official packs (which are downloaded on demand and never
committed). They cover slug normalization, per-provider indexing, the built-in
stencil short-circuit, the official-asset fallback for services missing from the
built-in stencils (the "DevOps/FinOps/Security agent" case), and the
fail-honest unresolved result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine.asset_index import (
    AssetEntry,
    ResolvedAsset,
    build_index,
    index_provider,
    index_to_json,
    normalize_slug,
    resolve_asset,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic packs mirroring the real layouts
# ---------------------------------------------------------------------------


@pytest.fixture()
def aws_pack(tmp_path: Path) -> str:
    root = tmp_path / "aws"
    svc = root / "Architecture-Service-Icons_07312026"
    (svc / "Arch_Security-Identity" / "32").mkdir(parents=True)
    (svc / "Arch_Security-Identity" / "32" / "Arch_AWS-Security-Agent_32.svg").write_text("<svg/>")
    (svc / "Arch_Management-Tools" / "32").mkdir(parents=True)
    (svc / "Arch_Management-Tools" / "32" / "Arch_AWS-DevOps-Agent_32.svg").write_text("<svg/>")
    (svc / "Arch_Compute" / "32").mkdir(parents=True)
    (svc / "Arch_Compute" / "32" / "Arch_Amazon-EKS_32.svg").write_text("<svg/>")
    # A PNG-only service to exercise ext ranking / png fallback.
    (svc / "Arch_Compute" / "64").mkdir(parents=True)
    (svc / "Arch_Compute" / "64" / "Arch_Amazon-EKS_64.png").write_text("png")
    return str(root)


@pytest.fixture()
def azure_pack(tmp_path: Path) -> str:
    root = tmp_path / "azure"
    icons = root / "Azure_Public_Service_Icons" / "Icons"
    (icons / "security").mkdir(parents=True)
    (icons / "security" / "10245-icon-service-Key-Vaults.svg").write_text("<svg/>")
    (icons / "networking").mkdir(parents=True)
    (icons / "networking" / "10076-icon-service-Application-Gateways.svg").write_text("<svg/>")
    return str(root)


@pytest.fixture()
def gcp_pack(tmp_path: Path) -> str:
    root = tmp_path / "gcp"
    (root / "Unique Icons" / "Vertex AI" / "SVG").mkdir(parents=True)
    (root / "Unique Icons" / "Vertex AI" / "SVG" / "VertexAI-512-color.svg").write_text("<svg/>")
    (root / "Unique Icons" / "GKE" / "SVG").mkdir(parents=True)
    (root / "Unique Icons" / "GKE" / "SVG" / "GKE-512-color.svg").write_text("<svg/>")
    return str(root)


# ---------------------------------------------------------------------------
# normalize_slug
# ---------------------------------------------------------------------------


def test_normalize_slug_basic():
    assert normalize_slug("AWS Security Agent") == "aws-security-agent"
    assert normalize_slug("AWS Security Agent", strip_vendor=True) == "security-agent"


def test_normalize_slug_strips_size_and_ext():
    assert normalize_slug("Arch_Amazon-EKS_32.svg", strip_vendor=True) == "eks"
    assert normalize_slug("Cloud_Storage-512-color.svg", strip_vendor=True) == "storage"


def test_normalize_slug_empty():
    assert normalize_slug("") == ""
    assert normalize_slug("  ") == ""


# ---------------------------------------------------------------------------
# index_provider
# ---------------------------------------------------------------------------


def test_index_provider_aws_prefers_svg_over_png(aws_pack):
    idx = index_provider("aws", aws_pack)
    assert "security-agent" in idx
    assert "devops-agent" in idx
    assert idx["eks"].ext == ".svg"  # SVG beats the PNG sibling


def test_index_provider_unknown_provider_raises(tmp_path):
    with pytest.raises(ValueError):
        index_provider("nope", str(tmp_path))


def test_index_provider_missing_root_raises():
    with pytest.raises(FileNotFoundError):
        index_provider("aws", "/no/such/dir")


# ---------------------------------------------------------------------------
# resolve_asset — built-in short-circuit
# ---------------------------------------------------------------------------


def test_resolve_builtin_stencil_wins(aws_pack):
    idx = index_provider("aws", aws_pack)
    r = resolve_asset("aws", "EKS", idx)
    assert r.source == "builtin"
    assert r.stencil == "mxgraph.aws4.eks"


# ---------------------------------------------------------------------------
# resolve_asset — official-asset fallback for NEW services
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query,expected_fragment", [
    ("DevOps agent", "DevOps-Agent"),
    ("Security agent", "Security-Agent"),
    ("AWS Security Agent", "Security-Agent"),
])
def test_resolve_new_agent_falls_back_to_official_svg(aws_pack, query, expected_fragment):
    idx = index_provider("aws", aws_pack)
    r = resolve_asset("aws", query, idx)
    assert r.source == "official-asset"
    assert r.ext == ".svg"
    assert expected_fragment in r.asset_path


def test_resolve_azure_plural_and_gcp_concat(azure_pack, gcp_pack):
    ai = index_provider("azure", azure_pack)
    assert resolve_asset("azure", "Key Vault", ai).asset_path.endswith("Key-Vaults.svg")
    assert resolve_asset("azure", "Application Gateway", ai).asset_path.endswith(
        "Application-Gateways.svg"
    )
    gi = index_provider("gcp", gcp_pack)
    assert resolve_asset("gcp", "Vertex AI", gi).asset_path.endswith("VertexAI-512-color.svg")


def test_resolve_unresolved_is_fail_honest(aws_pack):
    idx = index_provider("aws", aws_pack)
    r = resolve_asset("aws", "Totally Made Up Widget 9000", idx)
    assert r.source == "unresolved"
    assert r.asset_path is None and r.stencil is None


def test_resolve_oci_library_fallback():
    r = resolve_asset("oci", "Generative AI", None)
    assert r.source == "official-asset"
    assert r.asset_path.endswith("OCI Library.xml")


def test_resolve_unknown_provider_raises():
    with pytest.raises(ValueError):
        resolve_asset("nope", "x", None)


# ---------------------------------------------------------------------------
# build_index / serialization
# ---------------------------------------------------------------------------


def test_build_index_and_json_roundtrip(aws_pack, azure_pack):
    idx = build_index({"aws": aws_pack, "azure": azure_pack})
    assert set(idx) == {"aws", "azure"}
    text = index_to_json(idx)
    payload = json.loads(text)
    assert "security-agent" in payload["aws"]
    entry = payload["aws"]["security-agent"]
    assert entry["ext"] == ".svg"
    assert entry["provider"] == "aws"


# ---------------------------------------------------------------------------
# slug-collision logging (P1): two different services must not silently shadow
# ---------------------------------------------------------------------------


def test_index_provider_warns_on_slug_collision(tmp_path, caplog):
    """Two different AWS services whose display names normalize (vendor-stripped)
    to the same slug must WARN — the shadowed service would otherwise vanish
    from the index silently."""
    import logging

    root = tmp_path / "aws"
    svc = root / "Architecture-Service-Icons_07312026"
    # "AWS Cloud Storage" and "AWS Storage" both vendor-strip to slug "storage",
    # but carry distinct display names — a genuine collision.
    (svc / "Arch_Storage" / "32").mkdir(parents=True)
    (svc / "Arch_Storage" / "32" / "Arch_AWS-Cloud-Storage_32.svg").write_text("<svg/>")
    (svc / "Arch_Storage" / "32" / "Arch_AWS-Storage_32.svg").write_text("<svg/>")

    with caplog.at_level(logging.WARNING, logger="rule_engine.asset_index"):
        idx = index_provider("aws", str(root))

    assert "storage" in idx  # last-writer-wins keeps one entry
    assert any("slug collision" in r.message for r in caplog.records)


def test_index_provider_svg_over_png_same_service_no_warning(aws_pack, caplog):
    """An SVG upgrading a PNG for the SAME service (equal display name) is a
    legitimate format upgrade, not a collision — it must not warn."""
    import logging

    with caplog.at_level(logging.WARNING, logger="rule_engine.asset_index"):
        index_provider("aws", aws_pack)  # EKS ships both .svg and .png

    assert not any("slug collision" in r.message for r in caplog.records)
