"""WS6 (1.11.0) — data-defined diagram-type profile tests."""

from __future__ import annotations

from rule_engine.diagram_profiles import TypeProfile, load_type_profile


def test_unknown_and_empty_resolve_to_none():
    assert load_type_profile(None) is None
    assert load_type_profile("") is None
    assert load_type_profile("does-not-exist") is None


def test_network_profile_fields():
    p = load_type_profile("network")
    assert isinstance(p, TypeProfile)
    assert p.name == "network"
    assert p.base_class == "landscape"      # Req 6 AC1
    assert p.axis == "left-right"
    assert p.lint_profile == "network"
    assert "security_group" in p.special_containers
    # the 5 WS6 network roles are declared allowed
    for r in ("transit_gateway", "vpn_gateway", "direct_connect",
              "route_table", "network_firewall"):
        assert r in p.allowed_roles


def test_profile_whitespace_type_is_trimmed():
    assert load_type_profile("  network  ") is not None


def test_type_profile_is_frozen():
    p = load_type_profile("network")
    try:
        p.base_class = "flow"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("TypeProfile must be frozen")
