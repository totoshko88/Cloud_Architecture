"""WS10 (1.11.0) — render->index bridge: exact-name only, never a look-alike."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rule_engine import icon_resolver as ir
from rule_engine.asset_index import (
    bridge_resolve_style,
    index_provider,
    normalize_slug,
)

_AWS_PACK = Path.cwd() / "assets" / "vendor" / "aws-icons"
_HAVE_AWS_PACK = _AWS_PACK.is_dir()
pytestmark = pytest.mark.skipif(
    not _HAVE_AWS_PACK, reason="AWS vendor pack not present (git-ignored)"
)


def _mapped_roles():
    m = yaml.safe_load(open("mappings/aws-icons.yaml", encoding="utf-8"))
    return set((m.get("resources") or {}).keys()) | set((m.get("containers") or {}).keys())


def _an_unmapped_exact_slug():
    idx = index_provider("aws", str(_AWS_PACK))
    mapped = _mapped_roles()
    for slug in sorted(idx):
        if slug not in mapped and "-" in slug:
            return slug
    return None


def test_bridge_resolves_an_exact_unmapped_service():
    slug = _an_unmapped_exact_slug()
    assert slug is not None, "no un-mapped pack slug to test against"
    res = bridge_resolve_style(slug, "aws")
    assert res is not None
    assert "image=" in res["style_string"]
    assert res["icon_source"] == "custom"
    assert res["brand_hex"].startswith("#")


def test_bridge_never_substitutes_a_look_alike():
    # Property 11: a name that is NOT an exact slug must resolve to None, even if
    # it shares tokens with a real asset. The bridge is exact-slug only, so a
    # near-miss can never draw a different service's icon.
    assert bridge_resolve_style("zzz-not-a-real-service-xyz", "aws") is None
    # a partial of a real multi-token service is still not exact -> None
    idx = index_provider("aws", str(_AWS_PACK))
    multi = next((s for s in idx if s.count("-") >= 2), None)
    if multi:
        partial = multi.split("-")[0]  # one token of a multi-token slug
        if partial not in idx:  # only assert when the partial is itself not a slug
            assert bridge_resolve_style(partial, "aws") is None


def test_oci_has_no_file_bridge():
    # OCI is a shape library, not per-service files — no file bridge.
    assert bridge_resolve_style("anything", "oci") is None


def test_resolve_icon_uses_the_bridge_for_an_exact_unmapped_service():
    slug = _an_unmapped_exact_slug()
    assert slug is not None
    res = ir.resolve_icon(slug, "aws")   # must not raise now
    assert res["style_string"] and "image=" in res["style_string"]


def test_resolve_icon_still_fails_honestly_on_a_nonsense_role():
    with pytest.raises(ir.UnresolvedTypeError):
        ir.resolve_icon("zzz-not-a-real-service-xyz", "aws")


def test_mapped_role_is_unchanged_by_the_bridge():
    # A curated mapping entry resolves exactly as before (the bridge is only a
    # fallback on UnresolvedTypeError, never consulted for a mapped role).
    r = ir.resolve_icon("serverless_fn", "aws")
    assert r["style_string"] and r["brand_hex"].startswith("#")
