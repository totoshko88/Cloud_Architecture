"""Property + unit tests for the ``ip-range`` lint rule (1.10.0, Part C).

Requirement 3 (provider-diagram-conventions): a network diagram must use the
reserved documentation ranges (RFC5737 IPv4 TEST-NET blocks, RFC3849 IPv6
`2001:db8::/32`) or a private range, never a routable public address that could
leak or collide with a real network (AWS Networking convention). The rule scans
a Network_Diagram's on-diagram text (node labels, edge labels, the Legend, the
Flow list) for a Public_IP_Literal.

Property 3 (design.md): IP classification is correct and scoped — a
Documentation_Range or a private IP never trips ``ip-range``; a public literal
trips it only in a Network_Diagram (a ``landscape`` class OR a companion
``diagram_type`` of network / infrastructure / deployment). A token that looks
address-like but does not parse under ``ipaddress`` is ignored.

**Validates: Requirements 3.1, 3.2, 3.3**
"""

from __future__ import annotations

import ipaddress

from hypothesis import assume, given
from hypothesis import strategies as st

from rule_engine.linter import (
    DOCUMENTATION_RANGES,
    RULE_IP_RANGE,
    RULE_SEVERITIES,
    Artifact,
    Edge,
    Severity,
    _is_documentation_ip,
    _is_private_ip,
    lint,
)


def _flagged(node_names=(), *, diagram_class="flow", diagram_type=None,
             edges=(), legend_lines=None, title_cell=None) -> bool:
    a = Artifact(
        kind="diagram",
        node_names=list(node_names),
        edges=list(edges),
        diagram_class=diagram_class,
        diagram_type=diagram_type,
        legend_lines=legend_lines,
        title_cell=title_cell,
    )
    return RULE_IP_RANGE in {f["rule"] for f in lint(a)["findings"]}


# --------------------------------------------------------------------------- #
# Unit cases — the concrete corners of the rule.
# --------------------------------------------------------------------------- #


def test_public_ip_in_landscape_is_flagged():
    """A routable public IPv4 in a landscape's node label trips the rule."""
    assert _flagged(["ingress 8.8.8.8"], diagram_class="landscape")


def test_public_ip_in_network_type_is_flagged():
    """A public IP in a companion ``diagram_type=network`` diagram trips it."""
    assert _flagged(["gw 1.1.1.1"], diagram_type="network")
    assert _flagged(["gw 1.1.1.1"], diagram_type="infrastructure")
    assert _flagged(["gw 1.1.1.1"], diagram_type="deployment")


def test_public_ip_in_flow_diagram_is_not_flagged():
    """A flow/application diagram is not a Network_Diagram — never evaluated."""
    assert not _flagged(["gw 8.8.8.8"], diagram_class="flow")
    assert not _flagged(["gw 8.8.8.8"], diagram_type="data-flow")
    assert not _flagged(["gw 8.8.8.8"], diagram_type=None)


def test_documentation_ipv4_never_flagged():
    """Each RFC5737 TEST-NET block is a documentation range — never a finding."""
    for addr in ("192.0.2.10", "198.51.100.5", "203.0.113.200"):
        assert not _flagged([f"vpc {addr}"], diagram_class="landscape")


def test_documentation_ipv6_never_flagged():
    """The RFC3849 documentation prefix (written per RFC5952) is never flagged."""
    assert not _flagged(["egress 2001:db8::1"], diagram_class="landscape")


def test_private_ranges_never_flagged():
    """RFC1918 / RFC6598 / RFC6815 private ranges are never flagged."""
    for addr in ("10.0.1.4", "172.16.5.9", "192.168.1.1", "100.64.0.1", "198.18.0.7"):
        assert not _flagged([f"subnet {addr}"], diagram_class="landscape")


def test_public_ip_in_edge_label_is_flagged():
    """On-diagram text includes edge labels."""
    assert _flagged(
        edges=[Edge(source="a", target="b", label="peer 9.9.9.9")],
        diagram_class="landscape",
    )


def test_public_ip_in_legend_is_flagged():
    """On-diagram text includes the Legend lines."""
    assert _flagged(
        node_names=["S3"],
        legend_lines=["Legend", "public endpoint 9.9.9.9"],
        diagram_class="landscape",
    )


def test_non_parseable_address_like_token_is_ignored():
    """A token that looks like an address but does not parse is not a finding.

    ``999.999.999.999`` matches the dotted-quad shape but is not a valid IPv4,
    so it must be ignored rather than mis-flagged."""
    assert not _flagged(["bad 999.999.999.999"], diagram_class="landscape")
    assert not _flagged(["version 1.2.3.4.5"], diagram_class="landscape")


def test_version_string_not_an_ip_is_ignored():
    """A three-octet version string is not an IPv4 literal and is ignored."""
    assert not _flagged(["app v1.2.3"], diagram_class="landscape")


def test_rule_is_warning():
    assert RULE_SEVERITIES[RULE_IP_RANGE] == Severity.WARNING


# --------------------------------------------------------------------------- #
# Helper unit coverage.
# --------------------------------------------------------------------------- #


def test_is_documentation_ip_helper():
    assert _is_documentation_ip(ipaddress.ip_address("192.0.2.1"))
    assert _is_documentation_ip(ipaddress.ip_address("2001:db8::1"))
    assert not _is_documentation_ip(ipaddress.ip_address("8.8.8.8"))


def test_is_private_ip_helper():
    assert _is_private_ip(ipaddress.ip_address("10.0.0.1"))
    assert _is_private_ip(ipaddress.ip_address("100.64.0.1"))  # RFC6598
    assert _is_private_ip(ipaddress.ip_address("198.18.0.1"))  # RFC6815
    assert _is_private_ip(ipaddress.ip_address("127.0.0.1"))  # loopback
    assert not _is_private_ip(ipaddress.ip_address("8.8.8.8"))


# --------------------------------------------------------------------------- #
# Property 3 — classification is correct and scoped.
# --------------------------------------------------------------------------- #

# Documentation IPv4 addresses drawn from the reserved TEST-NET blocks.
_DOC_V4 = st.sampled_from(["192.0.2.", "198.51.100.", "203.0.113."]).flatmap(
    lambda prefix: st.integers(min_value=0, max_value=255).map(
        lambda host: f"{prefix}{host}"
    )
)
# Private IPv4 addresses (RFC1918 10/8).
_PRIVATE_V4 = st.integers(min_value=0, max_value=255).flatmap(
    lambda b: st.integers(min_value=0, max_value=255).map(lambda c: f"10.{b}.{c}.1")
)
# Arbitrary IPv4 addresses.
_ANY_V4 = st.integers(min_value=0, max_value=(1 << 32) - 1).map(
    lambda n: str(ipaddress.IPv4Address(n))
)


@given(addr=st.one_of(_DOC_V4, _PRIVATE_V4))
def test_property_doc_or_private_never_flagged_even_in_network(addr):
    """A documentation or private address is never a finding, even in a
    Network_Diagram (the safe half of Property 3)."""
    assert not _flagged([f"node {addr}"], diagram_class="landscape")


@given(addr=_ANY_V4)
def test_property_public_iff_global_and_only_in_network(addr):
    """A literal is flagged in a Network_Diagram exactly when it is a public
    (global, non-documentation, non-private) address — and never in a flow
    diagram (the scoped half of Property 3)."""
    ip = ipaddress.ip_address(addr)
    is_public = (
        ip.is_global
        and not _is_documentation_ip(ip)
        and not _is_private_ip(ip)
    )
    # In a Network_Diagram: flagged iff the address is public.
    assert _flagged([f"node {addr}"], diagram_class="landscape") == is_public
    # In a flow diagram: never flagged, regardless of the address.
    assert not _flagged([f"node {addr}"], diagram_class="flow")


@given(
    doc_addr=_DOC_V4,
    dtype=st.sampled_from(["network", "infrastructure", "deployment"]),
)
def test_property_network_types_scope_the_rule(doc_addr, dtype):
    """Every network-family ``diagram_type`` is a Network_Diagram, but a
    documentation address in one is still clean."""
    assert not _flagged([f"gw {doc_addr}"], diagram_type=dtype)
