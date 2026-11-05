"""Phase 3 item 15: scope / containers.

Covers:

* 15a — the public ``diagram_layout.container_style(kind, provider)`` helper
  resolves ``peer_account`` / ``external_cloud`` / ``edge_lane`` from the bundled
  mapping (no stale workspace copy) and carries the disambiguation ``kind=``
  token by default.
* 15b — a VPC-scoped role drawn inside an UNAMBIGUOUS ``peer_account`` /
  ``external_cloud`` box is NOT ``vpc-scoped-outside-vpc`` (its VPC is not drawn,
  the peer account is external); the PRIMARY account box still flags.
* 15c — an explicit ``kind=`` style token beats the signature match, so a peer
  account is told apart from the primary account despite the shared
  ``grIcon=group_account`` signature overlap.
* 15d — the neutral ``edge_lane`` container kind resolves and classifies cleanly
  on all five providers plus kubernetes (no signature collision with a region /
  availability-domain / external_cloud box).
"""
from __future__ import annotations

import pytest

from rule_engine import icon_resolver
from rule_engine.constants import CONTAINER_KINDS
from rule_engine.diagram_layout import Boundary, _boundary_style, container_style
from rule_engine.geometry import Box, DiagramGeometry, classify_container_kinds
from rule_engine.icon_refs import IconRef
from rule_engine.linter import Artifact, lint

_RDS = ("assets/vendor/aws-icons/Architecture-Service-Icons_07312026/Arch_Databases/32/"
        "Arch_Amazon-RDS_32.svg")

_ALL_PROVIDERS = ("aws", "azure", "gcp", "generic", "kubernetes", "oci")


# --------------------------------------------------------------------------- #
# 15d — edge_lane kind resolves + classifies cleanly on every provider
# --------------------------------------------------------------------------- #
def test_edge_lane_is_a_known_container_kind():
    assert "edge_lane" in CONTAINER_KINDS


@pytest.mark.parametrize("provider", _ALL_PROVIDERS)
def test_edge_lane_resolves_on_every_provider(provider: str):
    style = icon_resolver.resolve_container("edge_lane", provider)["style_string"]
    assert style and style.strip()


@pytest.mark.parametrize("provider", _ALL_PROVIDERS)
def test_edge_lane_classifies_without_collision(provider: str):
    mp = {provider: (icon_resolver.load_mapping(provider).get("containers") or {})}
    style = icon_resolver.resolve_container("edge_lane", provider)["style_string"]
    kinds = classify_container_kinds(style, [provider], mp)
    # edge_lane must be matched and must NOT collide with a region / AZ / peer box.
    assert "edge_lane" in kinds, (provider, sorted(kinds))
    assert not (kinds & {"region", "availability_domain", "external_cloud"}), (
        provider, sorted(kinds))


# --------------------------------------------------------------------------- #
# 15a — the container_style helper
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["peer_account", "external_cloud", "edge_lane"])
def test_container_style_helper_resolves_and_tags_kind(kind: str):
    style = container_style(kind, "aws")
    assert style and f"kind={kind}" in style
    # same body as resolve_container, plus the token
    base = icon_resolver.resolve_container(kind, "aws")["style_string"]
    assert style.startswith(base)


def test_container_style_helper_can_omit_token():
    style = container_style("peer_account", "aws", with_kind_token=False)
    assert "kind=" not in style
    assert style == icon_resolver.resolve_container("peer_account", "aws")["style_string"]


# --------------------------------------------------------------------------- #
# 15c — explicit kind token beats the signature match
# --------------------------------------------------------------------------- #
def test_kind_token_beats_signature_collision():
    """The AWS primary account and a peer account share
    ``grIcon=group_account`` + ``fillColor=none`` (accepted overlap), so the
    signature match classifies either as ``{boundary, peer_account}``. An
    explicit ``kind=peer_account`` token must resolve it to exactly that kind."""
    mp = {"aws": (icon_resolver.load_mapping("aws").get("containers") or {})}
    # the plain peer_account style (no token) is ambiguous with the account
    plain = icon_resolver.resolve_container("peer_account", "aws")["style_string"]
    assert "boundary" in classify_container_kinds(plain, ["aws"], mp)
    # the helper adds the token -> unambiguous
    tagged = container_style("peer_account", "aws")
    assert classify_container_kinds(tagged, ["aws"], mp) == {"peer_account"}


def test_boundary_cell_emits_kind_token_only_when_set():
    b_plain = Boundary("b", "Acct", 0, 0, 100, 100, style="rounded=0;dashed=1")
    assert "kind=" not in _boundary_style(b_plain)
    b_kind = Boundary("b", "Peer", 0, 0, 100, 100, style="rounded=0;dashed=1",
                      container_kind="peer_account")
    assert "kind=peer_account" in _boundary_style(b_kind)


# --------------------------------------------------------------------------- #
# 15b — peer-account member is not vpc-scoped-outside-vpc; primary still flags
# --------------------------------------------------------------------------- #
def _geo_account(container_kind: str | None) -> DiagramGeometry:
    """An outermost box (0,0,2000,2000) drawn either as the primary AWS account
    boundary or, when ``container_kind`` is given, as a peer/external box with an
    explicit ``kind=`` token. A separate VPC box is drawn to its right (so a
    network boundary exists for ``vpc-scoped-outside-vpc`` to fire), but the RDS
    is placed OUTSIDE that VPC, inside the account/peer box only."""
    g = DiagramGeometry()
    g.containers = {
        "box": Box("box", 0, 0, 1000, 2000),
        "vpc": Box("vpc", 1200, 100, 700, 700),  # a VPC elsewhere; RDS not inside
    }
    if container_kind is None:
        style = icon_resolver.resolve_container("boundary", "aws")["style_string"]
    else:
        style = container_style(container_kind, "aws")
    g.container_styles = {
        "box": style,
        "vpc": icon_resolver.resolve_container("network_boundary", "aws")["style_string"],
    }
    return g


def _place(g, nid, x, y, ref):
    g.nodes[nid] = Box(nid, x, y, 78, 78)
    g.node_styles[nid] = f"image;image={ref};"
    return IconRef(nid, "image", ref)


def _scope_findings(g, refs):
    art = Artifact(kind="diagram", node_names=[], geometry=g, icon_refs=refs,
                   title_cell="aws x — a / b | 2026-10-07 | v1", diagram_type="flow")
    return [f for f in lint(art)["findings"] if f["rule"] == "scope-placement"]


def test_vpc_scoped_role_in_primary_account_still_flags():
    g = _geo_account(None)
    refs = [_place(g, "rds", 300, 300, _RDS)]
    sp = _scope_findings(g, refs)
    assert len(sp) == 1 and "vpc-scoped-outside-vpc:rds" in sp[0]["reason"], sp


@pytest.mark.parametrize("kind", ["peer_account", "external_cloud"])
def test_vpc_scoped_role_in_peer_box_is_exempt(kind: str):
    g = _geo_account(kind)
    refs = [_place(g, "rds", 300, 300, _RDS)]
    assert _scope_findings(g, refs) == [], kind
