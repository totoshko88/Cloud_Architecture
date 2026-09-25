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

    build_geometry(drawio_text) -> DiagramGeometry
    check_grid_alignment(geo, grid=10)  -> list[str]   # misaligned node ids
    check_node_overlap(geo)             -> list[tuple]  # overlapping id pairs
    check_container_padding(geo, pad=10)-> list[tuple]  # (node, container, pad)
    check_edge_routing(geo)             -> list[tuple]  # (edge_id, reason)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Container / text classification and the root-layer id are shared with
# cli._parse_drawio via rule_engine.constants so the C4 boundary-detection rule
# cannot drift between node counting and the geometry-aware layout checks.
from rule_engine.constants import ROOT_LAYER_ID as _ROOT_LAYER_ID
from rule_engine.constants import is_boundary_container_style as _is_boundary_style
from rule_engine.constants import is_text_cell_style as _is_text_style

# The model grid step (draw.io ``gridSize`` default). Spacings and node origins
# are expected to be whole multiples of it (diagram-standards Layout Geometry).
GRID = 10

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

_CELL_RE = re.compile(r"<mxCell\b[^>]*?(?:/>|>.*?</mxCell>)", re.S)
_GEOM_RE = re.compile(r"<mxGeometry\b[^>]*?(?:/>|>.*?</mxGeometry>)", re.S)
_POINT_RE = re.compile(r'<mxPoint x="([-0-9.]+)" y="([-0-9.]+)"')


def _attr(cell: str, name: str) -> Optional[str]:
    m = re.search(rf'\b{name}="([^"]*)"', cell)
    return m.group(1) if m else None


def _style_num(cell: str, name: str) -> Optional[float]:
    """Read a numeric style token like ``exitX=0.25`` from a cell."""
    m = re.search(rf"\b{name}=([-0-9.]+)", cell)
    return float(m.group(1)) if m else None


def _style_token(cell: str, name: str) -> Optional[str]:
    """Read a string style token like ``endArrow=open`` from a cell."""
    m = re.search(rf"\b{name}=([A-Za-z0-9_]+)", cell)
    return m.group(1) if m else None


def _geom(cell: str) -> Optional[Dict[str, object]]:
    m = _GEOM_RE.search(cell)
    if not m:
        return None
    g = m.group(0)

    def n(a: str) -> Optional[float]:
        mm = re.search(rf'\b{a}="([-0-9.]+)"', g)
        return float(mm.group(1)) if mm else None

    points = [(float(x), float(y)) for x, y in _POINT_RE.findall(cell)]
    return {"x": n("x"), "y": n("y"), "w": n("width"), "h": n("height"), "points": points}


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


@dataclass
class DiagramGeometry:
    """The parsed geometry: top-level node boxes, container boxes, and edges."""

    nodes: Dict[str, Box] = field(default_factory=dict)
    containers: Dict[str, Box] = field(default_factory=dict)
    edges: List[EdgeGeom] = field(default_factory=list)


def build_geometry(text: str) -> DiagramGeometry:
    """Parse ``.drawio`` XML into a :class:`DiagramGeometry`.

    Only top-level nodes (parented to the root layer or a boundary container)
    and the boundary containers themselves are placed; embedded glyph sub-cells
    are ignored, exactly as the node-count parser does.
    """
    cells = _CELL_RE.findall(text)
    raw: Dict[str, Dict[str, object]] = {}
    for c in cells:
        cid = _attr(c, "id")
        if not cid:
            continue
        raw[cid] = {
            "cell": c,
            "parent": _attr(c, "parent") or "",
            "style": (_attr(c, "style") or ""),
            "vertex": 'vertex="1"' in c,
            "edge": 'edge="1"' in c,
            "geom": _geom(c),
            "source": _attr(c, "source"),
            "target": _attr(c, "target"),
        }

    # Boundary containers first (needed to classify node parents).
    boundary_ids = {
        cid
        for cid, d in raw.items()
        if d["vertex"] and _is_boundary_style(cid, str(d["style"]).lower())
    }
    node_parents = {_ROOT_LAYER_ID} | boundary_ids

    def origin(cid: str, seen: Optional[set] = None) -> Tuple[float, float]:
        seen = seen or set()
        if cid in ("0", _ROOT_LAYER_ID, None) or cid not in raw or cid in seen:
            return (0.0, 0.0)
        seen.add(cid)
        g = raw[cid]["geom"] or {}
        px, py = origin(str(raw[cid]["parent"]), seen)
        return (px + (g.get("x") or 0.0), py + (g.get("y") or 0.0))

    geo = DiagramGeometry()

    for cid in boundary_ids:
        g = raw[cid]["geom"]
        if g and g.get("w"):
            ax, ay = origin(cid)
            geo.containers[cid] = Box(cid, ax, ay, float(g["w"]), float(g["h"]))

    for cid, d in raw.items():
        if not d["vertex"] or cid in boundary_ids:
            continue
        if _is_text_style(str(d["style"]).lower()):
            continue
        if d["parent"] not in node_parents:
            continue
        g = d["geom"]
        if not g or not g.get("w"):
            continue
        ax, ay = origin(cid)
        geo.nodes[cid] = Box(cid, ax, ay, float(g["w"]), float(g["h"]))

    for cid, d in raw.items():
        if not d["edge"]:
            continue
        st = str(d["cell"])
        geo.edges.append(
            EdgeGeom(
                id=cid,
                source=d["source"] or "",
                target=d["target"] or "",
                orthogonal="orthogonaledgestyle" in st.lower(),
                exit=(_style_num(st, "exitX"), _style_num(st, "exitY")),
                entry=(_style_num(st, "entryX"), _style_num(st, "entryY")),
                points=list((d["geom"] or {}).get("points") or []),
                end_arrow=_style_token(st, "endArrow"),
                end_fill=(int(_style_num(st, "endFill")) if _style_num(st, "endFill") is not None else None),
                stroke_width=_style_num(st, "strokeWidth"),
            )
        )

    return geo


# --------------------------------------------------------------------------- #
# Geometry-aware checks (pure; return the offending items, empty == clean)
# --------------------------------------------------------------------------- #


def check_grid_alignment(geo: DiagramGeometry, grid: int = GRID) -> List[str]:
    """Return ids of nodes whose absolute x or y is not a multiple of ``grid``.

    Coordinates are compared after rounding to the nearest integer so that a
    value carrying float noise from accumulated coordinate math (e.g.
    ``219.9999999``) is judged against its intended integer origin rather than
    the raw float — the origins this engine emits are whole ``grid`` multiples,
    and a sub-pixel drift is not a real misalignment. (Node coordinates are
    always numeric here: :func:`build_geometry`'s ``origin`` coalesces a missing
    ``x``/``y`` to ``0.0`` before the box is built, so this never sees ``None``.)"""
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
    """Return ``(node_id, container_id, min_pad)`` where a node inside a
    container leaves less than ``pad`` on some side (or straddles the border).

    The node is measured by its **footprint** (icon + caption band), so a label
    that reaches the container border is caught even when the icon clears it. A
    node is considered "inside" a container when its footprint sits within the
    container region; the smallest of the four side gaps is compared to
    ``pad``."""
    out: List[Tuple[str, str, float]] = []
    for ncid, node in geo.nodes.items():
        n = node.footprint(label_band)
        for ccid, c in geo.containers.items():
            inside = c.x <= n.x and c.y <= n.y and n.right <= c.right and n.bottom <= c.bottom
            if not inside:
                # Straddling: overlaps the container region but not fully inside.
                straddles = (
                    n.x < c.right and c.x < n.right and n.y < c.bottom and c.y < n.bottom
                )
                if straddles:
                    out.append((ncid, ccid, 0.0))
                continue
            min_pad = min(n.x - c.x, n.y - c.y, c.right - n.right, c.bottom - n.bottom)
            if min_pad < pad:
                out.append((ncid, ccid, float(min_pad)))
    return out


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


def check_edge_direction(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for edges that break the directional contract.

    The contract (diagram-standards Edge Routing → "The directional contract"):
    an edge **exits** its source on the **right or bottom** and **enters** its
    target on the **left or top**. In draw.io fractions that means the exit
    point sits on the right/bottom half (``exitX >= 0.5`` or ``exitY >= 0.5``)
    and the entry point on the left/top half (``entryX <= 0.5`` or
    ``entryY <= 0.5``).

    A point is read as position within the node's unit square: ``x`` grows to
    the right, ``y`` grows downward. A valid **exit** leans to the right
    (``exitX >= 0.5``, which admits the right edge and the top-right/bottom-right
    corners) or sits on the bottom edge (``exitY == 1``). A valid **entry** leans
    to the left (``entryX <= 0.5``) or sits on the top edge (``entryY == 0``). A
    left-edge exit like ``(0, 0.5)`` or a right-edge entry like ``(1, 0.5)`` is
    the defect this catches.

    This is enforced only for edges that declare explicit contact points
    (``exitX/exitY`` / ``entryX/entryY``); an edge that floats its connection is
    left to draw.io's perimeter router and not judged here. A ``exit-<side>`` or
    ``enter-<side>`` reason names the violated half."""
    out: List[Tuple[str, str]] = []
    for e in geo.edges:
        ex, ey = e.exit
        nx, ny = e.entry
        # An edge is judged only if it pins at least one contact axis; a fully
        # floating edge is left to the perimeter router.
        #
        # A pinned axis is judged only against its OWN side of the contract, so
        # an edge that pins just one axis on the correct side is not flagged for
        # the unset complementary axis (the earlier logic false-flagged e.g. a
        # right-face exit given as exitX>=0.5 with exitY unset only when it read
        # exitY, and a right-face band given as exitY alone). Concretely:
        #   * a valid exit leans right (exitX >= 0.5) OR sits on the bottom
        #     (exitY == 1); the defect is a pinned left-edge exit (exitX < 0.5)
        #     or a pinned top-edge exit (exitY == 0) that no right/bottom pin
        #     rescues.
        #   * a valid entry leans left (entryX <= 0.5) OR sits on the top
        #     (entryY == 0); the defect is a pinned right-edge entry
        #     (entryX > 0.5) or a pinned bottom-edge entry (entryY == 1) that no
        #     left/top pin rescues.
        if ex is not None or ey is not None:
            exit_right_or_bottom = (ex is not None and ex >= 0.5) or (ey is not None and ey >= 1.0)
            exit_wrong = (ex is not None and ex < 0.5) or (ey is not None and ey <= 0.0)
            if exit_wrong and not exit_right_or_bottom:
                out.append((e.id, "exit-not-right-or-bottom"))
                continue
        if nx is not None or ny is not None:
            entry_left_or_top = (nx is not None and nx <= 0.5) or (ny is not None and ny <= 0.0)
            entry_wrong = (nx is not None and nx > 0.5) or (ny is not None and ny >= 1.0)
            if entry_wrong and not entry_left_or_top:
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
    length = (dx * dx + dy * dy) ** 0.5
    # At least 61 samples (the historical floor for short runs), and more for a
    # long run so spacing never exceeds _SEGMENT_SAMPLE_STEP.
    steps = max(60, int(length / _SEGMENT_SAMPLE_STEP))
    for i in range(steps + 1):
        t = i / steps
        px = p[0] + dx * t
        py = p[1] + dy * t
        if b.x + inset <= px <= b.right - inset and b.y + inset <= py <= b.bottom - inset:
            return True
    return False


def check_edge_routing(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return ``(edge_id, reason)`` for edges that break routing rules.

    Conservative to avoid false positives on validly routed diagrams:

    * a non-orthogonal edge is always flagged (``not-orthogonal``);
    * a **waypoint-free** edge whose straight run between its real contact
      points passes through an unrelated node is flagged
      (``straight-through-<node>``). An edge with explicit waypoints is assumed
      deliberately routed and is not flagged on the crossing criterion.
    """
    out: List[Tuple[str, str]] = []
    nodes = geo.nodes
    for e in geo.edges:
        if not e.orthogonal:
            out.append((e.id, "not-orthogonal"))
            continue
        if e.source not in nodes or e.target not in nodes:
            continue
        if e.points:
            continue  # author laid explicit waypoints — deliberate routing
        s, t = nodes[e.source], nodes[e.target]
        ex = e.exit[0] if e.exit[0] is not None else 1.0
        ey = e.exit[1] if e.exit[1] is not None else 0.5
        nx = e.entry[0] if e.entry[0] is not None else 0.0
        ny = e.entry[1] if e.entry[1] is not None else 0.5
        p = (s.x + ex * s.w, s.y + ey * s.h)
        q = (t.x + nx * t.w, t.y + ny * t.h)
        for other, b in nodes.items():
            if other in (e.source, e.target):
                continue
            # Sample the straight segment; a 2px inset means a mere graze of a
            # border does not count as a crossing.
            if segment_crosses_box(p, q, b):
                out.append((e.id, f"straight-through-{other}"))
                break
    return out


def check_edge_crosses_label(geo: DiagramGeometry, label_band: float = LABEL_BAND) -> List[Tuple[str, str]]:
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
    the geometry rules alone (which measure icon boxes) would miss."""
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
        for other, b in nodes.items():
            if other in (e.source, e.target):
                continue
            # The label band is the strip BELOW the icon (icon bottom .. +band).
            band = Box(other, b.x, b.bottom, b.w, label_band)
            crossed = any(
                segment_crosses_box(p, q, band)
                for p, q in zip(polyline, polyline[1:])
            )
            if crossed:
                out.append((e.id, other))
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
    out: List[Tuple[str, str]] = []
    ids = list(edge_segs)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            # A shared trunk is legitimate (diagram-standards "shared trunk,
            # opposite branches"): two edges that leave the SAME source (or reach
            # the same target) may share their stub before branching. Two edges
            # in a CHAIN through one node (target of one is the source of the
            # other, e.g. app→db and db→db') naturally touch that node's opposite
            # faces at its centre row — that shared contact point is the node, not
            # a merged corridor. Only flag genuinely unrelated edges.
            if (
                src_of[a] == src_of[b]
                or tgt_of[a] == tgt_of[b]
                or tgt_of[a] == src_of[b]
                or tgt_of[b] == src_of[a]
            ):
                continue
            shared = False
            for oa, la, loa, hia in edge_segs[a]:
                for ob, lb, lob, hib in edge_segs[b]:
                    if oa == ob and la == lb and loa < hib and lob < hia:
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
