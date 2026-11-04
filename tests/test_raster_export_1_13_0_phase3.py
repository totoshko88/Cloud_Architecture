"""1.13.0 phase 3 (item 13): raster export height estimate, size budget, --file.

* 13a: ``_canvas_height`` covers edge waypoints below the lowest vertex and a
  multi-line (wrapped) caption, so a tall-but-narrow canvas is not
  underestimated.
* 13b: the byte-size budget feeds the scale — ``_fit_size_budget`` re-exports at
  a smaller scale until the PNG is within the class budget (stub renderer).
* 13c: ``check_rasters(files=...)`` / ``rule-engine-check-rasters --file`` scopes
  the gate to the named diagram, so a sibling's stale raster does not block.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine import export_raster as er


_HEADER = '<mxGraphModel gridSize="10"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'


def _drawio_with_edge_point(y: int) -> str:
    # one icon near the top, an edge whose waypoint runs far below it.
    return (
        _HEADER
        + '<mxCell id="a" value="A" style="shape=mxgraph.aws4.resourceIcon;" vertex="1" parent="1">'
          '<mxGeometry x="100" y="100" width="78" height="78" as="geometry"/></mxCell>'
        + '<mxCell id="b" value="B" style="shape=mxgraph.aws4.resourceIcon;" vertex="1" parent="1">'
          '<mxGeometry x="100" y="200" width="78" height="78" as="geometry"/></mxCell>'
        + '<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="a" target="b">'
          '<mxGeometry relative="1" as="geometry">'
          f'<Array as="points"><mxPoint x="400" y="{y}"/></Array></mxGeometry></mxCell>'
        + "</root></mxGraphModel>"
    )


def test_canvas_height_covers_an_edge_waypoint(tmp_path):
    shallow = tmp_path / "shallow.drawio"
    shallow.write_text(_drawio_with_edge_point(260), encoding="utf-8")
    deep = tmp_path / "deep.drawio"
    deep.write_text(_drawio_with_edge_point(900), encoding="utf-8")
    h_shallow = er._canvas_height(shallow)
    h_deep = er._canvas_height(deep)
    # the deep waypoint (y=900) extends the canvas well past the icons (bottom
    # ~278 + label band), so the height must grow with it.
    assert h_deep > h_shallow
    assert h_deep >= 900 - 100


def test_canvas_height_covers_a_two_line_caption(tmp_path):
    one = tmp_path / "one.drawio"
    one.write_text(
        _HEADER
        + '<mxCell id="a" value="Short" style="verticalLabelPosition=bottom;" vertex="1" parent="1">'
          '<mxGeometry x="100" y="100" width="78" height="78" as="geometry"/></mxCell>'
        + "</root></mxGraphModel>", encoding="utf-8")
    two = tmp_path / "two.drawio"
    two.write_text(
        _HEADER
        + '<mxCell id="a" value="Line one&lt;br&gt;Line two" style="verticalLabelPosition=bottom;" vertex="1" parent="1">'
          '<mxGeometry x="100" y="100" width="78" height="78" as="geometry"/></mxCell>'
        + "</root></mxGraphModel>", encoding="utf-8")
    assert er._canvas_height(two) > er._canvas_height(one)


def test_fit_size_budget_reduces_scale_for_an_oversize_png(tmp_path, monkeypatch):
    png = tmp_path / "x.drawio.png"
    # a stub renderer whose "file size" shrinks with the square of the scale.
    sizes = {}

    def run_export(at_scale):
        # 600KB at scale 1.5, scales with area: size = 600KB * (s/1.5)**2
        kb = 600 * 1024 * (at_scale / 1.5) ** 2
        png.write_bytes(b"x" * int(kb))
        sizes["last"] = at_scale

    from rule_engine.raster_gate import MAX_SIZE_BYTES
    run_export(1.5)
    assert png.stat().st_size > MAX_SIZE_BYTES  # starts over budget
    final = er._fit_size_budget(Path("src.drawio"), png, 1.5, "flow", run_export)
    assert final < 1.5
    assert png.stat().st_size <= MAX_SIZE_BYTES


def test_fit_size_budget_leaves_a_within_budget_png(tmp_path):
    png = tmp_path / "x.drawio.png"
    png.write_bytes(b"x" * 100)  # tiny, within budget
    calls = []

    def run_export(at_scale):
        calls.append(at_scale)

    final = er._fit_size_budget(Path("s.drawio"), png, 1.5, "flow", run_export)
    assert final == 1.5
    assert calls == []  # no re-export for a within-budget PNG


def _triple(d: Path, name: str, cls: str = "flow"):
    src = d / f"{name}.drawio"
    src.write_text(_HEADER + '<mxCell id="a" value="A" style="x" vertex="1" parent="1">'
                   '<mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>'
                   "</root></mxGraphModel>", encoding="utf-8")
    comp = d / f"{name}.diagram.md"
    comp.write_text(f"---\ndiagram_class: {cls}\n---\n", encoding="utf-8")
    return src


def test_check_rasters_file_scoping(tmp_path):
    a = _triple(tmp_path, "01-topic")
    _triple(tmp_path, "02-topic")  # sibling, no PNG -> would be "missing"
    # scope to 01 only: 02's missing raster is not in the result set.
    refs = er_check(tmp_path, files=[a])
    ids = {Path(r.source).name for r in refs}
    assert ids == {"01-topic.drawio"}


def er_check(root, files=None):
    from rule_engine.raster_gate import check_rasters
    return check_rasters(str(root), str(root), files=files)
