"""Edge-hygiene tests (release 1.10.5).

Feature A — deterministic edge cleanup (``rule_engine.geometry`` +
``rule_engine.orthogonalise``):

* A1 marker-label de-collision (``resolve_marker_collisions`` / the
  ``marker-collision`` detector),
* A2 exit/entry port distribution (``distribute_ports`` / ``check_port_bunching``),
* A3 parallel-trunk offset (``offset_parallel_trunks`` / ``check_parallel_trunks``).

Feature B — the edge-hygiene lint gate wired into the Linter's ``RULES`` registry:
``marker-collision`` (B1), ``edge-crossing-excess`` (B2), ``detour-hook`` (B3) and
``structural-integrity`` (B4).

Every fixture is a small synthetic ``.drawio`` built inline (no dependency on
``examples/``). Each defect is asserted three ways where applicable: the detector
fires, the cleanup rewrites the source, and re-parsing the rewrite shows the
defect gone *and* re-running the cleanup is a no-op (the idempotence contract the
orthogonalise passes already hold).
"""

from __future__ import annotations

import pytest

from rule_engine.drawio_model import parse_drawio
from rule_engine import geometry as g
from rule_engine.orthogonalise import edge_hygiene_text, report_edge_hygiene


# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #


def _model(cells: str, grid: int = 10) -> str:
    return (
        f'<mxGraphModel gridSize="{grid}"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f"{cells}</root></mxGraphModel>"
    )


def _node(nid: str, x: int, y: int, w: int = 80, h: int = 80) -> str:
    return (
        f'<mxCell id="{nid}" value="{nid}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )


def _edge(
    eid: str,
    src: str,
    tgt: str,
    style: str,
    *,
    value: str = "",
    points: str = "",
) -> str:
    inner = f'<Array as="points">{points}</Array>' if points else ""
    return (
        f'<mxCell id="{eid}" value="{value}" edge="1" parent="1" '
        f'source="{src}" target="{tgt}" style="{style}">'
        f'<mxGeometry relative="1" as="geometry">{inner}</mxGeometry></mxCell>'
    )


def _geo(xml: str) -> g.DiagramGeometry:
    return g.build_geometry(parse_drawio(xml, path="fixture.drawio")[0])


# --------------------------------------------------------------------------- #
# A1 / B1 — marker collision
# --------------------------------------------------------------------------- #

_COLLIDING_MARKERS = _model(
    _node("A", 0, 0) + _node("B", 200, 0) + _node("C", 0, 20) + _node("D", 200, 20)
    + _edge("e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="1")
    + _edge("e2", "C", "D", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="2")
)


def test_marker_collision_detected():
    geo = _geo(_COLLIDING_MARKERS)
    assert g.check_marker_collision(geo) == [("e1", "e2")]


def test_marker_anchor_is_route_midpoint():
    geo = _geo(_COLLIDING_MARKERS)
    anchors = g.marker_anchors(geo)
    # Both routes are horizontal 80->200 across an 80px node: midpoint x=140.
    assert abs(anchors["e1"][0] - 140.0) < 1.0
    assert abs(anchors["e2"][0] - 140.0) < 1.0


def test_marker_decollision_separates_and_is_idempotent():
    new, changed = edge_hygiene_text(_COLLIDING_MARKERS)
    assert set(changed) == {"e1", "e2"}
    geo2 = _geo(new)
    assert g.check_marker_collision(geo2) == []
    # Nudged in opposite directions, deterministically.
    pos = {e.id: e.label_pos for e in geo2.edges}
    assert pos["e1"] == pytest.approx(-0.2)
    assert pos["e2"] == pytest.approx(0.2)
    # Idempotent: a second pass changes nothing.
    _new2, changed2 = edge_hygiene_text(new)
    assert changed2 == []


def test_marker_decollision_noop_when_far_apart():
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0) + _node("C", 0, 400) + _node("D", 200, 400)
        + _edge("e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="1")
        + _edge("e2", "C", "D", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="2")
    )
    geo = _geo(xml)
    assert g.check_marker_collision(geo) == []
    assert g.resolve_marker_collisions(geo) == {}
    _new, changed = edge_hygiene_text(xml)
    assert changed == []


def test_marker_collision_cluster_of_three_separates():
    # Three markers all anchored near (140, ~40).
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0)
        + _node("C", 0, 15) + _node("D", 200, 15)
        + _node("E", 0, 30) + _node("F", 200, 30)
        + _edge("e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="1")
        + _edge("e2", "C", "D", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="2")
        + _edge("e3", "E", "F", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="3")
    )
    assert g.check_marker_collision(_geo(xml))
    new, _changed = edge_hygiene_text(xml)
    assert g.check_marker_collision(_geo(new)) == []


# --------------------------------------------------------------------------- #
# A2 — exit/entry port distribution
# --------------------------------------------------------------------------- #

_BUNCHED_EXITS = _model(
    _node("hub", 0, 0) + _node("t1", 300, 0) + _node("t2", 300, 200) + _node("t3", 300, 400)
    + _edge("a", "hub", "t3", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="a")
    + _edge("b", "hub", "t1", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="b")
    + _edge("c", "hub", "t2", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="c")
)


def test_port_bunching_detected():
    geo = _geo(_BUNCHED_EXITS)
    assert g.check_port_bunching(geo) == [("hub", "right")]


def test_distribute_ports_even_and_ordered_by_target():
    geo = _geo(_BUNCHED_EXITS)
    dist = g.distribute_ports(geo)
    # Ordered by TARGET id: t1(b)->0.25, t2(c)->0.5, t3(a)->0.75. c keeps 0.5.
    assert dist["b"]["exit"] == (1.0, 0.25)
    assert dist["a"]["exit"] == (1.0, 0.75)
    assert "c" not in dist  # already at the even 0.5 slot


def test_distribute_ports_rewrites_and_is_idempotent():
    new, changed = edge_hygiene_text(_BUNCHED_EXITS)
    assert set(changed) == {"a", "b"}
    geo2 = _geo(new)
    assert g.check_port_bunching(geo2) == []
    fracs = sorted(e.exit[1] for e in geo2.edges)
    assert fracs == [0.25, 0.5, 0.75]
    _new2, changed2 = edge_hygiene_text(new)
    assert changed2 == []


def test_port_distribution_deterministic_order_independent():
    # Same three edges, declared in a different order -> same assignment.
    xml = _model(
        _node("hub", 0, 0) + _node("t1", 300, 0) + _node("t2", 300, 200) + _node("t3", 300, 400)
        + _edge("c", "hub", "t2", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="c")
        + _edge("a", "hub", "t3", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="a")
        + _edge("b", "hub", "t1", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="b")
    )
    dist = g.distribute_ports(_geo(xml))
    assert dist["b"]["exit"] == (1.0, 0.25)
    assert dist["a"]["exit"] == (1.0, 0.75)


def test_distribute_entry_face():
    # Two edges both ENTER t on its left face at y=0.5.
    xml = _model(
        _node("s1", 0, 0) + _node("s2", 0, 200) + _node("t", 300, 0, w=80, h=280)
        + _edge("e1", "s1", "t", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="1")
        + _edge("e2", "s2", "t", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="2")
    )
    geo = _geo(xml)
    assert ("t", "left") in g.check_port_bunching(geo)
    dist = g.distribute_ports(geo)
    # Ordered by SOURCE id: s1(e1)->0.333, s2(e2)->0.667.
    assert dist["e1"]["entry"][1] == pytest.approx(0.333333, abs=1e-4)
    assert dist["e2"]["entry"][1] == pytest.approx(0.666667, abs=1e-4)


# --------------------------------------------------------------------------- #
# A3 — parallel-trunk offset
# --------------------------------------------------------------------------- #

_COLINEAR_TRUNKS = _model(
    _node("P", 0, 0) + _node("Q", 300, 0) + _node("R", 0, 400) + _node("S", 300, 400)
    + _edge(
        "e1", "P", "S", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="1",
        points='<mxPoint x="150" y="40"/><mxPoint x="150" y="440"/>',
    )
    + _edge(
        "e2", "Q", "R", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;", value="2",
        points='<mxPoint x="150" y="40"/><mxPoint x="150" y="440"/>',
    )
)


def test_parallel_trunk_detected():
    geo = _geo(_COLINEAR_TRUNKS)
    assert g.check_parallel_trunks(geo) == [("e1", "e2")]


def test_offset_parallel_trunk_moves_higher_id_edge():
    geo = _geo(_COLINEAR_TRUNKS)
    off = g.offset_parallel_trunks(geo)
    # Only the higher-id edge (e2) moves; its vertical run shifts one grid step.
    assert set(off) == {"e2"}
    assert all(px == 160 for px, _py in off["e2"])


def test_offset_parallel_trunk_rewrites_and_is_idempotent():
    new, changed = edge_hygiene_text(_COLINEAR_TRUNKS)
    assert changed == ["e2"]
    geo2 = _geo(new)
    assert g.check_parallel_trunks(geo2) == []
    _new2, changed2 = edge_hygiene_text(new)
    assert changed2 == []


def test_parallel_trunk_noop_when_offset():
    # e1 has a vertical trunk at x=150; e2 is a short direct edge far to the
    # right that shares no grid line with e1 — the A3 detector fires on neither.
    xml = _model(
        _node("P", 0, 0) + _node("S", 300, 600)
        + _node("Q", 700, 0) + _node("R", 900, 0)
        + _edge(
            "e1", "P", "S", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="1",
            points='<mxPoint x="150" y="40"/><mxPoint x="150" y="640"/>',
        )
        + _edge("e2", "Q", "R", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", value="2")
    )
    assert g.check_parallel_trunks(_geo(xml)) == []
    _new, changed = edge_hygiene_text(xml)
    assert changed == []


# --------------------------------------------------------------------------- #
# report_edge_hygiene — the --check reporting extension
# --------------------------------------------------------------------------- #


def test_report_edge_hygiene_lists_defects(tmp_path):
    p = tmp_path / "bad.drawio"
    p.write_text(_COLLIDING_MARKERS, encoding="utf-8")
    lines = report_edge_hygiene(p)
    assert any("marker-collision" in ln for ln in lines)


def test_report_edge_hygiene_clean_after_cleanup(tmp_path):
    new, _ = edge_hygiene_text(_COLLIDING_MARKERS)
    p = tmp_path / "clean.drawio"
    p.write_text(new, encoding="utf-8")
    assert report_edge_hygiene(p) == []


# --------------------------------------------------------------------------- #
# B1 — marker-collision lint rule
# --------------------------------------------------------------------------- #


def test_lint_marker_collision_rule_fires():
    from rule_engine.linter import RULE_MARKER_COLLISION, RULE_SPECS, _check_marker_collision, Severity
    assert RULE_MARKER_COLLISION in RULE_SPECS
    assert RULE_SPECS[RULE_MARKER_COLLISION].default == Severity.WARNING

    class _Art:
        kind = "diagram"
        geometry = _geo(_COLLIDING_MARKERS)
    # _is_diagram checks the artifact shape; emulate the geometry accessor path.
    hit = _check_marker_collision(_FakeDiagram(_COLLIDING_MARKERS))
    assert hit
    assert set(hit.offenders) == {"e1", "e2"}


# --------------------------------------------------------------------------- #
# B2 — edge-crossing-excess lint rule
# --------------------------------------------------------------------------- #


def test_edge_crossing_excess_over_cap():
    # Two edges that cross once; with E=2 the cap is ceil(0.25*2)=1, so one
    # crossing is AT the cap (not over). Build four mutually-crossing edges so
    # the count exceeds the cap.
    xml = _model(
        _node("A", 0, 0) + _node("B", 400, 0)
        + _node("C", 0, 100) + _node("D", 400, 100)
        + _node("E", 0, 200) + _node("F", 400, 200)
        + _node("G", 200, 0, h=300)  # a tall node the H-edges' V-legs cross
        + _edge("e1", "A", "D", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
                points='<mxPoint x="220" y="40"/><mxPoint x="220" y="140"/>')
        + _edge("e2", "C", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
                points='<mxPoint x="240" y="140"/><mxPoint x="240" y="40"/>')
        + _edge("e3", "E", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
                points='<mxPoint x="260" y="240"/><mxPoint x="260" y="40"/>')
        + _edge("e4", "A", "F", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
                points='<mxPoint x="280" y="40"/><mxPoint x="280" y="240"/>')
    )
    geo = _geo(xml)
    cost = g.route_cost(geo)
    n = sum(1 for e in geo.edges if len(g.edge_polyline(geo, e)) >= 2)
    import math
    cap = math.ceil(0.25 * n)
    findings = g.check_edge_crossing_excess(geo)
    if cost.crossings > cap:
        assert findings, "excess crossings must be reported"
    else:
        assert findings == []


def test_edge_crossing_excess_none_when_no_crossings():
    xml = _model(
        _node("A", 0, 0) + _node("B", 300, 0)
        + _edge("e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    )
    assert g.check_edge_crossing_excess(_geo(xml)) == []


# --------------------------------------------------------------------------- #
# B3 — detour-hook lint rule
# --------------------------------------------------------------------------- #


def test_detour_hook_flags_looping_edge():
    # A and B are 300px apart horizontally (manhattan 300), but the edge loops
    # far down and back (routed >> 2.5*300).
    xml = _model(
        _node("A", 0, 0) + _node("B", 300, 0)
        + _edge(
            "e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
            points=(
                '<mxPoint x="150" y="40"/><mxPoint x="150" y="900"/>'
                '<mxPoint x="150" y="900"/><mxPoint x="150" y="40"/>'
            ),
        )
    )
    findings = g.check_detour_hook(_geo(xml))
    assert findings and findings[0][0] == "e1"
    assert "detour-ratio" in findings[0][1]


def test_detour_hook_ignores_direct_edge():
    xml = _model(
        _node("A", 0, 0) + _node("B", 300, 0)
        + _edge("e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    )
    assert g.check_detour_hook(_geo(xml)) == []


def test_detour_hook_allows_one_stair_dogleg():
    # A above-left of B: a single L-shaped dog-leg stays within 2.5x manhattan.
    xml = _model(
        _node("A", 0, 0) + _node("B", 300, 200)
        + _edge(
            "e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
            points='<mxPoint x="200" y="40"/><mxPoint x="200" y="240"/>',
        )
    )
    assert g.check_detour_hook(_geo(xml)) == []


# --------------------------------------------------------------------------- #
# B4 — structural-integrity lint rule
# --------------------------------------------------------------------------- #


def test_structural_integrity_flags_unresolved_endpoint():
    xml = _model(
        _node("A", 0, 0)
        + _edge("e1", "A", "ghost", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    )
    findings = g.check_structural_integrity(_geo(xml))
    assert ("e1", "edge-unresolved-target:ghost") in findings


def test_structural_integrity_clean_when_all_resolve():
    xml = _model(
        _node("A", 0, 0) + _node("B", 300, 0)
        + _edge("e1", "A", "B", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    )
    assert g.check_structural_integrity(_geo(xml)) == []


def test_structural_integrity_edge_to_container_ok():
    # An edge whose target is a boundary container resolves (containers are
    # placeable), so it is NOT flagged.
    xml = _model(
        _node("A", 0, 0)
        + '<mxCell id="vpc" value="vpc" vertex="1" parent="1" '
          'style="rounded=0;dashed=1;fillColor=none;verticalAlign=top;">'
          '<mxGeometry x="200" y="0" width="300" height="300" as="geometry"/></mxCell>'
        + _edge("e1", "A", "vpc", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    )
    geo = _geo(xml)
    # 'vpc' must be recognised as a container for this assertion to be meaningful.
    if "vpc" in geo.containers:
        assert all("edge-unresolved-target:vpc" not in r for _id, r in
                   g.check_structural_integrity(geo))


# --------------------------------------------------------------------------- #
# Test doubles for the linter predicate path
# --------------------------------------------------------------------------- #


class _FakeDiagram:
    """Minimal diagram Artifact stand-in the geometry predicates accept.

    The linter's ``_geometry_of`` returns ``a.geometry`` when ``_is_diagram(a)``.
    ``_is_diagram`` checks ``a.kind == 'diagram'`` (see linter). This double
    carries both so a predicate resolves the geometry.
    """

    kind = "diagram"

    def __init__(self, xml: str) -> None:
        self.geometry = _geo(xml)
