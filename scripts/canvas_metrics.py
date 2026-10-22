#!/usr/bin/env python3
"""Model-space canvas metrics for a ``.drawio`` corpus (1.10.12 WS0).

Why this exists
---------------
The 1.10.12 plan (``.agents/tasks/1.10.12-engine-plan.md``) judges every
routing / layout workstream against a measured baseline, never against PNG
sizes: an exported raster is upscaled by the exporter, so its pixel size says
nothing about how the engine used the canvas. Everything here is measured on
the **model** (draw.io units) parsed by the engine's own single parser
(:func:`rule_engine.drawio_model.parse_drawio` +
:func:`rule_engine.geometry.build_geometry`), so the numbers cannot drift from
what the linter sees.

Metrics (one row per diagram page)
----------------------------------
``bbox``           Width x height of the model bounding box: every node icon
                   and its caption (:func:`node_caption_box`), every container,
                   every text cell (title / Flow / Legend) and every edge
                   waypoint.
``page_ok``        ``mxGraphModel@pageWidth/pageHeight`` cover the bbox right /
                   bottom edge (defect C14). ``n`` names the short axis.
``util``           Content coverage, the ``canvas-quality`` lint definition:
                   (outer containers + nodes outside every container) / bbox of
                   nodes + containers + text cells.
``ler_out``        Largest empty axis-aligned rectangle on the canvas (bbox),
                   with node footprints (icon + caption), text cells and outer
                   containers as obstacles; ``w x h`` and % of bbox area.
``ler_in``         Largest empty rectangle INSIDE a container, with its direct
                   child node footprints, nested containers and its own top
                   caption strip as obstacles; ``w x h``, max over containers.
``X``              Edge-edge crossings, counted exactly as
                   :func:`rule_engine.geometry.route_cost` does (H x V proper
                   intersections of the polylines).
``Xav``            Avoidable crossings (1.10.12 WS3): how many crossings a greedy
                   sequence of single-edge legal face swaps removes WITHOUT adding
                   a routing finding -- the shared definition of
                   :func:`rule_engine.crossing_repair.avoidable_crossings`, which
                   the ``edge-crossing-avoidable`` lint rule and the engine's final
                   crossing-repair pass use too.
``Xraw``           The WS0 definition of ``Xav`` (kept for comparison with the
                   baseline): candidates are admitted on icon / caption / text-cell
                   clearance only, so a swap that would add another finding (a
                   shared corridor, a container crossed) still counts. A swap re-routes ONE
                   edge between face-centre contacts on a different legal face
                   pair (exit right/bottom, entry left/top, at least one face
                   changed), via a short stub + one lane (the edge's own stub
                   coordinates, the mid line, or 1-3 grid lanes outside the two
                   end boxes). A candidate is admitted only when it crosses no
                   node icon, no node caption (its own included), and no text
                   cell; a swap is kept only when it strictly lowers the total
                   crossing count. Each edge swaps at most once.
``back``           Back-edges: the target centre lies left of the source centre
                   (by more than one grid step) on the left -> right lane axis.
``own``            Own-caption cuts: an edge whose polyline crosses its own
                   source's or target's caption rectangle (defect C1). Purely
                   geometric: a line masked by ``labelBackgroundColor`` still
                   counts.
``vis``            Visible own-caption strikes (1.10.12 WS2): the subset of
                   ``own`` whose polyline crosses the caption's real TEXT
                   extent (:func:`geometry.caption_text_box`, no icon-width
                   floor), not merely the empty corner of the caption band.
``col``            Collinear pairs (defect C5): two edges with parallel legs
                   (each >= 2 grid steps long) whose lines are < 2 grid steps
                   apart and whose extents overlap or leave a gap of at most
                   ``COLLINEAR_GAP`` along the line, so they read as one line.
                   Two legs that meet at a shared point of edges sharing an
                   endpoint node (a sanctioned trunk junction) are exempt.
``capovf``         Container caption overflows (defect C4): the caption text
                   (longest line x 7.0 px/char + the style's spacing) is wider
                   than its container.
``undrawn``        Flow legend steps ``N.`` with no edge carrying marker ``N``
                   and no ``(not drawn)`` note (defect C2).
``comp``           Connected components of the node graph (``comp/orph``:
                   components and degree-0 nodes; defects C2/C3).
``sib``            Sibling-size spread (defect C8): sibling containers (same
                   tightest parent) aligned in a column (left edges within one
                   grid step) or a row (tops within one grid step). Reported as
                   ``same/raw``: the largest width (column) or height (row)
                   spread among siblings with the same direct-node count, and
                   the largest spread regardless of count.

Usage::

    .venv/bin/python scripts/canvas_metrics.py                 # corpus + SEP
    .venv/bin/python scripts/canvas_metrics.py FILE ...        # given files
    .venv/bin/python scripts/canvas_metrics.py --detail FILE   # name offenders
    .venv/bin/python scripts/canvas_metrics.py --json          # machine form

With no files it measures ``examples/**/*.drawio`` (corpus goldens) and
``tests/fixtures/sep/**/*.drawio`` (SEP regression fixtures). Exit status: 0
when every file parsed, 2 when one did not (it is still reported).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rule_engine.crossing_repair import avoidable_crossings as _avoidable  # noqa: E402
from rule_engine.drawio_model import DrawioParseError, parse_drawio  # noqa: E402
from rule_engine.geometry import (  # noqa: E402
    AXIS_EPS,
    CONTAINER_LABEL_BAND,
    GRID,
    LABEL_BAND,
    Box,
    DiagramGeometry,
    EdgeGeom,
    _tightest_enclosing,
    build_geometry,
    caption_lines,
    check_edge_strikes_own_text,
    container_caption_need,
    largest_empty_rect as _largest_empty_rect,
    collinear_edge_pairs,
    collapse_collinear,
    contact_faces,
    edge_polyline,
    leg_axis,
    node_caption_box,
    segment_crosses_box,
    segments_cross,
)

Point = Tuple[float, float]

#: Default corpus: committed goldens + SEP regression fixtures.
DEFAULT_GLOBS = ("examples/**/*.drawio", "tests/fixtures/sep/**/*.drawio")

#: Avoidable crossings: stub length out of a face before the first turn.
STUB = 2 * GRID
#: Container caption: per-char advance and draw.io default label spacing,
#: the same estimators the linter's container-caption checks use.
CAPTION_CHAR_W = 7.0
DRAWIO_SPACING = 2.0
#: Largest-empty-rectangle raster cell (model units).
LER_CELL = GRID

_FACE_NORMAL = {"right": (1, 0), "bottom": (0, 1), "left": (-1, 0), "top": (0, -1)}
_FACE_FRAC = {"right": (1.0, 0.5), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "top": (0.5, 0.0)}
_PAGE_ATTR_RE = re.compile(r'<mxGraphModel\b[^>]*>', re.S)
_FLOW_STEP_RE = re.compile(r"^\s*(\d+)\s*[.)]")
_MARKER_RE = re.compile(r"\d+")


# --------------------------------------------------------------------------- #
# Result row
# --------------------------------------------------------------------------- #


@dataclass
class Metrics:
    diagram: str
    diagram_class: str = "flow"
    nodes: int = 0
    edges: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    page_w: Optional[int] = None
    page_h: Optional[int] = None
    page_ok: bool = True
    utilisation: float = 0.0
    ler_out_w: int = 0
    ler_out_h: int = 0
    ler_out_pct: float = 0.0
    ler_in_w: int = 0
    ler_in_h: int = 0
    ler_in_container: str = ""
    crossings: int = 0
    avoidable: int = 0
    avoidable_raw: int = 0
    back_edges: int = 0
    own_caption_cuts: int = 0
    own_text_strikes: int = 0
    collinear_pairs: int = 0
    caption_overflows: int = 0
    undrawn_steps: int = 0
    components: int = 0
    orphans: int = 0
    sibling_spread_same: int = 0
    sibling_spread_raw: int = 0
    error: str = ""
    detail: Dict[str, list] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _companion_class(drawio: Path) -> str:
    md = drawio.with_name(drawio.name[: -len(".drawio")] + ".diagram.md")
    if not md.is_file():
        return "flow"
    m = re.search(r"^diagram_class:\s*([A-Za-z_-]+)", md.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "flow"


def _page_sizes(text: str) -> List[Tuple[Optional[int], Optional[int]]]:
    out = []
    for m in _PAGE_ATTR_RE.finditer(text):
        tag = m.group(0)
        pw = re.search(r'\bpageWidth="([\d.]+)"', tag)
        ph = re.search(r'\bpageHeight="([\d.]+)"', tag)
        out.append((int(float(pw.group(1))) if pw else None,
                    int(float(ph.group(1))) if ph else None))
    return out


def _caption(geo: DiagramGeometry, nid: str) -> Optional[Box]:
    label = geo.node_labels.get(nid, "")
    if not caption_lines(label):
        return None
    return node_caption_box(geo.nodes[nid], label)


def _footprint(geo: DiagramGeometry, nid: str) -> List[Box]:
    box = geo.nodes[nid]
    cap = _caption(geo, nid)
    return [box] + ([cap] if cap else [])


def _polylines(geo: DiagramGeometry) -> Dict[str, List[Point]]:
    out = {}
    for e in geo.edges:
        poly = edge_polyline(geo, e)
        if len(poly) >= 2:
            out[e.id] = poly
    return out


def _pair_crossings(a: Sequence[Point], b: Sequence[Point]) -> int:
    return sum(1 for s1 in zip(a, a[1:]) for s2 in zip(b, b[1:]) if segments_cross(s1, s2))


def _bbox(boxes: Iterable[Box], points: Iterable[Point] = ()) -> Optional[Box]:
    xs0, ys0, xs1, ys1 = [], [], [], []
    for b in boxes:
        xs0.append(b.x); ys0.append(b.y); xs1.append(b.right); ys1.append(b.bottom)
    for x, y in points:
        xs0.append(x); ys0.append(y); xs1.append(x); ys1.append(y)
    if not xs0:
        return None
    return Box("bbox", min(xs0), min(ys0), max(xs1) - min(xs0), max(ys1) - min(ys0))


# --------------------------------------------------------------------------- #
# Largest empty rectangle (maximal-rectangle-in-histogram over a cell raster)
# --------------------------------------------------------------------------- #


# Shared with the ``canvas-quality`` lint rule (1.10.12 WS6): one definition.
largest_empty_rect = _largest_empty_rect


# --------------------------------------------------------------------------- #
# Avoidable crossings (greedy single-edge legal face swaps)
# --------------------------------------------------------------------------- #


def _faces_of(frac: Tuple[Optional[float], Optional[float]], legal: Tuple[str, str]) -> Set[str]:
    return set(contact_faces(*frac)) & set(legal)


def _candidate_routes(geo: DiagramGeometry, e: EdgeGeom) -> List[Tuple[str, List[Point]]]:
    src, tgt = geo.nodes[e.source], geo.nodes[e.target]
    cur_exit = _faces_of(e.exit, ("right", "bottom"))
    cur_entry = _faces_of(e.entry, ("left", "top"))
    out: List[Tuple[str, List[Point]]] = []
    for fx in ("right", "bottom"):
        for fn in ("left", "top"):
            if fx in cur_exit and fn in cur_entry:
                continue  # not a swap: both faces unchanged
            ex, ey = _FACE_FRAC[fx]
            nx_, ny_ = _FACE_FRAC[fn]
            P = (src.x + ex * src.w, src.y + ey * src.h)
            Q = (tgt.x + nx_ * tgt.w, tgt.y + ny_ * tgt.h)
            A = (P[0] + STUB * _FACE_NORMAL[fx][0], P[1] + STUB * _FACE_NORMAL[fx][1])
            B = (Q[0] + STUB * _FACE_NORMAL[fn][0], Q[1] + STUB * _FACE_NORMAL[fn][1])
            cap_s, cap_t = _caption(geo, src.id), _caption(geo, tgt.id)
            low = max(src.bottom, tgt.bottom,
                      cap_s.bottom if cap_s else 0.0, cap_t.bottom if cap_t else 0.0)
            ys = {A[1], B[1], round((A[1] + B[1]) / 2 / GRID) * GRID}
            xs = {A[0], B[0], round((A[0] + B[0]) / 2 / GRID) * GRID}
            for k in (1, 2, 3):
                ys.add(min(src.y, tgt.y) - k * STUB)
                ys.add(low + k * STUB)
                xs.add(min(src.x, tgt.x) - k * STUB)
                xs.add(max(src.right, tgt.right) + k * STUB)
            tag = f"{fx}->{fn}"
            for y in sorted(ys):
                out.append((tag, collapse_collinear([P, A, (A[0], y), (B[0], y), B, Q])))
            for x in sorted(xs):
                out.append((tag, collapse_collinear([P, A, (x, A[1]), (x, B[1]), B, Q])))
    return out


def _route_admissible(geo: DiagramGeometry, route: List[Point], obstacles: Sequence[Box]) -> bool:
    if len(route) < 2:
        return False
    if any(leg_axis(p, q) not in ("H", "V") for p, q in zip(route, route[1:])):
        return False
    return not any(
        segment_crosses_box(p, q, b) for p, q in zip(route, route[1:]) for b in obstacles
    )


def avoidable_crossings_raw(geo: DiagramGeometry, polys: Dict[str, List[Point]]) -> Tuple[int, List[str]]:
    """The WS0 ``Xav`` definition (now ``Xraw``), unchanged."""
    edges = {e.id: e for e in geo.edges if e.id in polys}
    obstacles: List[Box] = list(geo.text_boxes.values())
    for nid in geo.nodes:
        obstacles.extend(_footprint(geo, nid))
    polys = dict(polys)
    ids = sorted(polys)

    def edge_x(eid: str, poly: Sequence[Point]) -> int:
        return sum(_pair_crossings(poly, polys[o]) for o in ids if o != eid)

    total0 = sum(_pair_crossings(polys[a], polys[b]) for i, a in enumerate(ids) for b in ids[i + 1:])
    swapped: Set[str] = set()
    applied: List[str] = []
    cand_cache: Dict[str, List[Tuple[str, List[Point]]]] = {}
    while True:
        best = None  # (gain, eid, tag, route)
        for eid in ids:
            if eid in swapped:
                continue
            cur = edge_x(eid, polys[eid])
            if cur == 0:
                continue
            if eid not in cand_cache:
                e = edges[eid]
                # WS10: a boundary-to-boundary edge (container endpoint) is not
                # face-swappable (no node box to re-anchor); it has no avoidable
                # candidates.
                if e.source not in geo.nodes or e.target not in geo.nodes:
                    cand_cache[eid] = []
                else:
                    cand_cache[eid] = [
                        (tag, r) for tag, r in _candidate_routes(geo, e)
                        if _route_admissible(geo, r, obstacles)
                    ]
            for tag, route in cand_cache[eid]:
                gain = cur - edge_x(eid, route)
                if gain > 0 and (best is None or gain > best[0]):
                    best = (gain, eid, tag, route)
        if best is None:
            break
        gain, eid, tag, route = best
        polys[eid] = route
        swapped.add(eid)
        applied.append(f"{eid} {tag} -{gain}")
    total1 = sum(_pair_crossings(polys[a], polys[b]) for i, a in enumerate(ids) for b in ids[i + 1:])
    return total0 - total1, applied


# --------------------------------------------------------------------------- #
# Individual metrics
# --------------------------------------------------------------------------- #


def own_caption_cuts(geo: DiagramGeometry, polys: Dict[str, List[Point]]) -> List[str]:
    out = []
    for e in geo.edges:
        poly = polys.get(e.id)
        if not poly:
            continue
        for nid in {e.source, e.target}:
            cap = _caption(geo, nid) if nid in geo.nodes else None
            if cap and any(segment_crosses_box(p, q, cap) for p, q in zip(poly, poly[1:])):
                out.append(f"{e.id}@{nid}")
    return sorted(out)


def collinear_pairs(geo: DiagramGeometry, polys: Dict[str, List[Point]]) -> List[str]:
    return sorted(f"{x}~{y}" for x, y in collinear_edge_pairs(geo, polys))


def caption_overflows(geo: DiagramGeometry) -> List[str]:
    """Containers whose caption is wider than the box (shared with the
    ``container-caption-overflow`` lint rule, 1.10.12 WS6)."""
    out = []
    for cid, box in geo.containers.items():
        need = container_caption_need(geo.container_labels.get(cid, ""),
                                      geo.container_styles.get(cid, ""))
        if need > box.w:
            out.append(f"{cid}(+{int(need - box.w)})")
    return sorted(out)


def undrawn_steps(page_cells, geo: DiagramGeometry) -> List[str]:
    markers: Set[int] = set()
    for e in geo.edges:
        lab = (e.label or "").strip()
        if lab and re.fullmatch(r"[\d\s,/&+-]+", lab):
            markers.update(int(m) for m in _MARKER_RE.findall(lab))
    out = []
    for cell in page_cells.values():
        lines = cell.lines
        if not cell.vertex or not lines or lines[0].strip() != "Flow":
            continue
        for ln in lines[1:]:
            m = _FLOW_STEP_RE.match(ln)
            if m and int(m.group(1)) not in markers and "(not drawn)" not in ln.lower():
                out.append(m.group(1))
    return sorted(set(out), key=int)


def components(geo: DiagramGeometry) -> Tuple[int, List[str]]:
    parent = {n: n for n in geo.nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    deg = {n: 0 for n in geo.nodes}
    for e in geo.edges:
        if e.source in parent and e.target in parent:
            deg[e.source] += 1
            deg[e.target] += 1
            parent[find(e.source)] = find(e.target)
    roots = {find(n) for n in geo.nodes}
    return len(roots), sorted(n for n, d in deg.items() if d == 0)


def sibling_spread(geo: DiagramGeometry) -> Tuple[int, int, List[str]]:
    # Sorted: build_geometry fills containers from a set, so their order follows
    # PYTHONHASHSEED; sorting keeps tie-breaks (and the baseline) reproducible.
    conts = sorted(geo.containers.values(), key=lambda b: b.id)
    parent_of = {c.id: (_tightest_enclosing(c, conts).id if _tightest_enclosing(c, conts) else "")
                 for c in conts}
    direct_nodes = {c.id: 0 for c in conts}
    for nid, b in geo.nodes.items():
        p = _tightest_enclosing(b, conts)
        if p is not None:
            direct_nodes[p.id] += 1
    same_best = raw_best = 0
    notes: List[str] = []
    groups: Dict[str, List[Box]] = {}
    for c in conts:
        groups.setdefault(parent_of[c.id], []).append(c)
    for sibs in groups.values():
        for key, dim, axis in ((lambda b: b.x, lambda b: b.w, "col"),
                               (lambda b: b.y, lambda b: b.h, "row")):
            pool = sorted(sibs, key=key)
            clusters: List[List[Box]] = []
            for b in pool:
                if clusters and abs(key(b) - key(clusters[-1][0])) <= GRID:
                    clusters[-1].append(b)
                else:
                    clusters.append([b])
            for cl in clusters:
                if len(cl) < 2:
                    continue
                raw = int(max(dim(b) for b in cl) - min(dim(b) for b in cl))
                by_count: Dict[int, List[float]] = {}
                for b in cl:
                    by_count.setdefault(direct_nodes[b.id], []).append(dim(b))
                same = int(max((max(v) - min(v)) for v in by_count.values()))
                raw_best = max(raw_best, raw)
                same_best = max(same_best, same)
                if raw:
                    notes.append(
                        f"{axis}@{int(key(cl[0]))}: "
                        + ", ".join(f"{b.id}={int(dim(b))}/n{direct_nodes[b.id]}" for b in cl)
                    )
    return same_best, raw_best, notes


# --------------------------------------------------------------------------- #
# Per-page driver
# --------------------------------------------------------------------------- #


def measure_page(label: str, page, page_size, diagram_class: str) -> Metrics:
    geo = build_geometry(page)
    polys = _polylines(geo)
    m = Metrics(diagram=label, diagram_class=diagram_class,
                nodes=len(geo.nodes), edges=len(geo.edges))

    # bbox (full: icons + captions + containers + text + waypoints)
    boxes: List[Box] = list(geo.containers.values()) + list(geo.text_boxes.values())
    for nid in geo.nodes:
        boxes.extend(_footprint(geo, nid))
    pts = [p for poly in polys.values() for p in poly]
    bb = _bbox(boxes, pts)
    if bb is None:
        return m
    m.bbox_w, m.bbox_h = int(round(bb.w)), int(round(bb.h))
    m.page_w, m.page_h = page_size
    short = []
    if m.page_w is not None and m.page_w < bb.right:
        short.append(f"w {m.page_w}<{int(bb.right)}")
    if m.page_h is not None and m.page_h < bb.bottom:
        short.append(f"h {m.page_h}<{int(bb.bottom)}")
    m.page_ok = not short
    m.detail["page"] = short

    # utilisation (canvas-quality lint definition)
    # Sorted: build_geometry fills containers from a set, so their order follows
    # PYTHONHASHSEED; sorting keeps tie-breaks (and the baseline) reproducible.
    conts = sorted(geo.containers.values(), key=lambda b: b.id)
    lint_bb = _bbox(list(geo.nodes.values()) + conts + list(geo.text_boxes.values()))
    outers = [c for c in conts if _tightest_enclosing(c, conts) is None]
    content = sum(c.w * c.h for c in outers)
    content += sum(n.w * n.h for n in geo.nodes.values() if _tightest_enclosing(n, conts) is None)
    m.utilisation = round(content / (lint_bb.w * lint_bb.h), 3) if lint_bb and lint_bb.w * lint_bb.h else 0.0

    # largest empty rectangles
    obst = list(geo.text_boxes.values()) + outers
    for nid in geo.nodes:
        obst.extend(_footprint(geo, nid))
    m.ler_out_w, m.ler_out_h = largest_empty_rect(bb, obst)
    m.ler_out_pct = round(100.0 * m.ler_out_w * m.ler_out_h / (bb.w * bb.h), 1)
    best_in = (0, 0, 0, "")
    for c in conts:
        inner = [Box("cap", c.x, c.y, c.w, CONTAINER_LABEL_BAND)]
        for o in conts:
            if o.id != c.id and _tightest_enclosing(o, conts) is c:
                inner.append(o)
        for nid, nb in geo.nodes.items():
            if _tightest_enclosing(nb, conts) is c:
                inner.extend(_footprint(geo, nid))
        w, h = largest_empty_rect(c, inner)
        if w * h > best_in[0]:
            best_in = (w * h, w, h, c.id)
    _, m.ler_in_w, m.ler_in_h, m.ler_in_container = best_in

    # crossings
    ids = sorted(polys)
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            n = _pair_crossings(polys[a], polys[b])
            if n:
                m.crossings += n
                pairs.append(f"{a}x{b}" + (f"({n})" if n > 1 else ""))
    m.detail["crossings"] = pairs
    m.avoidable, m.detail["avoidable"] = _avoidable(geo) if m.crossings else (0, [])
    m.avoidable_raw, m.detail["avoidable_raw"] = (
        avoidable_crossings_raw(geo, polys) if m.crossings else (0, []))

    # back-edges
    back = []
    for e in geo.edges:
        s, t = geo.nodes.get(e.source), geo.nodes.get(e.target)
        if s and t and t.center()[0] < s.center()[0] - GRID:
            back.append(e.id)
    m.back_edges = len(back)
    m.detail["back_edges"] = back

    m.detail["own_caption_cuts"] = own_caption_cuts(geo, polys)
    m.own_caption_cuts = len(m.detail["own_caption_cuts"])
    m.detail["own_text_strikes"] = sorted(f"{e}@{n}" for e, n in check_edge_strikes_own_text(geo))
    m.own_text_strikes = len(m.detail["own_text_strikes"])
    m.detail["collinear"] = collinear_pairs(geo, polys)
    m.collinear_pairs = len(m.detail["collinear"])
    m.detail["caption_overflows"] = caption_overflows(geo)
    m.caption_overflows = len(m.detail["caption_overflows"])
    m.detail["undrawn_steps"] = undrawn_steps(page.cells, geo)
    m.undrawn_steps = len(m.detail["undrawn_steps"])
    m.components, m.detail["orphans"] = components(geo)
    m.orphans = len(m.detail["orphans"])
    m.sibling_spread_same, m.sibling_spread_raw, m.detail["siblings"] = sibling_spread(geo)
    return m


def measure_file(path: Path) -> List[Metrics]:
    try:
        label = str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        label = str(path)
    text = path.read_text(encoding="utf-8")
    try:
        pages = parse_drawio(text, path=str(path))
    except DrawioParseError as exc:
        return [Metrics(diagram=label, error=f"parse-error:{exc.cause}")]
    sizes = _page_sizes(text)
    cls = _companion_class(path)
    out = []
    for i, page in enumerate(pages):
        name = label if len(pages) == 1 else f"{label}#{page.name}"
        size = sizes[i] if i < len(sizes) else (None, None)
        try:
            out.append(measure_page(name, page, size, cls))
        except DrawioParseError as exc:
            out.append(Metrics(diagram=name, error=f"parse-error:{exc.cause}"))
    return out


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

HEADER = ("| diagram | class | N/E | bbox | page | util | ler_out | ler_in | X | Xav | back "
          "| own | vis | col | capovf | undrawn | comp/orph | sib same/raw |")
RULE = "|" + "---|" * 19


def table_row(m: Metrics) -> str:
    if m.error:
        return f"| `{m.diagram}` | {m.error} |" + " |" * 17
    return (
        f"| `{m.diagram}` | {m.diagram_class} | {m.nodes}/{m.edges} | {m.bbox_w}x{m.bbox_h} "
        f"| {'ok' if m.page_ok else 'SHORT'} | {m.utilisation * 100:.0f}% "
        f"| {m.ler_out_w}x{m.ler_out_h} ({m.ler_out_pct:.0f}%) | {m.ler_in_w}x{m.ler_in_h} "
        f"| {m.crossings} | {m.avoidable} | {m.avoidable_raw} | {m.back_edges} | {m.own_caption_cuts} | {m.own_text_strikes} "
        f"| {m.collinear_pairs} | {m.caption_overflows} | {m.undrawn_steps} "
        f"| {m.components}/{m.orphans} | {m.sibling_spread_same}/{m.sibling_spread_raw} |"
    )


def detail_lines(m: Metrics) -> List[str]:
    out = [f"{m.diagram}"]
    for key, vals in m.detail.items():
        if vals:
            out.append(f"    {key}: {'; '.join(vals)}")
    if m.ler_in_container:
        out.append(f"    ler_in: {m.ler_in_w}x{m.ler_in_h} in {m.ler_in_container}")
    return out


def collect(files: Sequence[str]) -> List[Path]:
    if files:
        return [Path(f) for f in files]
    found: List[Path] = []
    for pattern in DEFAULT_GLOBS:
        found.extend(sorted(REPO_ROOT.glob(pattern)))
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="canvas_metrics", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="drawio files (default: corpus + SEP fixtures)")
    ap.add_argument("--detail", action="store_true", help="name the offenders of every metric")
    ap.add_argument("--json", action="store_true", help="emit JSON rows instead of a table")
    args = ap.parse_args(list(argv) if argv is not None else None)

    rows: List[Metrics] = []
    for path in collect(args.files):
        if not path.is_file():
            print(f"error: no such file: {path}", file=sys.stderr)
            return 2
        rows.extend(measure_file(path))

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False))
    else:
        print(HEADER)
        print(RULE)
        for r in rows:
            print(table_row(r))
        if args.detail:
            print()
            for r in rows:
                print("\n".join(detail_lines(r)))
    return 2 if any(r.error for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
