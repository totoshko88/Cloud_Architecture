"""Unit tests for asset enumeration (task 2.3).

Validates Requirement 2.9: each provider's ``inventory.json`` is non-empty and
every enumerated icon entry carries a non-empty icon id and a ``#RRGGBB`` brand
hex.

Tests use a ``tmp_path`` assets root so they never depend on real downloads
(the enumeration module ships an offline-safe seed inventory, so a fresh empty
staging directory still yields a non-empty inventory per provider).
"""

from __future__ import annotations

import json
import re

import pytest

from rule_engine.assets.enumerate import (
    build_inventory,
    write_all_inventories,
    write_inventory,
    SEED_INVENTORY,
)

# The four vendor providers that ship a seed inventory. ``generic`` carries no
# vendor asset pack and is intentionally excluded.
PROVIDERS = ("aws", "azure", "gcp", "oci")

# Brand hex must be a single '#' followed by exactly six hex digits.
BRAND_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _assert_icon_valid(icon) -> None:
    """Assert a single enumerated icon has a non-empty id and a #RRGGBB hex."""
    assert icon.icon_id, f"icon id must be non-empty: {icon!r}"
    assert isinstance(icon.icon_id, str)
    assert icon.icon_id.strip(), f"icon id must not be blank: {icon!r}"
    assert BRAND_HEX_RE.match(icon.brand_hex), (
        f"brand hex must match #RRGGBB, got {icon.brand_hex!r} for {icon!r}"
    )


def test_all_four_providers_have_seed_inventories() -> None:
    """Every vendor provider ships a curated seed inventory."""
    for provider in PROVIDERS:
        assert provider in SEED_INVENTORY
        assert len(SEED_INVENTORY[provider]) > 0


@pytest.mark.parametrize("provider", PROVIDERS)
def test_build_inventory_is_non_empty(provider: str, tmp_path) -> None:
    """build_inventory yields a non-empty inventory for each provider (offline)."""
    inventory = build_inventory(provider, assets_root=tmp_path)

    assert inventory.provider == provider
    assert len(inventory.icons) > 0, f"{provider} inventory must be non-empty"
    assert inventory.authoritative_asset_pack, "asset pack id must be recorded"
    assert inventory.icon_source in ("builtin", "custom")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_build_inventory_every_icon_has_id_and_brand_hex(provider: str, tmp_path) -> None:
    """Every enumerated icon carries a non-empty id and a #RRGGBB brand hex."""
    inventory = build_inventory(provider, assets_root=tmp_path)

    for icon in inventory.icons:
        _assert_icon_valid(icon)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_write_inventory_json_non_empty_and_well_formed(provider: str, tmp_path) -> None:
    """The written inventory.json is non-empty; every entry has id + #RRGGBB hex."""
    target = write_inventory(provider, assets_root=tmp_path)

    assert target.exists()
    assert target.name == "inventory.json"
    assert target.parent.name == provider

    data = json.loads(target.read_text(encoding="utf-8"))

    assert data["provider"] == provider
    assert data["authoritative_asset_pack"]
    assert data["icon_source"] in ("builtin", "custom")

    icons = data["icons"]
    assert isinstance(icons, list)
    assert len(icons) > 0, f"{provider} inventory.json must be non-empty"
    assert data["icon_count"] == len(icons)

    for entry in icons:
        icon_id = entry.get("icon_id")
        assert icon_id, f"every entry must carry an icon id: {entry!r}"
        assert icon_id.strip(), f"icon id must not be blank: {entry!r}"

        brand_hex = entry.get("brand_hex")
        assert brand_hex, f"every entry must carry a brand hex: {entry!r}"
        assert BRAND_HEX_RE.match(brand_hex), (
            f"brand hex must match #RRGGBB, got {brand_hex!r} for {entry!r}"
        )


def test_write_all_inventories_covers_every_provider(tmp_path) -> None:
    """write_all_inventories writes a non-empty inventory.json for each provider."""
    written = write_all_inventories(assets_root=tmp_path)

    for provider in PROVIDERS:
        assert provider in written
        path = written[provider]
        assert path.exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["icons"]) > 0, f"{provider} inventory.json must be non-empty"
        for entry in data["icons"]:
            assert entry.get("icon_id"), f"missing icon id: {entry!r}"
            assert BRAND_HEX_RE.match(entry.get("brand_hex", "")), (
                f"bad brand hex for {entry!r}"
            )
