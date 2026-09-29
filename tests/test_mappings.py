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
REQUIRED_CONTAINER_KINDS = frozenset({"boundary", "network_boundary"})
# All valid container kinds: the mandatory pair plus the optional OCI
# nested-level styles (Region ⊃ Availability Domain ⊃ Fault Domain, plus Subnet).
CONTAINER_KINDS = frozenset(
    {
        "boundary",
        "network_boundary",
        "region",
        "availability_domain",
        "fault_domain",
        "subnet",
        # 1.10.3 (D19): AWS public subnet + Corporate data center groups.
        "public_subnet",
        "on_premises",
    }
)

# Brand hex must be a single '#' followed by exactly six hex digits.
BRAND_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# AWS resource style prefix per Requirement 2 AC3.
# Updated in 1.10.2 to use official SVG file paths instead of mxgraph.aws4 stencils.
AWS_RESOURCE_STYLE_PREFIX = "image=assets/vendor/aws-icons/"

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
    """The ``containers`` map declares the mandatory pair, plus optional levels.

    Every profile MUST declare ``boundary`` and ``network_boundary`` (Req 2.6).
    A profile MAY additionally declare the optional OCI nested-level kinds
    (``region``/``availability_domain``/``fault_domain``/``subnet``); any key it
    declares must be a recognised container kind, and each must carry a style.
    """
    data = _load(provider)
    containers = data.get("containers") or {}
    declared = set(containers.keys())
    assert set(REQUIRED_CONTAINER_KINDS) <= declared, (
        f"{provider}: containers must declare at least "
        f"{sorted(REQUIRED_CONTAINER_KINDS)}, got {sorted(declared)}"
    )
    unknown = declared - set(CONTAINER_KINDS)
    assert not unknown, (
        f"{provider}: unknown container kind(s) {sorted(unknown)}; "
        f"valid kinds are {sorted(CONTAINER_KINDS)}"
    )
    # Each declared container carries a non-empty style string.
    for kind in declared:
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
# Requirement 2.3 — AWS resource styles use official SVG file paths.
# Updated in 1.10.2 to use official pack SVGs instead of mxgraph.aws4 stencils.
# --------------------------------------------------------------------------- #
def test_aws_resource_styles_use_aws4_resource_icon_prefix() -> None:
    """Every AWS resource style contains the official SVG file path prefix."""
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


# --------------------------------------------------------------------------- #
# OCI canonical v24.2 palette (docs REVIEW.md D17). The official OCI Architecture
# Diagram Toolkit uses a nested neutral-grey nesting system with terracotta
# network elements — never an all-red palette. These tests are the source guard
# that a regression back to red (#F80000 / #C74634) container strokes, or a lost
# Oracle Sans / #312D2A caption, is caught in the mapping before it reaches a
# generated diagram.
# --------------------------------------------------------------------------- #
_OCI_LEGACY_RED = ("#F80000", "#C74634", "#f80000", "#c74634")

# Canonical stroke per container kind, extracted verbatim from the reference
# Physical templates (OCI Style Guide for draw.io v24.2).
_OCI_CONTAINER_STROKE = {
    "boundary": "#AE562C",            # Compartment — terracotta
    "network_boundary": "#AE562C",    # VCN / OSN — terracotta
    "region": "#9E9892",              # OCI Region — neutral grey
    "availability_domain": "#9E9892",  # Availability Domain — neutral grey
    "fault_domain": "#9E9892",        # Fault Domain — neutral grey
    "subnet": "#AE562C",              # Subnet — terracotta (network element)
}

# Canonical fill per container kind (None = transparent / fillColor=none).
_OCI_CONTAINER_FILL = {
    "boundary": None,
    "network_boundary": None,
    "region": "#F5F4F2",
    "availability_domain": "#DFDCD8",
    "fault_domain": "#FCFBFA",
    "subnet": None,
}


def _style_token(style: str, name: str):
    m = re.search(rf"{re.escape(name)}=([^;]*)", style)
    return m.group(1) if m else None


def _assert_oracle_sans(family, where: str) -> None:
    """Oracle Sans first, then a sans-serif fallback.

    Oracle Sans is not a web font and is rarely installed, so a bare
    ``fontFamily=Oracle Sans`` renders in the browser's default SERIF face on
    most machines (and in every CI raster export). The fallback list keeps the
    caption sans-serif wherever Oracle Sans is missing.
    """
    families = [f.strip() for f in (family or "").split(",")]
    assert families[0] == "Oracle Sans", f"{where}: caption must use Oracle Sans, got {family!r}"
    assert families[-1] == "sans-serif", (
        f"{where}: fontFamily must end with a sans-serif fallback, got {family!r}"
    )


def test_oci_container_styles_follow_canonical_v24_palette() -> None:
    """Every OCI container style matches the official v24.2 stroke/fill palette.

    Guards docs REVIEW.md D17: OCI containers use the neutral-grey nested system
    (Region ⊃ AD ⊃ Fault Domain) with terracotta network elements, never the old
    all-red palette. A regression to #F80000 / #C74634, or a wrong fill, fails.
    """
    data = _load("oci")
    containers = data.get("containers") or {}
    for kind, want_stroke in _OCI_CONTAINER_STROKE.items():
        assert kind in containers, f"oci: missing container kind {kind!r}"
        style = containers[kind]["style"]
        # No legacy red anywhere in the style (stroke OR font).
        for red in _OCI_LEGACY_RED:
            assert red not in style, (
                f"oci container {kind}: legacy red {red} present — "
                f"palette regressed to the pre-D17 all-red styling"
            )
        assert _style_token(style, "strokeColor") == want_stroke, (
            f"oci container {kind}: strokeColor must be {want_stroke}, "
            f"got {_style_token(style, 'strokeColor')}"
        )
        want_fill = _OCI_CONTAINER_FILL[kind]
        got_fill = _style_token(style, "fillColor")
        if want_fill is None:
            assert got_fill == "none", (
                f"oci container {kind}: fillColor must be none, got {got_fill}"
            )
        else:
            assert got_fill == want_fill, (
                f"oci container {kind}: fillColor must be {want_fill}, got {got_fill}"
            )
        # Oracle Sans caption everywhere, with a sans-serif fallback.
        _assert_oracle_sans(_style_token(style, "fontFamily"), f"oci container {kind}")


def test_oci_resource_captions_are_oracle_sans_neutral_black() -> None:
    """Every OCI resource node caption uses Oracle Sans + #312D2A, never red text.

    The icon keeps its OCI-red brand fill, but the caption font color must be the
    Oracle near-black #312D2A (docs REVIEW.md D17), so labels read as Oracle's
    unified visual language rather than as red-on-white.
    """
    data = _load("oci")
    resources = data.get("resources") or {}
    assert resources, "oci mapping must declare resources"
    for key, entry in resources.items():
        style = entry.get("style", "")
        _assert_oracle_sans(_style_token(style, "fontFamily"), f"oci.resources.{key}")
        assert _style_token(style, "fontColor") == "#312D2A", (
            f"oci.resources.{key}: caption fontColor must be #312D2A "
            f"(Oracle near-black), got {_style_token(style, 'fontColor')}"
        )


# --------------------------------------------------------------------------- #
# 1.10.3 (REVIEW.md D18): container levels + styles follow each provider's own
# published diagrams, read from the mapping by every HA builder.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
def test_ha_providers_declare_region_and_zone_levels(provider: str) -> None:
    containers = _load(provider).get("containers") or {}
    for kind in ("boundary", "region", "network_boundary", "availability_domain"):
        assert kind in containers, f"{provider}: missing container kind {kind!r}"
        assert containers[kind].get("style"), f"{provider}.{kind}: empty style"


def test_azure_containers_follow_architecture_center_style() -> None:
    c = _load("azure")["containers"]
    vnet = c["network_boundary"]["style"]
    assert _style_token(vnet, "dashPattern") == "1 3", "VNet border is dotted"
    assert _style_token(vnet, "strokeColor") == "#0078D4"
    zone = c["availability_domain"]["style"]
    assert _style_token(zone, "fillColor") == "#F2F2F2"
    assert _style_token(zone, "strokeColor") == "none", "zones are borderless blocks"
    for kind, entry in c.items():
        assert _style_token(entry["style"], "fontColor") == "#000000", (
            f"azure.{kind}: captions are black, never blue on blue"
        )
    # The old AZ stroke #50E6FF was ~1.5:1 on white.
    assert "#50E6FF" not in str(c)


def _contrast_on_white(hex_color: str) -> float:
    def lin(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return 1.05 / (lum + 0.05)


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
def test_container_captions_meet_contrast(provider: str) -> None:
    for kind, entry in (_load(provider).get("containers") or {}).items():
        font = _style_token(entry["style"], "fontColor")
        assert font and _contrast_on_white(font) >= 4.5, (
            f"{provider}.{kind}: caption {font} is below 4.5:1 on white"
        )


# --------------------------------------------------------------------------- #
# 1.10.3 (REVIEW.md D19): vendor group boxes, copied from the draw.io app's own
# AWS / Groups palette, and the Azure VNet/Subnet corner icons.
# --------------------------------------------------------------------------- #
_AWS_OFFICIAL_GROUPS = {
    "boundary": ("group_account", "#CD2264"),
    "region": ("group_region", "#00A4A6"),
    "network_boundary": ("group_vpc2", "#8C4FFF"),
    "subnet": ("group_security_group", "#00A4A6"),
    "public_subnet": ("group_security_group", "#7AA116"),
    "on_premises": ("group_corporate_data_center", "#7D8998"),
}


@pytest.mark.parametrize("kind", sorted(_AWS_OFFICIAL_GROUPS))
def test_aws_containers_use_official_group_shapes(kind: str) -> None:
    style = _load("aws")["containers"][kind]["style"]
    icon, stroke = _AWS_OFFICIAL_GROUPS[kind]
    assert _style_token(style, "grIcon") == f"mxgraph.aws4.{icon}"
    assert _style_token(style, "strokeColor") == stroke


def test_aws_availability_zone_is_the_official_plain_dashed_box() -> None:
    # AWS ships no AZ group icon: the official entry is a dashed #147EBA box.
    style = _load("aws")["containers"]["availability_domain"]["style"]
    assert "grIcon" not in style
    assert _style_token(style, "strokeColor") == "#147EBA"
    assert _style_token(style, "dashed") == "1"


@pytest.mark.parametrize(
    "kind,icon",
    [("network_boundary", "Virtual_Networks.svg"), ("subnet", "Subnet.svg")],
)
def test_azure_network_boxes_carry_their_corner_icon(kind: str, icon: str) -> None:
    style = _load("azure")["containers"][kind]["style"]
    assert _style_token(style, "shape") == "label"
    assert _style_token(style, "image") == f"img/lib/azure2/networking/{icon}"
    assert _style_token(style, "imageAlign") == "left"
    assert _style_token(style, "imageVerticalAlign") == "top"
