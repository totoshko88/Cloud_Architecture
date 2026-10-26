"""G23 (1.11.0): VPC peering as a first-class resource node.

A VPC/VCN peering is a relationship on a data-flow diagram (a symmetric dashed
line, documented in the Flow narrative) but a RESOURCE on a network topology
diagram (an AWS *VPC Peering Connection* icon between the two VPCs/accounts, with
the two peering legs attaching to it — the published AWS network-diagram shape).

The materialization is driven by an EXPLICIT spec-level switch
``DiagramSpec.peering_as_node``, never by inferring network-ness inside
``layout()`` (``diagram_type`` is companion metadata the linter reads, invisible
to the layout engine).

Covered here:

* ``peering_as_node=True`` materializes a ``vpc_peering`` node + two plain legs,
  drops the direct peering edge, the node resolves an icon, and ``layout()`` +
  lint produce no ERROR / ``edge-endpoint`` / ``structural-integrity`` finding;
* ``peering_as_node=False`` renders the peering edge with an EMPTY value (no
  ``peering`` word on the canvas) and a symmetric dashed no-arrow line;
* a spec with no peering edges serializes byte-identically (regression guard).
"""
from __future__ import annotations

from dataclasses import replace

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.icon_resolver import resolve_icon
from rule_engine.layout import DiagramSpec, layout, materialize_peerings
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec
from rule_engine.linter import lint


# --------------------------------------------------------------------------- #
# Specs
# --------------------------------------------------------------------------- #


def _peering_spec(peering_as_node: bool = False) -> DiagramSpec:
    """A VPC-scoped workload node peered to an external peer-account node."""
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        NodeSpec(id="peer", role="compute_instance", lane="on-premises",
                 region="", slot=0, container="peer-ext"),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct",
                      label_key="vpc"),
        ContainerSpec(id="peer-ext", kind="external_cloud", region="",
                      parent=None, label_key="peer"),
    )
    edges = (EdgeSpec(id="p1", source="lambda", target="peer", marker="peering",
                      peering=True),)
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. VPC peering"),
        title="aws t — 1 / r | 2026-10-19 | v1",
        peering_as_node=peering_as_node,
    )


def _dense_peering_spec() -> DiagramSpec:
    """A DENSE network diagram: two VPC-scoped workloads peered to FOUR external
    peer accounts (the 08/10 shape). The single-peering spec did not exercise the
    case where several materialized pcx nodes would otherwise be wrapped in the
    account and overlap the VPC box; this one does."""
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        NodeSpec(id="rds", role="managed_sql", lane="workers", region="a",
                 slot=1, container="vpc-a"),
        NodeSpec(id="p0", role="compute_instance", lane="on-premises",
                 region="", slot=0, container="peer-ext"),
        NodeSpec(id="p1n", role="compute_instance", lane="on-premises",
                 region="", slot=1, container="peer-ext"),
        NodeSpec(id="p2n", role="compute_instance", lane="on-premises",
                 region="", slot=2, container="peer-ext"),
        NodeSpec(id="p3n", role="compute_instance", lane="on-premises",
                 region="", slot=3, container="peer-ext"),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct",
                      label_key="vpc"),
        ContainerSpec(id="peer-ext", kind="external_cloud", region="",
                      parent=None, label_key="peer"),
    )
    edges = (
        EdgeSpec(id="e1", source="lambda", target="p0", marker="", peering=True),
        EdgeSpec(id="e2", source="lambda", target="p1n", marker="", peering=True),
        EdgeSpec(id="e3", source="rds", target="p2n", marker="", peering=True),
        EdgeSpec(id="e4", source="rds", target="p3n", marker="", peering=True),
    )
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. VPC peering"),
        title="aws t — 1 / r | 2026-10-19 | v1",
        peering_as_node=True,
    )


def _no_peering_spec() -> DiagramSpec:
    """A plain two-node flow with no peering edge (regression guard subject)."""
    nodes = (
        NodeSpec(id="a", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="b", role="object_store", lane="data", region="", slot=0),
    )
    edges = (EdgeSpec(id="e1", source="a", target="b", marker="1"),)
    return DiagramSpec(diagram_id="t", diagram_name="t", axis="left-right",
                       nodes=nodes, edges=edges, containers=(),
                       flow_lines=("Flow", "1. x"),
                       title="aws t — 1 / r | 2026-10-19 | v1")


# --------------------------------------------------------------------------- #
# (c) Regression guard: no peering edges → byte-identical
# --------------------------------------------------------------------------- #


def test_materialize_is_identity_when_flag_off():
    spec = _peering_spec(peering_as_node=False)
    assert materialize_peerings(spec) is spec


def test_materialize_no_op_without_peering_edges():
    spec = replace(_no_peering_spec(), peering_as_node=True)
    # No node-to-node peering edge → the transform returns the spec unchanged.
    assert materialize_peerings(spec) is spec


def test_no_peering_spec_serializes_byte_identically():
    spec = _no_peering_spec()
    x1 = _serialize(spec)
    x2 = _serialize(spec)
    assert x1 == x2


# --------------------------------------------------------------------------- #
# (a) peering_as_node=True materializes a node + two legs
# --------------------------------------------------------------------------- #


def test_materialize_creates_a_vpc_peering_node_and_two_legs():
    m = materialize_peerings(_peering_spec(peering_as_node=True))
    pcx = [n for n in m.nodes if n.role == "vpc_peering"]
    assert len(pcx) == 1
    node = pcx[0]
    assert node.id == "p1-pcx"
    # Placed in the EXTERNAL peer's own band (the disjoint ``peer-ext`` sibling
    # boundary drawn OUTSIDE the account and every VPC), in the slot immediately
    # before its peer, so the pcx sits "between the boundaries, not inside
    # either" and its leg to the peer is a short forward hop (never a back-edge
    # piercing the peer glyph). This is the G23 dense-case placement.
    assert node.lane == "on-premises"
    assert node.container == "peer-ext"
    # The direct peering edge is gone; two plain legs replace it.
    ids = [e.id for e in m.edges]
    assert "p1" not in ids
    assert ids == ["p1-a", "p1-b"]
    legs = {e.id: e for e in m.edges}
    assert legs["p1-a"].source == "lambda" and legs["p1-a"].target == "p1-pcx"
    assert legs["p1-b"].source == "p1-pcx" and legs["p1-b"].target == "peer"
    assert all(not e.peering for e in m.edges)
    # The legs carry NO marker (empty): a peering leg is a bare line into the
    # VPC Peering icon, documented in the Flow narrative — never a marker badge
    # (the owner-flagged "empty black disc on peering legs" defect).
    assert legs["p1-a"].marker == "" and legs["p1-b"].marker == ""


def test_peering_legs_render_no_marker_badge_disc():
    """A materialized peering leg must draw NO marker badge at all — not an empty
    disc. With the native circle-badge skin an empty marker previously rendered a
    meaningless dark disc on each leg before/after the VPC Peering icon (the
    owner-flagged visual defect). The serialized leg cells must therefore carry
    an empty value and no badge ``<span>`` markup."""
    import re
    xml = _serialize(_peering_spec(peering_as_node=True))
    for leg_id in ("p1-a", "p1-b"):
        cell = re.search(rf'<mxCell id="{leg_id}"[^>]*>', xml)
        assert cell is not None, f"{leg_id} leg not serialized"
        c = cell.group(0)
        assert 'value=""' in c, f"{leg_id} should carry an empty value, got: {c}"
        # No badge markup (the disc span) leaked into the value.
        assert "span" not in c and "border-radius" not in c


def test_empty_marker_renders_nothing_even_with_badge_skin():
    """``_marker_value`` returns NOTHING for an empty/blank marker regardless of
    the badge skin, so no empty disc is ever drawn."""
    from rule_engine.diagram_layout import Skin, _marker_value
    circle = Skin(furniture_stroke="light", edge_stroke="#5A6B7B",
                  marker_badge="circle")
    assert _marker_value("", circle) == ""
    assert _marker_value("   ", circle) == ""
    # A real numbered marker still gets its badge.
    assert "span" in _marker_value("3", circle)


def _icon_inside(nbox, cbox) -> bool:
    """True when the node's icon box falls (any overlap) inside a container box."""
    return not (
        nbox.x >= cbox.x + cbox.w
        or nbox.x + 78 <= cbox.x
        or nbox.y >= cbox.y + cbox.h
        or nbox.y + 78 <= cbox.y
    )


def test_materialized_pcx_is_outside_both_boundaries():
    """The pcx node is a peering RESOURCE between boundaries — a member of the
    external peer box, never the account and never the VPC, so its placed icon
    falls inside neither the account box nor the VPC box (the dense-case
    invariant)."""
    m = materialize_peerings(_peering_spec(peering_as_node=True))
    pcx = next(n for n in m.nodes if n.role == "vpc_peering")
    assert pcx.container not in ("acct", "vpc-a")  # never account / VPC
    placed = layout(_peering_spec(peering_as_node=True), strict=False)
    pbox = placed.nodes["p1-pcx"]
    assert not _icon_inside(pbox, placed.containers["acct"])
    assert not _icon_inside(pbox, placed.containers["vpc-a"])


def test_materialize_is_idempotent():
    m = materialize_peerings(_peering_spec(peering_as_node=True))
    m2 = materialize_peerings(m)
    assert [n.id for n in m2.nodes] == [n.id for n in m.nodes]
    assert [e.id for e in m2.edges] == [e.id for e in m.edges]


def test_vpc_peering_node_resolves_an_icon():
    d = resolve_icon("vpc_peering", "aws")
    assert d["style_string"]


def test_dense_peerings_materialize_outside_vpc_no_blocking_finding():
    """The 08/10 dense shape: four materialized pcx nodes all land in the
    external peer band (not the account, not the VPC), so layout() + lint carry
    no container-padding / container-overlap / blocking finding."""
    spec = _dense_peering_spec()
    m = materialize_peerings(spec)
    pcx = [n for n in m.nodes if n.role == "vpc_peering"]
    assert len(pcx) == 4
    # Every pcx joins the external peer band (never the account or the VPC).
    assert all(n.container == "peer-ext" for n in pcx)

    placed = layout(spec, strict=False)
    assert all(f"{e.id}-pcx" in placed.nodes for e in spec.edges)
    # Each placed pcx icon falls inside neither the account box nor the VPC box.
    for e in spec.edges:
        pbox = placed.nodes[f"{e.id}-pcx"]
        assert not _icon_inside(pbox, placed.containers["acct"])
        assert not _icon_inside(pbox, placed.containers["vpc-a"])
    xml = _serialize(spec)
    findings = [f for art in _parse(xml) for f in lint(art)["findings"]]
    blocking = [
        f for f in findings
        if f["severity"] in ("ERROR", "CRITICAL") and f["rule"] != "companion-doc"
    ]
    assert blocking == [], blocking
    # The two defects the region-less cloud-lane placement produced must be gone.
    assert not any(
        f["rule"] in ("container-padding", "container-overlap")
        and f["severity"] in ("ERROR", "CRITICAL")
        for f in findings
    )


def test_layout_places_the_peering_node_no_blocking_finding():
    spec = _peering_spec(peering_as_node=True)
    placed = layout(spec, strict=False)
    assert "p1-pcx" in placed.nodes
    # layout() + lint produce no ERROR/edge-endpoint/structural-integrity finding.
    xml = _serialize(spec)
    g = geo.build_geometry(parse_drawio(xml, path="t.drawio")[0])
    assert geo.check_structural_integrity(g) == []
    findings = [f for art in _parse(xml) for f in lint(art)["findings"]]
    # ``companion-doc`` is unavoidable for a lone in-memory .drawio (no paired
    # .diagram.md on disk); every OTHER ERROR/CRITICAL would be a real defect.
    blocking = [
        f for f in findings
        if f["severity"] in ("ERROR", "CRITICAL") and f["rule"] != "companion-doc"
    ]
    assert blocking == [], blocking
    assert not any(
        f["rule"] in ("edge-endpoint", "structural-integrity") for f in findings
    )


# --------------------------------------------------------------------------- #
# (b) peering_as_node=False: empty-value symmetric dashed no-arrow line
# --------------------------------------------------------------------------- #


def test_peering_edge_has_no_on_canvas_word_and_is_dashed_no_arrow():
    xml = _serialize(_peering_spec(peering_as_node=False))
    # The direct peering edge is serialized (not materialized).
    assert 'source="lambda" target="peer"' in xml
    # Find the peering edge cell and assert its presentation.
    import re
    cell = re.search(r'<mxCell id="p1"[^>]*>', xml)
    assert cell is not None
    c = cell.group(0)
    assert 'value=""' in c                       # empty value — no 'peering' word
    assert "dashed=1" in c
    assert "startArrow=none" in c and "endArrow=none" in c


# --------------------------------------------------------------------------- #
# G38 (FEAT-003): per-peering caption via EdgeSpec.peering_label
# --------------------------------------------------------------------------- #


def _labelled_peering_spec(label: str | None) -> DiagramSpec:
    """The single-peering spec, with an optional short peer-resource label on
    the peering edge."""
    spec = _peering_spec(peering_as_node=True)
    edges = (replace(spec.edges[0], peering_label=label),)
    return replace(spec, edges=edges)


def test_peering_label_is_discoverable_on_materialized_pcx_node():
    from rule_engine.layout import peering_label_for

    m = materialize_peerings(_labelled_peering_spec("Atlas peering"))
    # The short peer-resource name travels on the materialized spec, keyed by the
    # pcx node id, and is read via the stable accessor the build scripts use.
    assert peering_label_for(m, "p1-pcx") == "Atlas peering"
    assert dict(m.peering_labels) == {"p1-pcx": "Atlas peering"}
    # The label is the SHORT peer-resource name, NOT the raw pcx- id.
    assert not peering_label_for(m, "p1-pcx").startswith("pcx-")


def test_peering_label_passes_node_label_length():
    """The caption must be short enough to pass ``node-label-length`` (≤ 4 words
    AND ≤ 40 chars); a raw pcx-id would be too long."""
    from rule_engine.layout import peering_label_for

    m = materialize_peerings(_labelled_peering_spec("Atlas peering"))
    caption = peering_label_for(m, "p1-pcx")
    assert len(caption.split()) <= 4 and len(caption) <= 40


def test_peering_without_label_is_backward_compatible():
    """A peering edge with NO peering_label still materializes, carries no entry
    in the mapping, and the accessor returns None (renderer falls back to its
    generic caption)."""
    from rule_engine.layout import peering_label_for

    m = materialize_peerings(_labelled_peering_spec(None))
    pcx = [n for n in m.nodes if n.role == "vpc_peering"]
    assert len(pcx) == 1 and pcx[0].id == "p1-pcx"
    assert m.peering_labels == ()
    assert peering_label_for(m, "p1-pcx") is None


def test_peering_label_keeps_word_suppression_and_empty_markers():
    """Adding a peering_label does not reintroduce the 'peering' word or a marker
    badge: the two legs stay non-peering with empty markers."""
    m = materialize_peerings(_labelled_peering_spec("Atlas peering"))
    legs = {e.id: e for e in m.edges if e.id in ("p1-a", "p1-b")}
    assert len(legs) == 2
    assert all(not e.peering for e in legs.values())
    assert all(e.marker == "" for e in legs.values())


def test_peering_label_default_keeps_edgespec_byte_identical():
    """EdgeSpec.peering_label defaults to None, so a spec that never sets it is
    unchanged (the field is additive and defaulted)."""
    spec = _peering_spec(peering_as_node=False)
    assert all(getattr(e, "peering_label", "sentinel") is None
               for e in spec.edges)
    # Identity is preserved when the flag is off.
    assert materialize_peerings(spec) is spec


# --------------------------------------------------------------------------- #
# Helpers — build + parse a spec into a .drawio string / artifacts
# --------------------------------------------------------------------------- #


def _serialize(spec: DiagramSpec) -> str:
    from rule_engine.diagram_layout import (
        Boundary, Edge, Node, build_diagram, image_icon, legend_lines_for,
    )
    from rule_engine.icon_resolver import resolve_container

    placed = layout(spec, strict=False)
    # After layout() the placed spec (with any materialized pcx node) is what we
    # render; read nodes/containers from placed.spec so a materialized node is
    # included.
    rendered = placed.spec

    def rend(role):
        style = resolve_icon(role, "aws")["style_string"]
        return image_icon(style.split("image=", 1)[1]) if "image=" in style else None

    nodes = [Node(id=n.id, label=n.id, x=int(placed.nodes[n.id].x),
                  y=int(placed.nodes[n.id].y), render=rend(n.role),
                  overlay=n.overlay)
             for n in rendered.nodes if n.id in placed.nodes]
    kind_style = {"account": "boundary", "vpc": "network_boundary"}
    bs = []
    for c in rendered.containers:
        box = placed.containers[c.id]
        if c.kind == "external_cloud":
            style = ("rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;"
                     "strokeColor=#666666;fontColor=#333333;verticalAlign=top;"
                     "align=left;spacingLeft=6;fontSize=12")
        else:
            style = resolve_container(kind_style[c.kind], "aws")["style_string"]
        bs.append(Boundary(id=c.id, label=c.id, x=int(box.x), y=int(box.y),
                           w=int(box.w), h=int(box.h), style=style, kind=c.kind))
    es = [Edge(id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
               marker=pe.spec.marker, dashed=pe.spec.dashed,
               peering=getattr(pe.spec, "peering", False),
               exit=pe.exit, entry=pe.entry,
               points=tuple((int(x), int(y)) for x, y in pe.points))
          for pe in placed.edges]
    return build_diagram(diagram_id="t", diagram_name="t", title=spec.title,
                         boundaries=bs, nodes=nodes, edges=es,
                         flow_lines=list(spec.flow_lines),
                         legend_x=placed.legend_x, legend_w=placed.legend_w,
                         legend_lines=list(legend_lines_for(bs)),
                         page_w=2000, page_h=1400)


def _parse(xml: str):
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".drawio")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(xml)
        return list(parse_artifacts(path))
    finally:
        os.unlink(path)
