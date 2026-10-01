"""Oracle adapter, repair loop, and right-margin Flow/Legend placement
(scored-router 1.8.0, Phase A, task 1.4).

This module holds the ``layout_engine`` finishing machinery that the pipeline
previously imported *back* from ``layout_engine``: the right-margin Flow/Legend
placement (:data:`LEGEND_W`, :func:`place_legend`), the geometry oracle adapter
(:func:`_run_oracle` and its helpers), the deterministic repair loop
(:func:`_repair`, :func:`orthogonalise_candidate`), and their constants
(:data:`MAX_REPAIR_ITERS`, :class:`LayoutError`, :class:`OracleFindings`).

Relocating them here — alongside :mod:`rule_engine.layout.base` — removes the
last piece of the old bidirectional dependency so ``pipeline`` imports its
finishing stage from within the package and ``layout_engine`` becomes a pure
re-export shim (design.md §``layout/`` package seam, Component 5).

Dependency direction (acyclic):

    base / model / routers / geometry / diagram_layout  →  layout.repair  →  pipeline

**Behavior-preserving.** Every definition here is relocated *verbatim* from
``layout_engine.py``; no field, default, name, or line of logic changed, so the
serialized oracle view and every repair are byte-identical to the pre-split
output (R1.1, R1.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout.repair``
    from ..diagram_layout import GRID, CONTAINER_PAD
    from ..geometry import Box, contact_faces, orthogonalise_route
    from .base import _snap
    from .model import Point, PlacedEdge, PlacedDiagram
    from .routers import _contact_point
    from .. import diagram_layout as _dl
    from .. import geometry as _geo
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import GRID, CONTAINER_PAD  # type: ignore[no-redef]
    from geometry import Box, contact_faces, orthogonalise_route  # type: ignore[no-redef]
    from layout.base import _snap  # type: ignore[no-redef]
    from layout.model import Point, PlacedEdge, PlacedDiagram  # type: ignore[no-redef]
    from layout.routers import _contact_point  # type: ignore[no-redef]
    import diagram_layout as _dl  # type: ignore[no-redef]
    import geometry as _geo  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Right-margin Flow/Legend placement (Req 8)
# ---------------------------------------------------------------------------

LEGEND_W = 280


def place_legend(account_box: Box, flow_lines: Tuple[str, ...]) -> Tuple[int, int]:
    """Return ``(legend_x, legend_w)`` for the right-margin Flow/Legend blocks (Req 8).

    * ``legend_x = account_box.right + CONTAINER_PAD`` — the blocks start at
      least one container-pad step past the outermost container's right edge, so
      they sit in the clear right margin and never overlap the cloud (Req 8.1,
      8.3). Because the account box wraps every region band, any node or nested
      container box is fully left of ``account_box.right`` and therefore left of
      ``legend_x``.
    * ``legend_w = LEGEND_W`` — a fixed narrow width (Req 8.2). ``build_diagram``
      is passed this as its ``legend_w`` parameter and uses its existing
      wrap-aware ``_text_h`` to grow the boxes *taller* (wrapped line count)
      rather than wider, so a long legend line never runs back into the diagram
      body. The engine reuses that sizing — it only pins the narrow width and
      the past-the-account x, not any height computation.

    Both returned values are grid-aligned integers (``CONTAINER_PAD`` and
    ``LEGEND_W`` are whole ``GRID`` multiples and ``account_box.right`` is
    grid-aligned by construction), so the emitted coordinates stay on the grid
    (Req 11.4). ``flow_lines`` is accepted so the signature matches the
    declaration the caller already holds (the Flow block covers every marker in
    ascending order — that ordering is the caller's ``flow_lines`` content,
    which ``build_diagram`` renders verbatim, Req 8.4); the pinned width does not
    depend on the line contents.
    """
    legend_x = _snap(account_box.right + CONTAINER_PAD)
    return legend_x, LEGEND_W



# ---------------------------------------------------------------------------
# Oracle adapter and repair loop (Req 9, Req 11)
# ---------------------------------------------------------------------------


#: Upper bound on repair iterations (Req 9.4). The loop terminates in a fixed
#: number of passes: each pass either clears a blocking finding or the layout is
#: declared unfixable. A small bound is enough because every repair strictly
#: reduces the blocking-finding count (grow a container, bump a corridor lane,
#: re-centre a block) and the pipeline emits only a handful of fixable defects.
MAX_REPAIR_ITERS = 8

class LayoutError(RuntimeError):
    """Raised when the repair loop cannot make a layout publication-eligible.

    Either a finding is *unfixable* (an over-connected node — the diagram must be
    split or re-laned, not nudged), or the bounded repair loop
    (:data:`MAX_REPAIR_ITERS`) exhausted its passes with a blocking finding still
    present. The message names the first unresolved finding so the fault is
    actionable (Req 9.3)."""


# ``PlacedEdge`` and ``PlacedDiagram`` now live in
# :mod:`rule_engine.layout.model` (scored-router 1.8.0 Phase A, task 1.1) and are
# re-imported at the top of this module, so they keep resolving here unchanged.


@dataclass
class OracleFindings:
    """The oracle's verdict on a candidate: blocking vs fixable geometry findings.

    ``blocking`` are the findings that make the (landscape-class) artifact
    publication-ineligible — the ERROR/CRITICAL geometry rules the repair loop
    must clear. ``fixable`` is the subset of blocking findings the engine knows a
    deterministic repair for; an unfixable blocking finding (e.g. over-connected)
    stays in ``blocking`` but not in ``fixable`` and forces a :class:`LayoutError`.
    Each finding is ``(rule, payload)`` where ``payload`` is the validator's own
    offending-item tuple/id, so a repair can act on it."""

    blocking: List[Tuple[str, object]]
    fixable: List[Tuple[str, object]]

    @property
    def clean(self) -> bool:
        return not self.blocking

    @property
    def first_unresolved(self) -> Optional[Tuple[str, object]]:
        return self.blocking[0] if self.blocking else None


#: A neutral, non-boundary stub icon style for oracle serialization. It resolves
#: to a real built-in AWS resourceIcon shape (so ``build_geometry`` parses a node
#: with geometry) but names no ``group_``/``grIcon=``/``dashed=1;fillColor=none``
#: token, so ``is_boundary_container_style`` never mistakes a node for a
#: container. The oracle only cares about *geometry*, not which glyph renders —
#: the real provider skin is applied later by the caller's ``build_diagram``.
_STUB_ICON_STYLE = (
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)


def _stub_boundary_style(cand: "PlacedDiagram", cid: str) -> str:
    """Return a dashed-rectangle boundary style the geometry parser recognizes.

    Uses the standard dashed borderless rectangle (``dashed=1;fillColor=none``)
    so ``is_boundary_container_style`` classifies the cell as a Boundary /
    Network-Boundary container — the same detection the linter applies."""
    return (
        "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;"
        "strokeColor=#00A000;fillColor=none;verticalAlign=top;"
        "fontColor=#00A000;fontSize=12"
    )


def _oracle_container_id(cid: str) -> str:
    """The id a container is serialized under when it carries a real style."""
    return cid if cid.startswith("boundary") else f"boundary-{cid}"


def _spec_container_id(cand: "PlacedDiagram", oid: object) -> object:
    """Map an oracle container id back to the spec's id (identity otherwise)."""
    if isinstance(oid, str) and oid.startswith("boundary-") and oid not in cand.containers:
        bare = oid[len("boundary-"):]
        if bare in cand.containers:
            return bare
    return oid


def _serialize_candidate(cand: "PlacedDiagram") -> str:
    """Serialize a candidate to ``.drawio`` text via ``build_diagram`` (stub icons).

    Builds the ``Node`` / ``Edge`` / ``Boundary`` objects ``build_diagram``
    consumes straight from the candidate's placed boxes and routed edges, using a
    neutral stub icon renderer (the oracle judges *geometry*, not the glyph). The
    returned text is exactly what the linter would parse, so re-parsing it with
    ``build_geometry`` gives the oracle the linter's own view (design.md →
    "Integration points & risks / _run_oracle adapter")."""
    # 1.10.6: draw each container with the caption and style the skin will use
    # when the spec carries them, so the oracle and the scored solver see the
    # caption exactly where the linter will (``edge-crosses-container-label``).
    captions = dict(getattr(cand.spec, "container_captions", ()) or ())
    styles = dict(getattr(cand.spec, "container_styles", ()) or ())
    boundaries = [
        _dl.Boundary(
            # A real provider style (a filled OCI region, an AWS group) is not
            # always recognisable as a container by style alone; the
            # ``boundary`` id prefix is (``is_boundary_container_style``). The
            # oracle maps the prefixed id back to the spec id (_run_oracle).
            id=_oracle_container_id(c.id) if c.id in styles else c.id,
            label=captions.get(c.id, c.id),
            x=int(box.x),
            y=int(box.y),
            w=int(box.w),
            h=int(box.h),
            style=styles.get(c.id) or _stub_boundary_style(cand, c.id),
        )
        for c in cand.spec.containers
        if (box := cand.containers.get(c.id)) is not None
    ]
    stub = _dl.builtin_icon(_STUB_ICON_STYLE)
    nodes = [
        _dl.Node(id=nid, label=nid, x=int(box.x), y=int(box.y), render=stub)
        for nid, box in sorted(cand.nodes.items())
    ]
    edges = [
        _dl.Edge(
            id=pe.spec.id,
            source=pe.spec.source,
            target=pe.spec.target,
            marker=pe.spec.marker,
            dashed=pe.spec.dashed,
            exit=pe.exit,
            entry=pe.entry,
            points=tuple((float(x), float(y)) for x, y in pe.points),
        )
        for pe in cand.edges
    ]
    return _dl.build_diagram(
        diagram_id=cand.spec.diagram_id,
        diagram_name=cand.spec.diagram_name,
        title=cand.spec.title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=cand.spec.flow_lines,
        legend_x=cand.legend_x,
        legend_w=cand.legend_w,
    )


#: The blocking geometry rules for a landscape-class diagram (diagram-lint →
#: Diagram Class): these are ERROR/CRITICAL and make the artifact
#: publication-ineligible, so the repair loop must clear them. Each entry pairs a
#: rule name with the validator that reports it; a non-empty result is a finding.
#: (``node-overlap`` is a WARNING in the ruleset but is treated as blocking here
#: because two icons drawn on top of each other is never acceptable output.)
def _collect_findings(geo: "_geo.DiagramGeometry") -> List[Tuple[str, object]]:
    """Run the geometry ``check_*`` set and return ``(rule, payload)`` findings.

    Deterministic ordering: the checks run in a fixed sequence and each check's
    own output is already sorted, so the finding list is stable for a given
    candidate (Req 9.4 / 11.1)."""
    findings: List[Tuple[str, object]] = []
    for cid, ccid, _pad in _geo.check_container_padding(geo, pad=CONTAINER_PAD):
        findings.append(("container-padding", (cid, ccid)))
    for pair in _geo.check_container_overlap(geo):
        findings.append(("container-overlap", pair))
    for pair in _geo.check_node_overlap(geo):
        findings.append(("node-overlap", pair))
    for eid, reason in _geo.check_edge_direction(geo):
        findings.append(("edge-direction", (eid, reason)))
    for eid in _geo.check_edge_float(geo):
        findings.append(("edge-float", eid))
    for pair in _geo.check_corridor_sharing(geo):
        findings.append(("corridor-sharing", pair))
    return findings


#: Blocking rule names (landscape severity). A finding under one of these blocks
#: publication and drives the repair loop; other rules are advisory WARNINGs.
_BLOCKING_RULES = frozenset(
    {
        "container-padding",
        "container-overlap",
        "node-overlap",
        "edge-direction",
        "edge-float",
        "corridor-sharing",
    }
)

#: Rules the engine knows a deterministic repair for (Req 9.2). A blocking
#: finding *not* in this set is unfixable and forces a :class:`LayoutError`.
_FIXABLE_RULES = frozenset({"container-padding", "corridor-sharing"})


def _run_oracle(candidate: "PlacedDiagram") -> "OracleFindings":
    """Serialize ``candidate``, re-parse it, and run the geometry oracle (Req 9.1).

    Cheapest correct adapter (design.md): serialize the candidate with
    ``build_diagram`` (stub icons), ``build_geometry`` it back, and run the
    ``check_*`` set — so the oracle sees exactly what the linter would. Findings
    are split into ``blocking`` (the landscape ERROR/CRITICAL rules) and the
    ``fixable`` subset the repair loop knows how to resolve."""
    text = _serialize_candidate(candidate)
    from rule_engine.drawio_model import parse_drawio as _parse_drawio_model

    geo = _geo.build_geometry(_parse_drawio_model(text, path="<oracle>.drawio")[0])
    all_findings = [
        (rule, tuple(_spec_container_id(candidate, p) for p in payload)
         if isinstance(payload, tuple) else _spec_container_id(candidate, payload))
        for rule, payload in _collect_findings(geo)
    ]
    blocking = [f for f in all_findings if f[0] in _BLOCKING_RULES]
    fixable = [f for f in blocking if f[0] in _FIXABLE_RULES]
    return OracleFindings(blocking=blocking, fixable=fixable)


def _grow_container(box: Box, step: int = GRID) -> Box:
    """Grow a container box outward by ``step`` on every side (padding repair)."""
    return Box(box.id, _snap(box.x - step), _snap(box.y - step),
               _snap(box.w + 2 * step), _snap(box.h + 2 * step))


def _bump_edge_corridor(pe: "PlacedEdge", step: int = GRID) -> "PlacedEdge":
    """Move an edge's long run onto the next corridor lane (sharing repair).

    Shifts every interior waypoint by one ``GRID`` step along the axis of the
    edge's dominant run (x for a vertical run, y for a horizontal run), so the
    two previously-merged parallel runs land on distinct grid lines
    (``check_corridor_sharing`` clean). Endpoints (the pinned contact points) are
    untouched; only the interior corridor waypoints move, keeping the edge
    attached to both nodes."""
    if len(pe.points) < 2:
        return pe
    # Decide the run axis from the dominant interior segment.
    (x0, y0), (x1, y1) = pe.points[0], pe.points[-1]
    vertical = abs(x1 - x0) <= abs(y1 - y0)
    moved: List[Point] = []
    for (px, py) in pe.points:
        if vertical:
            moved.append((_snap(px + step), py))
        else:
            moved.append((px, _snap(py + step)))
    return PlacedEdge(spec=pe.spec, exit=pe.exit, entry=pe.entry, points=moved)


def orthogonalise_candidate(candidate: "PlacedDiagram") -> "PlacedDiagram":
    """Re-align every edge of a placed diagram (:func:`orthogonalise_route`).

    Run as a **finishing pass** after placement and after **every** repair, so the
    oracle always judges the geometry that will actually be emitted.

    The second part matters more than it looks. ``_bump_edge_corridor`` moves an
    edge's interior waypoints by one grid step to separate two merged corridors,
    but deliberately leaves the **pinned contact points** alone — so a route whose
    first leg was level with its exit comes back diagonal, because the waypoint
    moved and the contact did not. That is why aligning only inside
    ``_place_and_route`` was not enough: any edge the corridor-sharing repair
    touched (the landscape's ``dns → lb_b`` standby hop among them) lost the
    alignment again before it was written out.
    """
    edges = []
    for pe in candidate.edges:
        src = candidate.nodes.get(pe.spec.source)
        tgt = candidate.nodes.get(pe.spec.target)
        if src is None or tgt is None:
            edges.append(pe)
            continue
        pts = orthogonalise_route(
            _contact_point(src, pe.exit),
            pe.points,
            _contact_point(tgt, pe.entry),
            contact_faces(*pe.exit),
            contact_faces(*pe.entry),
        )
        edges.append(
            PlacedEdge(spec=pe.spec, exit=pe.exit, entry=pe.entry, points=pts)
        )
    return PlacedDiagram(
        spec=candidate.spec,
        nodes=candidate.nodes,
        containers=candidate.containers,
        edges=edges,
        legend_x=candidate.legend_x,
        legend_w=candidate.legend_w,
    )


def _repair(
    candidate: "PlacedDiagram", findings: "OracleFindings"
) -> "PlacedDiagram":
    """Apply one deterministic fix per fixable finding type (Req 9.2, 9.4).

    Repairs, each named and deterministic (findings arrive in a stable order):

    * **container-padding** → *grow* the offending container one ``GRID`` step on
      every side, so its border clears the child footprint by ≥ ``CONTAINER_PAD``.
    * **corridor-sharing** → move the *later* (higher-id) of the two colliding
      edges onto the next corridor lane, so the two runs no longer share a line.
    * **over-connected / any unfixable blocking finding** → raise
      :class:`LayoutError` naming the finding (Req 9.3): the diagram must be split
      or re-laned, not nudged.

    Exactly one fix is applied per fixable finding in the current pass; the
    caller re-runs the oracle and repairs again until clean or the bound is hit.
    """
    # Any blocking finding with no known repair is unfixable — fail-honest.
    unfixable = [f for f in findings.blocking if f[0] not in _FIXABLE_RULES]
    if unfixable:
        rule, payload = unfixable[0]
        raise LayoutError(
            f"unfixable blocking finding {rule!r} on {payload!r}; the diagram "
            "must be split or re-laned (repair loop cannot resolve it)"
        )

    containers = dict(candidate.containers)
    edges = list(candidate.edges)
    edge_by_id = {pe.spec.id: i for i, pe in enumerate(edges)}

    for rule, payload in sorted(findings.fixable, key=lambda f: (f[0], repr(f[1]))):
        if rule == "container-padding":
            _node_id, ccid = payload  # type: ignore[misc]
            if ccid in containers:
                containers[ccid] = _grow_container(containers[ccid])
        elif rule == "corridor-sharing":
            a, b = payload  # type: ignore[misc]
            later = max(a, b)  # deterministic: the higher edge id yields
            idx = edge_by_id.get(later)
            if idx is not None:
                edges[idx] = _bump_edge_corridor(edges[idx])

    return PlacedDiagram(
        spec=candidate.spec,
        nodes=candidate.nodes,
        containers=containers,
        edges=edges,
        legend_x=candidate.legend_x,
        legend_w=candidate.legend_w,
    )
