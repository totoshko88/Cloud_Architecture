"""Property-based test for Icon Resolver provenance (task 7.9).

Feature: multicloud-diagram-inventory, Property 8: Icon and color provenance

Property 8 (design.md): for any successful resolution, the returned icon
identifier and brand color are members of the authoritative asset pack declared
for that Provider Profile. Concretely, the Icon Resolver must never invent or
placeholder a value: every value it returns for a (resource_type, provider) pair
must trace back to that provider's declared mapping file, which itself declares
its authoritative ``asset_pack`` and ``icon_source``.

**Validates: Requirements 2.9**

The test loads each provider's ``mappings/<provider>-icons.yaml`` directly with
PyYAML and cross-checks that :func:`resolve_icon`:

- returns an ``icon_source`` equal to the mapping file's top-level ``icon_source``
  (the provenance anchor declared alongside ``asset_pack``), and
- returns ``brand_hex`` and ``style_string`` that exactly match the values
  declared in that provider's mapping entry for the resolved resource type.

The resolver's documented lookup order is honored: the ``resources`` table
first, then a fallback to ``containers`` for the two structural types
(``boundary`` / ``network_boundary``) — the AWS layout keeps those two only
under ``containers``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    PROVIDERS,
    RESOURCE_TYPES,
    resolve_icon,
)

# Repository root is one level up from tests/ ; mappings/ live at the root.
REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPINGS_DIR = REPO_ROOT / "mappings"


def _load_mapping_file(provider: str) -> Dict[str, Any]:
    """Load a provider mapping directly from disk (independent of the resolver)."""
    path = MAPPINGS_DIR / f"{provider}-icons.yaml"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{path} must parse to a mapping"
    return data


def _declared_entry(data: Dict[str, Any], resource_type: str) -> Optional[Dict[str, Any]]:
    """Return the declared mapping entry using the resolver's lookup order.

    ``resources`` table first, then a fallback to ``containers`` for the two
    structural container kinds only.
    """
    resources = data.get("resources") or {}
    containers = data.get("containers") or {}
    entry = resources.get(resource_type)
    if entry is None and resource_type in CONTAINER_KINDS:
        entry = containers.get(resource_type)
    return entry


# Only exercise (provider, resource_type) pairs that are actually mapped, since
# Property 8 concerns *successful* resolutions. Build that domain up front.
_MAPPED_PAIRS: list[tuple[str, str]] = []
for _provider in PROVIDERS:
    _data = _load_mapping_file(_provider)
    for _rt in RESOURCE_TYPES:
        if _declared_entry(_data, _rt) is not None:
            _MAPPED_PAIRS.append((_provider, _rt))

assert _MAPPED_PAIRS, "expected at least one mapped (provider, resource_type) pair"


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pair=st.sampled_from(_MAPPED_PAIRS))
def test_resolved_icon_and_color_trace_to_declared_asset_pack(
    pair: tuple[str, str],
) -> None:
    """Every resolved id/color comes from the provider's declared mapping.

    Feature: multicloud-diagram-inventory, Property 8: Icon and color provenance
    Validates: Requirements 2.9
    """
    provider, resource_type = pair

    # Cross-check source: the on-disk mapping loaded independently of the resolver.
    data = _load_mapping_file(provider)

    # The mapping file must declare its authoritative asset pack + icon source;
    # these are the provenance anchors every resolved value must trace to.
    declared_asset_pack = data.get("asset_pack")
    declared_icon_source = data.get("icon_source")
    assert declared_asset_pack, f"{provider}: mapping declares no asset_pack"
    assert declared_icon_source, f"{provider}: mapping declares no icon_source"

    declared_entry = _declared_entry(data, resource_type)
    assert declared_entry is not None, (
        f"{provider}.{resource_type}: expected a declared mapping entry"
    )

    resolved = resolve_icon(resource_type, provider)

    # (1) icon_source equals the mapping file's top-level icon_source (the
    #     provenance anchor declared alongside asset_pack).
    assert resolved["icon_source"] == declared_icon_source, (
        f"{provider}.{resource_type}: icon_source {resolved['icon_source']!r} "
        f"does not match declared top-level icon_source {declared_icon_source!r}"
    )

    # (2) brand_hex exactly matches the value declared in the mapping entry;
    #     the resolver does not invent or default a color.
    assert resolved["brand_hex"] == declared_entry.get("brand_hex"), (
        f"{provider}.{resource_type}: brand_hex {resolved['brand_hex']!r} does "
        f"not match declared brand_hex {declared_entry.get('brand_hex')!r}"
    )

    # (3) style_string exactly matches the declared style; every returned style
    #     traces to the declared asset pack mapping (no placeholder).
    assert resolved["style_string"] == declared_entry.get("style"), (
        f"{provider}.{resource_type}: style_string {resolved['style_string']!r} "
        f"does not match declared style {declared_entry.get('style')!r}"
    )

    # No value is empty or a placeholder — provenance requires a concrete source.
    assert resolved["style_string"], f"{provider}.{resource_type}: empty style_string"
    assert resolved["brand_hex"], f"{provider}.{resource_type}: empty brand_hex"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
