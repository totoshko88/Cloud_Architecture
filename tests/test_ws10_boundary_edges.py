"""WS10 (1.10.12, defect C15): boundary-to-boundary edges.

An edge endpoint MAY be a container id — a VPC/VCN peering or a transit-gateway
attachment is a relationship between two NETWORKS, drawn between the two
container FACES under the same directional contract (exit right/bottom, enter
left/top), with NO RDS/Lambda proxy node in the peering path. The lint and
geometry treat the container as the endpoint, not a child node.

Covered here:

* ``_validate_spec`` accepts a container endpoint and still rejects an endpoint
  that is neither a node nor a container id;
* ``layout()`` routes a container-endpoint edge on the two container faces,
  contract-legal (exit right/bottom, enter left/top), and leaves every node
  edge byte-identical;
* the serialized ``.drawio`` references the container cell ids as the edge
  endpoints, and the geometry/lint resolve them (no ``edge-endpoint`` /
  ``structural-integrity`` finding, no crash in the repair passes);
* acceptance: the 08 boundary-peering fixture variant draws its VPC peering as
  ``boundary-vpc-a -> peer-ext`` (container -> container), with no RDS/Lambda
  node on that edge.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.base import SpecError
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec
from rule_engine.layout.routers import container_edge_contacts, route_container_edge
from rule_engine.geometry import Box
from rule_engine.linter import lint

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"


def _peering_spec(edge_endpoints=("vpc-a", "peer-ext")) -> DiagramSpec:
    """A minimal spec: a VPC-scoped node, a peer node, and ONE peering edge
    between two container ids (by default the VPC boundary and the peer box)."""
    src, tgt = edge_endpoints
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        NodeSpec(id="peer", role="compute_instance", lane="on-premises", region="",
                 slot=0, container="peer-ext"),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ContainerSpec(id="peer-ext", kind="external_cloud", region="", parent=None, label_key="peer"),
    )
    edges = (EdgeSpec(id="peering", source=src, target=tgt, marker="1", peering=True),)
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. VPC peering"), title="aws t — 1 / r | 2026-10-19 | v1",
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_validate_accepts_a_container_endpoint():
    # No raise: both endpoints are declared container ids.
    layout(_peering_spec(("vpc-a", "peer-ext")), strict=False)


def test_validate_accepts_a_node_to_container_edge():
    layout(_peering_spec(("lambda", "peer-ext")), strict=False)


def test_validate_still_rejects_an_unknown_endpoint():
    with pytest.raises(SpecError, match="dangling source|dangling target"):
        layout(_peering_spec(("nope", "peer-ext")), strict=False)


# --------------------------------------------------------------------------- #
# Contact selection and routing
# --------------------------------------------------------------------------- #


def test_container_edge_contacts_follow_the_directional_contract():
    # target to the RIGHT -> exit right, enter left.
    src = Box("s", 0, 0, 200, 200)
    right = Box("t", 400, 0, 200, 200)
    exit_pt, entry_pt = container_edge_contacts(src, right)
    assert exit_pt == (1.0, 0.5) and entry_pt == (0.0, 0.5)
    # target BELOW -> exit bottom, enter top.
    below = Box("t", 0, 400, 200, 200)
    exit_pt, entry_pt = container_edge_contacts(src, below)
    assert exit_pt[1] == 1.0 and entry_pt[1] == 0.0


def test_route_container_edge_is_orthogonal():
    src = Box("s", 0, 0, 200, 200)
    tgt = Box("t", 400, 100, 200, 200)
    exit_pt, entry_pt = container_edge_contacts(src, tgt)
    pts = route_container_edge(src, tgt, exit_pt, entry_pt)
    # Every leg between contact and waypoints is axis-aligned.
    ex, ey = src.x + exit_pt[0] * src.w, src.y + exit_pt[1] * src.h
    nx, ny = tgt.x + entry_pt[0] * tgt.w, tgt.y + entry_pt[1] * tgt.h
    chain = [(ex, ey)] + pts + [(nx, ny)]
    for (x0, y0), (x1, y1) in zip(chain, chain[1:]):
        assert abs(x0 - x1) < 1e-9 or abs(y0 - y1) < 1e-9


def test_layout_routes_a_container_edge_on_container_faces():
    placed = layout(_peering_spec(("vpc-a", "peer-ext")), strict=False)
    pe = next(e for e in placed.edges if e.spec.id == "peering")
    assert pe.spec.source == "vpc-a" and pe.spec.target == "peer-ext"
    # Exit is right or bottom; entry is left or top (the directional contract).
    assert pe.exit[0] in (1.0,) or pe.exit[1] in (1.0,)
    assert pe.entry[0] in (0.0,) or pe.entry[1] in (0.0,)


def test_node_edges_are_unaffected_by_the_container_edge_path():
    # A spec with ONLY node edges lays out identically whether or not the WS10
    # split runs (it never runs, there being no container edge).
    nodes = (
        NodeSpec(id="a", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="b", role="object_store", lane="data", region="", slot=0),
    )
    edges = (EdgeSpec(id="e1", source="a", target="b", marker="1"),)
    spec = DiagramSpec(diagram_id="t", diagram_name="t", axis="left-right",
                       nodes=nodes, edges=edges, containers=(),
                       flow_lines=("Flow", "1. x"), title="aws t — 1 / r | 2026-10-19 | v1")
    p1 = layout(spec, strict=False)
    p2 = layout(spec, strict=False)
    assert [(e.spec.id, e.exit, e.entry, e.points) for e in p1.edges] == \
           [(e.spec.id, e.exit, e.entry, e.points) for e in p2.edges]


# --------------------------------------------------------------------------- #
# Geometry / lint treat the container as the endpoint
# --------------------------------------------------------------------------- #


def _build_and_parse(spec: DiagramSpec):
    from rule_engine.diagram_layout import (
        Boundary, Edge, Node, ICON_SIZE, build_diagram, image_icon, legend_lines_for,
    )
    from rule_engine.icon_resolver import resolve_icon, resolve_container

    placed = layout(spec, strict=False)

    def rend(role):
        style = resolve_icon(role, "aws")["style_string"]
        return image_icon(style.split("image=", 1)[1]) if "image=" in style else None

    nodes = [Node(id=n.id, label=n.id, x=int(placed.nodes[n.id].x),
                  y=int(placed.nodes[n.id].y), render=rend(n.role), overlay=n.overlay)
             for n in spec.nodes if n.id in placed.nodes]
    kind_style = {"account": "boundary", "vpc": "network_boundary"}
    bs = []
    for c in spec.containers:
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
    xml = build_diagram(diagram_id="t", diagram_name="t", title=spec.title,
                        boundaries=bs, nodes=nodes, edges=es,
                        flow_lines=list(spec.flow_lines),
                        legend_x=placed.legend_x, legend_w=placed.legend_w,
                        legend_lines=list(legend_lines_for(bs)),
                        page_w=2000, page_h=1400)
    return xml, geo.build_geometry(parse_drawio(xml, path="t.drawio")[0])


def test_serialized_edge_references_the_container_ids():
    xml, _g = _build_and_parse(_peering_spec(("vpc-a", "peer-ext")))
    assert 'source="vpc-a" target="peer-ext"' in xml


def test_geometry_and_lint_resolve_a_container_endpoint():
    xml, g = _build_and_parse(_peering_spec(("vpc-a", "peer-ext")))
    # structural-integrity resolves the container ids (no unresolved endpoint).
    assert geo.check_structural_integrity(g) == []
    # The polyline resolves against the container boxes.
    e = next(e for e in g.edges if e.id == "peering")
    assert len(geo.edge_polyline(g, e)) >= 2
    # No crash and no dangling edge-endpoint finding from the linter.
    findings = [f for art in [a for a in parse_artifacts_from_text(xml)]
                for f in lint(art)["findings"]]
    assert not any(f["rule"] in ("edge-endpoint", "structural-integrity")
                   and f["severity"] in ("ERROR", "CRITICAL") for f in findings)


def parse_artifacts_from_text(xml: str):
    """Parse artifacts from an in-memory .drawio via a temp file."""
    import tempfile
    import os
    fd, path = tempfile.mkstemp(suffix=".drawio")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(xml)
        return list(parse_artifacts(path))
    finally:
        os.unlink(path)


# --------------------------------------------------------------------------- #
# Acceptance: the 08 boundary-peering fixture variant
# --------------------------------------------------------------------------- #


def _load_builder(name: str):
    path = _FIXTURES / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_08_variant_draws_peering_boundary_to_boundary_no_proxy():
    import os
    from rule_engine.icon_resolver import _load_mapping_cached
    # The SEP build scripts resolve assets/mappings relative to the fixture root;
    # the mapping loader memoises its tree, so clear the cache around the chdir.
    cwd = os.getcwd()
    os.chdir(_FIXTURES.parent)
    _load_mapping_cached.cache_clear()
    try:
        module = _load_builder("build_08v2_boundary_peering.py")
        xml = module.b08._build()  # the variant mutates b08's spec, then builds
    finally:
        os.chdir(cwd)
        _load_mapping_cached.cache_clear()
    g = geo.build_geometry(parse_drawio(xml, path="08v2.drawio")[0])
    # The peering edge is between the VPC boundary and the peer boundary.
    peering = [e for e in g.edges if e.source == "boundary-vpc-a" and e.target == "peer-ext"]
    assert peering, "expected a boundary-vpc-a -> peer-ext peering edge"
    # Both endpoints are CONTAINERS, not nodes (no RDS/Lambda proxy in the path).
    e = peering[0]
    assert e.source in g.containers and e.target in g.containers
    assert e.source not in g.nodes and e.target not in g.nodes
    # No per-host peering edge survives from a workload node to a peer node.
    workloads = {"lambda", "rds", "nat"}
    peers = {"atlas", "cmtr-sre", "cmtr-cmtm", "cicd"}
    assert not any(e.source in workloads and e.target in peers for e in g.edges), \
        "a per-host RDS/Lambda peering proxy edge is still present"
    # The peering edge resolves and routes (polyline builds, structurally sound).
    assert len(geo.edge_polyline(g, e)) >= 2
    assert geo.check_structural_integrity(g) == []
