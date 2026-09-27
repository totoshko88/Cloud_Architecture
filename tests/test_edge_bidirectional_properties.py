"""Property + unit tests for the ``edge-bidirectional`` lint rule (1.10.0, Part A).

Requirement 1 (provider-diagram-conventions): a two-way relationship is drawn as
two single-ended edges, never a single double-headed arrow. An edge is a
Bidirectional_Edge when its style sets **both** a non-``none`` ``startArrow`` and
a non-``none`` ``endArrow``.

Property 1 (design.md): bidirectional detection is exact — an edge with two
non-``none`` arrowheads trips ``edge-bidirectional``; a single-head edge (the
common case) never does.

**Validates: Requirements 1.1, 1.2**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import (
    RULE_EDGE_BIDIRECTIONAL,
    RULE_SEVERITIES,
    Artifact,
    Severity,
    lint,
)


def _edge(start_arrow=None, end_arrow=None):
    return EdgeGeom(
        id="e1",
        source="a",
        target="b",
        orthogonal=True,
        exit=(1.0, 0.5),
        entry=(0.0, 0.5),
        start_arrow=start_arrow,
        end_arrow=end_arrow,
    )


def _geo(edge):
    return DiagramGeometry(
        nodes={"a": Box("a", 0, 0, 78, 78), "b": Box("b", 300, 0, 78, 78)},
        edges=[edge],
    )


def _flagged(edge) -> bool:
    return bool(geo.check_edge_bidirectional(_geo(edge)))


# --------------------------------------------------------------------------- #
# Unit cases — the concrete corners of the rule.
# --------------------------------------------------------------------------- #


def test_two_heads_are_flagged():
    """Both a real start head and a real end head → bidirectional."""
    assert _flagged(_edge(start_arrow="classic", end_arrow="open"))


def test_single_head_is_not_flagged():
    """The common single-head edge (no start head, end head set) is clean."""
    assert not _flagged(_edge(start_arrow=None, end_arrow="open"))
    assert not _flagged(_edge(start_arrow="none", end_arrow="open"))


def test_start_head_but_end_off_is_not_flagged():
    """A single head that happens to sit on the start is still one head."""
    assert not _flagged(_edge(start_arrow="open", end_arrow="none"))


def test_no_heads_is_not_flagged():
    """A bare line with no explicit start head is not bidirectional."""
    assert not _flagged(_edge(start_arrow=None, end_arrow=None))
    assert not _flagged(_edge(start_arrow="none", end_arrow="none"))


def test_rule_is_warning_both_classes():
    assert RULE_SEVERITIES[RULE_EDGE_BIDIRECTIONAL] == Severity.WARNING


def test_lint_surfaces_the_rule():
    """A double-headed edge produces the finding through the public lint()."""
    a = Artifact(kind="diagram", geometry=_geo(_edge("classic", "classic")))
    findings = {f["rule"] for f in lint(a)["findings"]}
    assert RULE_EDGE_BIDIRECTIONAL in findings


def test_lint_clean_single_head():
    a = Artifact(kind="diagram", geometry=_geo(_edge(None, "open")))
    findings = {f["rule"] for f in lint(a)["findings"]}
    assert RULE_EDGE_BIDIRECTIONAL not in findings


def test_build_geometry_exposes_start_arrow():
    """The parser round-trips ``startArrow`` from the .drawio style string."""
    from rule_engine.drawio_model import parse_drawio

    xml = (
        '<mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="a" vertex="1" parent="1" value="A" '
        'style="shape=mxgraph.aws4.resourceIcon">'
        '<mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>'
        '<mxCell id="b" vertex="1" parent="1" value="B" '
        'style="shape=mxgraph.aws4.resourceIcon">'
        '<mxGeometry x="300" y="0" width="78" height="78" as="geometry"/></mxCell>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="b" '
        'style="edgeStyle=orthogonalEdgeStyle;startArrow=classic;endArrow=classic">'
        '<mxGeometry as="geometry"/></mxCell>'
        '</root></mxGraphModel>'
    )
    g = geo.build_geometry(parse_drawio(xml, path="<test>.drawio")[0])
    assert len(g.edges) == 1
    assert (g.edges[0].start_arrow or "").lower() == "classic"
    assert bool(geo.check_edge_bidirectional(g))


# --------------------------------------------------------------------------- #
# Property 1 — bidirectional detection is exact.
# --------------------------------------------------------------------------- #

#: Arrow tokens: ``None``/``"none"`` mean "no head"; anything else is a head.
_NO_HEAD = st.sampled_from([None, "none", "None", "NONE"])
_HEAD = st.sampled_from(["classic", "open", "block", "oval", "diamond", "thin"])
_ANY_ARROW = st.one_of(_NO_HEAD, _HEAD)


def _start_is_head(token) -> bool:
    """An unspecified ``startArrow`` resolves to ``none`` (no start head)."""
    return token is not None and token.lower() != "none"


def _end_is_head(token) -> bool:
    """An unspecified ``endArrow`` inherits draw.io's default head (a head is
    present); only an explicit ``none`` turns the end head off — matching the
    rule and ``arrow-style``."""
    return token is None or token.lower() != "none"


@given(start_arrow=_ANY_ARROW, end_arrow=_ANY_ARROW)
def test_property_bidirectional_iff_two_heads(start_arrow, end_arrow):
    """``edge-bidirectional`` fires exactly when BOTH ends carry a real head.

    Defaults are resolved as draw.io does: an unspecified start is ``none`` (no
    head), an unspecified end inherits the default head. So the rule is
    ``start-head AND NOT end-explicitly-off``."""
    expected = _start_is_head(start_arrow) and _end_is_head(end_arrow)
    assert _flagged(_edge(start_arrow=start_arrow, end_arrow=end_arrow)) == expected


@given(end_arrow=_ANY_ARROW)
def test_property_single_head_never_flagged(end_arrow):
    """With no start head, no end-arrow value ever makes the edge bidirectional."""
    assert not _flagged(_edge(start_arrow=None, end_arrow=end_arrow))
    assert not _flagged(_edge(start_arrow="none", end_arrow=end_arrow))
