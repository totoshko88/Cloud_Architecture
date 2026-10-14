"""Theme 27: geometric-containment on structural membership (Wave C).

A flat node (parent = root layer) whose icon box is inside a boundary it is not
parented to is an interloper; a node structurally parented to the boundary is a
member and is never flagged; a node outside every boundary is never flagged.
"""

from __future__ import annotations

from rule_engine.geometry import Box, DiagramGeometry, check_geometric_containment
from rule_engine.constants import ROOT_LAYER_ID


def _geo(nodes, containers, parents):
    g = DiagramGeometry()
    for b in nodes:
        g.nodes[b.id] = b
    for b in containers:
        g.containers[b.id] = b
    for nid, pid in parents.items():
        g.node_parent_ids[nid] = pid
    return g


ACCT = Box("acct", 0, 0, 1000, 800)


def test_structural_member_is_not_flagged():
    node = Box("app", 100, 100, 78, 78)  # inside acct
    g = _geo([node], [ACCT], {"app": "acct"})  # parented to the boundary
    assert check_geometric_containment(g) == []


def test_flat_interloper_inside_boundary_is_flagged():
    node = Box("peer", 100, 100, 78, 78)  # inside acct, but flat-parented
    g = _geo([node], [ACCT], {"peer": ROOT_LAYER_ID})
    assert ("peer", "acct") in check_geometric_containment(g)


def test_node_outside_every_boundary_is_not_flagged():
    node = Box("ext", 1200, 100, 78, 78)  # right of acct
    g = _geo([node], [ACCT], {"ext": ROOT_LAYER_ID})
    assert check_geometric_containment(g) == []


def test_no_parent_info_is_skipped():
    node = Box("app", 100, 100, 78, 78)
    g = DiagramGeometry()
    g.nodes["app"] = node
    g.containers["acct"] = ACCT
    # node_parent_ids empty -> cannot judge membership -> skipped
    assert check_geometric_containment(g) == []
