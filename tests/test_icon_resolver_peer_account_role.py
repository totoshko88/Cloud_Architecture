"""Theme 34: peer-account / peer-cloud high-level NODE roles.

A high-level view that draws a peer AWS account (or a peer cloud) as a single
NODE — not a captioned container with children — should carry the provider's
own high-level glyph instead of an anonymous grey box:

- AWS  → the AWS Organizations *Account* / *Management-Account* glyph.
- Azure → the Azure Subscriptions glyph (the built-in azure2 shape).
- GCP / OCI / generic → the neutral external box, because those packs ship no
  high-level org glyph (Icon Fidelity forbids a look-alike substitute).

These roles live in the ``resources`` table, so they never collide with the
``peer_account`` / ``external_cloud`` CONTAINER kinds (resolved from the
``containers`` table via ``resolve_container`` / ``_container_style``), which
stay captioned boundary boxes.
"""

from __future__ import annotations

import pytest

from rule_engine.icon_resolver import resolve_icon


@pytest.mark.parametrize("role", ["peer_account", "external_cloud"])
def test_aws_peer_role_uses_organizations_glyph(role):
    r = resolve_icon(role, "aws")
    assert "image=" in r["style_string"]
    assert "Res_AWS-Organizations_" in r["style_string"]
    assert r["style_string"].endswith(".svg")


@pytest.mark.parametrize("role", ["peer_account", "external_cloud"])
def test_azure_peer_role_uses_subscriptions_glyph(role):
    r = resolve_icon(role, "azure")
    assert "img/lib/azure2/general/Subscriptions.svg" in r["style_string"]


@pytest.mark.parametrize("provider", ["gcp", "oci", "generic"])
@pytest.mark.parametrize("role", ["peer_account", "external_cloud"])
def test_other_providers_keep_neutral_box(provider, role):
    r = resolve_icon(role, provider)
    # No high-level org glyph in these packs → neutral dashed box, not an image.
    assert "image=" not in r["style_string"]
    assert "dashed=1" in r["style_string"]
    assert r["brand_hex"] == "#333333"


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci", "generic"])
@pytest.mark.parametrize("role", ["peer_account", "external_cloud"])
def test_all_profiles_resolve(provider, role):
    """Every profile resolves the role (no UnresolvedTypeError), so a NodeSpec
    carrying role=peer_account never crashes regardless of provider."""
    r = resolve_icon(role, provider)
    assert r["style_string"]
