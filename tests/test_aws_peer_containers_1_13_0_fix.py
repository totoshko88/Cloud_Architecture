"""1.13.0 fix (task item 14): AWS declares ``peer_account`` and
``external_cloud`` container kinds.

Before, an AWS peer account / peer cloud fell back to the primary ``boundary``
style (the pink Account group), so a peer read as the primary account. Now the
peer account is the AWS Groups account group in neutral grey and the external
cloud a dashed neutral rectangle; ``container-style`` accepts both and still
flags an Account box painted in the Squid Ink brand anchor.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine.cli import parse_artifacts
from rule_engine.draw_cli import _container_style
from rule_engine.icon_resolver import resolve_container
from rule_engine.linter import lint

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def test_peer_account_resolves_to_the_grey_account_group():
    style = resolve_container("peer_account", "aws")["style_string"]
    assert "grIcon=mxgraph.aws4.group_account" in style
    assert "strokeColor=#7D8998" in style and "fontColor=#545B64" in style
    assert "#CD2264" not in style


def test_external_cloud_resolves_to_the_dashed_neutral_box():
    style = _container_style("external_cloud", "aws")
    assert "dashed=1" in style and "dashPattern=8 4" in style
    assert "strokeColor=#7D8998" in style and "fillColor=none" in style


def _lint_boxes(tmp_path: Path, styles):
    boundaries, nodes = [], []
    for i, style in enumerate(styles):
        x = 60 + i * 300
        boundaries.append(dl.Boundary(id=f"boundary-{i}", label=f"acct {i}", x=x, y=80,
                                      w=240, h=200, style=style))
        nodes.append(dl.Node(id=f"n{i}", label=f"n{i}", x=x + 80, y=170, render=_ICON))
    text = dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=boundaries,
        nodes=nodes, edges=[], flow_lines=["Flow"], legend_x=60 + 300 * len(styles),
        page_w=1600, page_h=500,
    )
    path = tmp_path / "01-t.drawio"
    path.write_text(text, encoding="utf-8")
    (art,) = parse_artifacts(str(path))
    return [f for f in lint(art)["findings"] if f["rule"] == "container-style"]


def test_container_style_accepts_both_peer_kinds(tmp_path):
    peer = resolve_container("peer_account", "aws")["style_string"]
    ext = resolve_container("external_cloud", "aws")["style_string"]
    primary = resolve_container("boundary", "aws")["style_string"]
    assert _lint_boxes(tmp_path, [primary, peer, ext]) == []


def test_container_style_still_flags_a_squid_ink_account(tmp_path):
    primary = resolve_container("boundary", "aws")["style_string"]
    black = primary.replace("#CD2264", "#232F3E")
    hits = _lint_boxes(tmp_path, [black])
    assert len(hits) == 1 and hits[0]["severity"] == "ERROR"
