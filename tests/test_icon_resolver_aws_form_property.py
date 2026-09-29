"""Property-based test for the Icon Resolver (task 7.4).

Feature: multicloud-diagram-inventory, Property 3: AWS style strings use official SVG file paths

Property 3 — AWS style strings use official SVG file paths (updated 1.10.2)
(Validates: Requirements 2.3):
For any mapped Normalized Resource Type resolved for provider ``aws``, the
returned style string contains the prefix ``image=assets/vendor/aws-icons/``,
referencing the official AWS SVG icon pack.

This was updated in v1.10.2 to migrate AWS from the legacy ``mxgraph.aws4.*``
stencils to official SVG file paths, consistent with Azure and GCP.

Scope: this property applies to the AWS *service* resource types — the types
declared under the mapping's ``resources`` table. The two structural types
(``boundary`` and ``network_boundary``) live under ``containers`` and use the
group style ``shape=mxgraph.aws4.group`` (which is a container shape, not a
service icon).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import load_mapping, resolve_icon

#: Prefix that every AWS service resource style string must contain (1.10.2+).
_AWS_IMAGE_PREFIX = "image=assets/vendor/aws-icons/"


def _aws_resource_types() -> list[str]:
    """The AWS service resource types declared under ``resources``."""
    data = load_mapping("aws")
    resources = data.get("resources") or {}
    return sorted(resources.keys())


# Sampled from the actual AWS `resources` service-type keys.
_AWS_RESOURCE_TYPES = _aws_resource_types()


@settings(max_examples=100)
@given(resource_type=st.sampled_from(_AWS_RESOURCE_TYPES))
def test_aws_style_uses_official_svg_file_paths(resource_type: str) -> None:
    """AWS service style strings use official SVG file paths.

    Feature: multicloud-diagram-inventory, Property 3: AWS style strings use official SVG file paths
    Validates: Requirements 2.3
    """
    result = resolve_icon(resource_type, "aws")

    style_string = result["style_string"]
    assert _AWS_IMAGE_PREFIX in style_string, (
        f"aws/{resource_type}: expected style string to contain "
        f"{_AWS_IMAGE_PREFIX!r}, got {style_string!r}"
    )


def test_aws_resource_types_is_non_empty() -> None:
    """Sanity guard: AWS declares service resource types to sample from."""
    assert _AWS_RESOURCE_TYPES, "expected a non-empty AWS resources table"
