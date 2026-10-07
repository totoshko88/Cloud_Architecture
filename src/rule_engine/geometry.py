"""Diagram geometry model and geometry-aware lint checks.

Round-2 review findings D2/D3/D6 observed that several diagram-standards rules
(`container-padding`, `edge-routing`, grid rhythm) were prose-only: the CLI
`.drawio` parser extracted topology (node names, edge labels, icons) but **no
coordinates**, so the linter could not actually evaluate layout quality on a real
file. This module adds a light geometry model harvested from the ``.drawio`` XML
and the pure, side-effect-free predicates that operate on it.

Design constraints learned while calibrating against the golden examples:

- **Only top-level nodes participate.** A vertex nested inside another node (an
  embedded OCI stencil group's sub-cells) is that node's glyph geometry, not a
  diagram node — exactly the rule the node-count parser already applies. The
  boundary/container detection mirrors ``cli._parse_drawio`` (REVIEW.md C4).
- **Absolute coordinates.** draw.io child geometry is relative to the parent, so
  a node placed inside a boundary container carries container-relative x/y. We
  resolve absolute origins by walking the parent chain.
- **Edge-routing must not raise false positives.** draw.io renders orthogonal
  edges and routes around nodes; a naive straight-line center-to-center test
  wrongly flags a valid edge that the author routed around a node with explicit
  waypoints (verified on the GCP/OCI golden examples, edge ``e5``). The
  conservative rule here therefore only flags an edge when it is **not**
  orthogonal, or when a **waypoint-free** edge would pass straight through an
  unrelated node between its real contact points. An edge carrying explicit
  ``<mxPoint>`` waypoints is treated as deliberately routed.

Public interface::

    build_geometry(page) -> DiagramGeometry            # page: drawio_model.Page
    check_grid_alignment(geo, grid=10)  -> list[str]   # misaligned node ids
    check_node_overlap(geo)             -> list[tuple]  # overlapping id pairs
    check_container_padding(geo, pad=10)-> list[tuple]  # (node, container, pad)
    check_edge_routing(geo)             -> list[tuple]  # (edge_id, reason)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Container / text classification and the root-layer id are shared with
# cli._parse_drawio via rule_engine.constants so the C4 boundary-detection rule
# cannot drift between node counting and the geometry-aware layout checks.
from rule_engine.constants import ROOT_LAYER_ID as _ROOT_LAYER_ID
from rule_engine.constants import is_boundary_container_style as _is_boundary_style
from rule_engine.constants import is_text_cell_style as _is_text_style

# The single `.drawio` parser (honest-gates R1). ``build_geometry`` now consumes
# a parsed :class:`~rule_engine.drawio_model.Page` rather than re-reading the XML
# with local regexes, and resolves absolute origins through
# :func:`~rule_engine.drawio_model.absolute_origin` — which raises
# ``DrawioParseError`` on a parent cycle instead of silently returning ``(0, 0)``.
from rule_engine.drawio_model import Page, absolute_origin

# The model grid step (draw.io ``gridSize`` default). Spacings and node origins
# are expected to be whole multiples of it (diagram-standards Layout Geometry).
GRID = 10

# The mandated container padding per side (diagram-standards Container Padding /
# ``diagram_layout.CONTAINER_PAD`` = 30). ``check_container_dead_space`` grows
# each child's footprint by this on all four sides to compute the container's
# minimum legitimate area demand. ``diagram_layout`` imports ``geometry`` only
# lazily (inside functions), so this top-level import is cycle-safe.
from rule_engine.diagram_layout import CONTAINER_PAD, STAIR_STEP

# The label band drawn *below* a node's icon (``verticalLabelPosition=bottom``).
# A node's on-canvas footprint is not just its 78x78 icon box — the service name
# renders in a band beneath it, and that band collides with the next row / the
# container border exactly as the icon does. The icon-only box (78x78) is
# therefore label-blind: it lets a label crowd or overflow a boundary while the
# padding/overlap checks pass. ``LABEL_BAND`` extends every node box downward by
# one label line so overlap and container-padding measure what the reader sees.
# One line at the 12px floor plus leading ~= 30px (three grid steps); this is a
# conservative floor, not a per-string measurement.
LABEL_BAND = 30

# How far past a container border a node may spill and still be attributed to
# THAT container (v1.5.3 spill detection in ``check_container_padding``). A node
# that shares a container's column/row but has slid at most one row-step (the
# canonical 160px row rhythm) past its border is read as "fell out of this
# container", not "belongs to a container a tier away". Kept at one row-step so a
# node genuinely inside a sibling/parent tier further off is never mis-attributed.
_SPILL_REACH = 160

def _style_num(cell: str, name: str) -> Optional[float]:
    """Read a numeric style token like ``exitX=0.25`` from a cell."""
    m = re.search(rf"\b{name}=([-0-9.]+)", cell)
    return float(m.group(1)) if m else None


def _style_token(cell: str, name: str) -> Optional[str]:
    """Read a string style token like ``endArrow=open`` from a cell."""
    m = re.search(rf"\b{name}=([A-Za-z0-9_]+)", cell)
    return m.group(1) if m else None


@dataclass
class Box:
    """An absolute-coordinate rectangle for a node or container."""

    id: str
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def center(self) -> Tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def footprint(self, label_band: float = LABEL_BAND) -> "Box":
        """Return this box grown downward by ``label_band`` for the node label.

        A node's visual footprint is its icon box plus the caption band drawn
        beneath it. The overlap and container-padding checks use the footprint,
        not the bare icon box, so a label that crowds the next row or a boundary
        border is caught (a purely icon-based test is label-blind)."""
        return Box(self.id, self.x, self.y, self.w, self.h + label_band)


@dataclass
class EdgeGeom:
    """An edge with its source/target ids, contact points, and waypoints."""

    id: str
    source: str
    target: str
    orthogonal: bool
    exit: Tuple[Optional[float], Optional[float]]
    entry: Tuple[Optional[float], Optional[float]]
    points: Sequence[Tuple[float, float]] = field(default_factory=list)
    # Arrowhead form (draw.io ``endArrow`` token, e.g. "open"/"block"/"classic")
    # and stroke width in pt. Used by check_arrow_style (REVIEW.md D5).
    end_arrow: Optional[str] = None
    end_fill: Optional[int] = None
    stroke_width: Optional[float] = None
    # Start-arrowhead form (draw.io ``startArrow`` token). An unspecified
    # ``startArrow`` resolves to ``none`` (a single-head edge), so this is
    # ``None`` for the common case. Used by ``edge-bidirectional`` (1.10.0,
    # Requirement 1): an edge with a non-``none`` start AND a non-``none`` end
    # arrowhead is a double-headed (bidirectional) edge.
    start_arrow: Optional[str] = None
    # The edge's rendered label (its ``value``). A numbered flow-marker edge
    # carries a bare integer here (``"4"``); an unlabelled edge carries ``""``.
    # Used by the marker de-collision pass and ``marker-collision`` (1.10.5).
    label: str = ""
    # The label's position ALONG the edge as a signed fraction in ``[-1, 1]``:
    # draw.io stores it as the ``x`` of an ``mxGeometry relative="1"`` on the
    # edge, where 0 is the route midpoint, -1 the source end and +1 the target
    # end. ``None`` means the author pinned nothing, so the label renders at the
    # geometric midpoint (fraction 0) — the common case. Carried so the marker
    # de-collision pass can read and rewrite it deterministically (1.10.5).
    label_pos: Optional[float] = None


@dataclass
class DiagramGeometry:
    """The parsed geometry: top-level node boxes, container boxes, and edges."""

    nodes: Dict[str, Box] = field(default_factory=dict)
    containers: Dict[str, Box] = field(default_factory=dict)
    edges: List[EdgeGeom] = field(default_factory=list)
    #: Container id -> its caption text (the group's ``value``). Used to size the
    #: left-aligned caption band in ``check_edge_crosses_container_label`` per its
    #: real text length, so a corridor clearing a SHORT caption (e.g. "az-a1") is
    #: not flagged while one slicing a LONG caption ("vpc-passive …") is.
    container_labels: Dict[str, str] = field(default_factory=dict)
    #: Container id -> its raw style. Lets ``check_edge_crosses_container_label``
    #: locate the caption TEXT where draw.io draws it (``align`` / ``spacingLeft``)
    #: and flag a vertical leg cutting through it. Absent for a programmatic
    #: geometry, in which case only the legacy horizontal-run check applies.
    container_styles: Dict[str, str] = field(default_factory=dict)
    #: Text-cell id -> its box. Text cells are deliberately excluded from
    #: ``nodes`` (the linter must not count a Legend as a node), but their
    #: geometry is needed to check that the Flow/Legend furniture sits in the
    #: right margin (``legend-placement``, v1.6.0).
    text_boxes: Dict[str, Box] = field(default_factory=dict)
    #: Text-cell id -> its first line (the box heading, e.g. ``Flow``/``Legend``).
    text_headings: Dict[str, str] = field(default_factory=dict)
    #: Node id -> the overlay marker term it carries (``overlay=<term>`` in the
    #: cell, the vocabulary convention the CLI already reads). An overlay-marked
    #: node is exempt from ``node-connectivity``: a passive/standby peer may be
    #: drawn without edges precisely because the marker says so.
    overlay_nodes: Dict[str, str] = field(default_factory=dict)
    #: Node id -> its decoded caption text (the cell ``value``). Lets the linter
    #: size a node's caption band from its real text width
    #: (:func:`node_caption_box`, 1.10.7). Empty for a programmatic geometry, in
    #: which case the icon-width band applies.
    node_labels: Dict[str, str] = field(default_factory=dict)
    #: The model grid step this geometry was built with (``page.grid_size`` in
    #: ``build_geometry``, else the module :data:`GRID` default). Carried so the
    #: grid-alignment check judges node origins against the *page's* declared
    #: grid rather than a hard-coded 10 (honest-gates R1.7).
    grid: int = GRID


def build_geometry(page: Page) -> DiagramGeometry:
    """Build a :class:`DiagramGeometry` from a parsed
    :class:`~rule_engine.drawio_model.Page`.

    Only top-level nodes (parented to the root layer or a boundary container)
    and the boundary containers themselves are placed; embedded glyph sub-cells
    are ignored, exactly as the node-count parser does.

    Cells come from ``page.cells`` (the single ``.drawio`` parser owns the XML);
    absolute origins are resolved with
    :func:`~rule_engine.drawio_model.absolute_origin`, which raises
    ``DrawioParseError("parent-cycle:<id>")`` on a parent cycle rather than
    silently returning ``(0, 0)`` as the pre-1.7 local ``origin`` walker did. The
    grid step comes from ``page.grid_size`` (``mxGraphModel@gridSize``, else 10),
    not the module ``GRID`` default.
    """
    cells = page.cells

    geo = DiagramGeometry(grid=page.grid_size)

    # Boundary containers first (needed to classify node parents).
    boundary_ids = {
        cid
        for cid, cell in cells.items()
        if cell.vertex and _is_boundary_style(cid, cell.style.lower())
    }
    node_parents = {_ROOT_LAYER_ID} | boundary_ids

    for cid in boundary_ids:
        cell = cells[cid]
        g = cell.geom
        if g and g.w:
            ax, ay = absolute_origin(page, cid)
            geo.containers[cid] = Box(cid, ax, ay, float(g.w), float(g.h))
            geo.container_labels[cid] = cell.label
            geo.container_styles[cid] = cell.style

    for cid, cell in cells.items():
        if not cell.vertex or cid in boundary_ids:
            continue
        g = cell.geom
        if _is_text_style(cell.style.lower()):
            # A text cell is NOT a node (it must never be counted by node-count),
            # but its box is recorded separately so the Flow/Legend furniture can
            # be checked against the diagram body (legend-placement).
            if g and g.w:
                ax, ay = absolute_origin(page, cid)
                geo.text_boxes[cid] = Box(cid, ax, ay, float(g.w), float(g.h))
                geo.text_headings[cid] = cell.lines[0] if cell.lines else ""
            continue
        if cell.parent not in node_parents:
            continue
        if not g or not g.w:
            continue
        ax, ay = absolute_origin(page, cid)
        geo.nodes[cid] = Box(cid, ax, ay, float(g.w), float(g.h))
        geo.node_labels[cid] = cell.label or ""
        overlay = cell.style_map.get("overlay")
        if overlay:
            geo.overlay_nodes[cid] = overlay

    for cid, cell in cells.items():
        if not cell.edge:
            continue
        st = cell.style
        # Waypoints are authored relative to the edge's parent cell, so an edge
        # parented to a container carries container-relative points. Translate
        # every point by the parent's absolute origin so routing checks see
        # page coordinates (honest-gates R1.6). An edge on the root layer has a
        # parent origin of (0, 0), so its points are unchanged.
        pox, poy = absolute_origin(page, cell.parent)
        points = (
            [(px + pox, py + poy) for px, py in cell.geom.points]
            if cell.geom
            else []
        )
        # The label's along-edge position is the ``x`` of a ``relative="1"`` edge
        # geometry (0 == route midpoint, -1 source end, +1 target end). Absent /
        # non-relative geometry pins nothing, so the label renders at the
        # midpoint — recorded as ``None`` so the de-collision pass can tell an
        # unpinned label (free to move) from one the author fixed.
        label_pos = (
            cell.geom.x
            if cell.geom is not None and cell.geom.relative and cell.geom.x
            else None
        )
        geo.edges.append(
            EdgeGeom(
                id=cid,
                source=cell.source or "",
                target=cell.target or "",
                orthogonal="orthogonaledgestyle" in st.lower(),
                exit=(_style_num(st, "exitX"), _style_num(st, "exitY")),
                entry=(_style_num(st, "entryX"), _style_num(st, "entryY")),
                points=points,
                end_arrow=_style_token(st, "endArrow"),
                end_fill=(int(_style_num(st, "endFill")) if _style_num(st, "endFill") is not None else None),
                stroke_width=_style_num(st, "strokeWidth"),
                start_arrow=_style_token(st, "startArrow"),
                label=cell.label or "",
                label_pos=label_pos,
            )
        )

    return geo


# --------------------------------------------------------------------------- #
# Geometry-aware checks (pure; return the offending items, empty == clean)
# --------------------------------------------------------------------------- #


def check_grid_alignment(
    geo: DiagramGeometry, grid: Optional[int] = None
) -> List[str]:
    """Return ids of nodes whose absolute x or y is not a multiple of ``grid``.

    ``grid`` defaults to the geometry's own grid step (``geo.grid``, which
    ``build_geometry`` sets from ``page.grid_size``), so a page that declares a
    non-default ``gridSize`` is judged against its own grid rather than a
    hard-coded 10. Pass ``grid`` explicitly to override.

    Coordinates are compared after rounding to the nearest integer so that a
    value carrying float noise from accumulated coordinate math (e.g.
    ``219.9999999``) is judged against its intended integer origin rather than
    the raw float — the origins this engine emits are whole ``grid`` multiples,
    and a sub-pixel drift is not a real misalignment. (Node coordinates are
    always numeric here: :func:`~rule_engine.drawio_model.absolute_origin`
    coalesces a missing ``x``/``y`` to ``0.0`` before the box is built, so this
    never sees ``None``.)"""
    if grid is None:
        grid = geo.grid
    out = []
    for cid, b in geo.nodes.items():
        if (round(b.x) % grid) or (round(b.y) % grid):
            out.append(cid)
    return sorted(out)


def check_node_overlap(
    geo: DiagramGeometry, label_band: float = LABEL_BAND
) -> List[Tuple[str, str]]:
    """Return id pairs whose node **footprints** overlap.

    The footprint is the icon box grown downward by ``label_band`` (the caption
    band), so two nodes whose icons clear each other but whose labels collide are
    still flagged — the defect a reader sees. Pass ``label_band=0`` for the
    legacy icon-only test."""
    boxes = [b.footprint(label_band) for b in geo.nodes.values()]
    out: List[Tuple[str, str]] = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom:
                out.append(tuple(sorted((a.id, b.id))))  # type: ignore[arg-type]
    return sorted(set(out))


def check_container_padding(
    geo: DiagramGeometry, pad: int = GRID, label_band: float = LABEL_BAND
) -> List[Tuple[str, str, float]]:
    """Return ``(inner_id, container_id, min_pad)`` where a node **or a nested
    container** inside a container leaves less than ``pad`` on some side (or
    straddles the border).

    Two kinds of finding are produced, both against the same ``pad`` floor:

    * **node-in-container** — a node's **footprint** (icon + caption band) must
      clear its enclosing boundary by ``pad`` on all four sides, so a label that
      reaches the container border is caught even when the icon clears it.
    * **container-in-container** (v1.5.2) — a *nested* boundary must clear its
      **parent** boundary by ``pad`` on every side too. diagram-standards
      Container Padding requires "≥ 1 grid step ... between a nested container
      (for example a Network Boundary inside a Boundary) and its parent". The
      four sides are measured symmetrically against ``pad`` — the same convention
      the node-in-container loop uses — so the check agrees with what
      ``size_containers`` produces. Before v1.5.2 this loop only measured nodes,
      so a VPC box sharing an edge with its Account box (zero padding) was never
      evaluated — the exact defect this closes.

    In both cases the ``inside`` predicate uses ``<`` on the far edges so that a
    child sharing an edge *exactly* with its parent (``right == right``) is still
    treated as inside-with-zero-padding (a finding), not as "not inside"."""
    out: List[Tuple[str, str, float]] = []

    # A node fully contained by SOME container is on its home turf; the spill
    # check below must not fire on it just because it also shares a band with a
    # neighbouring container a tier away. Precompute the set of "housed" nodes so
    # spill is reserved for genuinely orphaned nodes (in no container at all).
    housed: set = set()
    for ncid, node in geo.nodes.items():
        n = node.footprint(label_band)
        for c in geo.containers.values():
            if c.x <= n.x and c.y <= n.y and n.right <= c.right and n.bottom <= c.bottom:
                housed.add(ncid)
                break

    # --- node-in-container -------------------------------------------------- #
    for ncid, node in geo.nodes.items():
        n = node.footprint(label_band)
        for ccid, c in geo.containers.items():
            inside = c.x <= n.x and c.y <= n.y and n.right <= c.right and n.bottom <= c.bottom
            if not inside:
                # A node not fully inside is a finding when it *conflicts* with
                # the container border. Two conflict shapes are caught:
                #
                #  * **Straddle** — the boxes overlap on BOTH axes, so the node
                #    sits half in / half out (a corner or edge overlap).
                #  * **Spill** (v1.5.3) — the node's projection is fully contained
                #    in the container's band on ONE axis (it shares the
                #    container's column, or its row), yet it has slid just past
                #    the container's border on the other axis. This is a node
                #    that lines up with the container's contents but is drawn
                #    outside the box — the EC2-az-c / S3 defect in the
                #    inventory-driven AWS diagram, where a node in the VPC's
                #    x-band fell below the VPC's bottom edge. The pre-1.5.3 check
                #    required overlap on BOTH axes, so that node was neither
                #    "inside" nor "straddle" and slipped through as clean.
                #
                # Spill is deliberately narrow to avoid false positives:
                #   0. the node is ORPHANED — no container fully contains it. A
                #      node housed by some other container (a sibling AZ / the
                #      parent Account) legitimately shares a band with THIS one
                #      and must never be read as spilled out of it (an edge-tier
                #      node above the VPC, a second-AZ node below the first AZ).
                #   1. the node's band on the containment axis is FULLY within
                #      the container's band (``contained_x`` / ``contained_y``) —
                #      a mere partial overlap is not a spill; and
                #   2. the overflow past the border on the other axis is within
                #      one row/column step (``_SPILL_REACH``) — a node many steps
                #      away is unrelated, not spilled out of this one.
                # A node disjoint on BOTH axes (an external actor drawn to the
                # left of and above/below the boundary, e.g. the internet user)
                # is neither straddle nor spill and is correctly NOT flagged.
                overlaps_x = n.x < c.right and c.x < n.right
                overlaps_y = n.y < c.bottom and c.y < n.bottom
                if overlaps_x and overlaps_y:
                    out.append((ncid, ccid, 0.0))  # straddle
                elif ncid not in housed:
                    contained_x = c.x <= n.x and n.right <= c.right
                    # Only VERTICAL spill is flagged (a node in the container's
                    # x-band that slid past its top/bottom border). Horizontal
                    # spill is deliberately NOT flagged: an external actor
                    # (lane `actors`/`on-premises`) is drawn just to the LEFT of
                    # the boundary by design (diagram-standards: actors sit
                    # OUTSIDE the cloud boundaries), and geometry alone cannot
                    # tell that legitimate placement from a node that slid out
                    # the side. A row that does not fit the container's HEIGHT,
                    # by contrast, is unambiguously a spilled tier — the
                    # canonical EC2-az-c / S3 "fell below the VPC" defect.
                    vert_spill = contained_x and (
                        0 < n.y - c.bottom <= _SPILL_REACH
                        or 0 < c.y - n.bottom <= _SPILL_REACH
                    )
                    if vert_spill:
                        out.append((ncid, ccid, 0.0))  # spill past top/bottom
                continue
            min_pad = min(n.x - c.x, n.y - c.y, c.right - n.right, c.bottom - n.bottom)
            if min_pad < pad:
                out.append((ncid, ccid, float(min_pad)))

    # --- container-in-container (nested boundaries) ------------------------- #
    # A child boundary must clear its parent by ``pad`` on every side. We pick,
    # for each container, the *smallest* enclosing container as its parent so a
    # triple nest (Account ⊃ VPC ⊃ AZ) is measured against the immediate parent,
    # not the grandparent. The four gaps are measured symmetrically against plain
    # ``pad`` — the same convention the node-in-container loop above uses (a
    # parent's top caption shares the child's top padding, exactly as it shares a
    # top-row node's padding), so the check agrees with what ``size_containers``
    # produces and does not demand a stricter top rule than nodes get.
    boxes = list(geo.containers.values())
    for child in boxes:
        parent = _tightest_enclosing(child, boxes)
        if parent is None:
            continue
        left = child.x - parent.x
        right = parent.right - child.right
        top = child.y - parent.y
        bottom = parent.bottom - child.bottom
        min_pad = min(left, right, top, bottom)
        if min_pad < pad:
            out.append((child.id, parent.id, float(min_pad)))

    return out


def _tightest_enclosing(child: "Box", boxes: List["Box"]) -> Optional["Box"]:
    """Return the smallest container that strictly encloses ``child``.

    "Encloses" allows a shared edge (``<=``), because a child sharing a border
    with a candidate parent is still that parent's child (with zero padding, a
    finding) — not a disjoint sibling. Among all enclosing candidates the one
    with the smallest area is the *immediate* parent, so a grandparent never
    masks the tighter parent for the padding measurement."""
    best: Optional["Box"] = None
    best_area = float("inf")
    for cand in boxes:
        if cand.id == child.id:
            continue
        encloses = (
            cand.x <= child.x
            and cand.y <= child.y
            and child.right <= cand.right
            and child.bottom <= cand.bottom
        )
        if not encloses:
            continue
        area = cand.w * cand.h
        # Skip a candidate identical in area (same box) to avoid ties on a
        # duplicate; strictly-larger-or-tighter wins.
        if area < best_area:
            best, best_area = cand, area
    return best


def check_container_overlap(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return id pairs of **sibling** containers whose boxes overlap.

    Two containers are siblings when neither fully contains the other; a proper
    nesting (Account ⊃ Region ⊃ AZ) is expected and never flagged. But two peer
    boundaries that partially overlap (e.g. a primary-VPC box bleeding into the
    passive-VPC box) put shared area under two labelled groups at once — a
    structural defect that makes a node ambiguous about which boundary it lives
    in. This is the container-level twin of :func:`check_node_overlap`."""

    def _contains(outer: Box, inner: Box) -> bool:
        return (
            outer.x <= inner.x
            and outer.y <= inner.y
            and inner.right <= outer.right
            and inner.bottom <= outer.bottom
        )

    boxes = list(geo.containers.values())
    out: List[Tuple[str, str]] = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if _contains(a, b) or _contains(b, a):
                continue  # proper nesting, not a sibling overlap
            if a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom:
                out.append(tuple(sorted((a.id, b.id))))  # type: ignore[arg-type]
    return sorted(set(out))


# Tolerance for reading a draw.io unit-square fraction as lying *on* a face. The
# shared builder deliberately starts a stub a hair beyond the perimeter
# (``exitX=1.0256`` with ``exitPerimeter=0``) so the arrow does not bite into the
# glyph, so the right/bottom faces are matched with ">= 1.0", not "== 1.0".
_FACE_EPS = 1e-9

#: The faces an edge may legally leave its source from (right or bottom).
_LEGAL_EXIT_FACES = frozenset({"right", "bottom"})
#: The faces an edge may legally arrive at its target on (left or top).
_LEGAL_ENTRY_FACES = frozenset({"left", "top"})


def contact_faces(x: Optional[float], y: Optional[float]) -> frozenset[str]:
    """Return the unit-square faces a contact point lies on.

    A draw.io contact point is a fraction of the node box: ``x`` grows right,
    ``y`` grows downward. A coordinate at an extreme puts the point **on** that
    face, so ``(1, 0.5)`` is the right face, ``(0.5, 0)`` the top face, and a
    corner such as ``(1, 0)`` lies on **two** faces (right *and* top).

    A coordinate strictly between the extremes is a *band* position that names no
    face — ``(0.5, None)`` pins only how far right along an unspecified side the
    stub sits — so the returned set is empty and the caller falls back to judging
    the lean.
    """
    faces: set[str] = set()
    if x is not None:
        if x >= 1.0 - _FACE_EPS:
            faces.add("right")
        elif x <= _FACE_EPS:
            faces.add("left")
    if y is not None:
        if y >= 1.0 - _FACE_EPS:
            faces.add("bottom")
        elif y <= _FACE_EPS:
            faces.add("top")
    return frozenset(faces)


def check_edge_direction(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for edges that break the directional contract.

    The contract (diagram-standards Edge Routing → "The directional contract"):
    an edge **exits** its source on the **right or bottom** and **enters** its
    target on the **left or top**.

    **Face classification (v1.6.0).** The check reads which *face* of the unit
    square each contact point lies on (:func:`contact_faces`) rather than which
    half-plane it leans into. The pre-1.6.0 logic tested ``exitX >= 0.5`` in
    order to admit the right edge **and** the top-right / bottom-right corners —
    but ``exitX >= 0.5`` is also true of ``(0.5, 0)``, the **top-centre** point,
    so a pinned top exit was "rescued" by its own x and an edge leaving straight
    out of the top of its glyph linted clean. That is exactly what a clean-room
    install produced: an ``EC2 → S3`` edge pinned ``exit=(0.5, 0)``, visibly
    rising out of the top of the EC2 icon, with no finding. The entry side had
    the mirror hole: a bottom-centre arrival ``(0.5, 1)`` was rescued by
    ``entryX <= 0.5``.

    So a contact point that lies on a face is judged by that face:

    * a valid **exit** lies on the **right** (``exitX >= 1``) or **bottom**
      (``exitY >= 1``) face; the top-right ``(1, 0)`` and bottom-right ``(1, 1)``
      corners stay legal because they lie on the right face too, while the
      top-centre ``(0.5, 0)`` and left-centre ``(0, 0.5)`` points are defects;
    * a valid **entry** lies on the **left** (``entryX <= 0``) or **top**
      (``entryY <= 0``) face; the bottom-left ``(0, 1)`` corner stays legal,
      while the bottom-centre ``(0.5, 1)`` and right-centre ``(1, 0.5)`` points
      are defects.

    A *band* pin that names no face (e.g. ``exitX=0.75`` with no ``exitY``) keeps
    the pre-1.6.0 lean test, so every prior judgement on a single-axis pin is
    preserved.

    This is enforced only for edges that declare explicit contact points; an edge
    that floats its connection is left to draw.io's perimeter router and not
    judged here (``edge-float`` owns that). The reason names the offending face,
    e.g. ``exit-top-not-right-or-bottom``.
    """
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        ex, ey = e.exit
        nx, ny = e.entry
        # An edge is judged only if it pins at least one contact axis; a fully
        # floating edge is left to the perimeter router.
        if ex is not None or ey is not None:
            faces = contact_faces(ex, ey)
            if faces:
                if not (faces & _LEGAL_EXIT_FACES):
                    offending = "-".join(sorted(faces))
                    out.append((e.id, f"exit-{offending}-not-right-or-bottom"))
                    continue
            elif ex is not None and ex < 0.5:
                # Band pin on no face: keep the pre-1.6.0 lean test.
                out.append((e.id, "exit-not-right-or-bottom"))
                continue
        if nx is not None or ny is not None:
            faces = contact_faces(nx, ny)
            if faces:
                if not (faces & _LEGAL_ENTRY_FACES):
                    offending = "-".join(sorted(faces))
                    out.append((e.id, f"enter-{offending}-not-left-or-top"))
            elif nx is not None and nx > 0.5:
                out.append((e.id, "enter-not-left-or-top"))
    return out


def check_exit_thirds(geo: DiagramGeometry, min_sep: float = 0.2) -> List[Tuple[str, str]]:
    """Return ``(node_id, reason)`` for a node's over-crowded same-side fan-out
    (diagram-standards → Label-safe exits / *Distinct same-side exits*).

    Two soft, unambiguous conditions — deliberately **not** the rigid
    ``0.25/0.5/0.75`` grid, because the exit-priority ladder puts a
    straight-line edge (a target directly opposite) on the **centre** while the
    other edges spread around it, which is more readable than forcing thirds:

    1. **At most three exits per side.** A fourth means the node is
       over-connected — split or re-lane the diagram (``over-connected``).
    2. **Distinct exits (no two merge).** Any two exits on one side sit at least
       ``min_sep`` of the face apart (default 0.2 ≈ 16px on a 78px side), so they
       do not read as one doubled line at the glyph (``exits-merge``).

    Sides are keyed off the *exit* point only (source-side fan-out). An exit on
    the right face groups by its ``exitY`` band; an exit on the top/bottom face
    groups by its ``exitX`` band. A left-side exit is not judged here — it
    already violates the directional contract, which ``check_edge_direction``
    owns. Edges that float their exit (no explicit point) are ignored."""
    # Group each declared exit by (source, side); record the band coordinate.
    sides: Dict[Tuple[str, str], List[float]] = {}
    for e in geo.edges:
        ex, ey = e.exit
        if ex is None and ey is None:
            continue
        # Classify the exit face, then the coordinate that varies along it.
        if ey is not None and ey >= 1.0:            # bottom face
            side, coord = "bottom", (ex if ex is not None else 0.5)
        elif ey is not None and ey <= 0.0:          # top face
            side, coord = "top", (ex if ex is not None else 0.5)
        elif ex is not None and ex >= 0.5:          # right face (incl. >1 stubs)
            side, coord = "right", (ey if ey is not None else 0.5)
        else:
            # A left-side exit already violates the directional contract
            # (check_edge_direction owns that); the fan-out rule only judges the
            # sanctioned right/bottom/top faces, so it is not re-flagged here.
            continue
        sides.setdefault((e.source, side), []).append(coord)

    out: List[Tuple[str, str]] = []
    for (node, side), coords in sorted(sides.items()):
        if len(coords) <= 1:
            continue  # a single exit is always fine wherever it sits
        if len(coords) > 3:
            out.append((node, f"{side}-over-connected-{len(coords)}-exits"))
            continue
        got = sorted(round(c, 3) for c in coords)
        if any(b - a < min_sep for a, b in zip(got, got[1:])):
            pts = ",".join(f"{g:.2f}" for g in got)
            out.append((node, f"{side}-exits-merge(<{min_sep}: {pts})"))
    return out


def check_entry_thirds(geo: DiagramGeometry, min_sep: float = 0.2) -> List[Tuple[str, str]]:
    """Return ``(node_id, reason)`` for a TARGET's over-crowded same-face arrivals.

    The entry-side mirror of :func:`check_exit_thirds` (v1.5.1). ``check_exit_thirds``
    only inspects *source* fan-out, so two edges arriving on the SAME target face
    at the SAME point were invisible to it — the exact defect in the buggy AWS
    example, where two ``EC2 → RDS`` edges both entered RDS at ``entryX=0,
    entryY=0.5`` and merged into one doubled line at the glyph.

    Two soft conditions, matching the exit rule:

    1. **At most three entries per face.** A fourth means the node is
       over-connected — split or re-lane (``over-connected``).
    2. **Distinct entries (no two merge).** Any two arrivals on one face sit at
       least ``min_sep`` of the face apart (default 0.2), so they do not stack on
       one contact point (``entries-merge``).

    An entry face is keyed off the *entry* point: a left entry (``entryX <= 0.5``)
    groups by its ``entryY`` band; a top entry (``entryY <= 0``) by its ``entryX``
    band. A right-edge entry (``entryX > 0.5``) already violates the directional
    contract, which :func:`check_edge_direction` owns, so it is not judged here.
    Edges that float their entry (no explicit point) are ignored."""
    faces: Dict[Tuple[str, str], List[float]] = {}
    for e in geo.edges:
        nx, ny = e.entry
        if nx is None and ny is None:
            continue
        if ny is not None and ny <= 0.0:            # top face
            face, coord = "top", (nx if nx is not None else 0.5)
        elif nx is not None and nx <= 0.5:          # left face (incl. <0 stubs)
            face, coord = "left", (ny if ny is not None else 0.5)
        else:
            # A right-edge entry already breaks the directional contract
            # (check_edge_direction owns that); the arrival-crowding rule only
            # judges the sanctioned left/top faces.
            continue
        faces.setdefault((e.target, face), []).append(coord)

    out: List[Tuple[str, str]] = []
    for (node, face), coords in sorted(faces.items()):
        if len(coords) <= 1:
            continue
        if len(coords) > 3:
            out.append((node, f"{face}-over-connected-{len(coords)}-entries"))
            continue
        got = sorted(round(c, 3) for c in coords)
        if any(b - a < min_sep for a, b in zip(got, got[1:])):
            pts = ",".join(f"{g:.2f}" for g in got)
            out.append((node, f"{face}-entries-merge(<{min_sep}: {pts})"))
    return out


#: The step, in model units, between successive samples along a segment. Chosen
#: well below the smallest obstacle dimension the engine draws (a 78×78 icon,
#: and a ~30px label band) so no obstacle can slip entirely between two samples
#: on a long run. A fixed sample *count* (the old 61) under-sampled a wide
#: landscape run — its spacing exceeded a 78px icon, so a thin obstacle sitting
#: between two samples was missed (a false-negative crossing). Sampling by a
#: fixed *step* instead keeps the density constant regardless of run length.
_SEGMENT_SAMPLE_STEP = 8.0


def segment_crosses_box(
    p: Tuple[float, float], q: Tuple[float, float], b: Box, inset: float = 2.0
) -> bool:
    """Return True when the straight segment ``p``→``q`` passes through box ``b``.

    This is the **single** segment-sampling obstacle predicate: the straight run
    is sampled at a fixed spatial *step* (:data:`_SEGMENT_SAMPLE_STEP` model
    units, ≪ a 78px icon) rather than a fixed number of points, so the sample
    density stays constant on both a short stub and a multi-thousand-pixel
    landscape run — a thin obstacle can never fall entirely between two samples.
    A sample counts as a crossing only when it lands strictly inside ``b``
    shrunk by ``inset`` on every side, so a mere graze of a border is not a
    crossing. :func:`check_edge_routing` uses it to decide whether a
    waypoint-free edge cuts an unrelated node, and the layout engine's routers
    reuse the *same* predicate as their obstacle test so the router and the
    validator agree by construction (design.md → Routing)."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    lo_x, hi_x = b.x + inset, b.right - inset
    lo_y, hi_y = b.y + inset, b.bottom - inset
    if lo_x > hi_x or lo_y > hi_y:
        return False                     # the inset swallows the box: nothing inside
    # 1.10.6: answer the SAME question the fixed-step sampling asks, but in O(1).
    # Quick reject on bounding boxes first (the overwhelmingly common case: the
    # segment is nowhere near the box), then compute the parameter interval
    # [t0, t1] over which the segment lies inside the inset box and test only the
    # few sample indices bordering it with the original inequality. Any sample
    # farther than one step from the interval is outside by a full step, so the
    # verdict is byte-identical to sampling every ``i / steps`` — and the
    # geometry rules become cheap enough to score inside the layout solver.
    if (max(p[0], q[0]) < lo_x or min(p[0], q[0]) > hi_x
            or max(p[1], q[1]) < lo_y or min(p[1], q[1]) > hi_y):
        return False
    length = (dx * dx + dy * dy) ** 0.5
    # At least 61 samples (the historical floor for short runs), and more for a
    # long run so spacing never exceeds _SEGMENT_SAMPLE_STEP.
    steps = max(60, int(length / _SEGMENT_SAMPLE_STEP))
    t0, t1 = 0.0, 1.0
    for d, start, lo, hi in ((dx, p[0], lo_x, hi_x), (dy, p[1], lo_y, hi_y)):
        if d == 0:
            if not (lo <= start <= hi):
                return False
            continue
        a, c = (lo - start) / d, (hi - start) / d
        if a > c:
            a, c = c, a
        t0, t1 = max(t0, a), min(t1, c)
    n0, n1 = t0 * steps, t1 * steps
    if n1 - n0 > 3:
        return True                      # a sample sits a full step inside
    first = max(0, int(math.floor(n0)) - 1)
    last = min(steps, int(math.ceil(n1)) + 1)
    for i in range(first, last + 1):
        t = i / steps
        px = p[0] + dx * t
        py = p[1] + dy * t
        if lo_x <= px <= hi_x and lo_y <= py <= hi_y:
            return True
    return False


def check_edge_routing(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for edges that break routing rules.

    Conservative to avoid false positives on validly routed diagrams:

    * a non-orthogonal edge is always flagged (``not-orthogonal``);
    * a **waypoint-free** edge whose straight run between its real contact
      points passes through an unrelated node is flagged
      (``straight-through-<node>``);
    * a **waypointed** edge whose real *orthogonal* path (the axis-aligned knees
      draw.io actually draws, not the raw diagonals between points) runs through
      an unrelated node is flagged (``knee-through-<node>``, v1.5.4).

    **v1.5.4 — the orthogonal-knee gap.** Before this release a waypointed edge
    was trusted entirely on the crossing criterion, because sampling the raw
    diagonal between two points false-flagged a validly routed edge (draw.io
    routes orthogonally around nodes — the GCP/OCI golden ``e5`` case). But
    trusting the *diagonal* also missed the opposite defect: a waypointed edge
    whose real drawn path is an L-shaped knee whose horizontal (or vertical) leg
    slices an unrelated icon. The devoxx ``e8`` edge (EC2→S3, exit on the right
    face at y≈216, first waypoint up-and-right) leaves horizontally at y≈216 and
    runs straight through the RDS icon before turning up — a crossing the diagonal
    sample stepped cleanly over. The fix samples the **knee path** draw.io draws:
    each leg between consecutive polyline points is expanded to its horizontal-
    first axis-aligned segments (``_orthogonal_knee``), matching what an
    orthogonal edge renders (verified against the exported golden PNGs — ``e5``
    routes horizontal-to-waypoint-x then vertical, clear of ``vertex-ai``; ``e8``
    routes horizontal-at-exit-y, into ``rds``). All twelve golden examples stay
    clean under the knee model; only a genuine icon crossing trips it.
    """
    out: List[Tuple[str, str]] = []
    nodes = geo.nodes
    for e in geo.edges:
        if not e.orthogonal:
            out.append((e.id, "not-orthogonal"))
            continue
        if e.source not in nodes or e.target not in nodes:
            continue
        s, t = nodes[e.source], nodes[e.target]
        ex = e.exit[0] if e.exit[0] is not None else 1.0
        ey = e.exit[1] if e.exit[1] is not None else 0.5
        nx = e.entry[0] if e.entry[0] is not None else 0.0
        ny = e.entry[1] if e.entry[1] is not None else 0.5
        p = (s.x + ex * s.w, s.y + ey * s.h)
        q = (t.x + nx * t.w, t.y + ny * t.h)
        # (1) Self-piercing approach (v1.5.1). The last segment before the entry
        #     must reach the pinned entry contact FROM THE CORRECT SIDE, so it
        #     touches the target's perimeter, not its interior. A TOP entry
        #     (entryY == 0) must be approached from ABOVE (the segment's other end
        #     has y < entry_y); a LEFT entry (entryX == 0) from the LEFT
        #     (x < entry_x). The buggy ALB→S3 edge pinned a TOP entry but ran its
        #     final leg UP from a corridor BELOW the icon, so the leg pierced the
        #     target's own glyph to reach the top contact (the "enters through the
        #     icon instead of from the top" defect). This is target-specific, so
        #     it is checked here rather than in the unrelated-node loop below.
        approach = (e.points[-1] if e.points else p)
        pierce = _approach_pierces_target(approach, q, e.entry, t)
        if pierce:
            out.append((e.id, f"pierces-target-{e.target}"))
            continue
        # (2) A run that cuts an UNRELATED node icon.
        #
        #   * **waypoint-free** edge — sample its straight source→target run
        #     (``straight-through-<node>``). Reason unchanged.
        #   * **waypointed** edge (v1.5.4) — sample the *orthogonal knee* path
        #     draw.io actually draws, not the raw diagonals between the points.
        #     A waypointed edge used to be trusted entirely here (draw.io routes
        #     orthogonally around nodes, so sampling the raw diagonal
        #     false-flagged the validly routed golden ``e5``). But the drawn path
        #     is L-shaped knees, and a knee's leg can slice an icon the diagonal
        #     skips over — the devoxx ``e8`` horizontal stub cutting ``rds``. We
        #     expand each leg to its horizontal-first axis-aligned segments
        #     (``_orthogonal_knee``) and sample those (``knee-through-<node>``).
        if not e.points:
            for other, b in nodes.items():
                if other in (e.source, e.target):
                    continue
                # Sample the straight segment; a 2px inset means a mere graze of
                # a border does not count as a crossing.
                if segment_crosses_box(p, q, b):
                    out.append((e.id, f"straight-through-{other}"))
                    break
            continue

        # Waypointed: build the full polyline (real contacts + waypoints) and
        # expand every diagonal leg into the horizontal-first knee draw.io draws.
        polyline = [p] + list(e.points) + [q]
        knee_pts: List[Tuple[float, float]] = [polyline[0]]
        for a, b in zip(polyline, polyline[1:]):
            knee_pts.extend(_orthogonal_knee(a, b)[1:])
        for other, box in nodes.items():
            if other in (e.source, e.target):
                continue
            if any(
                segment_crosses_box(seg_a, seg_b, box)
                for seg_a, seg_b in zip(knee_pts, knee_pts[1:])
            ):
                out.append((e.id, f"knee-through-{other}"))
                break
    return out


def _orthogonal_knee(
    a: Tuple[float, float], b: Tuple[float, float]
) -> List[Tuple[float, float]]:
    """Return the axis-aligned vertices draw.io draws for the leg ``a``→``b``.

    An ``orthogonalEdgeStyle`` edge never draws a diagonal: a leg between two
    points that differ on both axes renders as an L — **horizontal first**, then
    vertical. That horizontal-first choice is what the exported golden PNGs show
    (``e5`` runs horizontal to the waypoint's x then drops vertically, clear of
    ``vertex-ai``; the devoxx ``e8`` runs horizontal at the exit's y, into
    ``rds``), so modelling the knee as H-first reproduces the real render and
    keeps all twelve goldens clean while catching the ``e8`` crossing. A leg that
    is already axis-aligned (shares an x or a y within 1px) is returned as-is."""
    (x0, y0), (x1, y1) = a, b
    if abs(x1 - x0) < 1 or abs(y1 - y0) < 1:
        return [a, b]
    return [a, (x1, y0), b]


def _approach_pierces_target(
    approach: Tuple[float, float],
    entry_pt: Tuple[float, float],
    entry_frac: Tuple[Optional[float], Optional[float]],
    target: Box,
) -> bool:
    """Return True when the final leg reaches ``entry_pt`` from the wrong side.

    ``approach`` is the last polyline vertex before the entry contact
    ``entry_pt`` (in absolute coords); ``entry_frac`` is the pinned
    ``(entryX, entryY)`` fraction; ``target`` is the target box. A pinned entry
    contact sits on one face of the target; the leg arriving at it must come from
    OUTSIDE that face, or it crosses the icon body to reach the contact:

    * a TOP entry (``entryY == 0``) must be approached from ABOVE
      (``approach_y < entry_y``);
    * a BOTTOM entry (``entryY == 1``) from BELOW (``approach_y > entry_y``);
    * a LEFT entry (``entryX == 0``) from the LEFT (``approach_x < entry_x``);
    * a RIGHT entry (``entryX == 1``) from the RIGHT (``approach_x > entry_x``).

    Only a clearly wrong-side approach (beyond a small tolerance, and while the
    approach is within the icon's cross-extent so it truly overlaps the glyph) is
    a pierce, so an orthogonal leg that meets the face squarely is never flagged.
    """
    fx, fy = entry_frac
    ax, ay = approach
    ex, ey = entry_pt
    tol = 2.0
    # TOP / BOTTOM faces: the approach x must be within the icon's x-extent for
    # the vertical leg to actually run through the glyph.
    if fy is not None and fy <= 0.0:  # top face → must come from above
        if target.x + tol < ax < target.right - tol and ay > ey + tol:
            return True
    if fy is not None and fy >= 1.0:  # bottom face → must come from below
        if target.x + tol < ax < target.right - tol and ay < ey - tol:
            return True
    # LEFT / RIGHT faces: the approach y must be within the icon's y-extent.
    if fx is not None and fx <= 0.0:  # left face → must come from the left
        if target.y + tol < ay < target.bottom - tol and ax > ex + tol:
            return True
    if fx is not None and fx >= 1.0:  # right face → must come from the right
        if target.y + tol < ay < target.bottom - tol and ax < ex - tol:
            return True
    return False


_HTML_BR_RE = re.compile(r"<br\s*/?>", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def caption_lines(label: str) -> List[str]:
    """Return the non-empty rendered lines of a node caption.

    ``<br>`` / ``<br/>`` become line breaks, every other tag is removed and HTML
    entities are unescaped, so a raw ``value`` and the parser's decoded label
    yield the same lines."""
    import html as _html

    text = _HTML_BR_RE.sub("\n", label or "")
    text = _html.unescape(_HTML_TAG_RE.sub("", text))
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def node_caption_box(box: Box, label: str, label_band: float = LABEL_BAND) -> Box:
    """Return the caption rectangle draw.io renders under a node's icon.

    The caption (``verticalLabelPosition=bottom``) is centred on the icon and
    is as wide as its longest line — estimated at :data:`_CAPTION_TEXT_CHAR_W`
    (7.0px/char at the 12px font, a conservative ceiling) — but never narrower
    than the icon. It starts at the icon bottom and is ``label_band`` tall, or
    16px per line when the caption wraps to more lines than that holds. A wide
    caption ("Amazon QuickSight dashboards") overhangs its 78px icon on both
    sides; the icon-width band (:func:`Box.footprint`) cannot see an edge
    cutting through that overhang (1.10.7)."""
    lines = caption_lines(label)
    longest = max((len(ln) for ln in lines), default=0)
    w = max(box.w, longest * _CAPTION_TEXT_CHAR_W)
    h = max(label_band, 16.0 * len(lines))
    return Box(box.id, box.x + box.w / 2.0 - w / 2.0, box.bottom, w, h)


def check_edge_crosses_label(
    geo: DiagramGeometry,
    label_band: float = LABEL_BAND,
    caption_width: bool = False,
) -> List[Tuple[str, str]]:
    """Return ``(edge_id, node_id)`` for edges whose routed polyline crosses an
    unrelated node's **label band** — the caption strip drawn beneath the icon
    (``verticalLabelPosition=bottom``), from the icon bottom down by
    ``label_band``.

    A run that clears every icon can still cut straight through a service caption
    a row below it (the "line crosses the service names" defect). This samples
    each edge's full polyline (its real contact points plus every ``<mxPoint>``
    waypoint) against each non-endpoint node's label-band rectangle, using the
    same :func:`segment_crosses_box` predicate the routers and ``check_edge_routing``
    use, so router and validator agree. Advisory (WARNING): it flags a crossing
    the geometry rules alone (which measure icon boxes) would miss.

    ``caption_width=True`` (the linter, 1.10.7) measures each UNRELATED node's
    caption at its real text width (:func:`node_caption_box`) when its label is
    known, so a run through the overhang of a wide caption is caught. The
    edge's own source/target stay exempt. The default ``False`` is the icon-width
    band the layout engine's scored objective (:func:`rule_violations`) uses —
    kept unchanged so engine output does not move."""
    out: List[Tuple[str, str]] = []
    nodes = geo.nodes
    labels = geo.node_labels if caption_width else {}
    for e in geo.edges:
        if e.source not in nodes or e.target not in nodes:
            continue
        s, t = nodes[e.source], nodes[e.target]
        ex = e.exit[0] if e.exit[0] is not None else 1.0
        ey = e.exit[1] if e.exit[1] is not None else 0.5
        nx = e.entry[0] if e.entry[0] is not None else 0.0
        ny = e.entry[1] if e.entry[1] is not None else 0.5
        polyline = [(s.x + ex * s.w, s.y + ey * s.h)]
        polyline += list(e.points)
        polyline += [(t.x + nx * t.w, t.y + ny * t.h)]
        for other, b in nodes.items():
            if other in (e.source, e.target):
                continue
            # The label band is the strip BELOW the icon (icon bottom .. +band).
            if labels.get(other):
                band = node_caption_box(b, labels[other], label_band)
            else:
                band = Box(other, b.x, b.bottom, b.w, label_band)
            crossed = any(
                segment_crosses_box(p, q, band)
                for p, q in zip(polyline, polyline[1:])
            )
            if crossed:
                out.append((e.id, other))
    return sorted(set(out))


#: The label band a BOUNDARY container draws INSIDE its top edge. Unlike a node
#: (caption below the icon), a container renders its name inside the top-left of
#: the group box (``verticalAlign=top;align=left``), so the strip that a routed
#: edge must clear runs from the container's TOP edge DOWN by one text line
#: (~30px = the same one-line floor as ``LABEL_BAND``).
CONTAINER_LABEL_BAND = 30

#: Per-character advance and left inset used to estimate a container caption's
#: horizontal extent from its text. The caption is LEFT-aligned inside the group
#: box (a group badge + ``spacingLeft`` inset, then ~12px text), so a corridor to
#: the RIGHT of the caption text does not cross it even on a very wide box. The
#: estimate is a conservative floor (round up), mirroring how ``LABEL_BAND`` is a
#: one-line floor rather than a per-string measurement.
_CONTAINER_LABEL_CHAR_W = 7.5   # ~advance per char at the 12px caption font
_CONTAINER_LABEL_INSET = 40.0   # group badge + spacingLeft before the text


def _container_caption_width(label: str, box_w: float) -> float:
    """Estimate the caption's horizontal extent, capped at the box width.

    A short caption ("az-a1") stays a narrow left strip; a long one
    ("vpc-passive us-west-2") reaches further right. Never exceeds ``box_w``."""
    est = _CONTAINER_LABEL_INSET + len(label) * _CONTAINER_LABEL_CHAR_W
    return min(box_w, est)


#: Per-character advance used when the caption's real style is known. 12px
#: Helvetica averages ~6.3px; 7.0 is a conservative ceiling (bold ~6.9).
_CAPTION_TEXT_CHAR_W = 7.0
#: draw.io's default ``spacing`` around a label (added to ``spacingLeft``).
_DRAWIO_LABEL_SPACING = 2.0
#: Clearance an edge keeps from either end of the caption text.
_CAPTION_CLEARANCE = 4.0


def _style_value(style: str, key: str) -> Optional[str]:
    m = re.search(rf"(?:^|;){re.escape(key)}=([^;]*)", style or "")
    return m.group(1) if m else None


def caption_text_extent(label: str, style: str, box: "Box") -> Tuple[float, float]:
    """Return the ``(x0, x1)`` model-x extent of a container caption's TEXT.

    Reads the caption's real ``align`` (draw.io default ``center``),
    ``spacingLeft`` / ``spacingRight`` and ``spacing`` from its style, so a
    left-aligned OCI/AWS caption and a centred Azure/GCP caption are both located
    where draw.io actually draws them. Capped to the container's own width.
    """
    text_w = min(box.w, len(label or "") * _CAPTION_TEXT_CHAR_W)
    spacing = float(_style_value(style, "spacing") or _DRAWIO_LABEL_SPACING)
    sl = float(_style_value(style, "spacingLeft") or 0.0) + spacing
    sr = float(_style_value(style, "spacingRight") or 0.0) + spacing
    align = (_style_value(style, "align") or "center").lower()
    if align == "left":
        x0 = box.x + sl
    elif align == "right":
        x0 = box.x + box.w - sr - text_w
    else:
        inner_mid = box.x + sl + (box.w - sl - sr) / 2.0
        x0 = inner_mid - text_w / 2.0
    return x0, x0 + text_w


def vertical_caption_cuts(
    polylines: Sequence[Sequence[Tuple[float, float]]],
    box: "Box",
    band: float = CONTAINER_LABEL_BAND,
) -> List[float]:
    """Return the x of every VERTICAL leg that passes through ``box``'s caption
    strip ``[box.y, box.y + band]`` — the candidates that can cut its text."""
    xs: List[float] = []
    y0, y1 = box.y, box.y + band
    for pl in polylines:
        for p, q in zip(pl, pl[1:]):
            if abs(q[0] - p[0]) > 0.5:
                continue  # not a vertical leg
            lo, hi = min(p[1], q[1]), max(p[1], q[1])
            if hi <= y0 or lo >= y1:
                continue
            if box.x < p[0] < box.x + box.w:
                xs.append(p[0])
    return xs


def free_caption_x0(
    label: str, style: str, box: "Box", cut_xs: Sequence[float]
) -> Optional[float]:
    """Return a caption text start ``x0`` that no ``cut_xs`` leg passes through.

    ``None`` when the caption's current position is already clear. Otherwise the
    nearest clear start to the current one, searched on the grid, rightward for a
    left-aligned caption (it stays left-anchored) and both ways for a centred
    one. Falls back to ``None`` when no clear slot fits inside the box.
    """
    x0, x1 = caption_text_extent(label, style, box)
    text_w = x1 - x0

    def clear(a: float) -> bool:
        return all(
            not (a - _CAPTION_CLEARANCE < cx < a + text_w + _CAPTION_CLEARANCE)
            for cx in cut_xs
        )

    if clear(x0):
        return None
    lo = box.x + _DRAWIO_LABEL_SPACING + GRID
    hi = box.x + box.w - GRID - text_w
    align = (_style_value(style, "align") or "center").lower()
    steps = range(1, int(box.w // GRID) + 1)
    for k in steps:
        for cand in ((x0 + k * GRID,) if align == "left" else (x0 + k * GRID, x0 - k * GRID)):
            if lo <= cand <= hi and clear(cand):
                return cand
    return None


def check_edge_crosses_container_label(
    geo: DiagramGeometry, band: float = CONTAINER_LABEL_BAND
) -> List[Tuple[str, str]]:
    """Return ``(edge_id, container_id)`` for edges whose polyline cuts a
    **container's top label band** — the caption strip a Boundary / Network
    Boundary group draws inside its top edge (``verticalAlign=top``).

    A cross-region corridor placed one grid step above a target VPC can run
    straight along that VPC's top edge, slicing its ``vpc-...`` caption (the
    edge-2 → ``vpc-passive`` defect) — a crossing the node-label check
    (:func:`check_edge_crosses_label`, which measures node captions only) never
    sees. This samples each edge's full polyline against every container's top
    band with the same :func:`segment_crosses_box` predicate.

    An edge legitimately entering or leaving a container touches its border, so a
    container is skipped for an edge whose source **or** target sits inside that
    container's box — only an *unrelated* container's caption is a defect.
    Advisory (WARNING), like ``edge-crosses-label``."""
    out: List[Tuple[str, str]] = []
    nodes = geo.nodes
    for e in geo.edges:
        if e.source not in nodes or e.target not in nodes:
            continue
        s, t = nodes[e.source], nodes[e.target]
        ex = e.exit[0] if e.exit[0] is not None else 1.0
        ey = e.exit[1] if e.exit[1] is not None else 0.5
        nx = e.entry[0] if e.entry[0] is not None else 0.0
        ny = e.entry[1] if e.entry[1] is not None else 0.5
        polyline = [(s.x + ex * s.w, s.y + ey * s.h)]
        polyline += list(e.points)
        polyline += [(t.x + nx * t.w, t.y + ny * t.h)]
        for cid, c in geo.containers.items():
            # The caption is left-aligned: size its width from the real caption
            # text so a corridor RIGHT of the (short) text does not false-flag,
            # while a run slicing a LONG caption still trips.
            label_w = _container_caption_width(geo.container_labels.get(cid, ""), c.w)
            label = Box(cid, c.x, c.y, label_w, band)  # top-left .. +one line
            # A run only defects the caption when a HORIZONTAL segment runs along
            # it. A near-VERTICAL segment that crosses the band is an edge
            # dropping IN through the container's top edge to reach a target
            # inside it (the sanctioned top entry) — not a run along the caption —
            # so it is not flagged. This replaces a membership exemption (which
            # wrongly let a horizontal run along the TARGET's own VPC caption
            # slip): the discriminator is the segment's direction, not which
            # container the endpoints belong to.
            # A run defects the caption only when a HORIZONTAL segment travels
            # ALONG it for a meaningful distance — i.e. the segment's overlap
            # with the caption band's x-extent exceeds a short-step threshold.
            # A near-vertical drop through the top edge (a sanctioned top entry)
            # has ~zero horizontal overlap; a short final entry-approach step that
            # only grazes the caption's right edge (l4/l9 clipping ~7px) is below
            # the threshold; a long run laid along the caption (edge 2, or a
            # cross-region rep line at the caption's y — l11) exceeds it.
            lab_x0, lab_x1 = label.x, label.right
            lab_y0, lab_y1 = label.y, label.bottom
            crossed = False
            for p, q in zip(polyline, polyline[1:]):
                if abs(q[0] - p[0]) <= abs(q[1] - p[1]):
                    continue  # not a horizontal segment
                seg_y = (p[1] + q[1]) / 2.0
                if not (lab_y0 <= seg_y <= lab_y1):
                    continue  # not within the caption's vertical band
                # horizontal overlap of [min,max] segment x with the caption x-extent
                seg_lo, seg_hi = min(p[0], q[0]), max(p[0], q[0])
                overlap = min(seg_hi, lab_x1) - max(seg_lo, lab_x0)
                if overlap > 2 * GRID:
                    crossed = True
                    break
            # 1.10.3: a VERTICAL leg through the caption TEXT cuts it too. The
            # sanctioned top entry drops through the container's top edge, but it
            # must do so beside the caption, not through its letters (edges 1/15
            # slicing the left-aligned ``vpc-primary …`` caption on the OCI
            # landscape). Needs the real style to locate the text, so it applies
            # only to a parsed diagram.
            style = geo.container_styles.get(cid)
            if not crossed and style is not None:
                tx0, tx1 = caption_text_extent(
                    geo.container_labels.get(cid, ""), style, c
                )
                crossed = any(
                    tx0 - _CAPTION_CLEARANCE < cx < tx1 + _CAPTION_CLEARANCE
                    for cx in vertical_caption_cuts([polyline], c, band)
                )
            if crossed:
                out.append((e.id, cid))
    return sorted(set(out))


_TEXT_CELL_RE = re.compile(r'<mxCell\b[^>]*\bstyle="([^"]*text;[^"]*)"[^>]*>', re.I)
_SPACING_TOKENS = ("spacingleft", "spacingright", "spacingtop", "spacingbottom")


def check_text_padding(text: str) -> List[str]:
    """Return the styles of text cells missing uniform inner padding.

    Every ``text;`` cell (Flow / Legend / note box) must set all four
    ``spacing{Left,Right,Top,Bottom}`` tokens so no line abuts the border
    (diagram-standards → text-box padding). A text cell missing any of the four
    is returned (as its style string) so the linter can flag ``text-padding``.
    The diagram *title* cell (``fillColor=none``, no border) is exempt — it has
    no visible box to pad against."""
    out: List[str] = []
    for style in _TEXT_CELL_RE.findall(text or ""):
        low = style.lower()
        # A text cell has a visible box only when it sets BOTH a concrete fill and
        # a concrete stroke color. A borderless cell (no fill/stroke, or an
        # explicit ``none``) — e.g. the diagram title or a free label — has no box
        # to pad and is exempt. Only a filled+stroked box (Flow/Legend/note) must
        # carry uniform inner padding.
        has_fill = bool(re.search(r"fillcolor=#[0-9a-f]{3,8}", low))
        has_stroke = bool(re.search(r"strokecolor=#[0-9a-f]{3,8}", low))
        if not (has_fill and has_stroke):
            continue
        if not all(tok in low for tok in _SPACING_TOKENS):
            out.append(style)
    return out


# --------------------------------------------------------------------------- #
# Route quality cost (v1.6.0)
#
# The routers choose every corridor, lane, and face by RULE, with no view of the
# diagram as a whole — ~25 named patterns in diagram-standards.md, each distilled
# from a hand-edit. That works until two patterns want the same plane, and then
# only a measurement can say which route is better.
#
# Two reviewer hand-edits of the AWS HA landscape (2026-09-26) made the case and
# also pinned down the objective:
#
#   * The first edit removed 2 parallel rails while *adding* a crossing (7 -> 6
#     crossings, 4 -> 2 rails). A crossing-only objective would have rejected it,
#     so rails must be weighted at least as heavily as crossings.
#   * The second edit improved every number at once (3 crossings, 2 rails, 45
#     turns, 10.0k ink against 7 / 4 / 50 / 11.0k), which is what a scored router
#     should be able to find.
#
# A third, decisive experiment: turning on the straight-drop spine route for
# landscapes (it is currently gated to compact diagrams) cuts turns 50 -> 41 and
# ink 11.0k -> 10.5k but raises crossings 7 -> 11. So the choice between two legal
# shapes genuinely varies per edge and per layout — it cannot be settled by
# another fixed rule, only by scoring the alternatives.
#
# This function is that score. It does not choose anything yet; see
# docs/REVIEW.md -> Open gaps for why acting on it needs the contact pipeline
# inverted (contacts are currently decided by eight global passes before any edge
# is routed, so there is no per-edge decision point to score).
# --------------------------------------------------------------------------- #

#: A vertical run must span at least this much to read as a "rail" beside a column
#: rather than a step between adjacent rows (roughly two row steps).
RAIL_MIN_SPAN = 300.0

#: How close a rail may come to an unrelated node's side border before it reads as
#: part of that column. Roughly half a column gap.
RAIL_CLEARANCE = 40.0


def rail_penalty(clearance: float) -> float:
    """Graded penalty for one rail run, by how close it passes an icon.

    This is the module-level penalty *function* (distinct from the
    :attr:`RouteCost.rail_penalty` *field*, which is the sum of this function
    over a diagram's rail runs). It replaces the binary "within
    :data:`RAIL_CLEARANCE`, yes/no" verdict with a value that grades the run:
    a vertical 2px from an icon is the defect a reviewer objects to, while one
    30px away is barely a rail, and the two must not score the same.

    Contract (the required properties — see design Component 4, Property 6):

    * **monotonically non-increasing in clearance** — for clearances
      ``d1 <= d2``, ``rail_penalty(d1) >= rail_penalty(d2)``. A run that passes
      closer is never penalised less than one that passes farther.
    * **zero at and above** :data:`RAIL_CLEARANCE` — ``rail_penalty(d) == 0``
      for every ``d >= RAIL_CLEARANCE``. Once a run clears the threshold it is
      no longer a rail, so it carries no rail penalty (it may still be scored on
      turns/ink elsewhere).

    The concrete curve is a clamped linear ramp
    ``max(0, (RAIL_CLEARANCE - clearance) / RAIL_CLEARANCE)``, chosen against the
    shipped corpus: the only rail runs in the corpus (the four HA landscapes)
    pass at exactly :data:`RAIL_CLEARANCE` (40px), so they sit at the zero end of
    the ramp, and any future run that creeps closer registers a strictly larger
    penalty (``d=20 -> 0.5``, ``d=2 -> 0.95``, ``d=0 -> 1.0``). The exact shape
    is a task detail; only monotonicity and the zero-at-threshold contract are
    required. A negative clearance (a run that has crossed into the node) is
    clamped to the maximum penalty of ``1.0``.
    """
    if clearance >= RAIL_CLEARANCE:
        return 0.0
    if clearance <= 0.0:
        return 1.0
    return (RAIL_CLEARANCE - clearance) / RAIL_CLEARANCE


@dataclass(frozen=True)
class RouteCost:
    """The measured quality of a diagram's edge routing (lower is better).

    Ordered by weight: a crossing or a rail is a legibility defect, while turns and
    ink are economy. ``as_tuple`` gives the comparison key a scored router would
    minimise.
    """

    crossings: int = 0
    rails: int = 0
    rail_penalty: float = 0.0
    turns: int = 0
    ink: float = 0.0
    crossing_pairs: Tuple[Tuple[str, str], ...] = ()
    rail_pairs: Tuple[Tuple[str, str, int, float], ...] = ()
    #: 1.10.6: declared routing rules the diagram breaks (:func:`rule_violations`)
    #: — the linter's ERROR-class findings and its advisory routing WARNINGs.
    rule_errors: int = 0
    rule_warnings: int = 0
    violations: Tuple[Tuple[str, str], ...] = ()

    def as_tuple(self) -> Tuple[int, int, int, float, int, float]:
        """Comparison key: rule errors ≫ rule warnings ≫ crossings ≫ rail_penalty
        ≫ turns ≫ ink.

        1.10.6 puts the declared rules first: a candidate that breaks a rule the
        linter reports (a run through an icon, a sliced caption, a leg leaving its
        container) never beats one that keeps them, however few crossings it has.
        Among rule-clean candidates the order is the 1.8.0 one. The graded
        ``rail_penalty`` (Σ penalty over rail runs, inversely proportional to
        clearance) ranks above turns rather than the binary ``rails`` count, so a
        run 2px from an icon ranks worse than one 30px away even though both are
        within :data:`RAIL_CLEARANCE`. The binary ``rails`` field is retained for
        ratchet readability but is not part of the ordering key.
        """
        return (self.rule_errors, self.rule_warnings, self.crossings,
                round(self.rail_penalty, 3), self.turns, round(self.ink))

    def summary(self) -> str:
        return (
            f"rule_errors={self.rule_errors}  rule_warnings={self.rule_warnings}  "
            f"crossings={self.crossings}  rails={self.rails}  "
            f"rail_penalty={self.rail_penalty:.3f}  "
            f"turns={self.turns}  ink={self.ink / 1000:.1f}k"
        )


def edge_polyline(geo: DiagramGeometry, edge: EdgeGeom) -> List[Point]:
    """Return an edge's full polyline: exit contact, waypoints, entry contact."""
    src, tgt = geo.nodes.get(edge.source), geo.nodes.get(edge.target)
    if src is None or tgt is None or None in edge.exit or None in edge.entry:
        return []
    return (
        [(src.x + edge.exit[0] * src.w, src.y + edge.exit[1] * src.h)]
        + [(x, y) for x, y in edge.points]
        + [(tgt.x + edge.entry[0] * tgt.w, tgt.y + edge.entry[1] * tgt.h)]
    )


def segments_cross(s1: Tuple[Point, Point], s2: Tuple[Point, Point]) -> bool:
    """True when an H segment and a V segment intersect strictly inside both.

    Touching at an endpoint is not a crossing — two edges may legitimately meet at
    a shared trunk corner.
    """
    for (p1, q1), (p2, q2) in ((s1, s2), (s2, s1)):
        if leg_axis(p1, q1) != "H" or leg_axis(p2, q2) != "V":
            continue
        y, x = p1[1], p2[0]
        x0, x1 = sorted((p1[0], q1[0]))
        y0, y1 = sorted((p2[1], q2[1]))
        if x0 + AXIS_EPS < x < x1 - AXIS_EPS and y0 + AXIS_EPS < y < y1 - AXIS_EPS:
            return True
    return False


def route_cost(geo: DiagramGeometry) -> RouteCost:
    """Measure a diagram's routing: crossings, parallel rails, turns, ink.

    * **crossing** — a horizontal segment of one edge properly intersects a
      vertical segment of another. Two edges that share an endpoint are **not**
      exempt: diagram-standards sanctions a *shared trunk* — the two branches
      running together in one stub just outside the node — but the same sentence
      requires that "the branches never overlap". Sharing a trunk makes the
      branches **touch**, and touching is already excluded by
      :func:`segments_cross` (it tests the strict interior of both segments), so
      the trunk needs no exemption of its own. A genuine *crossing* between two
      branches of one fan-out is the defect that pattern exists to prevent: one
      branch's stub cutting through a sibling's turn leg because the two exit
      bands were ordered against their directions of travel. Exempting it hid
      four such crossings per HA landscape from the measurement.
    * **parallel rail** — a vertical run of at least :data:`RAIL_MIN_SPAN` passing
      within :data:`RAIL_CLEARANCE` of an unrelated node's side border, over that
      node's own vertical extent. diagram-standards forbids this outright ("no long
      vertical run parallel to a node column") because it reads as a second rail
      beside the services.
    * **turns** — interior vertices, summed over every edge.
    * **ink** — total Manhattan length of every route.
    """
    polys: Dict[str, List[Point]] = {}
    edges: Dict[str, EdgeGeom] = {}
    turns = 0
    ink = 0.0
    for e in geo.edges:
        poly = edge_polyline(geo, e)
        if len(poly) < 2:
            continue
        polys[e.id] = poly
        edges[e.id] = e
        turns += max(0, len(poly) - 2)
        ink += sum(
            abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(poly, poly[1:])
        )

    crossings = 0
    crossing_pairs: List[Tuple[str, str]] = []
    ids = sorted(polys)
    for a_i in range(len(ids)):
        for b_i in range(a_i + 1, len(ids)):
            i, j = ids[a_i], ids[b_i]
            n = sum(
                1
                for s1 in zip(polys[i], polys[i][1:])
                for s2 in zip(polys[j], polys[j][1:])
                if segments_cross(s1, s2)
            )
            if n:
                crossings += n
                crossing_pairs.append((i, j))

    # Each rail run records ``(eid, nid, span, clearance)`` — the clearance
    # (nearest gap between the vertical run and the node's side border) is kept
    # so a ``--detail`` view can display it and so the graded ``rail_penalty``
    # is summed from the *same* detection that produces the binary ``rails``
    # count. The two therefore stay consistent by construction: a run that is
    # counted as a binary rail (``clearance <= RAIL_CLEARANCE``) is the same run
    # whose graded :func:`rail_penalty` is added to ``rail_penalty_total`` — the
    # summed field, not the module-level function it calls.
    rail_pairs: List[Tuple[str, str, int, float]] = []
    rail_penalty_total = 0.0
    seen = set()
    for eid, poly in polys.items():
        e = edges[eid]
        for a, b in zip(poly, poly[1:]):
            if leg_axis(a, b) != "V" or abs(b[1] - a[1]) < RAIL_MIN_SPAN:
                continue
            lo, hi = sorted((a[1], b[1]))
            for nid, box in sorted(geo.nodes.items()):
                if nid in (e.source, e.target) or box.bottom < lo or box.y > hi:
                    continue
                clearance = min(abs(a[0] - box.x), abs(a[0] - box.right))
                if clearance <= RAIL_CLEARANCE:
                    if (eid, nid) not in seen:
                        seen.add((eid, nid))
                        rail_pairs.append(
                            (eid, nid, int(abs(b[1] - a[1])), float(clearance))
                        )
                        rail_penalty_total += rail_penalty(float(clearance))

    errors, warnings = rule_violations(geo)
    return RouteCost(
        crossings=crossings,
        rails=len(rail_pairs),
        rail_penalty=rail_penalty_total,
        turns=turns,
        ink=ink,
        crossing_pairs=tuple(crossing_pairs),
        rail_pairs=tuple(rail_pairs),
        rule_errors=len(errors),
        rule_warnings=len(warnings),
        violations=errors + warnings,
    )


def check_edge_approach(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for routes whose legs are not axis-aligned.

    Three conditions, all of them about the source **fully determining** the drawn
    path rather than leaving it to draw.io:

    * ``diagonal-leg`` — two consecutive points are not axis-aligned. An
      ``orthogonalEdgeStyle`` edge never draws a diagonal: draw.io inserts its own
      corner and **picks the direction**, so an unaligned pair is a corner the
      author did not specify. That is how an edge ends up grazing a glyph or
      sliding along a container border even though every waypoint looked
      deliberate — and it is invisible to every other check, which reads the
      points as given.
    * ``exit-leg-<axis>`` — the leg leaving the source does not meet the exit face
      head-on (a right/left face is met horizontally, a top/bottom face
      vertically).
    * ``entry-leg-<axis>`` — the same for the leg arriving at the target. The
      canonical defect is a horizontal leg running **along** a node's top border
      into a top-centre entry, so the arrowhead slides across the glyph's edge
      instead of dropping into it.

    A corner contact lies on two faces and accepts either axis, so it is not
    constrained. An edge with no waypoints is a single straight run and is skipped,
    as is an edge that floats a contact (``edge-float`` owns that).
    """
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        src, tgt = geo.nodes.get(e.source), geo.nodes.get(e.target)
        if src is None or tgt is None or not e.points:
            continue
        if None in e.exit or None in e.entry:
            continue
        poly = (
            [(src.x + e.exit[0] * src.w, src.y + e.exit[1] * src.h)]
            + [(x, y) for x, y in e.points]
            + [(tgt.x + e.entry[0] * tgt.w, tgt.y + e.entry[1] * tgt.h)]
        )
        legs = [leg_axis(a, b) for a, b in zip(poly, poly[1:])]
        if "D" in legs:
            out.append((e.id, "diagonal-leg"))
        want_exit = required_leg_axis(contact_faces(*e.exit))
        if want_exit and legs[0] not in (want_exit, "0"):
            out.append((e.id, f"exit-leg-{legs[0]}-want-{want_exit}"))
        want_entry = required_leg_axis(contact_faces(*e.entry))
        if want_entry and legs[-1] not in (want_entry, "0"):
            out.append((e.id, f"entry-leg-{legs[-1]}-want-{want_entry}"))
    return out


def check_edge_crosses_container(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, container_id)`` for edges whose route passes THROUGH a
    Boundary container that neither endpoint belongs to.

    An edge between two nodes that are both OUTSIDE a container (or one just
    outside it) must route AROUND that container, not straight through its
    interior. The canonical defect: a fan-out from a VPC-scoped node to a
    regional node outside the VPC (GCP ``train → hub``) dipped into the VPC's
    below-row band and ran across the VPC interior, slicing the box and its
    inner nodes' captions. ``edge-crosses-container-label`` only guards the top
    caption strip; this guards the whole interior.

    An edge is exempt for a container it legitimately enters or leaves — i.e.
    one whose ``source`` or ``target`` node sits inside that container's box.
    Every OTHER container the polyline's interior segments cut is a finding.
    Advisory (WARNING)."""
    out: List[Tuple[str, str]] = []
    nodes = geo.nodes

    def _inside(box: Box, c: Box) -> bool:
        return c.x <= box.x and box.x + box.w <= c.right and \
            c.y <= box.y and box.y + box.h <= c.bottom

    for e in geo.edges:
        if e.source not in nodes or e.target not in nodes:
            continue
        if None in e.exit or None in e.entry:
            continue
        s, t = nodes[e.source], nodes[e.target]
        poly = (
            [(s.x + e.exit[0] * s.w, s.y + e.exit[1] * s.h)]
            + [(x, y) for x, y in e.points]
            + [(t.x + e.entry[0] * t.w, t.y + e.entry[1] * t.h)]
        )
        for cid, c in geo.containers.items():
            # Skip a container either endpoint belongs to (a legitimate crossing
            # of its border to enter/leave), or a nested parent of such a box.
            if _inside(s, c) or _inside(t, c):
                continue
            # Also skip a container that CONTAINS another container holding an
            # endpoint (an edge leaving an AZ legitimately crosses its VPC).
            if any(cid != oid and (_inside(s, o) or _inside(t, o))
                   and c.x <= o.x and o.right <= c.right
                   and c.y <= o.y and o.bottom <= c.bottom
                   for oid, o in geo.containers.items()):
                continue
            if any(segment_crosses_box(p, q, c, inset=GRID)
                   for p, q in zip(poly, poly[1:])):
                out.append((e.id, cid))
    return sorted(set(out))


#: How close (model units) a long edge leg may sit to a container border before
#: it reads as riding ON that border. The corpus defect sat 2px off a
#: non-grid-aligned border (a grid-aligned corridor at 730 beside a region right
#: edge at 728); 4px catches that with headroom without flagging a leg a clean
#: grid step (10px) away in the gap beside the box.
_BORDER_RIDE_TOL = 4.0

#: A leg shorter than this is a stub, not a "long run" that reads as a rail
#: alongside a border. Matches the STAIR_STEP the routers use (three grid steps).
_BORDER_RIDE_MIN_LEN = 3 * GRID


def check_edge_on_container_border(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, "<container>.<side>")`` for edges with a **long,
    axis-aligned leg that coincides with a container border** it does not belong
    to.

    A run sitting exactly on (or a hair beside) a Boundary box edge reads as part
    of that edge — the diagram-standards rule *"A long vertical never coincides
    with a container border"*. The canonical defect is a grid-aligned vertical
    corridor allocated at ``source_right + GRID`` that lands ~2px past a
    container whose right edge is **not** grid-aligned (a region box ending at
    728 while the corridor snaps to 730). The router's ``CorridorAllocator``
    only avoids other *edges*, not container borders, so nothing prevented it
    before; this check makes the defect visible and regression-proof.

    A leg is judged only when it is **long** (≥ :data:`_BORDER_RIDE_MIN_LEN`) and
    its constant coordinate lies within :data:`_BORDER_RIDE_TOL` of a container's
    left/right (vertical leg) or top/bottom (horizontal leg) edge, and the leg's
    extent overlaps that border's extent.

    Note this is a **parallel-ride** test, not a crossing test: a long *vertical*
    leg is compared only against *vertical* (left/right) borders, a long
    *horizontal* leg only against *horizontal* (top/bottom) borders. A leg that
    merely crosses a border perpendicularly (to enter or leave a container) runs
    across it, not along it, so it is never flagged — which is why, unlike
    ``edge-crosses-container``, there is no endpoint-inside exemption: a run
    *parallel* to and coincident with a border reads as part of that border even
    when one endpoint sits inside the box (the ``hub → obj`` fan-out whose drop
    lane hugged the region's right edge while ``hub`` sat inside the region).
    Advisory (WARNING)."""
    nodes = geo.nodes
    out: List[Tuple[str, str]] = []

    for e in geo.edges:
        if e.source not in nodes or e.target not in nodes:
            continue
        if None in e.exit or None in e.entry:
            continue
        s, t = nodes[e.source], nodes[e.target]
        poly = (
            [(s.x + e.exit[0] * s.w, s.y + e.exit[1] * s.h)]
            + [(x, y) for x, y in e.points]
            + [(t.x + e.entry[0] * t.w, t.y + e.entry[1] * t.h)]
        )
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            vertical = abs(x0 - x1) < 1 and abs(y1 - y0) >= _BORDER_RIDE_MIN_LEN
            horizontal = abs(y0 - y1) < 1 and abs(x1 - x0) >= _BORDER_RIDE_MIN_LEN
            if not (vertical or horizontal):
                continue
            for cid, c in geo.containers.items():
                if vertical:
                    lo, hi = sorted((y0, y1))
                    if hi < c.y or lo > c.bottom:
                        continue
                    if abs(x0 - c.x) <= _BORDER_RIDE_TOL:
                        out.append((e.id, f"{cid}.left"))
                    elif abs(x0 - c.right) <= _BORDER_RIDE_TOL:
                        out.append((e.id, f"{cid}.right"))
                else:
                    lo, hi = sorted((x0, x1))
                    if hi < c.x or lo > c.right:
                        continue
                    if abs(y0 - c.y) <= _BORDER_RIDE_TOL:
                        out.append((e.id, f"{cid}.top"))
                    elif abs(y0 - c.bottom) <= _BORDER_RIDE_TOL:
                        out.append((e.id, f"{cid}.bottom"))
    return sorted(set(out))


def check_node_connectivity(geo: DiagramGeometry) -> List[str]:
    """Return ids of role-bearing nodes drawn with **no incident edge**.

    A diagram is an architecture, not an inventory listing, when its nodes are
    related to one another. A node with zero incident edges tells the reader
    nothing about how it participates — and when two thirds of the nodes float,
    the picture has stopped being a diagram. This was the headline finding of the
    2026-09-25 audit: every one of the four HA landscape examples drew **34 nodes
    joined by 12 edges, leaving 20 nodes entirely unconnected** (the same 20 ids
    on all four providers, since they share one spec).

    Two categories are legitimately exempt:

    * **Boundary containers** — an Account / VPC / AZ frame is a grouping device,
      not a participant. They are already absent from ``geo.nodes``, and text
      cells (Flow / Legend / title) likewise.
    * **Overlay-marked nodes** — a node carrying an overlay marker
      (``overlay=<term>``, e.g. a ``standby`` passive peer) is *declaring* why it
      has no edges, double-encoded and documented in the Legend. That is the
      sanctioned way to draw a symmetric mirror tier without duplicating every
      edge into it.

    Pure topology (node ids minus the union of edge endpoints), so it is cheap and
    independent of layout.
    """
    endpoints: set[str] = set()
    for e in geo.edges:
        if e.source:
            endpoints.add(e.source)
        if e.target:
            endpoints.add(e.target)
    return sorted(
        nid
        for nid in geo.nodes
        if nid not in endpoints and nid not in geo.overlay_nodes
    )


# Calibrated dead-space threshold (placement-and-gates task 8). Measured across
# the 57 shipped corpus containers: the sparsest legitimate container packs at a
# ratio of 4.536 (container area / summed direct-child footprint+padding demand).
# The threshold is set to 5.0 — above the sparsest tier with headroom — so that
# 0 of 57 shipped containers flag. A container above this is sized far larger
# than its children legitimately demand: the opposite defect from
# ``container-padding`` (which checks the *minimum* clearance).
DEAD_SPACE_RATIO = 5.0

# The tighter dead-space threshold for an OUTER (top-level) Boundary — a
# container no other container encloses: the Account / Subscription / Project box
# (or, where a diagram draws no account, its region boxes). Calibrated in 1.10.7
# across the shipped corpus at 7.0px/char: the sparsest top-level container is
# the HA summary's region box at 2.08 (top-level because the summary draws no
# account); account boxes peak at 1.36 (oci/01; aws/01 = 1.05; the aws/03
# on-premises group = 1.94). The 1.10.0 quick run that shipped an account box
# with a large empty zone measured 4.04 (summary) and 3.71 (landscape) — both
# under the inner 5.0 threshold, which is why that defect linted clean. 2.5 sits
# above every legitimate corpus outer box with headroom and below both quick
# boxes. Inner (nested) containers keep :data:`DEAD_SPACE_RATIO`, whose 4.536
# sparsest legitimate tier is a nested box.
OUTER_DEAD_SPACE_RATIO = 2.5


def check_container_dead_space(
    geo: DiagramGeometry,
    pad: int = CONTAINER_PAD,
    threshold: float = DEAD_SPACE_RATIO,
    label_band: float = LABEL_BAND,
    outer_threshold: Optional[float] = OUTER_DEAD_SPACE_RATIO,
) -> List[Tuple[str, float]]:
    """Return ``(container_id, ratio)`` for containers with excessive dead space.

    The mirror of :func:`check_container_padding`: where padding checks the
    *minimum* clearance a container leaves its children, this checks the
    *maximum* slack. For each Boundary container the ratio measured is

        ratio = container_area / Σ(direct-child footprint grown by ``pad`` on all 4 sides)

    A **direct child** is a node or nested container whose *tightest* enclosing
    container is this one (mirrors :func:`_tightest_enclosing`), so a node inside
    a nested AZ counts against the AZ, and the VPC counts the AZ (a nested
    container) as its child — exactly as ``check_container_padding`` attributes
    padding per parent tier. A node's demand is its **footprint** (icon + label
    band) grown by ``pad``; a nested container's demand is its own box grown by
    ``pad``. Summing that lower-bound demand and dividing the container's actual
    area by it yields a dead-space ratio: ~1.0 means packed to the mandated
    minimum, a large ratio means sized far larger than its children need.

    A container **with no direct children is skipped** (a childless container is
    not "dead space around children", and the ratio would divide by zero). The
    threshold defaults to the calibrated :data:`DEAD_SPACE_RATIO`, above the
    sparsest legitimate corpus tier so no Shipped_Diagram false-positives. Pure
    function of the parsed geometry; advisory (never blocks on its own).

    An **outer** container — one no other container encloses
    (``_tightest_enclosing(c, others) is None``) — is judged against the tighter
    ``outer_threshold`` (:data:`OUTER_DEAD_SPACE_RATIO`, 1.10.7): the outermost
    Boundary is what the reader sees first, and an account box with a large
    empty zone suggests missing content. ``outer_threshold=None`` applies
    ``threshold`` to every container (the pre-1.10.7 behaviour).
    """
    boxes = list(geo.containers.values())
    out: List[Tuple[str, float]] = []
    for cbox in boxes:
        limit = threshold
        if outer_threshold is not None and _tightest_enclosing(cbox, boxes) is None:
            limit = outer_threshold
        demand = 0.0
        # Nodes whose tightest enclosing container is this one (by footprint).
        for node in geo.nodes.values():
            fp = node.footprint(label_band)
            parent = _tightest_enclosing(fp, boxes)
            if parent is not None and parent.id == cbox.id:
                demand += (fp.w + 2 * pad) * (fp.h + 2 * pad)
        # Nested containers whose tightest enclosing container is this one.
        for child in boxes:
            if child.id == cbox.id:
                continue
            parent = _tightest_enclosing(child, boxes)
            if parent is not None and parent.id == cbox.id:
                demand += (child.w + 2 * pad) * (child.h + 2 * pad)
        if demand <= 0:
            # No direct children — skip, never divide by zero (design Error
            # Handling: a container with no children is skipped).
            continue
        ratio = (cbox.w * cbox.h) / demand
        if ratio > limit:
            out.append((cbox.id, ratio))
    return out


def is_outer_container(geo: DiagramGeometry, cid: str) -> bool:
    """Return True when no other container encloses container ``cid``."""
    boxes = list(geo.containers.values())
    box = geo.containers.get(cid)
    return box is not None and _tightest_enclosing(box, boxes) is None


# --------------------------------------------------------------------------- #
# Container style (1.10.7): a Boundary drawn in its provider's declared style
# --------------------------------------------------------------------------- #

#: Style tokens that identify WHICH declared container a drawn box is (its
#: shape signature). A box whose signature matches no declared container is
#: unrecognised and skipped — the rule judges colour, not invention. The
#: signature carries the non-colour line and caption tokens too (dash pattern,
#: stroke width, caption alignment): with only shape/rounded/dashed/fill, every
#: plain dashed borderless rectangle — a bespoke functional group, an overlay
#: box — was taken for AWS's AZ box and judged against its colours.
_CONTAINER_SIGNATURE_TOKENS = (
    "shape",
    "image",
    "rounded",
    "dashed",
    "fillColor",
    "dashPattern",
    "strokeWidth",
    "align",
    "verticalAlign",
)
#: Style tokens whose value must equal the declared container's (the colour).
_CONTAINER_COLOUR_TOKENS = ("strokeColor", "fontColor")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{3,8}$")


def _style_tokens(style: str) -> Dict[str, str]:
    """Parse a draw.io style into ``{key: value}`` (bare flags map to ``""``)."""
    out: Dict[str, str] = {}
    for part in (style or "").split(";"):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        out[key.strip()] = value.strip() if sep else ""
    return out


def _norm_token(value: Optional[str]) -> Optional[str]:
    """Normalise a token value for comparison (hex colours case-insensitively)."""
    if value is None:
        return None
    return value.lower() if _HEX_RE.match(value) else value


def check_container_style(
    geo: DiagramGeometry,
    providers: Sequence[str],
    mappings: Mapping[str, Mapping[str, Any]],
) -> List[Tuple[str, str]]:
    """Return ``(container_id, reason)`` for containers drawn off their declared colour.

    ``mappings`` is ``{provider: <containers table of mappings/<provider>-icons.yaml>}``;
    ``providers`` the profiles the diagram may use (its title's provider, or all
    five for a multi-cloud title). Recognition, per drawn container style:

    * a style carrying ``grIcon=`` is an AWS group: the candidates are every
      ``aws`` container kind whose declared style names the same ``grIcon``
      (narrowed by equal ``fillColor`` when several share one, e.g. the private
      and public subnet groups);
    * any other style is matched by its shape signature — equal ``shape``,
      ``image``, ``rounded``, ``dashed``, ``fillColor``, ``dashPattern``,
      ``strokeWidth``, ``align`` and ``verticalAlign`` (an absent token equals
      only an absent token) — against every declared kind of ``providers``.

    A cell carrying an ``overlay=`` token (``spec-required-not-deployed``,
    ``observability-overlay``, …) is an overlay marker, not a Boundary, and is
    never judged. No candidate → the container is unrecognised and skipped. Otherwise it
    passes when ANY candidate's declared ``strokeColor`` and ``fontColor`` (only
    the tokens the declared style defines; hex compared case-insensitively)
    equal the drawn ones; a failure is reported against the closest candidate
    (fewest differing colour tokens, first on a tie) as
    ``'<provider>.<kind>:strokeColor expected <exp> got <act>[; fontColor …]'``.
    Pure; lint-only (not part of :func:`rule_violations`)."""
    out: List[Tuple[str, str]] = []
    declared: List[Tuple[str, str, Dict[str, str]]] = []
    for provider in sorted(mappings):
        for kind, entry in sorted((mappings.get(provider) or {}).items()):
            style = entry.get("style") if isinstance(entry, Mapping) else None
            if isinstance(style, str) and style:
                declared.append((provider, kind, _style_tokens(style)))
    for cid in sorted(geo.container_styles):
        drawn = _style_tokens(geo.container_styles[cid])
        if "overlay" in drawn:
            # An overlay marker draws a dashed box in its own vocabulary colour
            # (diagram-standards → Overlay Vocabulary); it is not a container.
            continue
        gr = drawn.get("grIcon")
        if gr is not None:
            cands = [d for d in declared if d[0] == "aws" and d[2].get("grIcon") == gr]
            if len(cands) > 1:
                fill = _norm_token(drawn.get("fillColor"))
                narrowed = [d for d in cands if _norm_token(d[2].get("fillColor")) == fill]
                if narrowed:
                    cands = narrowed
        else:
            cands = [
                d
                for d in declared
                if d[0] in providers
                and "grIcon" not in d[2]
                and all(
                    _norm_token(d[2].get(t)) == _norm_token(drawn.get(t))
                    for t in _CONTAINER_SIGNATURE_TOKENS
                )
            ]
        if not cands:
            continue
        failures: List[str] = []
        for provider, kind, tokens in cands:
            diffs = [
                f"{t} expected {tokens[t]} got {drawn.get(t, '<none>')}"
                for t in _CONTAINER_COLOUR_TOKENS
                if t in tokens and _norm_token(tokens[t]) != _norm_token(drawn.get(t))
            ]
            if not diffs:
                failures = []
                break
            failures.append(f"{provider}.{kind}:" + "; ".join(diffs))
        if failures:
            # Name the closest candidate (fewest differing colour tokens; the
            # first in declaration order on a tie) — several providers share
            # one dashed-rectangle signature on a multi-cloud diagram.
            out.append((cid, min(failures, key=lambda f: f.count(" expected "))))
    return out


# --------------------------------------------------------------------------- #
# Route orthogonalisation (v1.6.0)
#
# An ``orthogonalEdgeStyle`` edge never draws a diagonal. When two consecutive
# points of a route are not axis-aligned, draw.io inserts its own corner and
# **chooses which way it turns** — so a diagonal pair in the source is not a
# diagonal on screen, it is a corner the author did not specify. That is how an
# edge ends up grazing a glyph or sliding along a container border even though
# every waypoint looked deliberate.
#
# Measured across the shipped corpus before v1.6.0, 30 routed edges had such an
# unaligned leg at one or both ends: each router computed its corridor correctly
# but emitted the waypoint adjacent to a contact from the *corridor's* coordinates
# rather than the *contact's*. These helpers rewrite a finished polyline so every
# leg is explicitly H or V and both contact legs meet their face head-on, which
# moves the corner decision into the source where the geometry checks can see it.
#
# They live here, in pure geometry, because both artifact paths need them: the
# lane-grid layout engine (which routes) and the shared diagram builder (which
# renders hand-authored waypoint literals).
# --------------------------------------------------------------------------- #

Point = Tuple[float, float]

#: Tolerance for calling a leg axis-aligned. Contacts are grid-resolved, so a real
#: misalignment is >= one grid step; anything under half a pixel is float noise.
AXIS_EPS = 0.5

#: Outward normal of each contact face as a ``(dx, dy)`` sign pair. The approach
#: lane for a face sits one grid step along this normal — you meet a **top** entry
#: from above, a **left** entry from the left — so the side is a property of the
#: face, never of where the route happens to arrive from.
_FACE_NORMAL = {
    "top": (0, -1),
    "bottom": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def snap(value: float, grid: int = GRID) -> int:
    """Round ``value`` to the nearest whole ``grid`` multiple."""
    return int(round(value / grid) * grid)


def leg_axis(p: Point, q: Point) -> str:
    """Classify a leg: ``"H"``, ``"V"``, ``"0"`` (degenerate) or ``"D"`` (diagonal)."""
    dx, dy = abs(q[0] - p[0]), abs(q[1] - p[1])
    if dx < AXIS_EPS and dy < AXIS_EPS:
        return "0"
    if dy < AXIS_EPS:
        return "H"
    if dx < AXIS_EPS:
        return "V"
    return "D"


def required_leg_axis(faces: frozenset[str]) -> Optional[str]:
    """Return the leg axis that meets a contact face head-on.

    A right/left face is met by a **horizontal** leg, a top/bottom face by a
    **vertical** one. A corner lies on two faces and accepts either, so it returns
    ``None`` — no constraint.
    """
    horizontal = bool(faces & {"left", "right"})
    vertical = bool(faces & {"top", "bottom"})
    if horizontal and not vertical:
        return "H"
    if vertical and not horizontal:
        return "V"
    return None


def _face_normal(faces: frozenset[str], want: str) -> Tuple[int, int]:
    """Return the outward normal of the face that ``want`` must be met through."""
    for name in (("top", "bottom") if want == "V" else ("left", "right")):
        if name in faces:
            return _FACE_NORMAL[name]
    return (0, -1) if want == "V" else (-1, 0)


def collapse_collinear(pts: Sequence[Point]) -> List[Point]:
    """Drop midpoints that share an axis with both neighbours.

    Three consecutive points on one x (or one y) describe a single straight run, so
    the middle one is redundant. This also removes a **backtrack** — a point that
    overshoots and returns along the same axis — which is what turns a router's
    ``(1290, 270) → (1290, 410) → (1290, 380)`` overshoot into the one clean run
    ``(1290, 270) → (1290, 380)``.
    """
    out: List[Point] = []
    for p in pts:
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            same_x = abs(a[0] - b[0]) < AXIS_EPS and abs(b[0] - p[0]) < AXIS_EPS
            same_y = abs(a[1] - b[1]) < AXIS_EPS and abs(b[1] - p[1]) < AXIS_EPS
            if same_x or same_y:
                out[-1] = p
                continue
        if out and leg_axis(out[-1], p) == "0":
            continue  # duplicate point
        out.append(p)
    return out


def insert_orthogonal_corners(
    pts: Sequence[Point], first_axis: Optional[str]
) -> List[Point]:
    """Insert a corner wherever two consecutive points are diagonal.

    The corner continues along the **current** axis and then turns, so the route
    reads as a stair rather than a kink: after a horizontal run the corner is
    ``(q.x, p.y)``; after a vertical run, ``(p.x, q.y)``. ``first_axis`` seeds the
    current axis from the exit face, so the first leg leaves perpendicular to the
    face it exits.
    """
    pts = list(pts)
    if len(pts) < 2:
        return pts
    out: List[Point] = [pts[0]]
    axis = first_axis or leg_axis(pts[0], pts[1])
    if axis not in ("H", "V"):
        axis = "H"
    for q in pts[1:]:
        p = out[-1]
        kind = leg_axis(p, q)
        if kind == "0":
            continue
        if kind == "D":
            out.append((q[0], p[1]) if axis == "H" else (p[0], q[1]))
            out.append(q)
            axis = "V" if axis == "H" else "H"
            continue
        out.append(q)
        axis = kind
    return out


def force_contact_axis(
    pts: Sequence[Point],
    want: Optional[str],
    *,
    at_end: bool,
    faces: frozenset[str] = frozenset(),
    grid: int = GRID,
) -> List[Point]:
    """Make the leg touching a contact perpendicular to its face.

    When that leg runs *along* the face instead of into it, the arrow slides across
    the glyph's border to reach its contact point rather than meeting it head-on —
    the canonical defect being a horizontal leg running along a node's **top**
    border into a top-centre entry. The fix inserts an approach lane one grid step
    outside the face and turns there, so the final leg drops (or steps) straight
    into the contact.
    """
    out = list(pts)
    if want is None or len(out) < 2:
        return out
    contact = out[-1] if at_end else out[0]
    neighbour = out[-2] if at_end else out[1]
    if leg_axis(neighbour, contact) == want:
        return out
    nx, ny = _face_normal(faces, want)
    if want == "V":
        lane_y = snap(contact[1] + ny * grid, grid)
        lane, pulled = (contact[0], lane_y), (neighbour[0], lane_y)
    else:
        lane_x = snap(contact[0] + nx * grid, grid)
        lane, pulled = (lane_x, contact[1]), (lane_x, neighbour[1])
    if at_end:
        out[-2] = pulled
        out.insert(-1, lane)
    else:
        out[1] = pulled
        out.insert(1, lane)
    return out


def stretch_contact_approach(
    pts: Sequence[Point],
    want: Optional[str],
    *,
    at_end: bool,
    faces: frozenset[str] = frozenset(),
    step: int = STAIR_STEP,
    grid: int = GRID,
) -> List[Point]:
    """Ensure the head-on leg touching a contact is at least ``step`` long.

    ``force_contact_axis`` guarantees the final/first leg is perpendicular to the
    face; this guarantees it is a proper **stair** and not a stub. A perpendicular
    approach shorter than ``STAIR_STEP`` reads as the arrow starting inside the
    glyph (a 10px drop into ``obj``/``ingest`` on the GenAI pipeline). It moves the
    turn point (the neighbour of the contact) out along the leg's own axis so the
    contact leg spans ``step``, then relies on the surrounding
    ``insert_orthogonal_corners`` / ``collapse_collinear`` passes to re-align the
    leg feeding that turn. A leg already ``>= step`` (or one that is not
    perpendicular — ``force_contact_axis`` owns that) is left unchanged, so a
    correct route comes back untouched.
    """
    out = list(pts)
    if want is None or len(out) < 2:
        return out
    ci = len(out) - 1 if at_end else 0
    ni = len(out) - 2 if at_end else 1
    contact, neighbour = out[ci], out[ni]
    if leg_axis(neighbour, contact) != want:
        return out  # not head-on; force_contact_axis handles that first
    # The turn is only free to move when the leg feeding it is perpendicular (a
    # real corner). Moving it would otherwise slide a straight run sideways and
    # change the whole path shape — the byte-stable synthetic routes and any
    # node-free contact. So require a further point and a perpendicular feeder.
    fi = ni - 1 if at_end else ni + 1
    if not 0 <= fi < len(out):
        return out
    feeder = out[fi]
    perp = "H" if want == "V" else "V"
    if leg_axis(feeder, neighbour) != perp:
        return out
    nx, ny = _face_normal(faces, want)
    if want == "V":
        if abs(neighbour[1] - contact[1]) >= step:
            return out
        moved = (neighbour[0], snap(contact[1] + ny * step, grid))
        # Only stretch when the feeder leg (the perpendicular run into the turn)
        # is itself at least one stair long, so moving the turn cannot create a
        # sub-stair zig-zag near the contact (the e9 kink: a 10px feeder that the
        # stretch then split into two 10px legs). A turn fed by a short leg is
        # left where it is — the approach is short but clean.
        if abs(feeder[0] - neighbour[0]) < step:
            return out
        out[ni] = moved
    else:
        if abs(neighbour[0] - contact[0]) >= step:
            return out
        moved = (snap(contact[0] + nx * step, grid), neighbour[1])
        if abs(feeder[1] - neighbour[1]) < step:
            return out
        out[ni] = moved
    return out


def grid_resolve_contact(
    box: "Box", frac: Tuple[float, float], grid: int = GRID
) -> Tuple[Point, Tuple[float, float]]:
    """Return ``(absolute point, adjusted fraction)`` with the contact on the grid.

    A hand-written fraction such as ``0.25`` on a 78px icon resolves to
    ``y0 + 19.5`` — half a pixel off the grid every waypoint snaps to. Aligning a
    snapped waypoint to that contact would leave a permanent kink, which is the
    skew that makes an arrowhead look bent.

    Only the **along-face** coordinate is snapped, never the face coordinate. For a
    left/right face the leg meeting it is horizontal, so only its ``y`` has to sit
    on the grid; for a top/bottom face, only its ``x``. Snapping the face
    coordinate as well would pull the contact *inside* the glyph whenever the icon
    is not grid-commensurate — a 64px icon at ``x=540`` has its right edge at 604,
    and rounding that to 600 moves the contact off its own face, silently breaking
    the directional contract. A *band* pin that lies on no face has no face
    coordinate to protect, so both axes are snapped.
    """
    fx, fy = frac
    ax, ay = box.x + fx * box.w, box.y + fy * box.h
    faces = contact_faces(fx, fy)
    if faces & {"left", "right"}:
        ay = snap(ay, grid)
    elif faces & {"top", "bottom"}:
        ax = snap(ax, grid)
    else:
        ax, ay = snap(ax, grid), snap(ay, grid)
    nfx = (ax - box.x) / box.w if box.w else fx
    nfy = (ay - box.y) / box.h if box.h else fy
    return (ax, ay), (nfx, nfy)


def orthogonalise_route(
    exit_abs: Point,
    points: Sequence[Point],
    entry_abs: Point,
    exit_faces: frozenset[str],
    entry_faces: frozenset[str],
    grid: int = GRID,
) -> List[Point]:
    """Return ``points`` rewritten so every leg of the route is axis-aligned.

    Three passes: insert the corners the source left implicit
    (:func:`insert_orthogonal_corners`), collapse redundant midpoints and
    backtracks (:func:`collapse_collinear`), then force both contact legs
    perpendicular to their faces (:func:`force_contact_axis`) — re-running the
    first two so a newly inserted approach lane is itself aligned.

    Returns the **interior** waypoints only (the contacts are stored separately by
    every caller). Pure and deterministic: the same route always yields the same
    rewrite, and a route that is already orthogonal with perpendicular contact legs
    comes back unchanged.
    """
    pts: List[Point] = [tuple(exit_abs)] + [tuple(p) for p in points] + [tuple(entry_abs)]
    pts = insert_orthogonal_corners(pts, required_leg_axis(exit_faces))
    pts = collapse_collinear(pts)
    pts = force_contact_axis(
        pts, required_leg_axis(entry_faces), at_end=True, faces=entry_faces, grid=grid
    )
    pts = force_contact_axis(
        pts, required_leg_axis(exit_faces), at_end=False, faces=exit_faces, grid=grid
    )
    # Both contact legs now meet their face head-on; grow either that is a stub
    # shorter than one stair, so the arrow steps cleanly into the glyph instead
    # of starting inside it. Re-run the corner/collapse passes so the leg feeding
    # the moved turn stays aligned.
    pts = stretch_contact_approach(
        pts, required_leg_axis(entry_faces), at_end=True, faces=entry_faces, grid=grid
    )
    pts = stretch_contact_approach(
        pts, required_leg_axis(exit_faces), at_end=False, faces=exit_faces, grid=grid
    )
    pts = insert_orthogonal_corners(pts, required_leg_axis(exit_faces))
    pts = collapse_collinear(pts)
    return [(snap(x, grid), snap(y, grid)) for x, y in pts[1:-1]]


#: The headings that mark a text cell as the diagram's Flow/Legend furniture.
#: Matched on the box's FIRST rendered line, which diagram-standards already
#: pins exactly ("Has a value whose first line is exactly ``Flow``").
LEGEND_HEADINGS = frozenset({"flow", "legend"})


def check_legend_placement(
    geo: DiagramGeometry, grid: int = GRID
) -> List[Tuple[str, str]]:
    """Return ``(cell_id, reason)`` for Flow/Legend boxes outside the right margin.

    diagram-standards (*Reserve the right margin for Flow/Legend, clear of the
    cloud*) puts the ``Flow`` and ``Legend`` blocks in the **right margin**, their
    left edge at least one grid step **past the outermost container's right
    edge** — never overlapping the account/VPC boxes and never parked in the left
    margin under the actor column.

    Nothing enforced this before v1.6.0, and it showed: a clean-room install drew
    an otherwise-clean AWS diagram with both blocks stacked in the **left** margin
    below the external user, while every shipped golden (built through
    ``diagram_layout.build_diagram``) puts them on the right. The rule is the
    difference between a convention the builder happens to follow and one an agent
    hand-authoring a diagram must follow too.

    Three conditions are reported:

    * ``left-of-diagram-body`` — the box's left edge is not at least one grid step
      past the outermost container's right edge.
    * ``overlaps-<container-id>`` — the box's rectangle intersects a boundary
      container, i.e. the furniture is drawn on top of the cloud.
    * ``overlaps-node-<node-id>`` (1.10.7) — the box's rectangle intersects a
      node's icon or its caption rectangle (:func:`node_caption_box`, sized from
      the label text), i.e. the furniture hides a node. The quick summary drew
      its Flow box over an external consumer placed right of the account; the
      two container conditions could not see it, ``node-overlap`` skips text
      cells and ``edge-crosses-legend`` fires only when an edge runs through the
      box. The linter reports this reason as an ERROR on both classes.

    The two container conditions are skipped for a diagram with no boundary
    containers (a bare flow sketch has no body to reserve a margin against); the
    node condition is checked regardless.
    """
    if not geo.text_boxes:
        return []
    outer_right = (
        max(c.right for c in geo.containers.values()) if geo.containers else None
    )
    out: List[Tuple[str, str]] = []
    for cid, box in sorted(geo.text_boxes.items()):
        heading = geo.text_headings.get(cid, "").strip().lower()
        if heading not in LEGEND_HEADINGS:
            continue
        if outer_right is not None:
            if box.x < outer_right + grid:
                out.append((cid, "left-of-diagram-body"))
            for kid, container in sorted(geo.containers.items()):
                if (
                    box.x < container.right
                    and container.x < box.right
                    and box.y < container.bottom
                    and container.y < box.bottom
                ):
                    out.append((cid, f"overlaps-{kid}"))
        for nid in sorted(geo.nodes):
            icon = geo.nodes[nid]
            caption = node_caption_box(icon, geo.node_labels.get(nid, ""))
            if any(
                box.x < r.right and r.x < box.right
                and box.y < r.bottom and r.y < box.bottom
                for r in (icon, caption)
            ):
                out.append((cid, f"overlaps-node-{nid}"))
    return out


def check_edge_float(geo: DiagramGeometry) -> List[str]:
    """Return ids of edges that declare no explicit exit/entry contact point.

    On a dense (landscape) diagram every edge must fix its contact points
    (``exitX/exitY`` + ``entryX/entryY``) so the directional contract is checkable
    and the perimeter router cannot drift a side. A ``floated`` edge — one that
    sets neither an exit nor an entry point — is a landscape defect."""
    out: List[str] = []
    for e in geo.edges:
        has_exit = e.exit[0] is not None or e.exit[1] is not None
        has_entry = e.entry[0] is not None or e.entry[1] is not None
        if not (has_exit and has_entry):
            out.append(e.id)
    return sorted(out)


def check_corridor_sharing(geo: DiagramGeometry, grid: int = GRID) -> List[Tuple[str, str]]:
    """Return id pairs of edges that share a straight horizontal/vertical corridor.

    Two *long* edges must not run in the same corridor: parallel runs are offset
    by >= one grid step (diagram-standards Edge Routing). This flags a pair whose
    dominant straight segment lies on the **same grid line** (same y for a
    horizontal run, or same x for a vertical run) and whose extents overlap — the
    "two lines merge into one" defect.

    Conservative: only segments spanning more than one column/row step are
    considered "long"; short adjacent stubs are ignored. Each edge's segments are
    taken from its explicit waypoints (real routing); an edge with < 2 points
    (a straight source→target line) contributes its endpoints when both contact
    points are known via the connected node boxes."""
    # Build the set of straight segments each edge occupies.
    def segments_of(e: EdgeGeom) -> List[Tuple[str, float, float, float]]:
        """Return ('h'|'v', line, lo, hi) segments from an edge's waypoints."""
        pts: List[Tuple[float, float]] = list(e.points)
        # Prepend/append real contact points when the node boxes are known.
        if e.source in geo.nodes and e.exit[0] is not None and e.exit[1] is not None:
            s = geo.nodes[e.source]
            pts = [(s.x + e.exit[0] * s.w, s.y + e.exit[1] * s.h)] + pts
        if e.target in geo.nodes and e.entry[0] is not None and e.entry[1] is not None:
            t = geo.nodes[e.target]
            pts = pts + [(t.x + e.entry[0] * t.w, t.y + e.entry[1] * t.h)]
        segs: List[Tuple[str, float, float, float]] = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if abs(y1 - y0) <= 1 and abs(x1 - x0) > 2 * grid:  # horizontal long run
                segs.append(("h", round(y0), min(x0, x1), max(x0, x1)))
            elif abs(x1 - x0) <= 1 and abs(y1 - y0) > 2 * grid:  # vertical long run
                segs.append(("v", round(x0), min(y0, y1), max(y0, y1)))
        return segs

    edge_segs = {e.id: segments_of(e) for e in geo.edges}
    src_of = {e.id: e.source for e in geo.edges}
    tgt_of = {e.id: e.target for e in geo.edges}

    def _shared_stub_lines(e_id: str, other_id: str) -> set:
        """Return the corridor lines (``(orient, line)``) of the segment(s) of
        edge ``e_id`` that are INCIDENT to the node it shares with ``other_id``.

        Two edges that share a source (or a target) legitimately run together in
        the one *stub* touching that common node before branching apart
        (diagram-standards "shared trunk, opposite branches"). That stub is the
        segment whose endpoint is the shared node's contact point, so overlap on
        it is the sanctioned trunk, not a merge. Overlap on any OTHER segment is a
        genuine merged run and is flagged. When the edges share neither endpoint
        there is no trunk and this returns the empty set."""
        e = _edge_by_id[e_id]
        shared_pt = None
        if src_of[e_id] == src_of[other_id] and e.source in geo.nodes and e.exit[0] is not None and e.exit[1] is not None:
            s = geo.nodes[e.source]
            shared_pt = (s.x + e.exit[0] * s.w, s.y + e.exit[1] * s.h)
        elif tgt_of[e_id] == tgt_of[other_id] and e.target in geo.nodes and e.entry[0] is not None and e.entry[1] is not None:
            t = geo.nodes[e.target]
            shared_pt = (t.x + e.entry[0] * t.w, t.y + e.entry[1] * t.h)
        if shared_pt is None:
            return set()
        px, py = shared_pt
        lines = set()
        for orient, line, lo, hi in edge_segs[e_id]:
            # The stub segment is the one whose extent reaches the shared contact
            # (on its own axis) at the corridor line the contact sits on.
            if orient == "h" and abs(round(py) - line) <= 1 and lo - 1 <= px <= hi + 1:
                lines.add((orient, line))
            elif orient == "v" and abs(round(px) - line) <= 1 and lo - 1 <= py <= hi + 1:
                lines.add((orient, line))
        return lines

    _edge_by_id = {e.id: e for e in geo.edges}

    def _node_stub_lines(e_id: str, node_id: str) -> set:
        """Corridor lines of ``e_id``'s segment(s) touching its contact on ``node_id``."""
        e = _edge_by_id[e_id]
        pt = None
        if e.source == node_id and node_id in geo.nodes and None not in e.exit:
            n = geo.nodes[node_id]
            pt = (n.x + e.exit[0] * n.w, n.y + e.exit[1] * n.h)
        elif e.target == node_id and node_id in geo.nodes and None not in e.entry:
            n = geo.nodes[node_id]
            pt = (n.x + e.entry[0] * n.w, n.y + e.entry[1] * n.h)
        if pt is None:
            return set()
        px, py = pt
        lines = set()
        for orient, line, lo, hi in edge_segs[e_id]:
            if orient == "h" and abs(round(py) - line) <= 1 and lo - 1 <= px <= hi + 1:
                lines.add((orient, line))
            elif orient == "v" and abs(round(px) - line) <= 1 and lo - 1 <= py <= hi + 1:
                lines.add((orient, line))
        return lines

    def _incident_span(e_id: str, node_id: str, orient: str, line: float):
        """Extent (lo, hi) of ``e_id``'s segment on ``(orient, line)`` that is
        incident to its contact on ``node_id`` — the shared-stub sub-interval."""
        e = _edge_by_id[e_id]
        pt = None
        if e.source == node_id and node_id in geo.nodes and None not in e.exit:
            n = geo.nodes[node_id]
            pt = (n.x + e.exit[0] * n.w, n.y + e.exit[1] * n.h)
        elif e.target == node_id and node_id in geo.nodes and None not in e.entry:
            n = geo.nodes[node_id]
            pt = (n.x + e.entry[0] * n.w, n.y + e.entry[1] * n.h)
        if pt is None:
            return (float("inf"), float("-inf"))
        px, py = pt
        for o, ln, lo, hi in edge_segs[e_id]:
            if o != orient or abs(ln - line) > 1:
                continue
            if o == "h" and abs(round(py) - ln) <= 1 and lo - 1 <= px <= hi + 1:
                return (lo, hi)
            if o == "v" and abs(round(px) - ln) <= 1 and lo - 1 <= py <= hi + 1:
                return (lo, hi)
        return (float("inf"), float("-inf"))

    def _trunk_span(a: str, b: str, orient: str, line: float):
        # The shared stub covers only where BOTH edges' incident segments overlap.
        node = src_of[a] if src_of[a] == src_of[b] else tgt_of[a]
        la_ = _incident_span(a, node, orient, line)
        lb_ = _incident_span(b, node, orient, line)
        return (max(la_[0], lb_[0]), min(la_[1], lb_[1]))

    def _chain_span(a: str, b: str, node: str, orient: str, line: float):
        la_ = _incident_span(a, node, orient, line)
        lb_ = _incident_span(b, node, orient, line)
        return (max(la_[0], lb_[0]), min(la_[1], lb_[1]))

    out: List[Tuple[str, str]] = []
    ids = list(edge_segs)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            # A CHAIN through one node (the target of one edge is the source of
            # the other, e.g. app→db and db→db') naturally touches that node's
            # opposite faces at its centre row — that shared contact point is the
            # node, not a merged corridor, so a chain pair is always exempt.
            #
            # 1.10.3: exempt only the two stubs INCIDENT to the chain node. The
            # wholesale exemption let a chain pair merge on a lane away from the
            # node (GenAI ``e6`` train→hub and ``e7`` hub→sql sharing y=690) with
            # no finding, so the repair loop never separated them.
            chain_node = (
                tgt_of[a] if tgt_of[a] == src_of[b]
                else src_of[a] if tgt_of[b] == src_of[a] else None
            )
            chain_lines = (
                _node_stub_lines(a, chain_node) | _node_stub_lines(b, chain_node)
                if chain_node is not None else set()
            )
            # A shared TRUNK is legitimate (diagram-standards "shared trunk,
            # opposite branches") ONLY as a shared *stub* that then branches
            # apart — "the branches never overlap". So two edges that leave the
            # SAME source (or reach the SAME target) are exempt when their
            # same-corridor segments merely TOUCH (share the stub point) but not
            # when they run merged along a genuine shared length. This closes the
            # blind spot where two same-target descents (dns→lb and cdn→lb both
            # dropping into one top-entry corridor) merged into one line yet were
            # exempted wholesale by a bare source/target-equality test (1.10.1).
            shares_endpoint = src_of[a] == src_of[b] or tgt_of[a] == tgt_of[b]
            # For a shared-endpoint pair, the ONE corridor line of the stub that
            # touches the common node is the sanctioned trunk; overlap there is
            # fine, overlap anywhere else is a merged run. Intersect both edges'
            # trunk lines so only a genuinely shared stub is exempted.
            trunk_lines = (
                _shared_stub_lines(a, b) & _shared_stub_lines(b, a)
                if shares_endpoint else set()
            )
            shared = False
            for oa, la, loa, hia in edge_segs[a]:
                for ob, lb, lob, hib in edge_segs[b]:
                    if oa != ob or la != lb:
                        continue
                    # Overlap length on the shared corridor line. A non-positive
                    # overlap means the segments only touch at an endpoint (the
                    # sanctioned stub-then-branch), so it is not a merged run.
                    overlap = min(hia, hib) - max(loa, lob)
                    if overlap <= 0:
                        continue
                    # A shared-endpoint pair is exempt ONLY on the trunk line
                    # (the stub incident to the common node), and ONLY over the
                    # sub-interval the stub actually spans from the contact. Two
                    # edges leaving one node on the same corridor line but running
                    # in OPPOSITE directions (GCP ``hub→sql`` left vs ``hub→obj``
                    # right, both on y=690) overlap PAST the shared stub — that is
                    # a merge, not a trunk. Subtract the trunk span from the
                    # overlap and flag whatever is left.
                    if shares_endpoint and (oa, la) in trunk_lines:
                        lo_ov, hi_ov = max(loa, lob), min(hia, hib)
                        t_lo, t_hi = _trunk_span(a, b, oa, la)
                        # Overlap entirely within the shared stub → sanctioned.
                        if t_lo <= lo_ov and hi_ov <= t_hi:
                            continue
                    if chain_node is not None and (oa, la) in chain_lines:
                        c_lo, c_hi = _chain_span(a, b, chain_node, oa, la)
                        lo_ov, hi_ov = max(loa, lob), min(hia, hib)
                        if c_lo <= lo_ov and hi_ov <= c_hi:
                            continue
                    shared = True
                    break
                if shared:
                    break
            if shared:
                out.append(tuple(sorted((a, b))))  # type: ignore[arg-type]
    return sorted(set(out))


def check_arrow_style(geo: DiagramGeometry, min_stroke: float = 1.0) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for edges that break the arrow/line style rule.

    AWS diagram conventions prefer **open** arrowheads over heavy filled ones and
    a minimum stroke width of ~1pt. This flags an edge whose ``endArrow`` is a
    filled head (``block``/``classic``/``diamond``/``oval`` with fill on), or
    whose ``strokeWidth`` is below ``min_stroke``. An edge that declares no
    ``endArrow`` inherits the draw.io default (``classic``, filled) and is
    flagged so the style is made explicit. ``strokeWidth`` absent is treated as
    the 1pt default and is not flagged on width alone.
    """
    filled_heads = {"block", "classic", "classicthin", "diamond", "diamondthin", "oval", "box"}
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        ea = (e.end_arrow or "").lower()
        # Open/none heads, or an explicitly unfilled head (endFill=0), are fine.
        is_open = ea in ("open", "openthin", "none", "halfcircle") or e.end_fill == 0
        if not ea:
            out.append((e.id, "arrowhead-unspecified-defaults-filled"))
        elif ea in filled_heads and e.end_fill != 0:
            out.append((e.id, f"filled-arrowhead-{ea}"))
        if e.stroke_width is not None and e.stroke_width < min_stroke:
            out.append((e.id, f"stroke-width-{e.stroke_width}<{min_stroke}"))
    return out


def check_edge_bidirectional(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for double-headed (bidirectional) edges.

    Provider guidance (AWS ``diagram-as-code``) is to draw a two-way
    relationship as **two single-ended edges**, or annotate one edge with
    request/response — never a single double-headed arrow, which hides an
    ambiguous dependency. An edge is a Bidirectional_Edge when its style sets
    **both** a non-``none`` ``startArrow`` and a non-``none`` ``endArrow``.

    Arrow-token defaults are resolved exactly as draw.io does: an unspecified
    ``startArrow`` is ``none`` (no start head), so the common single-head edge
    (start ``none``, end set or defaulted) is never flagged; an unspecified
    ``endArrow`` inherits the default head. So the rule fires only when the
    author has *explicitly* placed a head on the start too. Advisory
    (``edge-bidirectional``, WARNING, both classes; Requirement 1).
    """
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        # An unspecified startArrow resolves to "none": a single-head edge.
        sa = (e.start_arrow or "none").lower()
        if sa == "none":
            continue
        # startArrow is a real head; the edge is bidirectional unless the end
        # was explicitly turned off (endArrow=none).
        ea = (e.end_arrow or "").lower()
        if ea == "none":
            continue
        out.append((e.id, f"double-head-start-{sa}-end-{ea or 'default'}"))
    return out


# --------------------------------------------------------------------------- #
# Edge hygiene — flow-marker de-collision, port distribution, parallel trunks
# (1.10.5, Feature A). Pure geometry, deterministic, idempotent.
# --------------------------------------------------------------------------- #

#: Minimum on-canvas separation (px) between two edge flow-marker labels before
#: they read as merged. A numbered marker is a ~12px glyph; two anchored closer
#: than this overprint (the GCP ``4``/``6`` merge, OCI ``3``/``5`` and ``6``/``7``
#: overlaps). Named so the threshold is declared once and shared by the
#: de-collision pass and the ``marker-collision`` lint check (1.10.5 A1/B1).
MARKER_MIN_SEP = 24.0

#: Minimum on-canvas clearance (px) between a flow-marker anchor and a segment of
#: a *different* edge (1.10.7 D37). Closer than this and that edge's line strikes
#: the number (the quick summary's ``9`` run printed straight through ``8``).
#: One grid step — about half of one 12px glyph — not :data:`MARKER_MIN_SEP`,
#: which is a marker-to-marker distance covering two glyphs. The comparison is
#: strict (``d < clearance``): the sanctioned one-grid-step parallel corridor
#: puts a neighbour's line exactly 10px from a marker, and must not be flagged.
MARKER_EDGE_CLEARANCE = float(GRID)

#: The fixed step (as an along-edge fraction of the signed ``[-1, 1]`` label
#: position) by which a colliding marker is nudged along its edge. One nudge
#: moves a marker ~⅒ of the route toward one end; small enough not to slide the
#: label off a short leg, large enough that one step clears a 24px overprint on
#: any route longer than ~240px. Deterministic and bounded so the pass is
#: idempotent (a separated pair is left untouched). (1.10.5 A1)
MARKER_NUDGE_STEP = 0.2

#: The extra grid step by which two co-linear parallel trunk runs are separated
#: so they do not draw as one line (1.10.5 A3). One :data:`GRID` step is the
#: minimum offset diagram-standards already mandates for parallel corridors.
PARALLEL_TRUNK_OFFSET = GRID

#: Detour coefficient: an edge whose routed (Manhattan) length exceeds the
#: straight Manhattan distance between its contacts by more than this factor is
#: a "detour hook" — it loops out and back instead of going where it is going
#: (1.10.5 B3). 2.5 clears the legitimate one-stair dog-leg every orthogonal
#: route needs while catching a genuine hook.
DETOUR_HOOK_COEFF = 2.5


def _edge_contacts(
    geo: DiagramGeometry, e: EdgeGeom
) -> Optional[Tuple[Point, Point]]:
    """Return ``(exit_abs, entry_abs)`` for an edge, or ``None`` when unresolved."""
    src, tgt = geo.nodes.get(e.source), geo.nodes.get(e.target)
    if src is None or tgt is None or None in e.exit or None in e.entry:
        return None
    return (
        (src.x + e.exit[0] * src.w, src.y + e.exit[1] * src.h),
        (tgt.x + e.entry[0] * tgt.w, tgt.y + e.entry[1] * tgt.h),
    )


def marker_anchor(poly: Sequence[Point], label_pos: Optional[float]) -> Optional[Point]:
    """Return the on-canvas point where an edge label renders.

    draw.io places an edge label at a signed arc-length fraction ``label_pos`` of
    the full polyline: ``0`` (or ``None``) is the geometric midpoint, ``-1`` the
    source end, ``+1`` the target end. This walks the polyline to the point at
    normalized arc-length ``t = (label_pos + 1) / 2`` — the same point the reader
    sees the number at. Returns ``None`` for a degenerate (zero-length) route.
    """
    pts = [tuple(p) for p in poly]
    if len(pts) < 2:
        return None
    seg_len = [
        abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(pts, pts[1:])
    ]
    total = sum(seg_len)
    if total <= 0:
        return pts[0]
    t = ((label_pos if label_pos is not None else 0.0) + 1.0) / 2.0
    t = min(1.0, max(0.0, t))
    target = t * total
    run = 0.0
    for (a, b), ln in zip(zip(pts, pts[1:]), seg_len):
        if run + ln >= target or ln == 0:
            frac = 0.0 if ln == 0 else (target - run) / ln
            return (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac)
        run += ln
    return pts[-1]


def _marker_edges(geo: DiagramGeometry) -> List[EdgeGeom]:
    """Return edges carrying a numeric flow-marker label, in stable id order."""
    return sorted(
        (e for e in geo.edges if e.label.strip().isdigit()),
        key=lambda e: e.id,
    )


def marker_anchors(geo: DiagramGeometry) -> Dict[str, Point]:
    """Return ``{edge_id: anchor_point}`` for every numeric-marker edge."""
    out: Dict[str, Point] = {}
    for e in _marker_edges(geo):
        contacts = _edge_contacts(geo, e)
        if contacts is None:
            continue
        poly = [contacts[0]] + [tuple(p) for p in e.points] + [contacts[1]]
        anchor = marker_anchor(poly, e.label_pos)
        if anchor is not None:
            out[e.id] = anchor
    return out


def check_marker_collision(
    geo: DiagramGeometry, min_sep: float = MARKER_MIN_SEP
) -> List[Tuple[str, str]]:
    """Return ``(edge_a, edge_b)`` id pairs whose flow-markers render < ``min_sep`` apart.

    The anchor is each marker's rendered point (:func:`marker_anchor`); two whose
    Euclidean distance is below :data:`MARKER_MIN_SEP` overprint and read as one
    number (1.10.5 B1). Pairs are sorted within and across for a deterministic,
    de-duplicated list.
    """
    anchors = marker_anchors(geo)
    ids = sorted(anchors)
    out: List[Tuple[str, str]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            (ax, ay), (bx, by) = anchors[ids[i]], anchors[ids[j]]
            if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < min_sep - AXIS_EPS:
                out.append((ids[i], ids[j]))
    return sorted(set(out))


def check_marker_label_collision(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, node_id)`` for flow-markers drawn on a node caption.

    A numbered marker whose rendered anchor (:func:`marker_anchors`) falls
    inside a node's caption rectangle (:func:`node_caption_box`, inclusive with
    :data:`AXIS_EPS` tolerance) overprints the service name: the reader sees
    "4" printed across "alerts" (1.10.7). Every node is checked, endpoints
    included — a marker on its own target's caption is as unreadable. Lint-only;
    not part of :func:`rule_violations`."""
    out: List[Tuple[str, str]] = []
    for eid, (px, py) in sorted(marker_anchors(geo).items()):
        for nid in sorted(geo.nodes):
            cap = node_caption_box(geo.nodes[nid], geo.node_labels.get(nid, ""))
            if (
                cap.x - AXIS_EPS <= px <= cap.right + AXIS_EPS
                and cap.y - AXIS_EPS <= py <= cap.bottom + AXIS_EPS
            ):
                out.append((eid, nid))
    return out


def _edge_polylines(geo: DiagramGeometry) -> Dict[str, List[Point]]:
    """Return ``{edge_id: [exit, *waypoints, entry]}`` for every resolved edge.

    Labelled or not: any edge's line can strike another edge's marker."""
    out: Dict[str, List[Point]] = {}
    for e in geo.edges:
        contacts = _edge_contacts(geo, e)
        if contacts is None:
            continue
        out[e.id] = [contacts[0]] + [tuple(p) for p in e.points] + [contacts[1]]
    return out


def _dist_point_segment(p: Point, a: Point, b: Point) -> float:
    """Euclidean distance from point ``p`` to the closed segment ``a``-``b``."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _dist_to_foreign_edges(
    p: Point, eid: str, polys: Mapping[str, Sequence[Point]]
) -> Tuple[float, Optional[str]]:
    """Return ``(distance, nearest_edge_id)`` from ``p`` to any edge other than ``eid``."""
    best, best_id = math.inf, None
    for oid in sorted(polys):
        if oid == eid:
            continue
        poly = polys[oid]
        for a, b in zip(poly, poly[1:]):
            d = _dist_point_segment(p, a, b)
            if d < best:
                best, best_id = d, oid
    return best, best_id


def check_marker_on_edge(
    geo: DiagramGeometry, clearance: float = MARKER_EDGE_CLEARANCE
) -> List[Tuple[str, str]]:
    """Return ``(marker_edge_id, foreign_edge_id)`` for markers struck by another line.

    A numbered marker whose rendered anchor (:func:`marker_anchors`) lies closer
    than ``clearance`` (strict, with :data:`AXIS_EPS` tolerance) to any segment of
    a **different** edge reads as crossed out by that edge (1.10.7 D37). Sorted,
    de-duplicated; every foreign edge within range is reported, not only the
    nearest."""
    polys = _edge_polylines(geo)
    out: List[Tuple[str, str]] = []
    for eid, p in sorted(marker_anchors(geo).items()):
        for oid in sorted(polys):
            if oid == eid:
                continue
            poly = polys[oid]
            if any(
                _dist_point_segment(p, a, b) < clearance - AXIS_EPS
                for a, b in zip(poly, poly[1:])
            ):
                out.append((eid, oid))
    return sorted(set(out))


#: Largest ``|label_pos|`` the on-edge slide may choose: keeps a slid marker off
#: the arrowhead and the exit stub at either end of its own edge (1.10.7 D37).
_MARKER_SLIDE_LIMIT = 0.8


def resolve_marker_collisions(
    geo: DiagramGeometry,
    min_sep: float = MARKER_MIN_SEP,
    step: float = MARKER_NUDGE_STEP,
    clearance: float = MARKER_EDGE_CLEARANCE,
) -> Dict[str, float]:
    """Return ``{edge_id: new_label_pos}`` for markers that must move to separate.

    Phase 1 (marker vs marker, 1.10.5): for each colliding pair (in sorted id
    order), the lower-id edge's marker slides toward its **source** and the
    higher-id edge's toward its **target**, by :data:`MARKER_NUDGE_STEP` along
    the signed ``[-1, 1]`` position, clamped to that range. The pass repeats
    until no pair is within ``min_sep`` or a bounded iteration cap is reached,
    so a cluster of three separates too.

    Phase 2 (marker vs foreign edge, 1.10.7 D37): each marker whose anchor lies
    closer than ``clearance`` to a segment of a **different** edge is slid along
    its **own** edge, nearest candidate first (``pos ∓ k·step``, k = 1…4, toward
    the source before the target, ``|pos| ≤ 0.8``). A candidate is accepted only
    when it clears every foreign segment by ``clearance``, every other marker by
    ``min_sep``, and every node icon and caption. When none qualifies the marker
    stays put and lint (``marker-collision`` ``marker-on-edge-<id>``) reports it.

    Only edges that actually move appear in the result; re-running on an
    already-separated diagram returns ``{}`` (idempotent).
    """
    markers = _marker_edges(geo)
    if not markers:
        return {}
    pos: Dict[str, float] = {
        e.id: (e.label_pos if e.label_pos is not None else 0.0) for e in markers
    }
    by_id = {e.id: e for e in markers}
    contacts = {e.id: _edge_contacts(geo, e) for e in markers}

    def anchor_of(eid: str) -> Optional[Point]:
        c = contacts[eid]
        if c is None:
            return None
        poly = [c[0]] + [tuple(p) for p in by_id[eid].points] + [c[1]]
        return marker_anchor(poly, pos[eid])

    ids = sorted(pos)
    # Bounded: at most ``step`` fits (2 / step) times end-to-end; double it as a
    # safety cap so a dense cluster still terminates deterministically.
    max_iter = int(4.0 / step) + 2
    for _ in range(max_iter):
        moved_any = False
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                pa, pb = anchor_of(a), anchor_of(b)
                if pa is None or pb is None:
                    continue
                dist = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5
                if dist >= min_sep - AXIS_EPS:
                    continue
                new_a = max(-1.0, min(1.0, pos[a] - step))
                new_b = max(-1.0, min(1.0, pos[b] + step))
                if new_a != pos[a] or new_b != pos[b]:
                    pos[a], pos[b] = new_a, new_b
                    moved_any = True
        if not moved_any:
            break

    # Phase 2 — slide a marker off a foreign edge's line (1.10.7 D37).
    polys = _edge_polylines(geo)
    boxes: List[Box] = []
    for nid in sorted(geo.nodes):
        box = geo.nodes[nid]
        boxes.append(box)
        boxes.append(node_caption_box(box, geo.node_labels.get(nid, "")))

    def in_box(p: Point) -> bool:
        return any(
            b.x - AXIS_EPS <= p[0] <= b.right + AXIS_EPS
            and b.y - AXIS_EPS <= p[1] <= b.bottom + AXIS_EPS
            for b in boxes
        )

    def clear_of_markers(eid: str, p: Point) -> bool:
        for oid in ids:
            if oid == eid:
                continue
            q = anchor_of(oid)
            if q is not None and ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5 < min_sep - AXIS_EPS:
                return False
        return True

    for eid in ids:
        here = anchor_of(eid)
        if here is None:
            continue
        if _dist_to_foreign_edges(here, eid, polys)[0] >= clearance - AXIS_EPS:
            continue
        start = pos[eid]
        for k in range(1, 5):
            chosen = None
            for sign in (-1.0, 1.0):
                cand = round(start + sign * k * step, 6)
                if abs(cand) > _MARKER_SLIDE_LIMIT + 1e-9:
                    continue
                pos[eid] = cand
                p = anchor_of(eid)
                pos[eid] = start
                if p is None:
                    continue
                if _dist_to_foreign_edges(p, eid, polys)[0] < clearance - AXIS_EPS:
                    continue
                if not clear_of_markers(eid, p) or in_box(p):
                    continue
                chosen = cand
                break
            if chosen is not None:
                pos[eid] = chosen
                break

    return {
        eid: round(pos[eid], 4)
        for eid, e in by_id.items()
        if abs(pos[eid] - (e.label_pos if e.label_pos is not None else 0.0)) > 1e-9
    }


def _face_of_contact(frac: Tuple[Optional[float], Optional[float]]) -> Optional[str]:
    """Return the single face a contact sits on (``top``/``bottom``/``left``/``right``)."""
    if None in frac:
        return None
    faces = contact_faces(frac[0], frac[1])
    # A corner lies on two faces; treat it as its horizontal face for ordering.
    for name in ("right", "left", "top", "bottom"):
        if name in faces:
            return name
    return None


def _even_fractions(n: int) -> List[float]:
    """Return ``n`` evenly-spaced interior fractions across a face: ``k/(n+1)``."""
    return [round((k + 1) / (n + 1), 6) for k in range(n)]


def check_port_bunching(
    geo: DiagramGeometry, min_sep: float = 0.15
) -> List[Tuple[str, str]]:
    """Return ``(node_id, face)`` where >=2 edges share a face with bunched contacts.

    When ``N >= 2`` edges exit (or enter) one node face and their along-face
    fractions are not evenly distributed — two lie closer than ``min_sep`` of the
    face, i.e. they nearly stack — the face is reported (1.10.5 A2). Deterministic
    node/face order. This is the *detector*; :func:`distribute_ports` computes the
    even fractions the cleanup applies.
    """
    faces = _collect_face_contacts(geo)
    out: List[Tuple[str, str]] = []
    for (nid, face), entries in sorted(faces.items()):
        if len(entries) < 2:
            continue
        fracs = sorted(f for _eid, _side, f in entries)
        if any(b - a < min_sep - 1e-9 for a, b in zip(fracs, fracs[1:])):
            out.append((nid, face))
    return sorted(set(out))


def _collect_face_contacts(
    geo: DiagramGeometry,
) -> Dict[Tuple[str, str], List[Tuple[str, str, float]]]:
    """Group edge contacts by ``(node_id, face)``.

    Each value is a list of ``(edge_id, side, along_frac)`` where ``side`` is
    ``"exit"`` or ``"entry"`` and ``along_frac`` is the position along the face
    (the x-fraction for a top/bottom face, the y-fraction for left/right).
    """
    faces: Dict[Tuple[str, str], List[Tuple[str, str, float]]] = {}
    for e in geo.edges:
        for nid, frac, side in (
            (e.source, e.exit, "exit"),
            (e.target, e.entry, "entry"),
        ):
            if nid not in geo.nodes or None in frac:
                continue
            face = _face_of_contact(frac)
            if face is None:
                continue
            along = frac[0] if face in ("top", "bottom") else frac[1]
            faces.setdefault((nid, face), []).append((e.id, side, float(along)))
    return faces


def distribute_ports(
    geo: DiagramGeometry, min_sep: float = 0.15
) -> Dict[str, Dict[str, Tuple[float, float]]]:
    """Return ``{edge_id: {side: (new_x, new_y)}}`` distributing bunched face ports.

    For every ``(node, face)`` the port-bunching detector flags, the edges on that
    face are re-fractioned to :func:`_even_fractions` in a **deterministic order
    keyed by the OTHER endpoint id** (then the edge id), so the assignment is
    stable and independent of input order. The face coordinate (0 or 1) is
    preserved; only the along-face fraction moves. ``side`` is ``"exit"`` or
    ``"entry"``. Only edges whose fraction actually changes are returned, so
    re-running on an evenly-distributed diagram yields ``{}`` (idempotent).
    """
    faces = _collect_face_contacts(geo)
    bunched = set(check_port_bunching(geo, min_sep=min_sep))
    by_id = {e.id: e for e in geo.edges}
    out: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for (nid, face), entries in sorted(faces.items()):
        if (nid, face) not in bunched:
            continue

        def _other(entry: Tuple[str, str, float]) -> str:
            eid, side, _ = entry
            e = by_id[eid]
            return (e.target if side == "exit" else e.source) or ""

        ordered = sorted(entries, key=lambda en: (_other(en), en[0]))
        new_fracs = _even_fractions(len(ordered))
        for (eid, side, along), nf in zip(ordered, new_fracs):
            if abs(nf - along) <= 1e-9:
                continue
            e = by_id[eid]
            frac = e.exit if side == "exit" else e.entry
            if face == "top":
                new = (nf, 0.0)
            elif face == "bottom":
                new = (nf, 1.0)
            elif face == "left":
                new = (0.0, nf)
            else:  # right
                new = (1.0, nf)
            out.setdefault(eid, {})[side] = (round(new[0], 6), round(new[1], 6))
    return out


def _long_runs(
    e: EdgeGeom, geo: DiagramGeometry, grid: int = GRID
) -> List[Tuple[str, float, float, float]]:
    """Return an edge's long axis-aligned runs as ``(orient, line, lo, hi)``.

    ``orient`` is ``"h"`` or ``"v"``; ``line`` is the shared coordinate (y for a
    horizontal run, x for a vertical one); ``lo``/``hi`` bound the run on its own
    axis. A run must span more than ``2*grid`` to count as a trunk. Mirrors the
    long-run extraction ``check_corridor_sharing`` uses.
    """
    contacts = _edge_contacts(geo, e)
    pts: List[Point] = list(e.points)
    if contacts is not None:
        pts = [contacts[0]] + pts + [contacts[1]]
    runs: List[Tuple[str, float, float, float]] = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if abs(y1 - y0) <= AXIS_EPS and abs(x1 - x0) > 2 * grid:
            runs.append(("h", y0, min(x0, x1), max(x0, x1)))
        elif abs(x1 - x0) <= AXIS_EPS and abs(y1 - y0) > 2 * grid:
            runs.append(("v", x0, min(y0, y1), max(y0, y1)))
    return runs


def check_parallel_trunks(
    geo: DiagramGeometry, grid: int = GRID
) -> List[Tuple[str, str]]:
    """Return ``(edge_a, edge_b)`` id pairs whose long runs coincide on one line.

    Two edges whose long runs sit on the **same** grid line (same y for a
    horizontal run, same x for a vertical one) with overlapping extent draw as a
    single line (1.10.5 A3). This is the *detector*; :func:`offset_parallel_trunks`
    computes the fixed-step offset the cleanup applies. Deterministic, de-duped.

    Distinct from ``corridor-sharing``: this fires only on an EXACT co-linear
    overlap (the two runs on the identical line, the merged-into-one case the
    offset pass repairs), where ``corridor-sharing`` also flags near-parallel
    runs and carries the shared-trunk/chain exemptions. Kept separate so the A3
    cleanup has a precise, exemption-free target.
    """
    runs = {e.id: _long_runs(e, geo, grid) for e in geo.edges}
    ids = sorted(runs)
    out: List[Tuple[str, str]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            found = False
            for oa, la, loa, hia in runs[a]:
                for ob, lb, lob, hib in runs[b]:
                    if oa != ob or abs(la - lb) > AXIS_EPS:
                        continue
                    if min(hia, hib) - max(loa, lob) > grid:
                        found = True
                        break
                if found:
                    break
            if found:
                out.append((a, b))
    return sorted(set(out))


def offset_parallel_trunks(
    geo: DiagramGeometry, grid: int = GRID, offset: int = PARALLEL_TRUNK_OFFSET
) -> Dict[str, List[Point]]:
    """Return ``{edge_id: new_points}`` offsetting the higher-id edge of each pair.

    For every co-linear pair :func:`check_parallel_trunks` flags, the
    **higher-id** edge's coincident run is shifted by one ``offset`` grid step off
    the shared line (a horizontal run moves in ``y``, a vertical run in ``x``), so
    the two no longer overprint. The lower-id edge is left in place, making the
    assignment deterministic. Only shifted edges are returned; a diagram with no
    coincident trunks yields ``{}`` (idempotent). The shift is snapped to the
    grid, and applied only to a waypoint that actually lies on the shared line.
    """
    pairs = check_parallel_trunks(geo, grid)
    by_id = {e.id: e for e in geo.edges}
    runs = {e.id: _long_runs(e, geo, grid) for e in geo.edges}
    # Collect, per higher-id edge, the (orient, line) it must move off.
    to_move: Dict[str, set] = {}
    for a, b in pairs:
        hi_id = b  # b > a by construction (sorted pair)
        for oa, la, loa, hia in runs[a]:
            for ob, lb, lob, hib in runs[hi_id]:
                if oa == ob and abs(la - lb) <= AXIS_EPS and min(hia, hib) - max(loa, lob) > grid:
                    to_move.setdefault(hi_id, set()).add((ob, round(lb)))
    out: Dict[str, List[Point]] = {}
    for eid, lines in to_move.items():
        e = by_id[eid]
        pts = [tuple(p) for p in e.points]
        moved = False
        new_pts: List[Point] = []
        for (px, py) in pts:
            npx, npy = px, py
            for orient, line in lines:
                if orient == "h" and abs(round(py) - line) <= AXIS_EPS:
                    npy = snap(py + offset, grid)
                    moved = True
                elif orient == "v" and abs(round(px) - line) <= AXIS_EPS:
                    npx = snap(px + offset, grid)
                    moved = True
            new_pts.append((npx, npy))
        if moved:
            out[eid] = new_pts
    return out


# --------------------------------------------------------------------------- #
# Edge hygiene lint checks (1.10.5, Feature B). Pure predicates.
# --------------------------------------------------------------------------- #


def check_edge_crossing_excess(
    geo: DiagramGeometry, per_edge_allowance: float = 0.25
) -> List[Tuple[str, str]]:
    """Return crossing edge-id pairs when the crossing count exceeds a per-diagram cap.

    Some crossings are unavoidable, but their number should stay proportional to
    the edge count. The cap is ``ceil(per_edge_allowance * E)`` where ``E`` is the
    number of routable edges; when the measured crossing count exceeds it, every
    crossing pair is reported as an offender (1.10.5 B2). Uses the same
    :func:`route_cost` crossing detection the scored router minimises, so the
    lint agrees with the router by construction. Below the cap: no findings.
    """
    crossings, n_edges, pairs = edge_crossing_stats(geo)
    if n_edges == 0:
        return []
    cap = math.ceil(per_edge_allowance * n_edges)
    if crossings <= cap:
        return []
    return pairs


#: Hard crossing cap for a ``landscape`` (1.10.7): more crossings than half the
#: routable edges is an ERROR, not a style nit. Calibrated across the shipped
#: corpus: the densest diagram crosses 0.22 x E (gcp/01, oci/01) and the HA
#: landscapes 3/21 = 0.14, while the 1.10.0 quick landscape — every edge
#: crossing another — measured 28/28 = 1.00. 0.5 leaves the corpus more than 2x
#: headroom and still blocks a landscape whose routing has collapsed.
HARD_CROSSING_RATIO = 0.5


def edge_crossing_stats(
    geo: DiagramGeometry,
) -> Tuple[int, int, List[Tuple[str, str]]]:
    """Return ``(crossings, routable_edges, sorted crossing pairs)``.

    The crossing count and pairs are :func:`route_cost`'s, so the lint and the
    scored router agree by construction; ``routable_edges`` counts edges with a
    resolvable polyline (two or more points)."""
    cost = route_cost(geo)
    n_edges = sum(1 for e in geo.edges if len(edge_polyline(geo, e)) >= 2)
    pairs = [tuple(sorted(pair)) for pair in cost.crossing_pairs]
    return cost.crossings, n_edges, pairs  # type: ignore[return-value]


def check_detour_hook(
    geo: DiagramGeometry, coeff: float = DETOUR_HOOK_COEFF
) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for edges routed far longer than they need.

    An edge's routed Manhattan length is compared to the straight Manhattan
    distance between its two contact points. When ``routed > coeff * manhattan``
    (and the manhattan distance is non-trivial) the edge loops out and back — a
    "detour hook" (1.10.5 B3). The reason carries the measured ratio. A
    zero-distance (self-loop-ish) or already-short edge is skipped.
    """
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        poly = edge_polyline(geo, e)
        if len(poly) < 2:
            continue
        routed = sum(
            abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(poly, poly[1:])
        )
        (sx, sy), (tx, ty) = poly[0], poly[-1]
        manhattan = abs(tx - sx) + abs(ty - sy)
        if manhattan <= 2 * geo.grid:
            continue  # contacts nearly co-located; ratio is meaningless
        if routed > coeff * manhattan + AXIS_EPS:
            out.append((e.id, f"detour-ratio-{routed / manhattan:.2f}"))
    return out


def check_structural_integrity(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(offender_id, reason)`` for structural defects in the model.

    Cross-checked against the ``awesome-copilot`` draw.io validator; only the
    checks NOT already enforced elsewhere are implemented here (``edge-endpoint``
    already covers a *missing* source/target reference via the CLI; ``parse-error``
    covers a parent CYCLE). This adds:

    * ``edge-unresolved-source:<id>`` / ``edge-unresolved-target:<id>`` — an edge
      whose ``source``/``target`` id resolves to neither a node nor a container
      box in the built geometry (a reference that survived parsing but points at
      nothing placeable).
    * ``node-no-geometry`` — a node id present in the model with a non-positive
      width or height (``build_geometry`` already drops a width-less node, so
      this fires only when a zero-area box slipped through; kept as the copilot
      validator's "every node has geometry" rule made explicit).

    Two copilot-validator rules are NOT re-checked here, by design:

    * **Duplicate cell ids** — the single ``.drawio`` parser keys cells by id
      into a mapping, so a duplicate id is collapsed before ``build_geometry``
      ever sees it; there is no deterministic post-parse signal of it in
      ``DiagramGeometry``.
    * **Parent-chain integrity** — a parent that does not exist, or a parent
      cycle, is already surfaced by the parser: ``absolute_origin`` raises
      ``DrawioParseError("parent-cycle:<id>")`` (→ ``parse-error``) on a cycle,
      and a node whose parent is neither the root layer nor a boundary container
      is simply not placed, so it cannot reach a routing check.

    Both limitations are recorded in ``diagram-lint.md`` (``structural-integrity``).
    """
    out: List[Tuple[str, str]] = []
    placeable = set(geo.nodes) | set(geo.containers)
    for e in geo.edges:
        if e.source and e.source not in placeable:
            out.append((e.id, f"edge-unresolved-source:{e.source}"))
        if e.target and e.target not in placeable:
            out.append((e.id, f"edge-unresolved-target:{e.target}"))
    for nid, box in sorted(geo.nodes.items()):
        if box.w <= 0 or box.h <= 0:
            out.append((nid, "node-no-geometry"))
    return sorted(set(out))


# --------------------------------------------------------------------------- #
# Rule-adherence checks (1.10.6). Three declared rules the linter did not read,
# and the scored view of every routing rule the layout engine now minimises.
# --------------------------------------------------------------------------- #


def _box_inside(inner: Box, outer: Box) -> bool:
    """True when ``inner`` lies wholly within ``outer`` (borders inclusive)."""
    return (outer.x <= inner.x and inner.right <= outer.right
            and outer.y <= inner.y and inner.bottom <= outer.bottom)


def check_edge_escapes_container(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, container_id)`` for routes that LEAVE the innermost
    container holding both of their endpoints.

    diagram-standards (*Route around a container, not through it*; *Reserve the
    right margin for Flow/Legend … route edges within the diagram body*): an edge
    between two nodes of one container is drawn inside that container. A run that
    steps out of it — into the strip between a region and its account, or out of
    the account into the right margin where the Flow/Legend furniture lives — reads
    as a relationship with something outside the box, and crosses its border
    twice for nothing. The canonical defects: OCI ``hub → model-storage`` turning
    in the gap OUTSIDE the region it never leaves (a corridor allocated one column
    past a region-rightmost source), and the 1.10.5 ``api → streaming`` override
    running down the right margin along the Flow box.

    The innermost common container is the smallest Boundary box enclosing both
    endpoint boxes; a polyline is convex-hull-bounded by its points, so a route
    stays inside a rectangle exactly when every waypoint does. An edge whose
    endpoints share no container (an external actor, a cross-cloud hop) is not
    judged."""
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        poly = edge_polyline(geo, e)
        if len(poly) < 3:
            continue
        s, t = geo.nodes[e.source], geo.nodes[e.target]
        common = [(cid, c) for cid, c in geo.containers.items()
                  if _box_inside(s, c) and _box_inside(t, c)]
        if not common:
            continue
        cid, c = min(common, key=lambda kv: (kv[1].w * kv[1].h, kv[0]))
        for x, y in poly[1:-1]:
            if x < c.x - AXIS_EPS or x > c.right + AXIS_EPS or y < c.y - AXIS_EPS or y > c.bottom + AXIS_EPS:
                out.append((e.id, cid))
                break
    return sorted(set(out))


def check_edge_crosses_legend(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, text_cell_id)`` for routes that run through, or along
    within one grid step of, a ``Flow`` / ``Legend`` box.

    diagram-standards (*No edge–label / edge–legend crossings*): keep every edge
    clear of the right-side Flow and Legend cells. ``edge-routing`` has always
    described this ("overlaps a label/legend") but never read the text boxes, so a
    run riding the Flow box's left border (the 1.10.5 OCI ``e3`` override at
    ``x=1010``, exactly the box's left edge) linted clean. The box is grown by one
    grid step so a run hugging its border counts, the same halo a container
    border gets."""
    furniture = [
        (cid, b) for cid, b in sorted(geo.text_boxes.items())
        if geo.text_headings.get(cid, "").strip().lower() in LEGEND_HEADINGS
    ]
    if not furniture:
        return []
    out: List[Tuple[str, str]] = []
    step = geo.grid or GRID
    for e in geo.edges:
        poly = edge_polyline(geo, e)
        if len(poly) < 2:
            continue
        for cid, b in furniture:
            halo = Box(cid, b.x - step, b.y - step, b.w + 2 * step, b.h + 2 * step)
            if any(segment_crosses_box(p, q, halo, inset=0.0) for p, q in zip(poly, poly[1:])):
                out.append((e.id, cid))
    return sorted(set(out))


def check_edge_jog(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for an edge between two DIRECTLY FACING nodes
    that is not drawn as one straight segment.

    diagram-standards (*Distinct same-side exits — straight line keeps the
    centre*): an edge whose target sits directly opposite — the next node on the
    same row, or directly below in the same column, nothing between — is the most
    readable route there is, so it keeps one straight line and the siblings spread
    around it. The engine broke this whenever a face carried three exits: the band
    spread handed the level edge the upper quarter while its entry stayed centred,
    and draw.io drew a 20px jog into a neighbour two centimetres away
    (``agent-tool-invoker → agent-bedrock-llm``).

    ``level-jog``: exit on the right face, entry on the left face, the two boxes
    share a horizontal band wider than a grid step with no node between them, yet
    the exit and entry heights differ. ``drop-jog``: the vertical mirror (bottom
    exit, top entry, shared column)."""
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        contacts = _edge_contacts(geo, e)
        if contacts is None:
            continue
        (ex, ey), (nx, ny) = contacts
        s, t = geo.nodes[e.source], geo.nodes[e.target]
        ef, nf = contact_faces(*e.exit), contact_faces(*e.entry)
        others = [b for nid, b in geo.nodes.items() if nid not in (e.source, e.target)]
        if "right" in ef and "left" in nf and t.x >= s.right:
            lo, hi = max(s.y, t.y), min(s.bottom, t.bottom)
            if hi - lo > GRID and abs(ey - ny) > AXIS_EPS and not any(
                b.x < t.x and b.right > s.right and b.y < hi and b.bottom > lo for b in others
            ):
                out.append((e.id, "level-jog"))
        elif "bottom" in ef and "top" in nf and t.y >= s.bottom:
            lo, hi = max(s.x, t.x), min(s.right, t.right)
            if hi - lo > GRID and abs(ex - nx) > AXIS_EPS and not any(
                b.y < t.y and b.bottom > s.bottom and b.x < hi and b.right > lo for b in others
            ):
                out.append((e.id, "drop-jog"))
    return sorted(set(out))


def rule_violations(
    geo: DiagramGeometry,
) -> Tuple[Tuple[Tuple[str, str], ...], Tuple[Tuple[str, str], ...]]:
    """Return ``(errors, warnings)``: every declared ROUTING rule a diagram breaks.

    The layout engine used to accept a candidate on six geometry rules (its
    repair oracle) and choose between candidates on crossings, rails, turns and
    ink alone — so a route that cut an icon (an ``edge-routing`` ERROR), sliced a
    caption, rode a border or left its container scored exactly like a clean one,
    and only the linter, after the fact, could tell. This is the linter's own view
    of the same geometry, reduced to two counts the solver and the placement loop
    minimise BEFORE crossings (``RouteCost.as_tuple``). The engine therefore picks
    the variant and the placement that keep the declared rules, rather than the
    one that merely crosses least (1.10.6).

    ``errors`` are the findings the engine must not ship: an ``edge-routing`` run
    through an unrelated icon or into its own target from the wrong side, and the
    repair oracle's own **blocking** routing rules (``edge-direction``,
    ``edge-float``, ``corridor-sharing``). Counting the oracle's blocking rules as
    errors keeps the scored objective CONSISTENT with the oracle: a candidate the
    oracle will block (e.g. an unrepairable ``corridor-sharing`` fan-out) can
    never out-score one it accepts merely because it has fewer advisory warnings
    — the regression that let a hub fan-out pick a band assignment the repair loop
    could not fix. ``warnings`` are the advisory routing rules the linter reports
    but does not block on. Each entry is ``(rule, offender)``; the tuples are
    sorted, so the counts are deterministic."""
    errors: List[Tuple[str, str]] = []
    warnings: List[Tuple[str, str]] = []
    for eid, reason in check_edge_routing(geo):
        bucket = errors if ("through-" in reason or reason.startswith("pierces-")) else warnings
        bucket.append(("edge-routing", f"{eid}:{reason}"))
    for eid, reason in check_edge_direction(geo):
        errors.append(("edge-direction", f"{eid}:{reason}"))
    for eid in check_edge_float(geo):
        errors.append(("edge-float", str(eid)))
    # corridor-sharing is a BLOCKING oracle rule (repair.py `_BLOCKING_RULES`), so
    # it ranks with the errors — the solver must avoid it before it minimises
    # crossings, or it can pick a route the oracle then refuses (1.10.6 fix).
    for finding in check_corridor_sharing(geo):
        errors.append(("corridor-sharing", repr(finding)))
    advisory = (
        ("edge-crosses-label", check_edge_crosses_label),
        ("edge-crosses-container-label", check_edge_crosses_container_label),
        ("edge-crosses-container", check_edge_crosses_container),
        ("edge-on-container-border", check_edge_on_container_border),
        ("edge-escapes-container", check_edge_escapes_container),
        ("edge-crosses-legend", check_edge_crosses_legend),
        ("edge-jog", check_edge_jog),
        ("exit-thirds", check_exit_thirds),
        ("entry-thirds", check_entry_thirds),
        ("edge-approach", check_edge_approach),
    )
    for rule, fn in advisory:
        for finding in fn(geo):
            warnings.append((rule, repr(finding)))
    return tuple(sorted(errors)), tuple(sorted(warnings))
