"""1.13.0 (feedback): the ``unconfirmed`` overlay term.

The diagram standards require an unconfirmed inventory item to be drawn dashed
and marked ``[?]``. Before 1.13.0 the overlay vocabulary was only ``standby``
and ``supporting``, so ``overlay="unconfirmed"`` rendered dashed via the
``_OVERLAY_SHAPE`` fallback but tripped ``overlay-legend-coverage``
(``undocumented-overlay``) because the term had no standard Legend line. It is
now first-class: a distinct dash pattern and a canonical Legend line, so the
``[?]`` convention is covered rather than a WARNING.
"""

from __future__ import annotations

from rule_engine import diagram_layout as dl


def test_unconfirmed_has_a_distinct_dash_shape():
    shape = dl._OVERLAY_SHAPE["unconfirmed"]
    assert "dashed=1" in shape
    # distinct from standby and supporting so the three read apart.
    assert shape != dl._OVERLAY_SHAPE["standby"]
    assert shape != dl._OVERLAY_SHAPE["supporting"]


def test_unconfirmed_has_a_standard_legend_line():
    line = dl.OVERLAY_LEGEND_LINES.get("unconfirmed")
    assert line is not None
    assert "unconfirmed" in line and "[?]" in line


def test_overlay_suffix_encodes_the_term_and_dashes():
    n = dl.Node("x", "X", 0, 0, render=None, overlay="unconfirmed")
    suffix = dl.overlay_suffix(n)
    assert "overlay=unconfirmed" in suffix and "dashed=1" in suffix


def test_overlay_legend_lines_emits_the_unconfirmed_line():
    n = dl.Node("x", "X", 0, 0, render=None, overlay="unconfirmed")
    lines = dl.overlay_legend_lines([n])
    assert any("unconfirmed" in ln and "[?]" in ln for ln in lines)


def test_standby_and_supporting_are_unchanged():
    # the two pre-existing terms keep their exact shapes + lines (byte-inert).
    assert dl._OVERLAY_SHAPE["standby"] == "dashed=1;dashPattern=6 4"
    assert dl._OVERLAY_SHAPE["supporting"] == "dashed=1;dashPattern=1 3"
    assert dl.OVERLAY_LEGEND_LINES["standby"].startswith("standby = passive peer")
    assert dl.OVERLAY_LEGEND_LINES["supporting"].startswith("supporting = ops")
