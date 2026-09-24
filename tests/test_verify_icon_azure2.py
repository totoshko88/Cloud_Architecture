"""Tests for azure2 icon-path verification (v1.3.x gap closure).

The Azure `azure2` shapes ship inside the draw.io app, so a well-formed but
non-existent path (`…/Azure_Cache_Redis.svg` vs the real `Cache_Redis.svg`)
rendered as a broken image and passed every guard. These tests pin that the
committed `mappings/azure2-shapes.json` allow-list now catches it.
"""

from __future__ import annotations

import json
import os

from rule_engine.azure2_shapes import DEFAULT_MANIFEST, load_manifest
from rule_engine.verify_icon import _resolve_azure2, RESOLVED, SKIPPED, UNRESOLVED, verify_drawio

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_manifest_present_and_nonempty():
    m = load_manifest()
    assert m is not None and len(m) > 100  # the azure2 library has hundreds of shapes


def test_resolve_known_azure2_path():
    m = load_manifest()
    # Cache_Redis is the real databases icon; Azure_Cache_Redis is the old typo.
    assert _resolve_azure2("img/lib/azure2/databases/Cache_Redis.svg", m)[0] == RESOLVED


def test_resolve_flags_nonexistent_azure2_path():
    m = load_manifest()
    status, detail = _resolve_azure2("img/lib/azure2/databases/Azure_Cache_Redis.svg", m)
    assert status == UNRESOLVED
    assert "broken-image" in detail


def test_resolve_skips_when_manifest_absent():
    assert _resolve_azure2("img/lib/azure2/databases/Cache_Redis.svg", None)[0] == SKIPPED


def test_azure_landscape_all_azure2_resolved():
    report = verify_drawio(
        os.path.join(HERE, "examples", "azure", "02-azure-ha-multiregion-landscape.drawio")
    )
    az = [r for r in report["references"] if r["kind"] == "azure2"]
    assert az, "expected azure2 image references"
    assert all(r["status"] == RESOLVED for r in az), [r for r in az if r["status"] != RESOLVED]


def test_manifest_is_deterministic_sorted():
    data = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert data["paths"] == sorted(data["paths"])
    assert data["count"] == len(data["paths"])
