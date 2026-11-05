"""1.13.0 fix (ITEM 7, lint half): two exits / entries pinned to the SAME
contact point are reported first as ``*-identical`` and are an ERROR on both
classes (the escalation diagram-lint.md always documented for exit-thirds)."""
from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import Artifact, RULE_SPECS, Severity, lint


def _edge(eid, s, t, exit_, entry):
    return EdgeGeom(id=eid, source=s, target=t, orthogonal=True, exit=exit_, entry=entry)


def _sev(result, rule):
    sevs = [f["severity"] for f in result["findings"] if f["rule"] == rule]
    return sevs


def test_identical_exits_reported_first():
    g = DiagramGeometry(edges=[
        _edge("e1", "src", "a", (1.0, 0.5), (0.0, 0.5)),
        _edge("e2", "src", "b", (1.0, 0.5), (0.0, 0.5)),
        _edge("e3", "x", "c", (1.0, 0.4), (0.0, 0.5)),
        _edge("e4", "x", "d", (1.0, 0.45), (0.0, 0.5)),
    ])
    out = geo.check_exit_thirds(g)
    assert out[0][0] == "src" and "right-exits-identical((1.0,0.5))" in out[0][1]
    assert ("x", "right-exits-merge(<0.2: 0.40,0.45)") in out


def test_identical_exits_error_on_flow_close_exits_warning():
    same = DiagramGeometry(edges=[
        _edge("e1", "src", "a", (1.0, 0.5), (0.0, 0.5)),
        _edge("e2", "src", "b", (1.0, 0.5), (0.0, 0.5)),
    ])
    close = DiagramGeometry(edges=[
        _edge("e1", "src", "a", (1.0, 0.5), (0.0, 0.5)),
        _edge("e2", "src", "b", (1.0, 0.55), (0.0, 0.5)),
    ])
    for g, want in ((same, Severity.ERROR), (close, Severity.WARNING)):
        art = Artifact(kind="diagram", node_names=["src"], geometry=g, diagram_class="flow")
        assert _sev(lint(art), "exit-thirds") == [want.value]


def test_identical_entries_error_on_both_classes():
    g = DiagramGeometry(edges=[
        _edge("e1", "a", "rds", (1.0, 0.5), (0.0, 0.5)),
        _edge("e2", "b", "rds", (1.0, 0.5), (0.0, 0.5)),
    ])
    out = geo.check_entry_thirds(g)
    assert out == [("rds", "left-entries-identical((0.0,0.5))")]
    for cls in ("flow", "landscape"):
        art = Artifact(kind="diagram", node_names=["rds"], geometry=g, diagram_class=cls)
        assert _sev(lint(art), "entry-thirds") == [Severity.ERROR.value]


def test_rule_specs_escalate_identical():
    assert RULE_SPECS["exit-thirds"].severity_for("flow", "right-exits-identical((1,0.5))") \
        == Severity.ERROR
    assert RULE_SPECS["entry-thirds"].severity_for("flow", "left-entries-identical((0,0.5))") \
        == Severity.ERROR
    assert RULE_SPECS["entry-thirds"].severity_for("flow", "left-entries-merge(...)") \
        == Severity.WARNING


# --------------------------------------------------------------------------- #
# FEAT-004 (engine half): the solver ranks identical contacts as errors, and
# layout() never emits them.
# --------------------------------------------------------------------------- #
def test_rule_violations_counts_identical_contacts_as_errors():
    g = DiagramGeometry(edges=[
        _edge("e1", "src", "a", (1.0, 0.5), (0.0, 0.5)),
        _edge("e2", "src", "b", (1.0, 0.5), (0.0, 0.5)),
        _edge("e3", "x", "rds", (1.0, 0.5), (0.0, 0.5)),
        _edge("e4", "y", "rds", (1.0, 0.5), (0.0, 0.5)),
    ])
    errors, warnings = geo.rule_violations(g)
    assert ("exit-thirds", repr(("src", "right-exits-identical((1.0,0.5))"))) in errors
    assert ("entry-thirds", repr(("rds", "left-entries-identical((0.0,0.5))"))) in errors
    assert not any("-identical" in w for _r, w in warnings)


def test_rule_violations_keeps_merging_contacts_advisory():
    g = DiagramGeometry(edges=[
        _edge("e1", "src", "a", (1.0, 0.5), (0.0, 0.5)),
        _edge("e2", "src", "b", (1.0, 0.55), (0.0, 0.5)),
    ])
    errors, warnings = geo.rule_violations(g)
    assert not any(r == "exit-thirds" for r, _ in errors)
    assert any(r == "exit-thirds" and "exits-merge" in w for r, w in warnings)


def test_separate_identical_contacts_moves_the_later_edge():
    from rule_engine.layout.contacts import separate_identical_contacts

    exits = {"e1": (1.0, 0.5), "e2": (1.0, 0.5), "e3": (0.5, 1.0)}
    separate_identical_contacts({("src", "right"): ["e1", "e2"], ("src", "bottom"): ["e3"]},
                                exits)
    assert exits["e1"] == (1.0, 0.5)               # the first keeps its band
    assert exits["e2"] == (1.0, 0.25)              # the later takes the next free band
    assert exits["e3"] == (0.5, 1.0)
    entries = {"e1": (0.0, 0.5), "e2": (0.0, 0.5)}
    separate_identical_contacts({("rds", "left"): ["e1", "e2"]}, entries, entry=True)
    assert entries["e2"] == (0.0, 0.25)
    distinct = {"e1": (1.0, 0.25), "e2": (1.0, 0.75)}
    separate_identical_contacts({("src", "right"): ["e1", "e2"]}, distinct)
    assert distinct == {"e1": (1.0, 0.25), "e2": (1.0, 0.75)}


def test_layout_fan_to_one_target_column_has_distinct_contacts():
    """A hub fanning two edges to targets stacked in ONE column to its right
    (both leave the right face) gets distinct exits, never one point."""
    from rule_engine.layout import layout
    from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

    nodes = (
        NodeSpec(id="hub", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="a", role="object_store", lane="data", region="", slot=0),
        NodeSpec(id="b", role="message_queue", lane="data", region="", slot=1),
    )
    edges = (EdgeSpec(id="e1", source="hub", target="a", marker="1"),
             EdgeSpec(id="e2", source="hub", target="b", marker="2"))
    spec = DiagramSpec(
        diagram_id="ident", diagram_name="ident", axis="left-right", nodes=nodes, edges=edges,
        containers=(ContainerSpec(id="account", kind="account", region="", parent=None,
                                  label_key="account"),),
        flow_lines=(), title="aws ident — 123456789012 / us-east-1 | 2026-11-03 | v1",
        order="manual")
    placed = layout(spec)
    exits = [tuple(pe.exit) for pe in placed.edges]
    assert len(set(exits)) == 2, exits
