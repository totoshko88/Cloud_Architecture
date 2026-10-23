"""1.10.12 WS2: an edge never strikes its own node caption (defect C1).

Three mechanisms, each pinned here on a small synthetic diagram:

* **z-order** — ``build_diagram`` emits every edge BENEATH the vertices (on the
  root layer before the boundaries, or as the first child of the last filled
  boundary it touches), and a node whose caption a beneath-edge crosses gets the
  local fill as caption background, so ``labelBackgroundColor`` really masks the
  line;
* **Variant A** — ``caption_routing.plan_caption_safe`` re-routes a straight
  bottom drop through the source caption via the side corridor (exit right,
  enter the target's top), and grows a container whose right-edge node needs the
  corridor; on an OVERLOADED source (three right exits already) the unavoidable
  bottom exit moves into a corner band outside the caption text;
* **lint** — ``edge-crosses-label`` reports reason ``edge-crosses-own-label``.
"""
from __future__ import annotations

import re
from contextlib import contextmanager

from rule_engine import caption_routing as _cr
from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.linter import lint


@contextmanager
def _corner_exit_fallback():
    """Enable the pre-1.11.0 corner-exit (D) / caption-wrap fallback.

    ENG-R1 (1.11.0, REVIEW.md G25) turns the corner-exit fallback OFF by
    default — an overloaded bottom exit keeps its ``exit-thirds`` band and is
    masked by its caption (ENG-R2) instead of being pushed into a corner. The
    two legacy-behaviour tests below opt the fallback back ON to pin that the
    corner-band / caption-wrap machinery still works when enabled."""
    prev = _cr._CORNER_EXIT_FALLBACK[0]
    _cr._CORNER_EXIT_FALLBACK[0] = True
    try:
        yield
    finally:
        _cr._CORNER_EXIT_FALLBACK[0] = prev

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _build(nodes, edges, boundaries=(), legend_x=900, **kw):
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=list(boundaries),
        nodes=nodes, edges=edges, flow_lines=["Flow"] + [f"{e.marker}. step" for e in edges],
        legend_x=legend_x, page_w=1200, page_h=900, **kw,
    )


def _drop():
    nodes = [dl.Node("a", "service-a", 200, 200, render=_ICON),
             dl.Node("b", "service-b", 200, 400, render=_ICON)]
    edges = [dl.Edge("e1", "a", "b", "1", exit=(0.5, 1.0), entry=(0.5, 0.0))]
    return nodes, edges


def test_straight_bottom_drop_takes_the_side_corridor():
    nodes, edges = _drop()
    g = _geo(_build(nodes, edges))
    e1 = g.edges[0]
    assert e1.exit[0] >= 1.0, e1.exit                    # right face
    assert e1.entry[1] <= 0.0, e1.entry                  # target top
    assert geo.check_edge_crosses_own_label(g) == []
    assert geo.check_edge_direction(g) == []
    assert geo.check_edge_approach(g) == []


def test_caption_safe_false_keeps_the_route_and_lint_reports_it(tmp_path):
    nodes, edges = _drop()
    text = _build(nodes, edges, caption_safe=False)
    g = _geo(text)
    assert geo.check_edge_crosses_own_label(g) == [("e1", "a")]
    assert geo.check_edge_strikes_own_text(g) == [("e1", "a")]
    path = tmp_path / "01-t.drawio"
    path.write_text(text, encoding="utf-8")
    findings = [f for art in parse_artifacts(str(path)) for f in lint(art)["findings"]]
    own = [f for f in findings if f["rule"] == "edge-crosses-label"
           and f.get("reason") == "edge-crosses-own-label"]
    assert own and own[0]["severity"] == "WARNING", findings
    assert "e1" in own[0]["offenders"]


def test_edges_are_emitted_beneath_vertices_and_mask_the_caption():
    nodes, edges = _drop()
    text = _build(nodes, edges, caption_safe=False)
    assert text.index('<mxCell id="e1"') < text.index('<mxCell id="a"')
    # The struck caption is painted on an opaque background.
    a = re.search(r'<mxCell id="a"[^>]*style="([^"]*)"', text).group(1)
    assert a.rstrip(";").endswith("labelBackgroundColor=#FFFFFF"), a


def test_edge_touching_a_filled_boundary_is_its_first_child():
    nodes, edges = _drop()
    box = dl.Boundary("boundary-r", "region", 150, 150, 300, 400,
                      style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F4F2;"
                            "strokeColor=#9E9892;verticalAlign=top;fontSize=12")
    text = _build(nodes, edges, boundaries=[box], caption_safe=False)
    cell = re.search(r'<mxCell id="e1"[^>]*>', text).group(0)
    assert 'parent="boundary-r"' in cell, cell
    assert text.index('<mxCell id="boundary-r"') < text.index('<mxCell id="e1"') \
        < text.index('<mxCell id="a"')
    # Waypoints are stored relative to the boundary, absolute geometry unchanged.
    g = _geo(text)
    assert geo.edge_polyline(g, g.edges[0])[0] == (240.0, 278.0)


def _overloaded_short():
    nodes = [dl.Node("hub", "hub", 200, 300, render=_ICON),
             dl.Node("t1", "t1", 500, 100, render=_ICON),
             dl.Node("t2", "t2", 500, 300, render=_ICON),
             dl.Node("t3", "t3", 500, 500, render=_ICON),
             dl.Node("d", "d", 200, 560, render=_ICON)]
    edges = [
        dl.Edge("e1", "hub", "t1", "1", exit=(1.0, 0.25), entry=(0.0, 0.5),
                points=((330, 320), (330, 140))),
        dl.Edge("e2", "hub", "t2", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
        dl.Edge("e3", "hub", "t3", "3", exit=(1.0, 0.75), entry=(0.0, 0.5),
                points=((330, 360), (330, 540))),
        dl.Edge("e4", "hub", "d", "4", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    ]
    return nodes, edges


def test_overloaded_source_uses_a_corner_band_outside_the_text():
    """LEGACY (fallback ON): three right exits are taken, so ``exit-thirds``
    leaves the bottom face; the short name ("hub", 21px) leaves a corner band
    beside the text. Pins that the corner-exit (D) machinery still works when
    the fallback is explicitly enabled (ENG-R1 default-off)."""
    nodes, edges = _overloaded_short()
    with _corner_exit_fallback():
        g = _geo(_build(nodes, edges))
    e4 = next(e for e in g.edges if e.id == "e4")
    assert e4.exit[1] >= 1.0, e4.exit                    # still the bottom face
    assert geo.check_edge_strikes_own_text(g) == []      # but clear of the text
    assert geo.check_exit_thirds(g) == []


def test_overloaded_source_default_keeps_thirds_and_masks_caption():
    """DEFAULT (ENG-R1, fallback OFF): the unavoidable bottom exit keeps a
    distinct ``exit-thirds`` band (not a corner) and its caption is masked
    (ENG-R2), so the diagram stays ``exit-thirds``-clean without the corner
    dodge. A short caption fits inside the icon, so there is no text strike."""
    nodes, edges = _overloaded_short()
    g = _geo(_build(nodes, edges))
    e4 = next(e for e in g.edges if e.id == "e4")
    assert e4.exit[1] >= 1.0, e4.exit                    # still the bottom face
    assert geo.check_exit_thirds(g) == []                # distinct band, not merged


def test_container_grows_to_hold_the_side_corridor():
    """The source is the right-most node of its box; the corridor past its wide
    caption leaves the box, so the box grows right instead (with padding) and
    the right-margin Flow/Legend moves with it."""
    nodes = [dl.Node("a", "a-wide-service-name", 200, 200, render=_ICON),
             dl.Node("b", "b", 200, 400, render=_ICON)]
    edges = [dl.Edge("e1", "a", "b", "1", exit=(0.5, 1.0), entry=(0.5, 0.0))]
    box = dl.Boundary("boundary-acct", "acct", 170, 140, 138, 400)
    g = _geo(_build(nodes, edges, boundaries=[box], legend_x=338))
    assert geo.check_edge_crosses_own_label(g) == []
    acct = g.containers["boundary-acct"]
    assert acct.right > 308, acct
    assert all(t.x >= acct.right + dl.CONTAINER_PAD for k, t in g.text_boxes.items()
               if k != "title"), g.text_boxes
    assert geo.check_edge_escapes_container(g) == []


def test_text_extent_is_narrower_than_the_caption_band():
    box = geo.Box("n", 0, 0, 78, 78)
    assert geo.caption_text_box(box, "app-az1").w == 49.0
    assert geo.node_caption_box(box, "app-az1").w == 78.0


def test_wrap_caption_breaks_at_space_or_hyphen_nearest_the_middle():
    assert geo.wrap_caption("Lambda core (13 fns)") == "Lambda core\n(13 fns)"
    assert geo.wrap_caption("Lambda VPC-attached") == "Lambda VPC-\nattached"
    assert geo.wrap_caption("tool-invoker") == "tool-\ninvoker"
    assert geo.wrap_caption("SEP platform") == "SEP\nplatform"
    # Never inside a word; no break point, or already two lines -> None.
    assert geo.wrap_caption("orchestrator") is None
    assert geo.wrap_caption("a-") is None
    assert geo.wrap_caption("a\nb") is None


def test_wrapped_caption_footprint_is_one_line_taller():
    """A second caption line adds ``CAPTION_LINE_H`` (16px) everywhere the
    caption is measured: caption box, text box and node footprint."""
    box = geo.Box("n", 0, 0, 78, 78)
    assert geo.node_caption_box(box, "a\nb").h == geo.LABEL_BAND + 16.0
    assert geo.caption_text_box(box, "a\nb").h == geo.LABEL_BAND + 16.0
    g = geo.DiagramGeometry(nodes={"n": box}, node_labels={"n": "a\nb"})
    assert geo.node_footprint(g, "n").h == 78 + geo.LABEL_BAND + 16.0
    assert geo.node_footprint(g, "n", 0).h == 78  # the icon-only test is unchanged


def _overloaded_wide(label: str):
    nodes = [dl.Node("hub", label, 200, 300, render=_ICON),
             dl.Node("t1", "t1", 500, 100, render=_ICON),
             dl.Node("t2", "t2", 500, 300, render=_ICON),
             dl.Node("t3", "t3", 500, 500, render=_ICON),
             dl.Node("d", "d", 200, 600, render=_ICON)]
    edges = [
        dl.Edge("e1", "hub", "t1", "1", exit=(1.0, 0.25), entry=(0.0, 0.5),
                points=((330, 320), (330, 140))),
        dl.Edge("e2", "hub", "t2", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
        dl.Edge("e3", "hub", "t3", "3", exit=(1.0, 0.75), entry=(0.0, 0.5),
                points=((330, 360), (330, 540))),
        dl.Edge("e4", "hub", "d", "4", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    ]
    return nodes, edges


def test_overloaded_source_with_a_wide_caption_wraps_it():
    """LEGACY (fallback ON): three right exits, an unavoidable bottom exit and
    a caption wider than the icon -> the caption wraps onto two lines and the
    bottom exit leaves past the narrower text. Pins the caption-wrap macro-move
    still works when the corner-exit fallback is explicitly enabled (ENG-R1
    default-off)."""
    nodes, edges = _overloaded_wide("Lambda core (13 fns)")
    with _corner_exit_fallback():
        text = _build(nodes, edges)
    assert 'value="Lambda core&#10;(13 fns)"' in text
    g = _geo(text)
    assert g.node_labels["hub"] == "Lambda core\n(13 fns)"
    e4 = next(e for e in g.edges if e.id == "e4")
    assert e4.exit[1] >= 1.0, e4.exit
    assert geo.check_edge_strikes_own_text(g) == []
    assert geo.check_exit_thirds(g) == []
    assert geo.check_container_padding(g) == [] and geo.check_node_overlap(g) == []


def test_overloaded_wide_caption_default_masks_instead_of_wrapping():
    """DEFAULT (ENG-R1, fallback OFF): with the corner/wrap fallback off, a wide
    caption is NOT wrapped; the bottom exit keeps its ``exit-thirds`` band and
    the caption is masked (ENG-R2) so the line passes behind the name."""
    nodes, edges = _overloaded_wide("Lambda core (13 fns)")
    text = _build(nodes, edges)
    assert 'value="Lambda core&#10;(13 fns)"' not in text   # NOT wrapped
    g = _geo(text)
    assert g.node_labels["hub"] == "Lambda core (13 fns)"
    e4 = next(e for e in g.edges if e.id == "e4")
    assert e4.exit[1] >= 1.0, e4.exit
    assert geo.check_exit_thirds(g) == []


def test_overloaded_source_without_a_break_point_keeps_its_label():
    """Fallback: no space or hyphen -> no wrap; the node keeps its masked
    bottom exit (an accepted residual, still reported by the WARNING)."""
    nodes, edges = _overloaded_wide("orchestratorservice")
    text = _build(nodes, edges)
    g = _geo(text)
    assert g.node_labels["hub"] == "orchestratorservice"
    assert 'value="orchestratorservice"' in text
