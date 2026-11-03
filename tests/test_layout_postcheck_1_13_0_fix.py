"""1.13.0 fix (FEAT-004, item 12): the post-layout lint-only check.

``layout()`` runs the lint-only ERROR rules the solver does not score
(``scope-placement``, ``geometric-containment``, ``container-style``,
``container-caption-overflow`` overprints, ``legend-placement`` overlaps) once
on the finished diagram and reports them in ``layout_warnings`` with
``degraded`` set, instead of handing back a result that looks clean and is then
blocked by the linter. Goldens stay ``layout_warnings == ()``.
"""
from __future__ import annotations

import dataclasses

from rule_engine.layout import layout
from rule_engine.layout import postcheck as pc
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

_TITLE = "aws postcheck — 123456789012 / us-east-1 | 2026-11-03 | v1"
_CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
    ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
)


def _spec(waf_container):
    nodes = (
        NodeSpec(id="user", role="client", lane="actors", region="", slot=0),
        NodeSpec(id="waf", role="waf", lane="edge", region="a" if waf_container else "",
                 slot=0, container=waf_container),
        NodeSpec(id="fn", role="serverless_fn", lane="workers", region="a", slot=0,
                 container="region-a"),
    )
    edges = (
        EdgeSpec(id="e1", source="user", target="waf", marker="1"),
        EdgeSpec(id="e2", source="waf", target="fn", marker="2"),
    )
    return DiagramSpec(diagram_id="pc", diagram_name="pc", axis="left-right", nodes=nodes,
                       edges=edges, containers=_CONTAINERS, flow_lines=(), title=_TITLE)


def test_waf_in_a_region_is_reported_and_degrades_the_layout():
    placed = layout(_spec("region-a"))
    assert any(w.startswith("scope-placement:") and "global-in-region:waf" in w
               for w in placed.layout_warnings), placed.layout_warnings
    assert placed.degraded is True


def test_postcheck_is_quiet_on_a_clean_layout():
    placed = layout(_spec(None))
    lines, blocking = pc.postcheck(placed)
    assert lines == [] and blocking is False
    assert not any(w.startswith("scope-placement:") for w in placed.layout_warnings)


def test_postcheck_never_raises():
    placed = layout(_spec(None))
    broken = dataclasses.replace(placed, nodes={})
    assert pc.postcheck(broken) == ([], False)


def test_golden_spec_has_no_layout_warnings():
    """The aws/01 golden spec (layout() + build_diagram) stays clean."""
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import build_aws_agent_platform_example as example
    finally:
        sys.path.remove(str(scripts))
    placed = layout(example.SPEC, strict=True)
    assert placed.layout_warnings == ()
    assert placed.degraded is False


def test_nested_solver_layouts_do_not_run_the_postcheck(monkeypatch):
    calls = []
    real = pc.postcheck

    def counting(placed):
        calls.append(placed.spec.diagram_id)
        return real(placed)

    monkeypatch.setattr(pc, "postcheck", counting)
    layout(_spec(None))
    assert calls == ["pc"]
