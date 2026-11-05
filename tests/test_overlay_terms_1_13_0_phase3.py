"""1.13.0 phase 3 item 18 — overlay terms for inventory-unbacked facts.

Two residuals from the 09-13 / 03 feedback (B):

1. ``unconfirmed`` is usable on an EDGE (an inventory-unbacked relationship — the
   11 SQS consumer, the 09 e21 assumption): ``Edge(unconfirmed=True)`` renders a
   dashed line carrying the ``overlay=unconfirmed`` token, the numeric marker
   value is unchanged (so flow-marker / flow-legend checks keyed on
   ``isdigit()`` still see a plain number), and ``overlay_legend_lines`` emits
   the standard ``unconfirmed`` Legend line when scanning edges.
2. ``no-known-caller`` is a node overlay term (the 03 strapi-alb cluster): it has
   a distinct shape + Legend line and, like every overlay-marked node, is
   excluded from ``graph-islands`` and accepted by ``node-connectivity``.
"""
from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine.drawio_model import parse_drawio


# --- 1. unconfirmed on an edge --------------------------------------------

def _edge(**kw):
    base = dict(id="e1", source="a", target="b", marker="3")
    base.update(kw)
    return dl.Edge(**base)


def test_unconfirmed_edge_renders_dashed_with_overlay_token():
    cell = dl.edge_cell(_edge(unconfirmed=True))
    assert "dashed=1" in cell
    assert "overlay=unconfirmed" in cell
    # the numeric marker is still the plain value (NOT suffixed with [?]).
    assert 'value="3"' in cell


def test_confirmed_edge_is_byte_identical_to_before():
    plain = dl.edge_cell(_edge())
    assert "overlay=unconfirmed" not in plain
    assert "dashPattern=8 8" not in plain


def test_unconfirmed_edge_marker_is_parsed_as_numeric():
    # The style token must not break the numeric-marker parse: an unconfirmed
    # edge keeps value "3", so geometry still treats it as a flow marker.
    xml = (
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'{dl.edge_cell(_edge(unconfirmed=True))}'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    page = parse_drawio(xml, path="<t>.drawio")[0]
    e = next(c for c in page.cells.values() if c.edge)
    assert e.label == "3"
    assert e.style_map.get("overlay") == "unconfirmed"


def test_overlay_legend_lines_scans_edges():
    lines = dl.overlay_legend_lines([], [_edge(unconfirmed=True)])
    assert any("unconfirmed" in ln for ln in lines)


def test_overlay_legend_lines_edges_default_empty_is_inert():
    # No edges arg, or no unconfirmed edge -> no line (byte-inert).
    assert dl.overlay_legend_lines([]) == ()
    assert dl.overlay_legend_lines([], [_edge()]) == ()


# --- 2. no-known-caller node term -----------------------------------------

def test_no_known_caller_has_a_distinct_shape_and_legend():
    shape = dl._OVERLAY_SHAPE["no-known-caller"]
    assert "dashed=1" in shape
    assert shape not in (
        dl._OVERLAY_SHAPE["standby"],
        dl._OVERLAY_SHAPE["supporting"],
        dl._OVERLAY_SHAPE["unconfirmed"],
    )
    line = dl.OVERLAY_LEGEND_LINES.get("no-known-caller")
    assert line is not None and "no known caller" in line


def test_no_known_caller_node_gets_overlay_token_and_ring():
    n = dl.Node("strapi-alb", "strapi-alb", 0, 0, render=None, overlay="no-known-caller")
    assert "overlay=no-known-caller" in dl.overlay_suffix(n)
    assert dl.overlay_ring_cell(n) != ""  # a ring is drawn


def test_no_known_caller_excluded_from_islands_and_connectivity():
    # A node carrying ANY overlay term is in geo.overlay_nodes, so graph-islands
    # and node-connectivity both exempt it — the plumbing is the overlay token,
    # which the parser records for no-known-caller like every other term.
    from rule_engine import geometry as geo
    xml = (
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="strapi" value="strapi-alb" '
        'style="image;image=x.svg;overlay=no-known-caller;dashed=1;dashPattern=1 2;" '
        'vertex="1" parent="1"><mxGeometry x="100" y="100" width="78" height="78" as="geometry"/></mxCell>'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    g = geo.build_geometry(parse_drawio(xml, path="<t>.drawio")[0])
    assert g.overlay_nodes.get("strapi") == "no-known-caller"
    # no incident edge, but overlay-marked -> not a node-connectivity finding
    assert "strapi" not in geo.check_node_connectivity(g)
