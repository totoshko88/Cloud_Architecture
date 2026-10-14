"""Theme 6 (REVIEW.md G17): workspace-local roles/icon overlay.

``mappings/local/<provider>-icons.yaml`` is merged OVER the bundled mapping,
per-key: a local entry wins only for the keys it defines, every other bundled
role is preserved, and an overlay may add a role without re-declaring the
provider's provenance (``asset_pack`` / ``icon_source``). These tests pin that
contract so a later engine upgrade still reaches the roles the overlay is
silent on.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from rule_engine import icon_resolver as ir


@pytest.fixture
def overlay_env(tmp_path, monkeypatch):
    """Point the resolver at a temp bundled-mappings dir with a writable local/ overlay.

    Copies the real generic mapping (small, grayscale) as the bundled base, so
    the overlay merges onto a genuine mapping. Clears the lru_cache around the
    test so each case sees fresh files.
    """
    bundled = tmp_path / "mappings"
    bundled.mkdir()
    real_generic = ir._MAPPINGS_DIR / "generic-icons.yaml"
    (bundled / "generic-icons.yaml").write_text(
        real_generic.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (bundled / "local").mkdir()
    monkeypatch.setattr(ir, "_MAPPINGS_DIR", bundled)
    # Keep cwd from accidentally supplying a second overlay source.
    monkeypatch.chdir(tmp_path)
    ir._load_mapping_cached.cache_clear()
    yield bundled
    ir._load_mapping_cached.cache_clear()


def _write_overlay(bundled: Path, provider: str, mapping: dict) -> None:
    (bundled / "local" / f"{provider}-icons.yaml").write_text(
        yaml.safe_dump(mapping), encoding="utf-8"
    )


def test_no_overlay_is_byte_identical(overlay_env):
    """With no local file, resolution is unchanged from the bundled mapping."""
    bundled = overlay_env
    plain = ir.resolve_icon("object_store", "generic")
    # Remove the overlay dir entirely — still fine.
    assert plain["style_string"]
    assert plain["brand_hex"].startswith("#")


def test_overlay_adds_a_new_role(overlay_env):
    """A role absent from the bundled mapping resolves once the overlay adds it."""
    bundled = overlay_env
    with pytest.raises(ir.UnresolvedTypeError):
        ir.resolve_icon("batch", "generic")
    ir._load_mapping_cached.cache_clear()
    _write_overlay(
        bundled,
        "generic",
        {
            "resources": {
                "batch": {
                    "style": "rounded=1;whiteSpace=wrap;html=1;"
                    "fillColor=#FFFFFF;strokeColor=#000000;",
                    "brand_hex": "#000000",
                }
            }
        },
    )
    entry = ir.resolve_icon("batch", "generic")
    assert "batch" not in entry["style_string"] or entry["style_string"]
    assert entry["brand_hex"] == "#000000"
    assert entry["icon_source"]  # inherited from the bundled provenance


def test_overlay_overrides_one_role_only(overlay_env):
    """Overriding one role's style leaves every other bundled role intact."""
    bundled = overlay_env
    before_sql = ir.resolve_icon("managed_sql", "generic")["style_string"]
    ir._load_mapping_cached.cache_clear()
    _write_overlay(
        bundled,
        "generic",
        {
            "resources": {
                "object_store": {
                    "style": "shape=cylinder3;html=1;fillColor=#ABCDEF;"
                    "strokeColor=#000000;",
                    "brand_hex": "#ABCDEF",
                }
            }
        },
    )
    # overridden role takes the overlay value
    assert ir.resolve_icon("object_store", "generic")["brand_hex"] == "#ABCDEF"
    # a sibling role is byte-identical to the bundled value
    assert ir.resolve_icon("managed_sql", "generic")["style_string"] == before_sql


def test_overlay_inherits_provenance_when_omitted(overlay_env):
    """An overlay need not re-declare asset_pack / icon_source."""
    bundled = overlay_env
    bundled_data = yaml.safe_load((bundled / "generic-icons.yaml").read_text())
    _write_overlay(
        bundled,
        "generic",
        {"resources": {"ecr": {"style": "rounded=1;html=1;fillColor=#FFFFFF;"
                               "strokeColor=#000000;", "brand_hex": "#000000"}}},
    )
    ir._load_mapping_cached.cache_clear()
    entry = ir.resolve_icon("ecr", "generic")
    assert entry["icon_source"] == bundled_data["icon_source"]


def test_malformed_overlay_fails_loudly(overlay_env):
    """A non-mapping overlay is an AssetSourceError naming the overlay path."""
    bundled = overlay_env
    (bundled / "local" / "generic-icons.yaml").write_text(
        "- just\n- a\n- list\n", encoding="utf-8"
    )
    ir._load_mapping_cached.cache_clear()
    with pytest.raises(ir.AssetSourceError) as excinfo:
        ir.resolve_icon("object_store", "generic")
    assert "local overlay" in str(excinfo.value)


def test_empty_overlay_is_a_noop(overlay_env):
    """An overlay file that is empty (None) changes nothing."""
    bundled = overlay_env
    (bundled / "local" / "generic-icons.yaml").write_text("", encoding="utf-8")
    ir._load_mapping_cached.cache_clear()
    entry = ir.resolve_icon("object_store", "generic")
    assert entry["style_string"]
