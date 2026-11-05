"""L2 (1.13.0) — external-fan exit-face hint (``NodeSpec.exit_face``).

A node at a container's edge whose edges target an EXTERNAL sibling band/node
can force the exit toward those bands (``up`` / ``left``) instead of the
directional-contract default right/bottom, which would rake the fan back across
the account. The hint:

* reaches the COMMITTED geometry through the real ``layout()`` pipeline (it
  seeds the scored solver's rule-based variant via ``_global_contacts``);
* is contract-LEGAL — ``check_edge_direction`` is clean because the target
  carries the ``external=1`` style token (the long-haul external exception);
* fires ONLY for an external target — an in-cloud edge from the same source
  keeps the normal ladder;
* is byte-inert when ``exit_face`` is ``None`` (every pre-1.13.0 spec).
"""
from __future__ import annotations

import pytest

from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.base import SpecError
from rule_engine.layout.contacts import select_contacts
from rule_engine.layout.model import Box, ContainerSpec, EdgeSpec, NodeSpec


def _exit_face_of(exit_pt) -> str:
    fx, fy = exit_pt
    if fy is not None and fy <= 0.0:
        return "top"
    if fy is not None and fy >= 1.0:
        return "bottom"
    if fx is not None and fx <= 0.0:
        return "left"
    return "right"


# --------------------------------------------------------------------------- #
# Unit: select_contacts override
# --------------------------------------------------------------------------- #

def _two_box(src_xy, tgt_xy):
    placed = {
        "s": Box("s", src_xy[0], src_xy[1], 48, 48),
        "ext": Box("ext", tgt_xy[0], tgt_xy[1], 48, 48),
    }
    edge = EdgeSpec(id="e0", source="s", target="ext", marker="1")
    return edge, placed


def test_override_fires_only_with_hint_and_external_target():
    # external target ABOVE the source; exit_face="up" -> top exit.
    edge, placed = _two_box((500, 500), (480, 100))
    ex, en = select_contacts(edge, placed, exit_face="up", target_external=True)
    assert _exit_face_of(ex) == "top"
    # a left hint -> left exit.
    ex, _ = select_contacts(edge, placed, exit_face="left", target_external=True)
    assert _exit_face_of(ex) == "left"
    # right hint -> the contract default (falls through to the ladder).
    ex, _ = select_contacts(edge, placed, exit_face="right", target_external=True)
    assert _exit_face_of(ex) == "right"


def test_override_inert_without_external_target_or_hint():
    edge, placed = _two_box((500, 500), (480, 100))
    base_ex, base_en = select_contacts(edge, placed)
    # hint set but target NOT external -> no override.
    ex, en = select_contacts(edge, placed, exit_face="up", target_external=False)
    assert (ex, en) == (base_ex, base_en)
    # external target but NO hint -> no override.
    ex, en = select_contacts(edge, placed, exit_face=None, target_external=True)
    assert (ex, en) == (base_ex, base_en)


# --------------------------------------------------------------------------- #
# End-to-end: forced exit reaches committed geometry and lints clean
# --------------------------------------------------------------------------- #

def _fan_spec(exit_face):
    containers = (
        ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
    )
    nodes = (
        NodeSpec(id="users", role="client", lane="actors", region="", slot=0),
        NodeSpec(id="corner", role="compute_instance", lane="data", region="a", slot=0,
                 container="vpc-a", exit_face=exit_face),
        # an external sibling the corner node fans to.
        NodeSpec(id="atlas", role="saas", lane="actors", region="", slot=1, external=True),
    )
    edges = (
        EdgeSpec(id="e0", source="users", target="corner", marker="1"),
        EdgeSpec(id="e1", source="corner", target="atlas", marker="2"),
    )
    return DiagramSpec(
        diagram_id="l2", diagram_name="l2", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. call", "2. sync"),
        title="aws l2 — 000000000000 / eu-central-1 | 2026-10-28 | v1",
        order="manual",
    )


def _committed_exit(placed, edge_id):
    for pe in placed.edges:
        if pe.spec.id == edge_id:
            return pe.exit
    raise AssertionError(f"no committed edge {edge_id!r}")


def test_forced_exit_reaches_committed_geometry():
    up = layout(_fan_spec("up"))
    assert _exit_face_of(_committed_exit(up, "e1")) == "top"
    left = layout(_fan_spec("left"))
    assert _exit_face_of(_committed_exit(left, "e1")) == "left"


def test_forced_external_exit_lints_clean():
    for face in ("up", "left"):
        placed = layout(_fan_spec(face))
        # The forced top/left exit on e1 (external target) raises no residual
        # directional-contract finding: the oracle (which serializes, re-parses
        # and runs check_edge_direction) leaves no edge-direction layout_warning
        # and does not degrade the diagram.
        assert not placed.degraded, (face, placed.layout_warnings)
        assert not any("edge-direction" in w for w in placed.layout_warnings), (
            face, placed.layout_warnings,
        )


def test_exit_face_none_is_inert():
    # The same spec with no hint must leave e1 on a contract-default face.
    none_placed = layout(_fan_spec(None))
    assert _exit_face_of(_committed_exit(none_placed, "e1")) in ("right", "bottom")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def test_unknown_exit_face_raises():
    with pytest.raises(SpecError):
        layout(_fan_spec("sideways"))
