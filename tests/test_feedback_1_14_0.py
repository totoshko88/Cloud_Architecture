"""1.14.0: the three FIUB generation-feedback defects (RE-FB-001..003).

* RE-FB-001 — the ``spec-required-not-deployed`` overlay is drawn (a red dashed
  ring), and ``overlay-rendered`` (ERROR) catches a Legend that defines an
  overlay no cell carries, or a marked node with no ring; an undocumented
  overlay (``overlay-legend-coverage``) is now an ERROR too.
* RE-FB-002 — look-alike glyphs: two roles of one ``glyph_family`` on a canvas
  get a role badge, and ``indistinguishable-role-glyphs`` (WARNING) reports a
  family whose roles still draw unbadged.
* RE-FB-003 — two edges with a different source AND target that share a
  stretch of one line are ``collinear-edges`` ``cross-source-overlap``, an
  ERROR; a fan-out / fan-in stays WARNING-or-exempt.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.cli import _legend_defined_terms, parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.icon_resolver import glyph_key_of_style, role_glyph
from rule_engine.linter import lint

_LAMBDA = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_BEDROCK = dl.image_icon(
    "assets/vendor/aws-icons/Architecture-Service-Icons_07312026/"
    "Arch_Artificial-Intelligence/48/Arch_Amazon-Bedrock_48.svg"
)
_TITLE = "aws t — 111122223333 / eu-central-1 | 2026-11-25 | v1"


def _build(nodes, edges=(), legend_extra=(), title=_TITLE) -> str:
    acct = dl.Boundary(id="boundary-acct", label="Account 111122223333",
                       x=60, y=60, w=760, h=260, stroke="#CD2264")
    legend = list(dl.legend_lines_for([])) + list(legend_extra)
    flow = ["Flow"] + [f"{e.marker}. step" for e in edges if e.marker]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=title, boundaries=[acct],
        nodes=list(nodes), edges=list(edges), flow_lines=flow,
        legend_x=900, legend_lines=legend, page_w=1400, page_h=500,
    )


def _lint_text(tmp_path: Path, text: str):
    path = tmp_path / "01-t.drawio"
    path.write_text(text, encoding="utf-8")
    (art,) = parse_artifacts(str(path))
    return art, lint(art)["findings"]


def _hits(findings, rule):
    return [f for f in findings if f["rule"] == rule]


def _cell(text: str, cid: str) -> str:
    m = re.search(r'<mxCell id="' + re.escape(cid) + r'".*?</mxCell>', text, re.S)
    assert m, cid
    return m.group(0)


# --------------------------------------------------------------------------- #
# RE-FB-001
# --------------------------------------------------------------------------- #


def test_spec_required_overlay_draws_a_red_dashed_ring():
    n = dl.Node("guard", "Guardrails", 120, 150, render=_LAMBDA,
                overlay="spec-required-not-deployed")
    ring = dl.overlay_ring_cell(n)
    assert ring, "a spec-required-not-deployed node must get a ring"
    assert "strokeColor=#D64550" in ring and "dashed=1" in ring
    assert dl.OVERLAY_LEGEND_LINES["spec-required-not-deployed"].startswith(
        "spec-required-not-deployed =")
    # the neutral terms keep their neutral ring colour (byte-inert)
    sb = dl.overlay_ring_cell(dl.Node("s", "S", 0, 0, render=_LAMBDA, overlay="standby"))
    assert f"strokeColor={dl.OVERLAY_RING_STROKE};strokeWidth=1.5;" in sb


def test_built_diagram_with_spec_required_overlay_is_clean(tmp_path):
    nodes = [
        dl.Node("a", "api", 120, 150, render=_LAMBDA),
        dl.Node("guard", "Guardrails", 340, 150, render=_LAMBDA,
                overlay="spec-required-not-deployed"),
    ]
    edges = [dl.Edge(id="e1", source="a", target="guard", marker="1")]
    text = _build(nodes, edges, dl.overlay_legend_lines(nodes))
    assert "overlayring-guard" in text
    _art, findings = _lint_text(tmp_path, text)
    assert not _hits(findings, "overlay-rendered")
    assert not _hits(findings, "overlay-legend-coverage")


def test_marked_node_without_ring_is_overlay_not_rendered(tmp_path):
    nodes = [
        dl.Node("a", "api", 120, 150, render=_LAMBDA),
        dl.Node("guard", "Guardrails", 340, 150, render=_LAMBDA,
                overlay="spec-required-not-deployed"),
    ]
    edges = [dl.Edge(id="e1", source="a", target="guard", marker="1")]
    text = _build(nodes, edges, dl.overlay_legend_lines(nodes))
    text = re.sub(r'\s*<mxCell id="overlayring-guard".*?</mxCell>', "", text, flags=re.S)
    _art, findings = _lint_text(tmp_path, text)
    hits = _hits(findings, "overlay-rendered")
    assert hits and hits[0]["severity"] == "ERROR"
    assert "guard:spec-required-not-deployed" in hits[0]["offenders"]


def test_legend_defining_an_undrawn_overlay_is_an_error(tmp_path):
    nodes = [dl.Node("a", "api", 120, 150, render=_LAMBDA),
             dl.Node("b", "worker", 340, 150, render=_LAMBDA)]
    edges = [dl.Edge(id="e1", source="a", target="b", marker="1")]
    text = _build(nodes, edges, ["Dashed red = spec-required-not-deployed"])
    _art, findings = _lint_text(tmp_path, text)
    hits = _hits(findings, "overlay-rendered")
    assert hits and hits[0]["severity"] == "ERROR"
    assert "spec-required-not-deployed" in hits[0]["offenders"]


def test_undocumented_overlay_is_now_an_error(tmp_path):
    nodes = [dl.Node("a", "api", 120, 150, render=_LAMBDA),
             dl.Node("m", "monitor", 340, 150, render=_LAMBDA, overlay="supporting")]
    text = _build(nodes)  # no overlay legend line
    _art, findings = _lint_text(tmp_path, text)
    hits = _hits(findings, "overlay-legend-coverage")
    assert hits and hits[0]["severity"] == "ERROR"


def test_legend_definition_needs_an_equals_binding():
    terms = {"supporting", "standby", "spec-required-not-deployed"}
    lines = [
        "Legend",
        "Dashed red = spec-required-not-deployed",
        "standby = passive peer",
        "Ops services supporting the workload are grey",  # prose, no binding
        "callout 'draft' = unconfirmed path, first-draft assumption",  # a word, not the side
    ]
    terms.add("unconfirmed")
    assert _legend_defined_terms(lines, terms) == ["spec-required-not-deployed", "standby"]


# --------------------------------------------------------------------------- #
# RE-FB-002
# --------------------------------------------------------------------------- #


def test_mapping_declares_the_bedrock_family_and_badges():
    base = role_glyph("llm_platform", "aws")
    gr = role_glyph("bedrock_guardrails", "aws")
    kb = role_glyph("bedrock_kb", "aws")
    ac = role_glyph("bedrock_agentcore", "aws")
    assert base["family"] == gr["family"] == kb["family"] == ac["family"] == "bedrock"
    assert (gr["badge"], kb["badge"], ac["badge"]) == ("GR", "KB", "AC")
    assert base["badge"] == ""
    assert role_glyph("no-such-role", "aws") is None
    assert role_glyph("llm_platform", "not-a-provider") is None


def test_glyph_key_prefers_iconref_over_inline_data():
    assert glyph_key_of_style("image=data:image/svg+xml,AAA;iconRef=a/b.svg") == "a/b.svg"
    assert glyph_key_of_style("shape=x;resIcon=mxgraph.aws4.lambda") == "mxgraph.aws4.lambda"
    assert glyph_key_of_style("image=data:image/svg+xml,AAA") == ""


def test_look_alike_roles_get_badges_and_role_tokens(tmp_path):
    nodes = [
        dl.Node("llm", "Bedrock", 120, 150, render=_BEDROCK, role="llm_platform"),
        dl.Node("gr", "Guardrails", 340, 150, render=_BEDROCK, role="bedrock_guardrails"),
        dl.Node("kb", "Bedrock KB", 560, 150, render=_BEDROCK, role="bedrock_kb"),
    ]
    edges = [dl.Edge(id="e1", source="llm", target="gr", marker="1"),
             dl.Edge(id="e2", source="gr", target="kb", marker="2")]
    text = _build(nodes, edges)
    assert 'value="GR"' in _cell(text, "rolebadge-gr")
    assert 'value="KB"' in _cell(text, "rolebadge-kb")
    assert "rolebadge-llm" not in text  # the base role reads by elimination
    assert "role=bedrock_kb" in _cell(text, "kb")
    page = parse_drawio(text, path="t.drawio")[0]
    g = geo.build_geometry(page)
    assert set(g.nodes) == {"llm", "gr", "kb"}  # a badge is not a node
    art, findings = _lint_text(tmp_path, text)
    assert sorted(art.node_names) == ["Bedrock", "Bedrock KB", "Guardrails"]
    assert not _hits(findings, "indistinguishable-role-glyphs")


def test_role_without_look_alike_emits_nothing():
    nodes = [dl.Node("llm", "Bedrock", 120, 150, render=_BEDROCK, role="llm_platform"),
             dl.Node("f", "fn", 340, 150, render=_LAMBDA, role="serverless_fn")]
    text = _build(nodes, [dl.Edge(id="e1", source="f", target="llm", marker="1")])
    assert "role=" not in text and "rolebadge-" not in text
    plain = _build([dl.Node("llm", "Bedrock", 120, 150, render=_BEDROCK),
                    dl.Node("f", "fn", 340, 150, render=_LAMBDA)],
                   [dl.Edge(id="e1", source="f", target="llm", marker="1")])
    assert text == plain  # byte-inert when no look-alike shares the canvas


def test_unbadged_look_alikes_are_reported(tmp_path):
    nodes = [
        dl.Node("llm", "Bedrock", 120, 150, render=_BEDROCK, role="llm_platform"),
        dl.Node("gr", "Guardrails", 340, 150, render=_BEDROCK, role="bedrock_guardrails"),
    ]
    text = _build(nodes, [dl.Edge(id="e1", source="llm", target="gr", marker="1")])
    text = re.sub(r'\s*<mxCell id="rolebadge-gr".*?</mxCell>', "", text, flags=re.S)
    _art, findings = _lint_text(tmp_path, text)
    hits = _hits(findings, "indistinguishable-role-glyphs")
    assert hits and hits[0]["severity"] == "WARNING"
    assert "bedrock_guardrails(gr)" in hits[0]["offenders"][0]


# --------------------------------------------------------------------------- #
# RE-FB-003
# --------------------------------------------------------------------------- #


def _geo_with_legs(polys, ends):
    """A geometry with node-free edges, so the collinear test sees only legs."""
    page = parse_drawio(_build([dl.Node("a", "a", 120, 150, render=_LAMBDA)]),
                        path="t.drawio")[0]
    g = geo.build_geometry(page)
    edges = [geo.EdgeGeom(id=eid, source=s, target=t, orthogonal=True,
                          exit=(None, None), entry=(None, None), points=[])
             for eid, (s, t) in ends.items()]
    return replace(g, edges=edges), polys


def test_cross_source_overlap_kind():
    polys = {
        "e10": [(110.0, 300.0), (140.0, 300.0), (140.0, 480.0), (590.0, 480.0)],
        "e2": [(110.0, 430.0), (140.0, 430.0), (140.0, 470.0), (290.0, 470.0)],
    }
    g, polys = _geo_with_legs(polys, {"e10": ("slack", "alb"), "e2": ("hooks", "waf")})
    kinds = {k for _a, _b, k in geo.collinear_edge_findings(g, polys)}
    assert "cross-source-overlap" in kinds


def test_shared_source_overlap_is_not_cross_source():
    polys = {
        "e1": [(110.0, 300.0), (140.0, 300.0), (140.0, 480.0), (590.0, 480.0)],
        "e2": [(110.0, 430.0), (140.0, 430.0), (140.0, 470.0), (290.0, 470.0)],
    }
    g, polys = _geo_with_legs(polys, {"e1": ("src", "t1"), "e2": ("src", "t2")})
    kinds = {k for _a, _b, k in geo.collinear_edge_findings(g, polys)}
    assert "cross-source-overlap" not in kinds
