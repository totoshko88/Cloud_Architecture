"""1.13.0 phase 3 item 19 — advise entry-face suggestions + coincident-node SpecError.

Two residuals from the 08/09 feedback (A, F11):

1. ``classify_edge`` on two endpoints that occupy the SAME placed position
   (``dx == dy == 0``) raises the dedicated ``CoincidentNodesError`` naming both
   nodes, and ``layout()`` re-raises it as a ``SpecError`` the author can act on
   ("give one a different slot / sub") — the SEP 08 IGW-at-slot-9 case, which
   previously surfaced as an internal ``UnclassifiableEdgeError (dx=0,dy=0)``.
2. ``rule-engine-advise`` proposes the alternative legal entry face for each
   ``end-to-end-merge`` collinear pair (the SEP 09 e12/e26 merge), since the lint
   names the pair but the spec has no per-edge face field.
"""
from __future__ import annotations

import pytest

from rule_engine.geometry import Box
from rule_engine.layout.base import SpecError
from rule_engine.layout.model import EdgeSpec
from rule_engine.layout.routers import (
    CoincidentNodesError,
    UnclassifiableEdgeError,
    classify_edge,
)


# --- 1. coincident nodes -> CoincidentNodesError / SpecError --------------

def test_classify_edge_coincident_raises_coincident_subtype():
    placed = {
        "igw": Box("igw", 500, 400, 78, 78),
        "ec2": Box("ec2", 500, 400, 78, 78),   # same position
    }
    e = EdgeSpec(id="e13", source="igw", target="ec2", marker="1")
    with pytest.raises(CoincidentNodesError) as ei:
        classify_edge(e, placed)
    msg = str(ei.value)
    assert "igw" in msg and "ec2" in msg
    # it IS an UnclassifiableEdgeError subtype (back-compat for existing catches).
    assert isinstance(ei.value, UnclassifiableEdgeError)


def test_distinct_positions_do_not_raise_coincident():
    placed = {
        "a": Box("a", 0, 0, 78, 78),
        "b": Box("b", 300, 0, 78, 78),
    }
    e = EdgeSpec(id="e", source="a", target="b", marker="1")
    # a normal rightward same-row edge classifies fine.
    assert classify_edge(e, placed) in {"straight", "fan-out-row", "cross-region"}


def test_layout_reraises_coincident_as_specerror():
    """A spec whose two nodes resolve to the same position surfaces a SpecError
    (naming both and hinting slot/sub), not an internal routing error."""
    from rule_engine.layout import layout
    from rule_engine.layout.model import ContainerSpec, DiagramSpec, NodeSpec
    import rule_engine.layout.routers as routers

    # Force the coincidence at routing time: monkeypatch classify_edge's view is
    # overkill; instead build a spec that places two nodes at one point. The
    # robust, engine-version-independent way is to assert the re-raise wrapper
    # itself: patch classify_edge to raise CoincidentNodesError and confirm
    # layout() converts it to SpecError.
    spec = DiagramSpec(
        diagram_id="t", diagram_name="t", axis="left-right",
        nodes=(
            NodeSpec(id="a", role="compute_instance", lane="workers", region="", slot=0),
            NodeSpec(id="b", role="object_store", lane="data", region="", slot=0),
        ),
        edges=(EdgeSpec(id="e1", source="a", target="b", marker="1"),),
        containers=(ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),),
        flow_lines=("Flow", "1. a to b"),
        title="t | 2025-01-15 | v1",
        order="manual",
    )
    orig = routers.classify_edge

    def _raise_coincident(edge, placed):
        raise CoincidentNodesError(
            f"edge {edge.id!r}: nodes {edge.source!r} and {edge.target!r} "
            f"occupy the same position (lane/region/slot/sub coincide)"
        )

    routers.classify_edge = _raise_coincident
    # the pipeline imported classify_edge by name; patch there too.
    import rule_engine.layout.pipeline as pipeline
    pipeline.classify_edge = _raise_coincident
    try:
        with pytest.raises(SpecError) as ei:
            layout(spec)
        assert "same position" in str(ei.value)
        assert "slot or sub" in str(ei.value)
        assert "'a'" in str(ei.value) and "'b'" in str(ei.value)
    finally:
        routers.classify_edge = orig
        pipeline.classify_edge = orig


# --- 2. advise entry-face suggestions -------------------------------------

def test_entry_face_suggestions_empty_when_no_merge():
    # A clean 2-node spec has no end-to-end merge, so no suggestion.
    from rule_engine.advise_cli import advise
    from rule_engine.layout.model import ContainerSpec, DiagramSpec, NodeSpec
    spec = DiagramSpec(
        diagram_id="t", diagram_name="t", axis="left-right",
        nodes=(
            NodeSpec(id="a", role="compute_instance", lane="workers", region="", slot=0),
            NodeSpec(id="b", role="object_store", lane="data", region="", slot=0),
        ),
        edges=(EdgeSpec(id="e1", source="a", target="b", marker="1"),),
        containers=(ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),),
        flow_lines=("Flow", "1. a to b"),
        title="t | 2025-01-15 | v1",
    )
    rec = advise(spec)
    assert rec["entry_face_suggestions"] == []


def test_entry_face_suggestions_proposes_alternative_face(monkeypatch):
    # Stub an end-to-end-merge finding and assert the helper proposes the
    # alternative legal entry face for the later-id edge (the SEP 09 e12/e26
    # shape). The geometry-merge DETECTION itself is covered by
    # tests/test_ws8_collinear.py; here we pin the advise contract.
    import rule_engine.advise_cli as ac
    from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom

    geo = DiagramGeometry(
        nodes={"a": Box("a", 0, 0, 78, 78), "b": Box("b", 300, 0, 78, 78)},
        containers={},
        edges=[
            EdgeGeom(id="e12", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="12"),
            EdgeGeom(id="e26", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="26"),
        ],
    )
    # The helper imports these at module level inside the function body, so
    # patch the source modules the local imports bind to.
    import rule_engine.layout.repair as repair
    import rule_engine.geometry as _g
    import rule_engine.drawio_model as dm
    monkeypatch.setattr(repair, "_serialize_candidate", lambda placed: "<xml/>")
    monkeypatch.setattr(dm, "parse_drawio", lambda xml, path=None: [object()])
    monkeypatch.setattr(_g, "build_geometry", lambda page: geo)
    monkeypatch.setattr(_g, "collinear_edge_findings",
                        lambda g: [("e12", "e26", "end-to-end-merge")])

    out = ac.entry_face_suggestions(object())
    assert len(out) == 1
    s = out[0]
    assert s["edge"] == "e26"               # the later-id edge is the one to move
    assert s["pair"] == ["e12", "e26"]
    # e26's entry is a left face (entryX<=0), so the alternative is the top face.
    assert s["from_face"] == "left" and s["to_face"] == "top"
    assert "e26" in s["hint"] and "top" in s["hint"]
