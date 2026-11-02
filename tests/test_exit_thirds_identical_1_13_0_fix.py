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
