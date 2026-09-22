"""Unit tests for the per-provider icon mapping tables (task 3.4).

Validates the ``mappings/<provider>-icons.yaml`` files against:

- Requirement 9.3 / R7 AC10: every mapping defines all nine neutral resource
  types (Boundary, Network Boundary, serverless function, object store, managed
  SQL, message queue, secrets store, managed Kubernetes, LLM platform).
- Requirement 2.6: exactly one Boundary and one Network Boundary container
  group style per provider.
- Requirement 2.2: every entry that carries a brand hex formats it as a single
  ``#`` followed by exactly six hexadecimal digits (``#RRGGBB``).
- Requirement 2.3: AWS resource styles use the AWS 2019+ shape library form
  ``shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.<service>``.
- Requirement 2.7: the generic profile contains no vendor icon token and uses
  only grayscale colors.

Tests load each YAML file with PyYAML; they do not import the rule engine so
they exercise the on-disk mapping data directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# Repository root is two levels up from this test file (tests/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPINGS_DIR = REPO_ROOT / "mappings"

# All five provider profiles.
PROVIDERS = ("aws", "azure", "gcp", "oci", "generic")

# The nine neutral resource types (Requirement 9 AC10). Boundary and
# network_boundary are the two structural/container concepts.
NEUTRAL_CONCEPTS = frozenset(
    {
        "boundary",
        "network_boundary",
        "serverless_fn",
        "object_store",
        "managed_sql",
        "message_queue",
        "secrets_store",
        "managed_k8s",
        "llm_platform",
    }
)

# The two container concepts every profile must declare exactly.
CONTAINER_KINDS = frozenset({"boundary", "network_boundary"})

# Brand hex must be a single '#' followed by exactly six hex digits.
BRAND_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# AWS resource style prefix per Requirement 2 AC3.
AWS_RESOURCE_STYLE_PREFIX = "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4."

# Vendor icon tokens that must never appear in the generic profile.
VENDOR_ICON_TOKENS = (
    "mxgraph.aws4",
    "resIcon=",
    "grIcon=",
    "mxgraph.azure",
    "mxgraph.gcp",
    "mxgraph.oci",
)

# Any hex color that is grayscale has equal R, G, and B components. The generic
# profile also uses the keyword ``none`` for container fills.
HEX_COLOR_RE = re.compile(r"#([0-9A-Fa-f]{6})")


def _load(provider: str) -> dict:
    """Load and parse a provider mapping file."""
    path = MAPPINGS_DIR / f"{provider}-icons.yaml"
    assert path.exists(), f"mapping file missing: {path}"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{path} must parse to a mapping"
    return data


def _covered_concepts(data: dict) -> set:
    """The union of concepts declared under ``resources`` and ``containers``."""
    resources = data.get("resources") or {}
    containers = data.get("containers") or {}
    return set(resources.keys()) | set(containers.keys())


def _iter_entries(data: dict):
    """Yield (section, key, entry) for every resource and container entry."""
    for section in ("resources", "containers"):
        for key, entry in (data.get(section) or {}).items():
            yield section, key, entry


def _is_grayscale(hex6: str) -> bool:
    r, g, b = hex6[0:2], hex6[2:4], hex6[4:6]
    return r.lower() == g.lower() == b.lower()


# --------------------------------------------------------------------------- #
# Requirement 9.3 / R7 AC10 — all nine neutral concepts covered.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", PROVIDERS)
def test_all_nine_neutral_concepts_covered(provider: str) -> None:
    """Every mapping covers all nine neutral resource types."""
    data = _load(provider)
    covered = _covered_concepts(data)
    missing = NEUTRAL_CONCEPTS - covered
    assert not missing, f"{provider}: missing neutral concepts {sorted(missing)}"


# --------------------------------------------------------------------------- #
# Requirement 2.6 — exactly one boundary and one network_boundary container.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", PROVIDERS)
def test_exactly_one_boundary_and_network_boundary_container(provider: str) -> None:
    """The ``containers`` map declares exactly {boundary, network_boundary}."""
    data = _load(provider)
    containers = data.get("containers") or {}
    assert set(containers.keys()) == CONTAINER_KINDS, (
        f"{provider}: containers must be exactly {sorted(CONTAINER_KINDS)}, "
        f"got {sorted(containers.keys())}"
    )
    # Each declared container carries a non-empty style string.
    for kind in CONTAINER_KINDS:
        style = (containers[kind] or {}).get("style")
        assert style and style.strip(), (
            f"{provider}: container {kind} must declare a non-empty style"
        )


# --------------------------------------------------------------------------- #
# Requirement 2.2 — every brand hex present is #RRGGBB.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", PROVIDERS)
def test_brand_hex_is_rrggbb(provider: str) -> None:
    """Every entry that carries a brand_hex formats it as #RRGGBB."""
    data = _load(provider)
    seen = 0
    for section, key, entry in _iter_entries(data):
        assert isinstance(entry, dict), f"{provider}.{section}.{key} must be a mapping"
        brand_hex = entry.get("brand_hex")
        if brand_hex is None:
            continue
        seen += 1
        assert BRAND_HEX_RE.match(brand_hex), (
            f"{provider}.{section}.{key}: brand_hex must match #RRGGBB, "
            f"got {brand_hex!r}"
        )
    assert seen > 0, f"{provider}: expected at least one brand_hex entry"


@pytest.mark.parametrize("provider", ("aws", "azure", "gcp", "oci", "generic"))
def test_every_resource_entry_has_brand_hex(provider: str) -> None:
    """Every resource entry carries a #RRGGBB brand hex per resource."""
    data = _load(provider)
    resources = data.get("resources") or {}
    for key, entry in resources.items():
        brand_hex = entry.get("brand_hex")
        assert brand_hex, f"{provider}.resources.{key}: missing brand_hex"
        assert BRAND_HEX_RE.match(brand_hex), (
            f"{provider}.resources.{key}: brand_hex must match #RRGGBB, "
            f"got {brand_hex!r}"
        )


# --------------------------------------------------------------------------- #
# Requirement 2.3 — AWS resource styles use the aws4 resourceIcon prefix.
# --------------------------------------------------------------------------- #
def test_aws_resource_styles_use_aws4_resource_icon_prefix() -> None:
    """Every AWS resource style contains the aws4 resourceIcon prefix."""
    data = _load("aws")
    resources = data.get("resources") or {}
    assert resources, "aws mapping must declare resources"
    for key, entry in resources.items():
        style = entry.get("style", "")
        assert AWS_RESOURCE_STYLE_PREFIX in style, (
            f"aws.resources.{key}: style must contain "
            f"{AWS_RESOURCE_STYLE_PREFIX!r}, got {style!r}"
        )


# --------------------------------------------------------------------------- #
# Requirement 2.7 — generic profile has no vendor icon token; grayscale only.
# --------------------------------------------------------------------------- #
def test_generic_styles_contain_no_vendor_icon_token() -> None:
    """No generic style string contains a vendor icon token."""
    data = _load("generic")
    for section, key, entry in _iter_entries(data):
        style = entry.get("style", "")
        for token in VENDOR_ICON_TOKENS:
            assert token not in style, (
                f"generic.{section}.{key}: style must not contain vendor token "
                f"{token!r}, got {style!r}"
            )


def test_generic_colors_are_grayscale() -> None:
    """Every color in the generic profile is grayscale (R == G == B)."""
    data = _load("generic")
    for section, key, entry in _iter_entries(data):
        # brand_hex must be grayscale.
        brand_hex = entry.get("brand_hex")
        if brand_hex:
            assert BRAND_HEX_RE.match(brand_hex), (
                f"generic.{section}.{key}: bad brand_hex {brand_hex!r}"
            )
            assert _is_grayscale(brand_hex[1:]), (
                f"generic.{section}.{key}: brand_hex must be grayscale, "
                f"got {brand_hex!r}"
            )
        # every hex color embedded in the style string must be grayscale.
        style = entry.get("style", "")
        for hex6 in HEX_COLOR_RE.findall(style):
            assert _is_grayscale(hex6), (
                f"generic.{section}.{key}: non-grayscale color #{hex6} in style "
                f"{style!r}"
            )
