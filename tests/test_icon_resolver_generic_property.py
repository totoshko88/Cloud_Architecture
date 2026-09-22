"""Property-based test for the generic Icon Resolver profile (task 7.7).

Feature: multicloud-diagram-inventory, Property 6: Generic profile is grayscale and vendor-icon-free

Property 6 (design.md) — Generic profile is grayscale and vendor-icon-free
(**Validates: Requirements 2.7**):

    WHERE the Provider is ``generic``, THE Icon Resolver SHALL return only plain
    rectangle shapes or UML shapes, SHALL restrict fill and stroke colors to
    grayscale values ranging from white to black, and SHALL exclude all vendor
    icons.

For any mapped Normalized Resource Type resolved for provider ``generic`` (and
for both container kinds resolved via :func:`resolve_container`), this test
asserts that:

- the returned ``style_string`` contains none of the vendor icon tokens
  (``mxgraph.aws4``, ``resIcon=``, ``grIcon=``, ``mxgraph.azure``,
  ``mxgraph.gcp``, ``mxgraph.oci``), and
- every embedded ``#RRGGBB`` color in the style is grayscale (``R == G == B``),
  and
- the resolved ``brand_hex`` is itself grayscale.
"""

from __future__ import annotations

import re
from typing import Iterable

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    load_mapping,
    resolve_container,
    resolve_icon,
)

# Vendor icon / shape tokens that must never appear in a generic style string.
# `resIcon=` and `grIcon=` are the AWS4 resource- and group-icon keys; the
# `mxgraph.<vendor>` prefixes are the per-vendor draw.io shape libraries.
_VENDOR_TOKENS: tuple[str, ...] = (
    "mxgraph.aws4",
    "resIcon=",
    "grIcon=",
    "mxgraph.azure",
    "mxgraph.gcp",
    "mxgraph.oci",
)

#: Matches any #RRGGBB hex color embedded in a draw.io style string.
_HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def _is_grayscale(hex_color: str) -> bool:
    """True iff a #RRGGBB color has equal red, green, and blue channels."""
    value = hex_color.lstrip("#")
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return r == g == b


def _embedded_colors(style: str) -> list[str]:
    """Return every #RRGGBB color literal embedded in a style string."""
    return _HEX_COLOR_RE.findall(style)


def _assert_no_vendor_tokens(style: str, label: str) -> None:
    for token in _VENDOR_TOKENS:
        assert token not in style, (
            f"generic {label}: style contains forbidden vendor token "
            f"{token!r}: {style!r}"
        )


def _assert_all_grayscale(colors: Iterable[str], label: str) -> None:
    for color in colors:
        assert _is_grayscale(color), (
            f"generic {label}: embedded color {color!r} is not grayscale "
            f"(R==G==B)"
        )


# The mapped resource types for the generic profile, sourced directly from the
# mapping file so the domain reflects the real contents.
_GENERIC_RESOURCE_TYPES: list[str] = sorted(
    (load_mapping("generic").get("resources") or {}).keys()
)

assert _GENERIC_RESOURCE_TYPES, "expected the generic profile to map resources"


@settings(max_examples=200)
@given(resource_type=st.sampled_from(_GENERIC_RESOURCE_TYPES))
def test_generic_resolve_icon_is_grayscale_and_vendor_free(
    resource_type: str,
) -> None:
    """Every generic resolve_icon result is grayscale and vendor-icon-free.

    Feature: multicloud-diagram-inventory, Property 6: Generic profile is grayscale and vendor-icon-free
    Validates: Requirements 2.7
    """
    result = resolve_icon(resource_type, "generic")

    style = result["style_string"]
    brand_hex = result["brand_hex"]

    # (1) No vendor icon token appears in the style string.
    _assert_no_vendor_tokens(style, f"resource {resource_type}")

    # (2) Every embedded #RRGGBB color in the style is grayscale.
    _assert_all_grayscale(
        _embedded_colors(style), f"resource {resource_type} style"
    )

    # (3) The brand_hex is itself grayscale.
    assert _is_grayscale(brand_hex), (
        f"generic resource {resource_type}: brand_hex {brand_hex!r} is not "
        f"grayscale (R==G==B)"
    )


@settings(max_examples=200)
@given(kind=st.sampled_from(CONTAINER_KINDS))
def test_generic_resolve_container_is_grayscale_and_vendor_free(
    kind: str,
) -> None:
    """Every generic container style is grayscale and vendor-icon-free.

    Feature: multicloud-diagram-inventory, Property 6: Generic profile is grayscale and vendor-icon-free
    Validates: Requirements 2.7
    """
    result = resolve_container(kind, "generic")
    style = result["style_string"]

    # No vendor icon token, and every embedded #RRGGBB color is grayscale.
    # (Container styles may declare fillColor=none, which carries no color.)
    _assert_no_vendor_tokens(style, f"container {kind}")
    _assert_all_grayscale(_embedded_colors(style), f"container {kind} style")
