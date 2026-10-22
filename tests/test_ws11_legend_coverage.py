"""WS11 (1.10.12, defect C10): the Legend never lists an undrawn boundary.

``diagram_layout.legend_lines_for`` names the outer/inner boundary only when
that boundary is actually drawn, and it is applied on EVERY build path. The new
``legend-boundary-coverage`` lint rule (WARNING) reports a Legend that still
lists a boundary not on the canvas — the mirror of ``legend-present``.

Covered here:

* the geometry check ``check_legend_boundary_coverage`` flags an account-only
  diagram whose Legend lists an inner boundary, and is silent once the inner
  line is dropped or an inner boundary is drawn;
* ``legend_lines_for`` drops the inner line for an account-only set of
  boundaries and keeps both for an account + VPC nesting;
* ``build_diagram`` applies ``legend_lines_for`` when ``legend_lines is None``;
* the lint rule reports the WARNING and goes silent after the fix;
* acceptance: SEP 01 and 04, rebuilt through their scripts, no longer list an
  inner boundary that is not drawn.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box, DiagramGeometry
from rule_engine.linter import lint

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"

_INNER = "Inner boundary = Network Boundary (captioned; provider style)"
_OUTER = "Outer boundary = stack Boundary (captioned; provider style)"


def _geo_with_containers(boxes) -> DiagramGeometry:
    g = DiagramGeometry()
    for cid, (x, y, w, h) in boxes.items():
        g.containers[cid] = Box(cid, x, y, w, h)
    return g


# --------------------------------------------------------------------------- #
# The geometry check
# --------------------------------------------------------------------------- #


def test_account_only_with_inner_line_is_flagged():
    g = _geo_with_containers({"acct": (0, 0, 400, 400)})
    offenders = geo.check_legend_boundary_coverage(g, list(dl.STANDARD_LEGEND_LINES))
    assert offenders == [_INNER]  # outer IS drawn; inner is not


def test_account_and_vpc_is_clean():
    g = _geo_with_containers({"acct": (0, 0, 800, 800), "vpc": (50, 50, 400, 400)})
    assert geo.check_legend_boundary_coverage(g, list(dl.STANDARD_LEGEND_LINES)) == []


def test_no_boundary_flags_both_lines():
    g = DiagramGeometry()
    offenders = geo.check_legend_boundary_coverage(g, list(dl.STANDARD_LEGEND_LINES))
    assert set(offenders) == {_OUTER, _INNER}


def test_sibling_region_boxes_have_no_inner_boundary():
    # Two disjoint sibling boxes (the HA summaries) -> no nesting -> no inner.
    g = _geo_with_containers({"r1": (0, 0, 300, 300), "r2": (400, 0, 300, 300)})
    has_outer, has_inner = geo._container_nesting(g)
    assert has_outer and not has_inner


def test_check_is_silent_when_legend_omits_the_undrawn_line():
    g = _geo_with_containers({"acct": (0, 0, 400, 400)})
    legend = list(dl.legend_lines_for([dl.Boundary(
        id="acct", label="a", x=0, y=0, w=400, h=400, style="", kind="account")]))
    assert geo.check_legend_boundary_coverage(g, legend) == []


# --------------------------------------------------------------------------- #
# legend_lines_for on the build path
# --------------------------------------------------------------------------- #


def _box(kind):
    return dl.Boundary(id=kind, label=kind, x=0, y=0, w=200, h=200, style="", kind=kind)


def test_legend_lines_for_account_only_drops_inner():
    lines = dl.legend_lines_for([_box("account")])
    assert _OUTER in lines and _INNER not in lines


def test_legend_lines_for_account_and_vpc_keeps_both():
    lines = dl.legend_lines_for([_box("account"), _box("vpc")])
    assert _OUTER in lines and _INNER in lines


def test_build_diagram_applies_legend_lines_for_when_none():
    """build_diagram, given no explicit legend_lines, names only drawn boundaries."""
    icon = dl.builtin_icon(
        "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
        "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
    )
    account = dl.Boundary(id="boundary-account", label="SEP account",
                          x=60, y=60, w=200, h=200,
                          style="rounded=0;dashed=1;fillColor=none;strokeColor=#CD2264;"
                                "fontColor=#CD2264;verticalAlign=top;align=left",
                          kind="account")
    node = dl.Node("n", "n", 120, 120, render=icon)
    xml = dl.build_diagram(
        diagram_id="t", diagram_name="t",
        title="aws t — 1 / r | 2026-10-19 | v1",
        boundaries=[account], nodes=[node],
        edges=[], flow_lines=["Flow"], legend_x=500, page_w=900, page_h=600,
        legend_lines=None,
    )
    assert _OUTER in xml and _INNER not in xml


# --------------------------------------------------------------------------- #
# The lint rule
# --------------------------------------------------------------------------- #


def _lint_rule(xml: str, tmp_path, name: str):
    path = tmp_path / f"{name}.drawio"
    path.write_text(xml, encoding="utf-8")
    return [f for art in parse_artifacts(str(path)) for f in lint(art)["findings"]
            if f["rule"] == "legend-boundary-coverage"]


def _account_only_xml(legend_lines):
    icon = dl.builtin_icon(
        "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
        "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
    )
    # A dashed borderless rectangle is recognised as a Boundary container by the
    # shared detector (constants.is_boundary_container_style).
    account = dl.Boundary(id="boundary-account", label="SEP account",
                          x=60, y=60, w=200, h=200,
                          style="rounded=0;dashed=1;fillColor=none;strokeColor=#CD2264;"
                                "fontColor=#CD2264;verticalAlign=top;align=left",
                          kind="account")
    node = dl.Node("n", "n", 120, 120, render=icon)
    return dl.build_diagram(
        diagram_id="t", diagram_name="t",
        title="aws t — 1 / r | 2026-10-19 | v1",
        boundaries=[account], nodes=[node], edges=[], flow_lines=["Flow"],
        legend_x=500, page_w=900, page_h=600, legend_lines=legend_lines,
    )


def test_lint_flags_an_undrawn_inner_boundary(tmp_path):
    xml = _account_only_xml(list(dl.STANDARD_LEGEND_LINES))
    hits = _lint_rule(xml, tmp_path, "raw")
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert hits[0]["reason"] == "legend-names-undrawn-boundary"
    assert _INNER in hits[0]["offenders"]


def test_lint_is_silent_once_the_inner_line_is_dropped(tmp_path):
    account = dl.Boundary(id="acct", label="a", x=0, y=0, w=200, h=200, style="", kind="account")
    xml = _account_only_xml(list(dl.legend_lines_for([account])))
    assert _lint_rule(xml, tmp_path, "fixed") == []


# --------------------------------------------------------------------------- #
# Acceptance on SEP 01 / 04
# --------------------------------------------------------------------------- #


def _geo_of_script(name: str):
    import os
    from rule_engine.icon_resolver import _load_mapping_cached
    path = _FIXTURES / name
    cwd = os.getcwd()
    os.chdir(_FIXTURES.parent)   # SEP scripts resolve assets relative to the root
    _load_mapping_cached.cache_clear()
    try:
        spec = importlib.util.spec_from_file_location(path.stem + "_ws11", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # build_diagram runs at import
    finally:
        os.chdir(cwd)
        _load_mapping_cached.cache_clear()
    return geo.build_geometry(parse_drawio(module.drawio, path=name + ".drawio")[0]), module


def test_sep_01_and_04_do_not_list_an_undrawn_inner_boundary():
    for name in ("build_01_sep_context.py", "build_04_flow_lms_launch.py"):
        g, module = _geo_of_script(name)
        legend = list(module.legend_lines)
        offenders = geo.check_legend_boundary_coverage(g, legend)
        assert offenders == [], (name, offenders)
        # And the inner line is genuinely absent from the legend text.
        assert _INNER not in legend, name
