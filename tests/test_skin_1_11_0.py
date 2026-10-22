"""WS1 (1.11.0) — presentation skin tests.

The skin restyles furniture borders and edge colour as pure STYLE channels: it
must never move a node or edge coordinate, and the default skin (or no skin at
all) must reproduce the 1.10.12 byte output exactly.
"""

from __future__ import annotations

import re

from rule_engine import diagram_layout as dl


def _edge(**kw):
    return dl.Edge(id="e1", source="a", target="b", marker="1",
                   exit=(1.0, 0.5), entry=(0.0, 0.5), **kw)


def test_default_skin_fields():
    assert dl.DEFAULT_SKIN.furniture_stroke == "black"
    assert dl.DEFAULT_SKIN.edge_stroke is None
    assert dl.DEFAULT_SKIN.marker_badge == "none"


def test_edge_cell_default_skin_is_byte_identical():
    """None vs the default skin vs furniture-only skin all emit the same edge."""
    base = dl.edge_cell(_edge())
    assert dl.edge_cell(_edge(), skin=None) == base
    assert dl.edge_cell(_edge(), skin=dl.DEFAULT_SKIN) == base
    # edge colour unset → no strokeColor token on the edge
    assert "strokeColor=" not in base


def test_edge_cell_edge_stroke_adds_strokecolor_only():
    skin = dl.Skin(edge_stroke="#5A6B7B")
    out = dl.edge_cell(_edge(), skin=skin)
    assert "strokeColor=#5A6B7B;" in out
    # geometry/contacts unchanged: the exit/entry fractions are identical
    base = dl.edge_cell(_edge())
    for tok in ("exitX=1.0", "entryX=0.0", "edgeStyle=orthogonalEdgeStyle"):
        assert tok in out and tok in base


def test_edge_stroke_never_moves_waypoints():
    e = _edge(points=((120.0, 200.0), (120.0, 360.0)))
    base = dl.edge_cell(e)
    skinned = dl.edge_cell(e, skin=dl.Skin(edge_stroke="#3B4A5A"))
    pts = lambda s: re.findall(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)"', s)
    assert pts(base) == pts(skinned)


def test_text_cell_default_skin_is_byte_identical():
    lines = ("Flow", "1. a to b")
    base = dl.text_cell("flow-legend", lines, 10, 20, 320, 200)
    assert dl.text_cell("flow-legend", lines, 10, 20, 320, 200, skin=None) == base
    assert dl.text_cell("flow-legend", lines, 10, 20, 320, 200, skin=dl.DEFAULT_SKIN) == base
    assert "strokeColor=#000000" in base


def test_text_cell_light_furniture_stroke():
    lines = ("Legend",)
    out = dl.text_cell("legend", lines, 10, 20, 320, 200, skin=dl.Skin(furniture_stroke="light"))
    assert "strokeColor=#B3B3B3" in out
    assert "strokeColor=#000000" not in out
    # fill and padding untouched (only the stroke token swapped)
    assert "fillColor=#FFFFFF" in out
    assert out.count("strokeColor=") == 1


def test_marker_badge_none_is_byte_inert_default():
    # the badge is a later geometry feature; carrying marker_badge='none' must
    # change nothing in the edge cell today.
    base = dl.edge_cell(_edge())
    assert dl.edge_cell(_edge(), skin=dl.Skin(marker_badge="none")) == base


def test_marker_badge_circle_renders_disc_and_square_box():
    circ = dl.edge_cell(_edge(), skin=dl.Skin(marker_badge="circle"))
    sq = dl.edge_cell(_edge(), skin=dl.Skin(marker_badge="square"))
    assert "border-radius:50%" in circ and "background:#1A1A1A" in circ
    assert "border-radius:3px" in sq


def test_marker_badge_label_still_reads_as_a_digit():
    """The badge wraps the number in HTML; the drawio parser strips HTML, so the
    marker is still detected (node-count, marker-* rules keep working)."""
    import re
    from html import unescape

    circ = dl.edge_cell(_edge(), skin=dl.Skin(marker_badge="circle"))
    val = re.search(r'value="([^"]*)"', circ).group(1)
    text = re.sub(r"<[^>]+>", "", unescape(val)).strip()
    assert text == "1" and text.isdigit()


def test_marker_badge_does_not_move_the_edge_geometry():
    e = _edge(points=((120.0, 200.0), (120.0, 360.0)))
    base = dl.edge_cell(e)
    badged = dl.edge_cell(e, skin=dl.Skin(marker_badge="circle"))
    pts = lambda s: re.findall(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)"', s)
    assert pts(base) == pts(badged)
    for tok in ("exitX=1.0", "entryX=0.0"):
        assert tok in base and tok in badged

