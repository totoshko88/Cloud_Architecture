"""1.13.0 fix (task item 3): ``flow_steps='document'`` never silently drops
the Flow.

* the canvas carries a ``flow-legend`` INDEX cell pointing at the companion's
  ``## Flow`` section, and the Legend's marker line points there too;
* ``flow_companion_section`` renders the section a builder writes;
* the linter reads the companion section (or a sibling ``.flow.md``) and
  ``flow-legend`` reports uncovered markers (WARNING) or an ERROR
  ``flow-steps-missing`` when the steps are written nowhere;
* box mode is unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine.cli import parse_artifacts
from rule_engine.linter import RULE_FLOW_LEGEND, lint

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"
_FLOW = ["Flow", "Ingest (1-2)", "1. a calls b", "2. b calls c", "3. c answers"]

_FRONTMATTER = """---
id: t
title: t
kb_namespace: t
section: t
category: t
status: draft
updated: 2026-10-19
owner: t
author: t
next_review_date: 2027-04-19
tags:
  - t
related_docs: []
---

# t
"""


def _build(flow_steps: str = "box", **kw) -> str:
    nodes = [
        dl.Node(id="a", label="a", x=100, y=200, render=_ICON),
        dl.Node(id="b", label="b", x=320, y=200, render=_ICON),
        dl.Node(id="c", label="c", x=540, y=200, render=_ICON),
    ]
    edges = [
        dl.Edge(id="e1", source="a", target="b", marker="1"),
        dl.Edge(id="e2", source="b", target="c", marker="2"),
        dl.Edge(id="e3", source="c", target="a", marker="3", exit=(0.5, 1.0), entry=(0.5, 1.0),
                points=((579.0, 320.0), (139.0, 320.0))),
    ]
    return dl.build_diagram(
        diagram_id="t", diagram_name="01-t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=_FLOW, legend_x=800,
        page_w=1300, page_h=600, flow_steps=flow_steps, **kw,
    )


def _cell_value(text: str, cid: str) -> str:
    m = re.search(r'<mxCell id="' + cid + r'" value="([^"]*)"', text)
    assert m, cid
    return m.group(1)


def _write(tmp_path: Path, text: str, companion_body: str = "") -> Path:
    d = tmp_path / "01-t.drawio"
    d.write_text(text, encoding="utf-8")
    (tmp_path / "01-t.diagram.md").write_text(_FRONTMATTER + companion_body, encoding="utf-8")
    return d


def _flow_findings(path: Path):
    (art,) = parse_artifacts(str(path))
    return art, [f for f in lint(art)["findings"] if f["rule"] == RULE_FLOW_LEGEND]


def test_document_mode_draws_an_index_and_points_the_legend_at_the_companion():
    text = _build("document")
    flow = _cell_value(text, "flow-legend").split("&#10;")
    assert flow[0] == "Flow"
    assert "Ingest (1-2)" in flow
    assert flow[-1] == "Steps 1–3: see companion 01-t.diagram.md → ## Flow"
    assert not any(line.startswith("1.") for line in flow)
    legend = _cell_value(text, "legend").split("&#10;")
    assert dl.DOCUMENT_MARKER_LEGEND_LINE in legend
    assert not any(line.endswith("see Flow list") for line in legend)


def test_companion_section_renders_numbered_steps():
    sec = dl.flow_companion_section(_FLOW)
    assert sec.startswith("## Flow\n\n")
    assert "1. a calls b\n2. b calls c\n3. c answers\n" in sec
    assert "**Ingest (1-2)**" in sec


def test_companion_with_all_steps_lints_clean(tmp_path):
    path = _write(tmp_path, _build("document"), "\n" + dl.flow_companion_section(_FLOW) + "\n## Notes\n\n4. not a step\n")
    art, hits = _flow_findings(path)
    assert art.flow_source == "companion"
    assert art.flow_legend_lines == ["Flow", "1. a calls b", "2. b calls c", "3. c answers"]
    assert hits == []


def test_companion_without_the_section_is_an_error(tmp_path):
    path = _write(tmp_path, _build("document"), "\n## Overview\n\nno steps here\n")
    art, hits = _flow_findings(path)
    assert art.flow_source == "missing"
    assert len(hits) == 1
    assert hits[0]["severity"] == "ERROR"
    assert "flow-steps-missing" in str(hits[0])


def test_companion_covering_some_steps_is_a_warning_naming_the_rest(tmp_path):
    path = _write(tmp_path, _build("document"), "\n## Flow\n\n1. a calls b\n")
    art, hits = _flow_findings(path)
    assert art.flow_source == "companion"
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert "uncovered-markers:2,3" in str(hits[0])


def test_sibling_flow_md_is_read(tmp_path):
    path = _write(tmp_path, _build("document"))
    (tmp_path / "01-t.flow.md").write_text("1. a\n2. b\n3. c\n", encoding="utf-8")
    art, hits = _flow_findings(path)
    assert art.flow_source == "companion" and hits == []


def test_box_mode_is_unchanged(tmp_path):
    box = _build("box")
    assert box == _build()  # the default
    flow = _cell_value(box, "flow-legend").split("&#10;")
    assert flow == _FLOW
    assert "see companion" not in box
    art, hits = _flow_findings(_write(tmp_path, box))
    assert art.flow_source == "canvas" and hits == []
