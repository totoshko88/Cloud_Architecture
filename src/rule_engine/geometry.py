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

# The model grid step (draw.io ``gridSize`` default). Spacings and node origins
# are expected to be whole multiples of it (diagram-standards Layout Geometry).
GRID = 10

_CELL_RE = re.compile(r"<mxCell\b[^>]*?(?:/>|>.*?</mxCell>)", re.S)
_GEOM_RE = re.compile(r"<mxGeometry\b[^>]*?(?:/>|>.*?</mxGeometry>)", re.S)
_POINT_RE = re.compile(r'<mxPoint x="([-0-9.]+)" y="([-0-9.]+)"')
_ROOT_LAYER_ID = "1"


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


def _is_boundary_style(cid: str, style_low: str) -> bool:
    """Mirror of ``cli._parse_drawio`` container detection (REVIEW.md C4)."""
    is_group = "group" in style_low or "container=1" in style_low
    is_dashed = "dashed=1" in style_low and "fillcolor=none" in style_low
    is_boundary_group = is_group and ("group_" in style_low or "gricon=" in style_low)
    return cid.startswith("boundary") or is_dashed or is_boundary_group


def _is_text_style(style_low: str) -> bool:
    return style_low.startswith("text;") or "text;" in style_low


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
    """Return ids of nodes whose absolute x or y is not a multiple of ``grid``."""
    out = []
    for cid, b in geo.nodes.items():
        if (b.x % grid) or (b.y % grid):
            out.append(cid)
    return sorted(out)


def check_node_overlap(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Return id pairs whose node boxes overlap (axis-aligned intersection)."""
    boxes = list(geo.nodes.values())
    out: List[Tuple[str, str]] = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom:
                out.append(tuple(sorted((a.id, b.id))))  # type: ignore[arg-type]
    return sorted(set(out))


def check_container_padding(
    geo: DiagramGeometry, pad: int = GRID
) -> List[Tuple[str, str, float]]:
    """Return ``(node_id, container_id, min_pad)`` where a node inside a
    container leaves less than ``pad`` on some side (or straddles the border)."""
    out: List[Tuple[str, str, float]] = []
    for ncid, n in geo.nodes.items():
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
            hit = any(
                b.x + 2 <= p[0] + (q[0] - p[0]) * i / 60.0 <= b.right - 2
                and b.y + 2 <= p[1] + (q[1] - p[1]) * i / 60.0 <= b.bottom - 2
                for i in range(61)
            )
            if hit:
                out.append((e.id, f"straight-through-{other}"))
                break
    return out


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
