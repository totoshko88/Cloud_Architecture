"""1.10.12 WS6: container geometry (defects C4, C8, C9).

Pinned here on small synthetic diagrams:

* **caption fit** — the layout engine widens a container to hold its caption
  (inserting the missing width as a column to its right); the shared builder
  grows a hand-placed boundary into free space or wraps its caption; the
  ``container-caption-overflow`` rule reports what is left (WARNING, ERROR when
  the overflowing text prints over a node);
* **shared slot pitch** — external sibling bands use one pitch, so bands with
  the same slot count are identical and their columns line up;
  ``sibling-size-uniformity`` reports aligned siblings that differ;
* **compaction** — external bands sit one pad from the account;
* **legend** — Mode B is a below-body block left-aligned with the body, and
  ``legend-placement`` accepts a box below the whole body;
* **canvas-quality** — judged by the largest empty rectangle.
"""

from __future__ import annotations

from dataclasses import replace

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine import layout_engine as le
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box
from rule_engine.layout.model import ContainerSpec as _CS
from rule_engine.layout.model import DiagramSpec as _DS
from rule_engine.layout.model import EdgeSpec as _ES
from rule_engine.layout.model import NodeSpec as _NS
from rule_engine.layout.place import external_band_pitch
from rule_engine.linter import lint

_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-21 | v1"
_BOX = "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;verticalAlign=top;align=left;spacingLeft=10;fontSize=12"
_ICON = "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;fillColor=#ED7100;verticalLabelPosition=bottom;verticalAlign=top;html=1;fontSize=12"


def _raw(containers=(), nodes=(), texts=()):
    """A minimal .drawio page: ``containers`` = (id, label, x, y, w, h),
    ``nodes`` = (id, label, x, y), ``texts`` = (id, first line, x, y, w, h)."""
    cells = ['<mxCell id="0" />', '<mxCell id="1" parent="0" />',
             f'<mxCell id="title" value="{_TITLE}" style="text;html=1;fontSize=16" vertex="1" parent="1">'
             '<mxGeometry x="40" y="0" width="600" height="30" as="geometry" /></mxCell>']
    for cid, label, x, y, w, h in containers:
        cells.append(f'<mxCell id="{cid}" value="{label}" style="{_BOX}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
    for nid, label, x, y in nodes:
        cells.append(f'<mxCell id="{nid}" value="{label}" style="{_ICON}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="78" height="78" as="geometry" /></mxCell>')
    for tid, first, x, y, w, h in texts:
        cells.append(f'<mxCell id="{tid}" value="{first}&lt;br&gt;x" style="text;html=1;fillColor=#FFFFFF;strokeColor=#000000;spacingLeft=10;spacingRight=10;spacingTop=10;spacingBottom=10;fontSize=12" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
    return ('<mxfile><diagram id="d" name="d"><mxGraphModel gridSize="10" pageWidth="2000" pageHeight="2000"><root>'
            + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _findings(tmp_path, text, rule, diagram_class=None):
    path = tmp_path / "01-t.drawio"
    path.write_text(text, encoding="utf-8")
    out = []
    for art in parse_artifacts(str(path)):
        if diagram_class:
            art = replace(art, diagram_class=diagram_class)
        out += [f for f in lint(art)["findings"] if f["rule"] == rule]
    return out


_LONG = "se vpc-05cd5663a70d3a65c (192.168.128.0/20)"


# --------------------------------------------------------------------------- #
# container-caption-overflow
# --------------------------------------------------------------------------- #


def test_caption_overflow_is_a_warning_when_nothing_is_overprinted(tmp_path):
    text = _raw(containers=[("boundary-vpc", _LONG, 100, 100, 140, 200)],
                nodes=[("db", "RDS", 130, 190)])
    hits = _findings(tmp_path, text, "container-caption-overflow")
    need = geo.container_caption_need(_LONG, _BOX)
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert hits[0]["reason"] == f"caption-overflow:+{int(-(-(need - 140) // 1))}"
    assert hits[0]["offenders"] == ["boundary-vpc"]


def test_caption_overflow_overprinting_a_node_is_an_error(tmp_path):
    # API Gateway sits right of the VPC with its icon on the caption strip.
    text = _raw(containers=[("boundary-vpc", _LONG, 100, 100, 140, 200)],
                nodes=[("db", "RDS", 130, 190), ("apigw", "API Gateway (5 APIs)", 260, 90)])
    hits = _findings(tmp_path, text, "container-caption-overflow")
    assert len(hits) == 1 and hits[0]["severity"] == "ERROR"
    assert hits[0]["reason"].startswith("caption-overprints-node:+")
    assert hits[0]["offenders"] == ["boundary-vpc", "apigw"]


def test_caption_that_fits_is_silent(tmp_path):
    text = _raw(containers=[("boundary-vpc", "vpc-a", 100, 100, 140, 200)],
                nodes=[("db", "RDS", 130, 190)])
    assert _findings(tmp_path, text, "container-caption-overflow") == []


# --------------------------------------------------------------------------- #
# sibling-size-uniformity
# --------------------------------------------------------------------------- #


def _band(cid, x, y, w, n, pitch=220):
    nodes = [(f"{cid}{i}", f"n{i}", x + 60 + i * pitch, y + 60) for i in range(n)]
    return (cid, cid, x, y, w, 200), nodes


def test_column_siblings_with_the_same_slot_count_must_share_a_width(tmp_path):
    a, an = _band("bandA", 1000, 100, 618, 3)
    b, bn = _band("bandB", 1000, 330, 660, 3)
    c, cn = _band("bandC", 1000, 560, 398, 2)
    text = _raw(containers=[a, b, c], nodes=an + bn + cn)
    hits = _findings(tmp_path, text, "sibling-size-uniformity")
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert hits[0]["offenders"] == ["bandA", "bandB"]
    assert hits[0]["reason"] == "col@1000:width-spread:42"
    # Identical 3-slot bands (the 2-slot band is narrower, not compared) pass.
    b2, bn2 = _band("bandB", 1000, 330, 618, 3)
    assert _findings(tmp_path, _raw(containers=[a, b2, c], nodes=an + bn2 + cn),
                     "sibling-size-uniformity") == []


def test_a_two_node_stack_is_not_compared_with_a_two_node_row(tmp_path):
    stack = ("nsA", "nsA", 100, 100, 200, 400)
    row = ("nsB", "nsB", 400, 100, 420, 200)
    nodes = [("s0", "s0", 160, 160), ("s1", "s1", 160, 320),
             ("r0", "r0", 460, 160), ("r1", "r1", 680, 160)]
    assert _findings(tmp_path, _raw(containers=[stack, row], nodes=nodes),
                     "sibling-size-uniformity") == []


# --------------------------------------------------------------------------- #
# canvas-quality: largest empty rectangle
# --------------------------------------------------------------------------- #


def test_canvas_quality_reports_the_largest_empty_rectangle(tmp_path):
    # Nodes along the top and left edge only: the lower-right block is a void.
    nodes = [(f"t{i}", "n", 40 + i * 200, 40) for i in range(6)]
    nodes += [(f"l{i}", "n", 40, 240 + i * 200) for i in range(4)]
    hits = _findings(tmp_path, _raw(nodes=nodes), "canvas-quality")
    reasons = [h["reason"] for h in hits]
    assert any(r.startswith("empty-rectangle:") for r in reasons), reasons
    assert not any(r.startswith("canvas-utilization") for r in reasons)


def test_an_evenly_spread_icon_canvas_passes_canvas_quality(tmp_path):
    # A grid of bare icons: low "coverage" by area, but no void.
    nodes = [(f"n{r}{c}", "n", 40 + c * 200, 40 + r * 200) for r in range(4) for c in range(5)]
    assert _findings(tmp_path, _raw(nodes=nodes), "canvas-quality") == []


def test_canvas_empty_rect_matches_the_metrics_script():
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("cm", root / "scripts" / "canvas_metrics.py")
    cm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cm)
    page = root / "examples" / "aws" / "02-aws-ha-multiregion-summary.drawio"
    m = cm.measure_file(page)[0]
    w, h, _share = geo.canvas_empty_rect(_geo(page.read_text(encoding="utf-8")))
    assert (w, h) == (m.ler_out_w, m.ler_out_h)


# --------------------------------------------------------------------------- #
# legend-placement: below-body mode
# --------------------------------------------------------------------------- #


def test_legend_placement_accepts_a_block_below_the_body(tmp_path):
    body = [("boundary-acct", "acct", 100, 100, 600, 300)]
    nodes = [("a", "a", 160, 190)]
    below = _raw(containers=body, nodes=nodes,
                 texts=[("flow-legend", "Flow", 100, 440, 300, 120),
                        ("legend", "Legend", 410, 440, 300, 120)])
    assert _findings(tmp_path, below, "legend-placement") == []
    # Still beside the body on the left: flagged as before.
    beside = _raw(containers=body, nodes=nodes,
                  texts=[("flow-legend", "Flow", 0, 100, 90, 120)])
    assert [h["reason"] for h in _findings(tmp_path, beside, "legend-placement")] == [
        "left-of-diagram-body"]


def test_mode_b_is_left_aligned_one_pad_below_the_body():
    nodes = [dl.Node(id="n1", label="Student (verify)", x=0, y=0),
             dl.Node(id="n2", label="Atlas", x=1322, y=322)]
    boundaries = [dl.Boundary(id="b", label="b", x=100, y=0, w=1000, h=380)]
    edges = [dl.Edge(id="e1", source="n1", target="n2", marker="1",
                     points=((60, 460), (1361, 460)))]
    lx, ly, mode, pw, ph = dl.theme43_legend_placement(
        nodes, boundaries, ("Flow", "1. a"), ("Legend", "x"), 300, edges=edges)
    assert mode == "row-below"
    assert lx == 0                                   # body left
    # The lowest waypoint (460) is below the lowest caption (322 + 78 + 30):
    # the block starts one pad below it, on the grid.
    assert ly == 460 + dl.CONTAINER_PAD
    assert ly % dl.GRID == 0


# --------------------------------------------------------------------------- #
# Builder-side caption fit (hand-placed geometry)
# --------------------------------------------------------------------------- #


def test_builder_grows_a_boundary_into_free_space():
    b = dl.Boundary(id="acct", label="SEP — AWS 870325637521 / eu-central-1",
                    x=100, y=100, w=180, h=200)
    n = dl.Node(id="sep", label="SEP", x=150, y=170)
    (out,) = dl.fit_boundary_captions([b], [n], [], legend_x=1200)
    assert out.x == 100 and out.w >= geo.container_caption_need(b.label, dl._boundary_style(b))
    assert out.w % dl.GRID == 0


def test_builder_wraps_a_caption_when_the_strip_is_taken():
    b = dl.Boundary(id="acct", label="SEP — AWS 870325637521 / eu-central-1",
                    x=100, y=100, w=200, h=200)
    inside = dl.Node(id="sep", label="SEP", x=150, y=170)
    neighbour = dl.Node(id="mongo", label="MongoDB", x=310, y=120)
    (out,) = dl.fit_boundary_captions([b], [inside, neighbour], [], legend_x=1200)
    assert out.w == 200
    assert "<br>" in out.label
    assert geo.container_caption_need(out.label, dl._boundary_style(out)) <= out.w


def test_builder_leaves_a_fitting_caption_alone():
    b = dl.Boundary(id="acct", label="acct", x=100, y=100, w=200, h=200)
    assert dl.fit_boundary_captions([b], [], []) == [b]


# --------------------------------------------------------------------------- #
# Engine: caption fit, shared pitch, compaction
# --------------------------------------------------------------------------- #


def _vpc_caption_spec():
    nodes = (
        _NS(id="db", role="managed_sql", lane="data", region="a", slot=0, container="vpc-a"),
        _NS(id="fn", role="serverless_fn", lane="data", region="a", slot=1, container="region-a"),
        _NS(id="api", role="api_gateway", lane="edge", region="a", slot=1, container="region-a"),
    )
    containers = (
        _CS(id="acct", kind="account", region="", parent=None, label_key="m"),
        _CS(id="region-a", kind="region", region="a", parent="acct", label_key="r"),
        _CS(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="v"),
    )
    edges = (_ES("e1", "api", "fn", "1"), _ES("e2", "fn", "db", "2"))
    return _DS(
        diagram_id="c4", diagram_name="c4", axis="north-south", nodes=nodes,
        edges=edges, containers=containers, flow_lines=("Flow", "1. a", "2. b"),
        title=_TITLE,
        container_captions=(("acct", "acct 123"), ("region-a", "Region eu-central-1"),
                            ("vpc-a", _LONG)),
        container_styles=(("vpc-a", "align=left;spacingLeft=30;verticalAlign=top"),),
    )


def test_layout_widens_a_container_to_its_caption():
    pd = le.layout(_vpc_caption_spec())
    vpc = pd.containers["vpc-a"]
    need = geo.container_caption_need(_LONG, "align=left;spacingLeft=30")
    assert vpc.w >= need
    # The regional nodes stay clear of the widened VPC (footprint + one pad).
    for nid in ("fn", "api"):
        fp = pd.nodes[nid].footprint(geo.LABEL_BAND)
        assert (fp.right + dl.CONTAINER_PAD <= vpc.x or vpc.right + dl.CONTAINER_PAD <= fp.x
                or fp.bottom <= vpc.y or vpc.bottom <= fp.y), nid
    # Parents wrap it.
    assert pd.containers["region-a"].right >= vpc.right + dl.CONTAINER_PAD


def test_a_spec_without_captions_is_not_widened():
    spec = replace(_vpc_caption_spec(), container_captions=(), container_styles=())
    pd = le.layout(spec)
    assert pd.containers["vpc-a"].w < geo.container_caption_need(_LONG, "")


def _bands_spec():
    """An account plus four external bands above it (3, 3, 2, 3 slots)."""
    nodes = [
        _NS(id="app", role="serverless_fn", lane="workers", region="a", slot=0, container="region-a"),
        _NS(id="q", role="message_queue", lane="workers", region="a", slot=1, container="region-a"),
    ]
    containers = [
        _CS(id="acct", kind="account", region="", parent=None, label_key="m"),
        _CS(id="region-a", kind="region", region="a", parent="acct", label_key="r"),
    ]
    labels = {"app": "Lambda", "q": "SQS"}
    slot = 0
    sizes = {"ingress": 3, "peer": 3, "ident": 2, "integ": 3}
    for band, n in sizes.items():
        containers.append(_CS(id=band, kind="peer_account", region="", parent=None, label_key=None))
        for i in range(n):
            nid = f"{band}{i}"
            nodes.append(_NS(id=nid, role="peer_account", lane="actors", region="",
                             slot=slot, container=band))
            labels[nid] = "EPM-CMTR CMTM/SRE/EKS (088595288622)" if nid == "peer0" else nid
            slot += 1
    edges = (
        _ES("e1", "ingress0", "app", "1"),
        _ES("e2", "app", "q", "2"),
        _ES("e3", "q", "peer0", "3"),
        _ES("e4", "ident0", "app", "4"),
        _ES("e5", "q", "integ0", "5"),
    )
    return _DS(
        diagram_id="c8", diagram_name="c8", axis="north-south", nodes=tuple(nodes),
        edges=edges, containers=tuple(containers),
        flow_lines=("Flow",) + tuple(f"{i}. s" for i in range(1, 6)), title=_TITLE,
        node_labels=tuple(labels.items()),
    ), sizes


def test_external_bands_share_one_slot_pitch():
    spec, sizes = _bands_spec()
    pitch = external_band_pitch(spec)
    # The widest caption (36 chars x 7px) plus two grid steps of air.
    assert pitch == 280
    pd = le.layout(spec)
    for band, n in sizes.items():
        assert pd.containers[band].w == n * pitch + 2 * dl.CONTAINER_PAD, band
        xs = sorted(pd.nodes[f"{band}{i}"].x for i in range(n))
        assert all(b - a == pitch for a, b in zip(xs, xs[1:])), band
    three = {pd.containers[b].w for b, n in sizes.items() if n == 3}
    assert len(three) == 1


def test_external_bands_sit_one_pad_from_the_account():
    spec, sizes = _bands_spec()
    pd = le.layout(spec)
    acct = pd.containers["acct"]
    bands = {b: pd.containers[b] for b in sizes}
    above = [b for b in bands.values() if b.bottom <= acct.y]
    beside = [b for b in bands.values() if b.x >= acct.right]
    assert above and beside and len(above) + len(beside) == len(bands)
    # One pad, rounded up to the grid (a band is 198px tall, its nodes on the grid).
    assert all(dl.CONTAINER_PAD <= acct.y - b.bottom < dl.CONTAINER_PAD + dl.GRID for b in above)
    assert {b.x for b in beside} == {acct.right + dl.CONTAINER_PAD}
    assert min(b.y for b in beside) == acct.y
    ys = sorted(beside, key=lambda b: b.y)
    assert all(dl.CONTAINER_PAD <= n.y - p.bottom < dl.CONTAINER_PAD + dl.GRID
               for p, n in zip(ys, ys[1:]))
    # Nothing overlaps.
    boxes = list(bands.values()) + [acct]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a.right <= b.x or b.right <= a.x or a.bottom <= b.y or b.bottom <= a.y


def test_bands_below_the_account_move_up_to_one_pad():
    nodes = [_NS(id="app", role="k8s", lane="workers", region="a", slot=0, container="az-a1")]
    containers = [
        _CS(id="acct", kind="account", region="", parent=None, label_key="m"),
        _CS(id="region-a", kind="region", region="a", parent="acct", label_key="r"),
        _CS(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="v"),
        _CS(id="az-a1", kind="az", region="a", parent="vpc-a", label_key="z"),
        _CS(id="peer", kind="external_cloud", region="", parent=None, label_key="p"),
    ]
    for i in range(3):
        nodes.append(_NS(id=f"p{i}", role="object_store", lane="on-premises",
                         region="", slot=i, container="peer"))
    spec = _DS(diagram_id="b", diagram_name="b", axis="north-south", nodes=tuple(nodes),
               edges=(_ES("e1", "app", "p0", "1"),), containers=tuple(containers),
               flow_lines=("Flow", "1. a"), title=_TITLE)
    pd = le.layout(spec)
    acct, peer = pd.containers["acct"], pd.containers["peer"]
    assert dl.CONTAINER_PAD <= peer.y - acct.bottom < dl.CONTAINER_PAD + dl.GRID
