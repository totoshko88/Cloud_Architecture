"""Theme 35: open-source brand NODE roles (Keycloak / Redis / PostgreSQL).

Mirror the ``mongodb_atlas`` pattern: on the vendor profiles each role resolves
to its colorized Simple Icons leaf under the git-ignored
``assets/vendor/opensource-colorized/`` dir (identification use, file path only,
populated by ``rule-engine-build-icon-sets --update-pins``); on ``generic`` it is
a neutral labelled box. Curated in ``asset-sources.yaml`` -> ``opensource.icons``.
"""

from __future__ import annotations

import pytest

from rule_engine.icon_resolver import resolve_icon

_BRANDS = ("keycloak", "redis", "postgresql")
_SLUG = {"keycloak": "keycloak", "redis": "redis", "postgresql": "postgresql"}


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
@pytest.mark.parametrize("role", _BRANDS)
def test_vendor_profiles_use_colorized_leaf(provider, role):
    r = resolve_icon(role, provider)
    assert (
        f"assets/vendor/opensource-colorized/{_SLUG[role]}.svg" in r["style_string"]
    )


@pytest.mark.parametrize("role", _BRANDS)
def test_generic_keeps_neutral_box(role):
    r = resolve_icon(role, "generic")
    assert "image=" not in r["style_string"]
    assert r["brand_hex"] == "#333333"


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci", "generic"])
@pytest.mark.parametrize("role", _BRANDS)
def test_all_profiles_resolve(provider, role):
    assert resolve_icon(role, provider)["style_string"]
