"""Crossing-aware contact selection: the final crossing-repair pass (1.10.12 WS3, C7).

Why this exists
---------------
The directional contract (exit right/bottom, enter left/top) leaves an edge up
to four legal face pairs, and the layout engine used to pick the face from a
geometric precondition, not from crossings. SEP 09 ``e3`` (Route 53 →
CloudFront) is the canonical case: a back-edge whose target had a left gap was
always entered on the LEFT face, where ``e1`` already arrived, so its drop cut
``e1``; the TOP entry was legal, shorter and crossing-free. The scored search
now offers face variants (:mod:`rule_engine.layout.variants`), but routing is
greedy per edge and the caption planner (WS2) re-routes afterwards, so a
crossing a single legal face swap could remove can still survive. This pass
removes it on the finished document.

What it does
------------
:func:`plan_crossing_repair` takes the parsed geometry of a finished diagram
(the linter's view: real caption widths, wrapped captions, every obstacle) and,
for every crossing pair, tries contract-legal alternatives:

* **single re-route** of either edge: every legal exit/entry face pair (right
  exit; a bottom exit only from a source with no caption, Variant A), entry
  slots kept distinct from the face's other contacts, with stub + one lane
  shapes and the WS2 side-corridor shapes;
* **corridor swap** of two edges converging on one target face (or diverging
  from one source face): their approach (or departure) corridors trade places,
  so the nesting follows the source order (SEP 01 ``e4``/``e5``);
* **joint re-route** of the two edges together.

Candidates are pre-filtered with the WS2 cheap geometry
(:func:`rule_engine.caption_routing._admissible`: head-on axis-aligned legs, no
icon / caption / text box / foreign container / container caption crossed, no
detour hook, no shared corridor, no border ride) and scored on the full
routing oracle. A move is kept **only** when the crossing count drops and no
new finding appears: no routing error, warning, collinear pair, own-caption
cut or caption strike is added, and no finding absent before shows up.

:func:`avoidable_crossings` is the measuring side (``scripts/canvas_metrics.py``
``Xav`` and the ``edge-crossing-avoidable`` lint rule): how many crossings a
greedy sequence of single-edge legal face swaps removes. Both sides share the
candidate generator, so what the lint calls avoidable is what the repair tries.

Pure and deterministic: candidates are enumerated in a fixed order, ties break
on that order, and nothing depends on unordered iteration.
"""
from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from rule_engine import caption_routing as _cr
from rule_engine.caption_routing import CaptionPlan, Route
from rule_engine.geometry import (
    AXIS_EPS,
    GRID,
    Box,
    DiagramGeometry,
    EdgeGeom,
    caption_lines,
    collapse_collinear,
    collinear_edge_pairs,
    contact_faces,
    edge_polyline,
    grid_resolve_contact,
    leg_axis,
    node_caption_box,
    segment_crosses_box,
    segments_cross,
)

Point = Tuple[float, float]

#: Stub length out of / into a face before the first / after the last turn.
STUB = 2 * GRID
#: Lane offsets (in stubs) tried outside the two end boxes.
_LANE_K = (1, 2, 3)
#: Candidates per edge (or pair) that reach the full oracle.
_ORACLE_BUDGET = 16
#: Joint search: candidates kept per member.
_JOINT_POOL = 80
#: Passes over the crossing pairs (a later move can free a face for an earlier one).
_MAX_PASSES = 4

_FACE_NORMAL = {"right": (1, 0), "bottom": (0, 1), "left": (-1, 0), "top": (0, -1)}


# --------------------------------------------------------------------------- #
# Crossings
# --------------------------------------------------------------------------- #


def _pair_x(a: Sequence[Point], b: Sequence[Point]) -> int:
    return sum(1 for s1 in zip(a, a[1:]) for s2 in zip(b, b[1:]) if segments_cross(s1, s2))


def crossing_pairs(geo: DiagramGeometry) -> List[Tuple[str, str, int]]:
    """``(a, b, n)`` for every crossing edge pair (ids sorted), route_cost's count."""
    polys = _cr._polylines(geo)
    ids = sorted(polys)
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            n = _pair_x(polys[a], polys[b])
            if n:
                out.append((a, b, n))
    return out


# --------------------------------------------------------------------------- #
# Candidate shapes
# --------------------------------------------------------------------------- #


def _has_caption(geo: DiagramGeometry, nid: str) -> bool:
    return bool(caption_lines(geo.node_labels.get(nid, "")))


def _exits(geo: DiagramGeometry, e: EdgeGeom) -> List[Tuple[Point, Tuple[float, float], str]]:
    """Free legal exits: the right face (centre and thirds), and the bottom face
    only when the source has no caption below its icon (Variant A, WS2)."""
    out = [(pt, frac, "right") for pt, frac in _cr._exit_options(geo, e)]
    if not _has_caption(geo, e.source):
        s = geo.nodes[e.source]
        used = _cr._face_fractions(geo, e, e.source, "bottom", exit=True)
        for fx in (0.5, 0.25, 0.75):
            pt, frac = grid_resolve_contact(s, (fx, 1.0 + 2.0 / s.h))
            if _cr._free(frac[0], used):
                out.append((pt, frac, "bottom"))
    return out


def face_shapes(geo: DiagramGeometry, e: EdgeGeom) -> List[_cr.Shape]:
    """Every stub + one-lane shape between the free legal faces of ``e``.

    For each exit / entry pair the route leaves the exit face head-on by one
    stub, runs one lane (a horizontal or vertical line: the two stubs' own
    lines, the midline, or one to three stubs outside both end boxes), and
    enters the entry face head-on by one stub. This is the face-swap shape
    family ``Xav`` measures; the caller filters it for admissibility."""
    s, t = geo.nodes[e.source], geo.nodes[e.target]
    cap_s, cap_t = _cr._caption(geo, e.source), _cr._caption(geo, e.target)
    low = max(s.bottom, t.bottom, cap_s.bottom if cap_s else 0.0, cap_t.bottom if cap_t else 0.0)
    out: List[_cr.Shape] = []
    for P, pf, fx in _exits(geo, e):
        for Q, qf in _cr._entry_options(geo, e):
            fn = "top" if "top" in contact_faces(*qf) else "left"
            A = (P[0] + STUB * _FACE_NORMAL[fx][0], P[1] + STUB * _FACE_NORMAL[fx][1])
            B = (Q[0] + STUB * _FACE_NORMAL[fn][0], Q[1] + STUB * _FACE_NORMAL[fn][1])
            ys = {A[1], B[1], round((A[1] + B[1]) / 2 / GRID) * GRID}
            xs = {A[0], B[0], round((A[0] + B[0]) / 2 / GRID) * GRID}
            for k in _LANE_K:
                ys.add(_cr._floor_grid(min(s.y, t.y) - k * STUB))
                ys.add(_cr._ceil_grid(low + k * STUB))
                xs.add(_cr._floor_grid(min(s.x, t.x) - k * STUB))
                xs.add(_cr._ceil_grid(max(s.right, t.right) + k * STUB))
            for y in sorted(ys):
                out.append((P, pf, Q, qf, [A, (A[0], y), (B[0], y), B]))
            for x in sorted(xs):
                out.append((P, pf, Q, qf, [A, (x, A[1]), (x, B[1]), B]))
    return out


def _route_of(e: EdgeGeom) -> Route:
    return (tuple(e.exit), tuple(e.entry), tuple(tuple(p) for p in e.points))


def _ranked(
    geo: DiagramGeometry, e: EdgeGeom, free: Sequence[str] = (), side: bool = True,
) -> List[_cr.Cand]:
    """Admissible candidate routes for ``e``, fewest crossings first.

    ``free`` edges are re-routed together with ``e``: they reserve no face slot
    and are not obstacles (the joint search counts them itself). ``side`` adds
    the WS2 side-corridor shapes to the face-swap family."""
    view = _cr._without(geo, free) if free else geo
    polys = _cr._polylines(geo)
    skip = {e.id, *free}
    ctx = _cr._ctx(geo, e, skip, False)
    others = [_cr._segs(polys[o]) for o in sorted(polys) if o not in skip]
    e_view = next((o for o in view.edges if o.id == e.id), e)
    shapes = face_shapes(view, e_view)
    if side:
        shapes += _cr._side_shapes(view, e_view)
    out: List[_cr.Cand] = []
    seen: Set[tuple] = set()
    for order, (P, pf, Q, qf, pts) in enumerate(shapes):
        interior = _cr._normalised(P, pf, Q, qf, pts)
        poly = [tuple(P)] + interior + [tuple(Q)]
        key = (round(pf[0], 4), round(pf[1], 4), round(qf[0], 4), round(qf[1], 4),
               tuple((round(x), round(y)) for x, y in interior))
        if key in seen:
            continue
        seen.add(key)
        adm = _cr._admissible(geo, e, poly, pf, qf, ctx)
        if adm is None:
            continue
        _hits, grown = adm
        sp = _cr._segs(poly)
        x = sum(_cr._cross_segs(sp, o) for o in others)
        ink = sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in zip(poly, poly[1:]))
        grow = sum(b.w * b.h for b in grown.values())
        out.append(((x, grow, len(interior), round(ink), order),
                    (tuple(pf), tuple(qf), tuple(interior)), poly, grown))
    out.sort(key=lambda r: r[0])
    return out


# --------------------------------------------------------------------------- #
# Acceptance: crossings drop, no new finding
# --------------------------------------------------------------------------- #


class _Base:
    """The diagram before a move: its score and its finding set."""

    def __init__(self, geo: DiagramGeometry, collinear_cap: int):
        self.score = _cr._score(geo)
        errors, warnings = _cr._violations(geo)
        self.findings: FrozenSet = frozenset(errors) | frozenset(warnings)
        self.collinear_cap = collinear_cap


def _accept(trial: DiagramGeometry, base: _Base) -> Optional[_cr._Score]:
    """The trial's score when it has fewer crossings than ``base`` and adds
    nothing the oracle or the route-quality ratchet reports, else None."""
    sc = _cr._score(trial)
    b = base.score
    if sc.crossings >= b.crossings:
        return None
    if (sc.errors > b.errors or sc.warnings > b.warnings or sc.rails > b.rails
            or sc.collinear > base.collinear_cap or sc.own > b.own or sc.vis > b.vis):
        return None
    errors, warnings = _cr._violations(trial)
    if (frozenset(errors) | frozenset(warnings)) - base.findings:
        return None
    return sc


def _apply(
    geo: DiagramGeometry, combo: Sequence[Tuple[str, Route]], grown: Dict[str, Box],
) -> Optional[Tuple[DiagramGeometry, float]]:
    trial = geo
    for rid, route in combo:
        trial = _cr._with_route(trial, rid, route)
    return _cr._with_growth(trial, grown)


Move = Tuple[Dict[str, Route], Dict[str, Box], float, _cr._Score]


def _try(geo: DiagramGeometry, combo: Sequence[Tuple[str, Route]], grown: Dict[str, Box],
         base: _Base) -> Optional[Move]:
    applied = _apply(geo, combo, grown)
    if applied is None:
        return None
    trial, dx = applied
    sc = _accept(trial, base)
    if sc is None:
        return None
    return dict(combo), grown, dx, sc


def _better(a: Optional[Move], b: Optional[Move]) -> Optional[Move]:
    if b is None:
        return a
    if a is None:
        return b
    ka = a[3].key() + (sum(x.w * x.h for x in a[1].values()), len(a[0]))
    kb = b[3].key() + (sum(x.w * x.h for x in b[1].values()), len(b[0]))
    return b if kb < ka else a


# --------------------------------------------------------------------------- #
# Moves
# --------------------------------------------------------------------------- #


def _edge(geo: DiagramGeometry, eid: str) -> EdgeGeom:
    return next(o for o in geo.edges if o.id == eid)


def _edge_x(polys: Dict[str, List[Point]], eid: str, poly: Sequence[Point],
            skip: Sequence[str] = ()) -> int:
    return sum(_pair_x(poly, polys[o]) for o in sorted(polys) if o != eid and o not in skip)


def _best_single(geo: DiagramGeometry, eid: str, base: _Base) -> Optional[Move]:
    e = _edge(geo, eid)
    polys = _cr._polylines(geo)
    cur = _edge_x(polys, eid, polys.get(eid, []))
    best: Optional[Move] = None
    for cand in [c for c in _ranked(geo, e) if c[0][0] < cur][:_ORACLE_BUDGET]:
        best = _better(best, _try(geo, [(eid, cand[1])], cand[3], base))
    return best


def _swapped_leg(poly: Sequence[Point], last: bool, axis: str, value: float) -> Optional[List[Point]]:
    """``poly``'s interior points with its last (or first) INTERIOR leg along
    ``axis`` moved to ``value`` (a V leg's x, an H leg's y); None when there is
    no such leg. The two contact points never move."""
    n = len(poly)
    idx = range(n - 3, 0, -1) if last else range(1, n - 2)
    for i in idx:
        p, q = poly[i], poly[i + 1]
        if leg_axis(p, q) != axis:
            continue
        pts = [tuple(x) for x in poly[1:-1]]
        k = 0 if axis == "V" else 1
        for j in (i - 1, i):
            pt = list(pts[j])
            pt[k] = value
            pts[j] = tuple(pt)
        return pts
    return None


def _leg_coord(poly: Sequence[Point], last: bool, axis: str) -> Optional[float]:
    n = len(poly)
    idx = range(n - 3, 0, -1) if last else range(1, n - 2)
    for i in idx:
        if leg_axis(poly[i], poly[i + 1]) == axis:
            return poly[i][0] if axis == "V" else poly[i][1]
    return None


def _swap_moves(geo: DiagramGeometry, a: str, b: str, base: _Base) -> Optional[Move]:
    """Corridor swap: two edges converging on one target face (or diverging
    from one source face) trade their approach (departure) corridor, so the
    corridor nesting follows the source (target) order."""
    ea, eb = _edge(geo, a), _edge(geo, b)
    polys = _cr._polylines(geo)
    pa, pb = polys.get(a), polys.get(b)
    if not pa or not pb:
        return None
    best: Optional[Move] = None
    pairs = []
    if ea.target == eb.target:
        fa, fb = contact_faces(*ea.entry), contact_faces(*eb.entry)
        for face, axis in (("left", "V"), ("top", "H")):
            if face in fa and face in fb:
                pairs.append((True, axis))
    if ea.source == eb.source:
        fa, fb = contact_faces(*ea.exit), contact_faces(*eb.exit)
        for face, axis in (("right", "V"), ("bottom", "H")):
            if face in fa and face in fb:
                pairs.append((False, axis))
    for last, axis in pairs:
        ca, cb = _leg_coord(pa, last, axis), _leg_coord(pb, last, axis)
        if ca is None or cb is None or abs(ca - cb) < AXIS_EPS:
            continue
        na, nb = _swapped_leg(pa, last, axis, cb), _swapped_leg(pb, last, axis, ca)
        if na is None or nb is None:
            continue
        combo = [(a, (tuple(ea.exit), tuple(ea.entry), tuple(_clean(pa[0], na, pa[-1])))),
                 (b, (tuple(eb.exit), tuple(eb.entry), tuple(_clean(pb[0], nb, pb[-1]))))]
        if not all(_admissible_route(geo, rid, r, [a, b]) for rid, r in combo):
            continue
        best = _better(best, _try(geo, combo, {}, base))
    return best


def _clean(P: Point, pts: Sequence[Point], Q: Point) -> List[Point]:
    return collapse_collinear([tuple(P)] + [tuple(p) for p in pts] + [tuple(Q)])[1:-1]


def _admissible_route(geo: DiagramGeometry, eid: str, route: Route, free: Sequence[str]) -> bool:
    e = _edge(geo, eid)
    trial = _cr._with_route(geo, eid, route)
    te = _edge(trial, eid)
    poly = edge_polyline(trial, te)
    if len(poly) < 2:
        return False
    ctx = _cr._ctx(geo, e, set(free) | {eid}, False)
    adm = _cr._admissible(geo, e, poly, route[0], route[1], ctx)
    return adm is not None and not adm[1]


#: Joint search over three edges: candidates kept per member.
_TRIPLE_POOL = 24
#: Third members tried with a crossing pair (edges sharing an endpoint node).
_MAX_THIRDS = 4


def _best_group(geo: DiagramGeometry, eids: Sequence[str], base: _Base) -> Optional[Move]:
    """Re-route ``eids`` (two or three edges) together: each takes a candidate
    (or keeps its route), face slots stay distinct, no two share a corridor,
    and the group crosses less than before. Three edges cover a face whose
    exit (or entry) order has to be permuted (SEP 02: Lambda's right face)."""
    polys = _cr._polylines(geo)
    members = [_edge(geo, x) for x in eids]
    ids = set(eids)
    rest = [_cr._segs(polys[x]) for x in sorted(polys) if x not in ids]
    cur = sum(_cr._cross_segs(_cr._segs(polys.get(m.id, [])), r) for m in members for r in rest)
    cur += sum(_pair_x(polys.get(x, []), polys.get(y, []))
               for x, y in itertools.combinations(eids, 2))
    pool = _JOINT_POOL if len(eids) == 2 else _TRIPLE_POOL
    lists: List[List[_cr.Cand]] = []
    for m in members:
        cands = _ranked(geo, m, free=sorted(ids - {m.id}))
        keep = _cr._keep(geo, m, rest)
        lists.append(([keep] if keep is not None else []) + cands[:pool])
    if not all(lists):
        return None
    segs = [[_cr._segs(c[2]) for c in lst] for lst in lists]
    n = len(members)
    pairs = list(itertools.combinations(range(n), 2))
    combos = []
    for idx in itertools.product(*(range(len(lst)) for lst in lists)):
        picks = [lists[k][i] for k, i in enumerate(idx)]
        if all(p[0][-1] == -1 for p in picks):
            continue  # every member keeps its route: no move
        x = sum(p[0][0] for p in picks)
        if x >= cur:
            continue
        ok = True
        for p, q in pairs:
            x += _cr._cross_segs(segs[p][idx[p]], segs[q][idx[q]])
            if (x >= cur or not _cr._distinct(picks[p][1], picks[q][1], members[p], members[q])
                    or _cr._runs_collide(segs[p][idx[p]], segs[q][idx[q]])):
                ok = False
                break
        if ok:
            combos.append(((x, sum(p[0][1] for p in picks), [p[0][2:] for p in picks]), idx))
    combos.sort(key=lambda c: c[0])
    best: Optional[Move] = None
    for _, idx in combos[:_ORACLE_BUDGET]:
        picks = [lists[k][i] for k, i in enumerate(idx)]
        grown = _cr._merge_growth(*(p[3] for p in picks))
        combo = [(m.id, p[1]) for m, p in zip(members, picks) if p[0][-1] != -1]
        best = _better(best, _try(geo, combo, grown, base))
        if best is not None:
            break
    return best


def _thirds(geo: DiagramGeometry, a: str, b: str) -> List[str]:
    """Edges sharing an endpoint node with ``a`` or ``b`` (declared order)."""
    ends = {x for e in (_edge(geo, a), _edge(geo, b)) for x in (e.source, e.target)}
    out = [o.id for o in geo.edges
           if o.id not in (a, b) and None not in o.exit and None not in o.entry
           and ({o.source, o.target} & ends)]
    return out[:_MAX_THIRDS]


def _best_joint(geo: DiagramGeometry, a: str, b: str, base: _Base) -> Optional[Move]:
    """Joint re-route of a crossing pair, then of the pair with one edge that
    shares an endpoint with it."""
    found = _best_group(geo, (a, b), base)
    if found is not None:
        return found
    best: Optional[Move] = None
    for c in _thirds(geo, a, b):
        best = _better(best, _best_group(geo, (a, b, c), base))
    return best


# --------------------------------------------------------------------------- #
# The planner
# --------------------------------------------------------------------------- #


def plan_crossing_repair_geo(geo: DiagramGeometry) -> Tuple[CaptionPlan, DiagramGeometry]:
    """Plan re-routes so every crossing a legal face / corridor change can
    remove without adding a finding is removed. Returns the plan and the
    geometry it produces; ``geo`` is not modified."""
    work = replace(geo, edges=list(geo.edges), containers=dict(geo.containers),
                   text_boxes=dict(geo.text_boxes))
    routes: Dict[str, Route] = {}
    grown_all: Dict[str, Box] = {}
    text_dx = 0.0
    _cr._RANK_CACHE.clear()
    cap = len(collinear_edge_pairs(geo))
    order = {e.id: i for i, e in enumerate(geo.edges)}
    tried: Set[Tuple[str, str, int]] = set()
    for _ in range(_MAX_PASSES):
        pairs = crossing_pairs(work)
        if not pairs:
            break
        progressed = False
        for a, b, _n in sorted(pairs, key=lambda p: (min(order.get(p[0], 0), order.get(p[1], 0)), p)):
            if not any((a, b) == (x, y) for x, y, _ in crossing_pairs(work)):
                continue  # removed by an earlier move
            ea, eb = _edge(work, a), _edge(work, b)
            if None in ea.exit or None in ea.entry or None in eb.exit or None in eb.entry:
                continue
            key = (a, b, len(routes))
            if key in tried:
                continue
            tried.add(key)
            base = _Base(work, cap)
            found = None
            for move in (lambda: _swap_moves(work, a, b, base),
                         lambda: _better(_best_single(work, a, base), _best_single(work, b, base)),
                         lambda: _best_joint(work, a, b, base)):
                found = move()
                if found is not None:
                    break
            if found is None:
                continue
            moved, grown, _dx, _sc = found
            for rid, route in moved.items():
                work = _cr._with_route(work, rid, route)
                routes[rid] = route
            if grown:
                applied = _cr._with_growth(work, grown)
                if applied is not None:
                    work, dx = applied
                    text_dx += dx
                    grown_all.update({cid: work.containers[cid] for cid in grown})
            progressed = True
        if not progressed:
            break
    _cr._RANK_CACHE.clear()
    return CaptionPlan(routes, grown_all, text_dx), work


def plan_crossing_repair(geo: DiagramGeometry) -> CaptionPlan:
    """The plan part of :func:`plan_crossing_repair_geo`."""
    return plan_crossing_repair_geo(geo)[0]


# --------------------------------------------------------------------------- #
# Measuring side: avoidable crossings (Xav / edge-crossing-avoidable)
# --------------------------------------------------------------------------- #


def avoidable_crossings(geo: DiagramGeometry) -> Tuple[int, List[str]]:
    """How many crossings a greedy sequence of single-edge legal face swaps
    removes, and the swaps (``"<edge> <exit>-><entry> -<gain>"``).

    A swap re-routes ONE edge onto a different legal face pair (exit right, or
    bottom from an uncaptioned source; entry left/top; at least one face
    changed) with the :func:`face_shapes` family, admitted only when it passes
    the WS2 cheap geometry (no icon, caption, text box, foreign container or
    container caption crossed, no shared corridor, no border ride, no detour
    hook) and adds no routing finding. Each edge swaps at most once; a swap is
    kept only when it strictly lowers the total crossing count."""
    polys = dict(_cr._polylines(geo))
    ids = sorted(polys)
    by_id = {e.id: e for e in geo.edges}

    def total(ps: Dict[str, List[Point]]) -> int:
        return sum(_pair_x(ps[x], ps[y]) for i, x in enumerate(ids) for y in ids[i + 1:])

    t0 = total(polys)
    if not t0:
        return 0, []
    work = geo
    base_errors, base_warnings = _cr._violations(geo)
    base_findings = frozenset(base_errors) | frozenset(base_warnings)
    swapped: Set[str] = set()
    applied: List[str] = []
    while True:
        best = None
        for eid in ids:
            if eid in swapped or eid not in by_id:
                continue
            cur = _edge_x(polys, eid, polys[eid])
            if cur == 0:
                continue
            e = _edge(work, eid)
            cur_exit = set(contact_faces(*e.exit)) & {"right", "bottom"}
            cur_entry = set(contact_faces(*e.entry)) & {"left", "top"}
            for cand in _ranked(work, e, side=False):
                pf, qf = cand[1][0], cand[1][1]
                fx = set(contact_faces(*pf)) & {"right", "bottom"}
                fn = set(contact_faces(*qf)) & {"left", "top"}
                if fx & cur_exit and fn & cur_entry:
                    continue  # not a face swap
                gain = cur - _edge_x(polys, eid, cand[2])
                if gain <= 0 or (best is not None and gain <= best[0]):
                    break  # ranked by crossings: no later candidate gains more
                if cand[3]:
                    continue  # needs a container to grow: not a plain swap
                trial = _cr._with_route(work, eid, cand[1])
                errors, warnings = _cr._violations(trial)
                if (frozenset(errors) | frozenset(warnings)) - base_findings:
                    continue
                tag = f"{_face_name(fx)}->{_face_name(fn)}"
                best = (gain, eid, tag, cand)
                break  # candidates are ranked by crossings: the first admitted is best
        if best is None:
            break
        gain, eid, tag, cand = best
        work = _cr._with_route(work, eid, cand[1])
        polys[eid] = list(cand[2])
        swapped.add(eid)
        applied.append(f"{eid} {tag} -{gain}")
    _cr._RANK_CACHE.clear()
    return t0 - total(polys), applied


def _face_name(faces: Set[str]) -> str:
    for f in ("right", "bottom", "left", "top"):
        if f in faces:
            return f
    return "?"


__all__ = [
    "avoidable_crossings",
    "crossing_pairs",
    "face_shapes",
    "plan_crossing_repair",
    "plan_crossing_repair_geo",
]
