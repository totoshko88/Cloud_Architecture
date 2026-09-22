"""Property-based test for the Icon Resolver (task 7.4).

Feature: multicloud-diagram-inventory, Property 3: AWS style strings use the aws4 resource-icon form

Property 3 — AWS style strings use the aws4 resource-icon form
(Validates: Requirements 2.3):
For any mapped Normalized Resource Type resolved for provider ``aws``, the
returned style string contains the prefix
``shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.``.

Scope: this property applies to the AWS *service* resource types — the seven
types declared under the mapping's ``resources`` table. Those carry the AWS
2019+ built-in resource-icon form. The two structural types (``boundary`` and
``network_boundary``) live under ``containers`` and use the group style
``shape=mxgraph.aws4.group`` rather than the resourceIcon form, so they are
outside this property's domain.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import load_mapping, resolve_icon

#: Prefix that every AWS service resource-icon style string must contain.
_AWS4_RESOURCE_ICON_PREFIX = "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4."


def _aws_resource_types() -> list[str]:
    """The AWS service resource types declared under ``resources``."""
    data = load_mapping("aws")
    resources = data.get("resources") or {}
    return sorted(resources.keys())


# Sampled from the actual AWS `resources` service-type keys.
_AWS_RESOURCE_TYPES = _aws_resource_types()


@settings(max_examples=100)
@given(resource_type=st.sampled_from(_AWS_RESOURCE_TYPES))
def test_aws_style_uses_aws4_resource_icon_form(resource_type: str) -> None:
    """AWS service style strings carry the aws4 resource-icon prefix.

    Feature: multicloud-diagram-inventory, Property 3: AWS style strings use the aws4 resource-icon form
    Validates: Requirements 2.3
    """
    result = resolve_icon(resource_type, "aws")

    style_string = result["style_string"]
    assert _AWS4_RESOURCE_ICON_PREFIX in style_string, (
        f"aws/{resource_type}: expected style string to contain "
        f"{_AWS4_RESOURCE_ICON_PREFIX!r}, got {style_string!r}"
    )


def test_aws_resource_types_is_non_empty() -> None:
    """Sanity guard: AWS declares service resource types to sample from."""
    assert _AWS_RESOURCE_TYPES, "expected a non-empty AWS resources table"
