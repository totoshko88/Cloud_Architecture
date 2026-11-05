"""Phase 3 item 9 (F14): L2 external-band composition.

Before the fix, a node with ``external=True`` had its declared ``container``
IGNORED for placement (forced to the root layer), so declaring it a member of an
``ext-*`` band left the band with no children and ``layout()`` raised
``SpecError: container 'ext-ingress' has no children to size around``.

The fix (``layout.base._assign_nodes_to_leaves``): an ``external=True`` node
whose declared container is an EXTERNAL band kind (``peer_account`` /
``external_cloud`` / ``edge_lane``) stays a MEMBER of that band — it is already
outside every cloud boundary, so keeping it assigned gives the band children to
size around while it is still treated as external (scope not judged, no
container-padding spill). A cloud container on an external node is still ignored.

``row_of`` (G19) is NOT shipped (see CHANGELOG Notes); this file covers the
composition fix, which is the must-have.
"""
from __future__ import annotations

import pytest

from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.base import SpecError, _EXTERNAL_BAND_KINDS
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec


def _spec(band_kind: str, *, external: bool, exit_face=None) -> DiagramSpec:
    containers = (
        ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
        ContainerSpec(id="ext-ingress", kind=band_kind, region="", parent=None, label_key="external_cloud"),
    )
    nodes = (
        NodeSpec(id="svc", role="compute_instance", lane="data", region="a", slot=0, container="vpc-a"),
        NodeSpec(id="partner", role="saas", lane="actors", region="", slot=0,
                 container="ext-ingress", external=external, exit_face=exit_face),
    )
    edges = (EdgeSpec(id="e0", source="partner", target="svc", marker="1"),)
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. call"),
        title="aws t — 000000000000 / eu-central-1 | 2026-10-28 | v1",
        order="manual",
    )


def test_edge_lane_is_an_external_band_kind():
    assert {"peer_account", "external_cloud", "edge_lane"} <= _EXTERNAL_BAND_KINDS


@pytest.mark.parametrize("band_kind", ["external_cloud", "peer_account", "edge_lane"])
def test_external_member_builds_and_sizes_the_band(band_kind: str):
    placed = layout(_spec(band_kind, external=True))
    assert not placed.degraded, placed.layout_warnings
    # the band exists and encloses its external member
    band = placed.containers["ext-ingress"]
    node = placed.nodes["partner"]
    assert (band.x <= node.x and band.y <= node.y
            and node.x + node.w <= band.x + band.w
            and node.y + node.h <= band.y + band.h), (band, node)


def test_external_member_without_container_still_raises_empty_band():
    # Control: an external node that does NOT declare the band container leaves
    # the band truly empty — still a SpecError (the fix is scoped to members).
    spec = _spec("external_cloud", external=True)
    nodes = tuple(
        n if n.id != "partner" else NodeSpec(
            id="partner", role="saas", lane="actors", region="", slot=0,
            container=None, external=True)
        for n in spec.nodes
    )
    spec = DiagramSpec(
        diagram_id=spec.diagram_id, diagram_name=spec.diagram_name, axis=spec.axis,
        nodes=nodes, edges=spec.edges, containers=spec.containers,
        flow_lines=spec.flow_lines, title=spec.title, order=spec.order,
    )
    with pytest.raises(SpecError, match="has no children to size around"):
        layout(spec)


def test_external_member_is_not_scope_judged():
    # An external=True band member emits external=1, so scope-placement does not
    # judge its role: the built diagram carries no scope-placement warning and is
    # not degraded.
    placed = layout(_spec("external_cloud", external=True))
    assert not placed.degraded
    assert not any("scope-placement" in w or "vpc-scoped-outside-vpc" in w
                   for w in placed.layout_warnings), placed.layout_warnings


def test_exit_face_fires_for_external_band_member():
    placed = layout(_spec("external_cloud", external=True, exit_face="right"))
    assert not placed.degraded
    # the edge from the external member is committed (exit_face is accepted on a
    # band member, not rejected by _validate_spec)
    assert any(pe.spec.id == "e0" for pe in placed.edges)
