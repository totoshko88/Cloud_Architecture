"""Variant A: an edge never strikes its own node's caption (1.10.12 WS2, D3 / G15).

Why this exists
---------------
A service node's name is drawn centred directly under its icon
(``verticalLabelPosition=bottom``) and is at least as wide as the icon. A
**bottom exit** therefore always drops straight through the source's own
caption (``lb-pr|imary``), and a lane or corridor that turns inside a wide
caption's overhang strikes it too. diagram-standards resolved the conflict as
text in 1.10.7 (*Variant A*): a spine whose source carries a caption below its
icon routes via the **side corridor** (exit right, drop in the gap beside the
column, enter the target's top/left); a straight bottom drop is allowed only
where no caption is in the way. Until 1.10.12 the engine only masked the strike
(``labelBackgroundColor``), and the mask did not work because edges rendered
above vertices.

What it does
------------
:func:`plan_caption_safe_routes` takes the parsed geometry of a finished
diagram (the linter's own view, so the caption width and every obstacle are the
ones the linter measures) and, for every edge whose polyline crosses its own
source or target caption (:func:`geometry.check_edge_crosses_own_label`),
generates contract-legal alternatives:

* **side corridor** — exit the right face, step out past the caption overhang,
  drop/rise in the gap, then enter the target's top or left face;
* **prefix swap** — the same right exit and corridor, re-joining the original
  route at its first lane, so the edge keeps the lanes the layout allocated;
* **leg shift** — an interior leg that cuts a wide caption's overhang moves
  sideways by whole grid steps until it clears it;
* **container growth** — when the side corridor of a node at the right edge of
  its container would leave that container, the container (and every ancestor,
  keeping the padding) grows right/down instead, and the right-margin
  Flow/Legend moves with it;
* **joint search** — one or two edges competing for the same face slots or
  corridors (named by the oracle) are re-routed together with it;
* **corner exit** (D) — on an OVERLOADED source (its right face already holds
  three exits, so ``exit-thirds`` leaves only the bottom), the unavoidable
  bottom exit moves into a corner band outside the caption's real text extent
  (:func:`geometry.caption_text_box`, the same 7.0px/char estimator), so the
  line never touches the letters. Such a route still crosses the icon-wide
  caption band and keeps its ``edge-crosses-own-label`` WARNING.

Each candidate is pre-filtered on cheap geometry (axis-aligned legs, no icon,
caption or text box crossed, no detour hook) and the best few are scored on the
full routing oracle (:func:`geometry.rule_violations` plus the caption-width
label, detour and marker checks). A candidate is accepted only when it clears
the caption (or, for a corner exit, the caption text) AND adds no routing
error, no routing warning and **no crossing**. An edge with no such candidate
keeps its route; the shared builder draws it beneath the node, whose caption
background masks it.

Pure and deterministic: candidates are enumerated in a fixed order, ties break
on that order, and nothing depends on dict iteration of unordered sets.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rule_engine.diagram_layout import CONTAINER_PAD
from rule_engine.geometry import (
    AXIS_EPS,
    COLLINEAR_GAP,
    COLLINEAR_OFFSET,
    CONTAINER_LABEL_BAND,
    GRID,
    RAIL_CLEARANCE,
    RAIL_MIN_SPAN,
    Box,
    DiagramGeometry,
    EdgeGeom,
    caption_lines,
    caption_text_box,
    check_container_dead_space,
    check_container_overlap,
    check_container_padding,
    check_legend_placement,
    check_node_overlap,
    wrap_caption,
    check_edge_crosses_container_label,
    container_caption_geom,
    polyline_cuts_container_caption,
    check_edge_strikes_own_text,
    collapse_collinear,
    collinear_edge_pairs,
    check_detour_hook,
    check_edge_crosses_label,
    check_edge_crosses_own_label,
    check_marker_icon_collision,
    check_marker_label_collision,
    contact_faces,
    edge_polyline,
    grid_resolve_contact,
    leg_axis,
    marker_anchors,
    node_caption_box,
    required_leg_axis,
    route_cost,
    rule_violations,
    segment_crosses_box,
)

Point = Tuple[float, float]
#: ``(exit fraction, entry fraction, interior waypoints)``.
Route = Tuple[Tuple[float, float], Tuple[float, float], Tuple[Point, ...]]

#: Right-face exit heights tried, in preference order (centre first).
_EXIT_FRACTIONS = (0.5, 0.25, 0.75)
#: Entry contacts tried besides the edge's current one, in preference order.
_ENTRY_FRACTIONS = ((0.5, 0.0), (0.0, 0.5), (0.25, 0.0), (0.75, 0.0), (0.0, 0.25), (0.0, 0.75))
#: Two contacts on one face closer than this merge (``exit-thirds`` floor).
_MIN_FACE_SEP = 0.2
#: Shortest head-on leg out of / into a face: two grid steps. diagram-standards
#: asks for one grid step before the first turn; two keeps the corner clear of
#: the glyph and lets a corridor fit inside a container's 30px padding.
_STUB = 2 * GRID
#: How many grid steps a corridor / lane / leg shift may move.
_CORRIDOR_STEPS = 6
#: First side-corridor column: this far past the source right face. Two grid
#: steps by default; an edge with no solution is retried from one grid step
#: (diagram-standards: step out at least one grid step before the first turn)
#: — a nearer corridor can fit where the default one is taken, but planned
#: first it would crowd the corridors other edges need.
_CORRIDOR_START = [2 * GRID]
_LANE_STEPS = 3
_SHIFT_STEPS = 12
#: Candidates per edge that reach the full oracle (the rest are pre-filtered).
_ORACLE_BUDGET = 24
#: A route longer than this multiple of its contacts' Manhattan distance is a
#: detour hook (``geometry.DETOUR_HOOK_COEFF``); keep a margin under it.
_DETOUR_LIMIT = 2.4
#: Passes over the offending edges (a later fix can free a face for an earlier one).
_MAX_PASSES = 3
#: A container may grow right/down by at most this much to hold a corridor.
_MAX_GROWTH = 6 * GRID
#: Clearance kept between a corner exit and the estimated caption text. Zero:
#: the 7.0px/char estimate is already a ceiling (real 12px glyphs are
#: narrower), and a grid-resolved corner contact strictly outside it never
#: touches the letters.
_TEXT_CLEARANCE = 0.0
#: Clearance kept between a run and a container caption's text.
_TEXT_CLEARANCE_C = 4.0
#: Joint search: partners tried, and candidates kept per edge in a combination.
_MAX_PARTNERS = 4
#: Joint search: candidates considered per member, and leading candidates of
#: the edge (and of its first partner) used as seeds of a greedy assignment.
_JOINT_POOL = 600
_JOINT_SEEDS = 30



@dataclass(frozen=True)
class _Score:
    """The oracle view of one whole diagram (lower is better, field order = weight)."""

    errors: int
    warnings: int
    crossings: int
    rails: int
    rail_penalty: float
    collinear: int
    own: int
    vis: int
    turns: int
    ink: float

    def key(self) -> Tuple:
        return (self.errors, self.warnings, self.crossings, self.rails,
                round(self.rail_penalty, 3), self.collinear, self.own, self.vis,
                self.turns, round(self.ink))

    def no_worse(self, base: "_Score", collinear_cap: int) -> bool:
        """Nothing the route-quality ratchet or the oracle measures rises above
        ``base`` (the diagram before this move); collinear pairs stay within
        ``collinear_cap`` (their count before the whole plan), so one move may
        reuse a pair an earlier move removed but the plan never ends worse."""
        return (self.errors <= base.errors and self.warnings <= base.warnings
                and self.crossings <= base.crossings and self.rails <= base.rails
                and round(self.rail_penalty, 3) <= round(base.rail_penalty, 3)
                and self.collinear <= collinear_cap
                and self.own <= base.own and self.vis <= base.vis)


@dataclass(frozen=True)
class CaptionPlan:
    """What :func:`plan_caption_safe` changes.

    ``routes``: ``{edge_id: (exit, entry, interior points)}``; ``containers``:
    ``{container_id: grown Box}``; ``text_dx``: how far the right-margin text
    boxes (Flow / Legend) move right to stay clear of a grown container;
    ``wraps``: ``{node_id: two-line caption}`` for an overloaded source whose
    caption is wrapped (:func:`geometry.wrap_caption`) so its bottom exit
    clears the text."""

    routes: Dict[str, Route]
    containers: Dict[str, Box]
    text_dx: float = 0.0
    wraps: Dict[str, str] = field(default_factory=dict)


def _polylines(geo: DiagramGeometry) -> Dict[str, List[Point]]:
    out: Dict[str, List[Point]] = {}
    for e in geo.edges:
        poly = edge_polyline(geo, e)
        if len(poly) >= 2:
            out[e.id] = poly
    return out


def _segs(poly: Sequence[Point]) -> Tuple[List[Tuple[float, float, float]], List[Tuple[float, float, float]]]:
    """``(H, V)``: horizontal legs as ``(y, x0, x1)``, vertical as ``(x, y0, y1)``."""
    hs, vs = [], []
    for p, q in zip(poly, poly[1:]):
        if abs(p[1] - q[1]) < AXIS_EPS and abs(p[0] - q[0]) >= AXIS_EPS:
            hs.append((p[1], min(p[0], q[0]), max(p[0], q[0])))
        elif abs(p[0] - q[0]) < AXIS_EPS and abs(p[1] - q[1]) >= AXIS_EPS:
            vs.append((p[0], min(p[1], q[1]), max(p[1], q[1])))
    return hs, vs


def _cross_segs(a, b) -> int:
    """Proper H x V intersections between two :func:`_segs` results — the same
    strict-interior test as :func:`geometry.segments_cross`."""
    n = 0
    for (hs, vs) in ((a[0], b[1]), (b[0], a[1])):
        for y, x0, x1 in hs:
            for x, y0, y1 in vs:
                if x0 + AXIS_EPS < x < x1 - AXIS_EPS and y0 + AXIS_EPS < y < y1 - AXIS_EPS:
                    n += 1
    return n


def _pair_crossings(a: Sequence[Point], b: Sequence[Point]) -> int:
    return _cross_segs(_segs(a), _segs(b))


def _violations(geo: DiagramGeometry) -> Tuple[Tuple, Tuple]:
    errors, warnings = rule_violations(geo)
    extra = tuple(sorted(
        [("edge-crosses-label", repr(f)) for f in check_edge_crosses_label(geo, caption_width=True)]
        + [("detour-hook", repr(f)) for f in check_detour_hook(geo)]
        + [("marker-label-collision", repr(f)) for f in check_marker_label_collision(geo)]
        + [("marker-icon-collision", repr(f)) for f in check_marker_icon_collision(geo)]
    ))
    return errors, tuple(warnings) + extra


#: Half the size of a rendered flow marker (one or two 12px bold digits).
_MARKER_HALF = 10.0


def _markers_on_container_captions(geo: DiagramGeometry) -> int:
    """Flow markers whose anchor lands on a container caption's text (the
    ``3`` printed over a centred ``az-a1``). The marker lint judges node
    captions only, so a re-route that moves a lane under a container caption
    would go unseen."""
    n = 0
    anchors = marker_anchors(geo)
    for cid, c in geo.containers.items():
        _box, extent = container_caption_geom(
            geo.container_labels.get(cid, ""), geo.container_styles.get(cid), c)
        if extent is None:
            continue
        tx0, tx1 = extent
        for x, y in anchors.values():
            if (tx0 - _MARKER_HALF < x < tx1 + _MARKER_HALF
                    and c.y - _MARKER_HALF < y < c.y + CONTAINER_LABEL_BAND + _MARKER_HALF):
                n += 1
    return n


def _extras(geo: DiagramGeometry) -> int:
    """Advisory findings :func:`geometry.rule_violations` does not count."""
    return (len(check_edge_crosses_label(geo, caption_width=True))
            + len(check_detour_hook(geo))
            + len(check_marker_label_collision(geo))
            + len(check_marker_icon_collision(geo))
            + _markers_on_container_captions(geo))


def _score(geo: DiagramGeometry) -> _Score:
    """The ratchet's own measure (:func:`geometry.route_cost`) plus the advisory
    extras, the collinear pairs (a re-route must not create the one-line
    illusion WS8 removes) and the two own-caption counts."""
    cost = route_cost(geo)
    return _Score(cost.rule_errors, cost.rule_warnings + _extras(geo), cost.crossings,
                  cost.rails, cost.rail_penalty, len(collinear_edge_pairs(geo)),
                  len(check_edge_crosses_own_label(geo)),
                  len(check_edge_strikes_own_text(geo)), cost.turns, cost.ink)


def _caption(geo: DiagramGeometry, nid: str) -> Optional[Box]:
    label = geo.node_labels.get(nid, "")
    if nid not in geo.nodes or not caption_lines(label):
        return None
    return node_caption_box(geo.nodes[nid], label)


def _text(geo: DiagramGeometry, nid: str) -> Optional[Box]:
    """The caption's real text extent grown by the clearance kept from it."""
    label = geo.node_labels.get(nid, "")
    if nid not in geo.nodes or not caption_lines(label):
        return None
    t = caption_text_box(geo.nodes[nid], label)
    c = _TEXT_CLEARANCE
    return Box(t.id, t.x - c, t.y, t.w + 2 * c, t.h)


def _ceil_grid(v: float) -> int:
    return int(-(-v // GRID) * GRID)


def _floor_grid(v: float) -> int:
    return int((v // GRID) * GRID)


def _face_fractions(geo: DiagramGeometry, e: EdgeGeom, node: str, face: str, *, exit: bool) -> List[float]:
    """Along-face fractions other edges already use on ``node``'s ``face``."""
    out = []
    for o in geo.edges:
        if o.id == e.id:
            continue
        if exit and o.source == node and None not in o.exit:
            if face in contact_faces(*o.exit):
                out.append(o.exit[1] if face in ("left", "right") else o.exit[0])
        if not exit and o.target == node and None not in o.entry:
            if face in contact_faces(*o.entry):
                out.append(o.entry[1] if face in ("left", "right") else o.entry[0])
    return out


def _free(frac: float, used: Iterable[float]) -> bool:
    return all(abs(frac - u) >= _MIN_FACE_SEP for u in used)


def _exit_options(geo: DiagramGeometry, e: EdgeGeom) -> List[Tuple[Point, Tuple[float, float]]]:
    """Free right-face exits (the side corridor's start)."""
    s = geo.nodes[e.source]
    used = _face_fractions(geo, e, e.source, "right", exit=True)
    out = []
    for fy in _EXIT_FRACTIONS:
        # The engine's clean arrow start: two pixels past the right face.
        pt, frac = grid_resolve_contact(s, (1.0 + 2.0 / s.w, fy))
        if _free(frac[1], used):
            out.append((pt, frac))
    return out


def _corner_exit_options(geo: DiagramGeometry, e: EdgeGeom) -> List[Tuple[Point, Tuple[float, float]]]:
    """Free bottom-face exits OUTSIDE the source caption's real text extent (D).

    Grid positions along the bottom face, nearest the face centre first (the
    shortest overhang), each at least :data:`_MIN_FACE_SEP` from every other
    bottom exit. Empty when the text is as wide as the icon."""
    s = geo.nodes[e.source]
    txt = _text(geo, e.source)
    if txt is None:
        return []
    used = _face_fractions(geo, e, e.source, "bottom", exit=True)
    xs = [s.x + k * GRID for k in range(1, int(s.w // GRID) + 1) if s.x + k * GRID < s.right - 2]
    xs = [x for x in xs if x < txt.x or x > txt.right]
    xs.sort(key=lambda x: (abs(x - (s.x + s.w / 2)), x))
    # Last resort: the two bottom corners themselves (still the bottom face,
    # left by a vertical leg — :func:`_admissible` enforces it).
    xs += [x for x in (s.right, s.x) if x < txt.x or x > txt.right]
    out = []
    for x in xs:
        pt, frac = grid_resolve_contact(s, ((x - s.x) / s.w, 1.0 + 2.0 / s.h))
        if _free(frac[0], used):
            out.append((pt, frac))
    return out


def _entry_options(
    geo: DiagramGeometry, e: EdgeGeom, extra_top_x: Iterable[float] = (),
) -> List[Tuple[Point, Tuple[float, float]]]:
    t = geo.nodes[e.target]
    cands: List[Tuple[float, float]] = []
    if None not in e.entry and contact_faces(*e.entry) & {"left", "top"}:
        cands.append((float(e.entry[0]), float(e.entry[1])))
    cands.extend(_ENTRY_FRACTIONS)
    for x in extra_top_x:
        # A corner exit's straight drop may land on the target's top corner
        # (still the top face, met by a vertical leg).
        if t.x <= x <= t.right:
            cands.append(((x - t.x) / t.w, 0.0))
    out, seen = [], set()
    for frac in cands:
        pt, rfrac = grid_resolve_contact(t, frac)
        faces = contact_faces(*rfrac)
        face = "top" if "top" in faces else "left"
        along = rfrac[0] if face == "top" else rfrac[1]
        key = (round(pt[0]), round(pt[1]))
        if key in seen:
            continue
        seen.add(key)
        if not _free(along, _face_fractions(geo, e, e.target, face, exit=False)):
            continue
        out.append((pt, rfrac))
    return out


def _corridor_xs(geo: DiagramGeometry, e: EdgeGeom) -> List[int]:
    """Side-corridor columns right of the source, past its caption overhang,
    from one grid step out (diagram-standards: step out one grid step before
    the first turn)."""
    s = geo.nodes[e.source]
    cap = _caption(geo, e.source)
    lo = max(s.right + _CORRIDOR_START[0], (cap.right + GRID) if cap else 0.0)
    x0 = _ceil_grid(lo)
    return [x0 + k * GRID for k in range(_CORRIDOR_STEPS + 1)]


Shape = Tuple[Point, Tuple[float, float], Point, Tuple[float, float], List[Point]]


def _side_shapes(geo: DiagramGeometry, e: EdgeGeom) -> List[Shape]:
    """Every side-corridor shape for ``e`` (right exit), unnormalised."""
    s, t = geo.nodes[e.source], geo.nodes[e.target]
    s_cap = _caption(geo, e.source)
    orig = list(e.points)
    out: List[Shape] = []
    xs = _corridor_xs(geo, e)
    for P, pf in _exit_options(geo, e):
        for Q, qf in _entry_options(geo, e):
            top = "top" in contact_faces(*qf)
            shapes: List[List[Point]] = []
            if top:
                # Lanes above the target top; when the target is below, also
                # lanes just under the source caption and the original lanes.
                lanes = {_floor_grid(t.y - _STUB) - k * GRID for k in range(_LANE_STEPS + 1)}
                if t.y > P[1]:
                    floor = (s_cap.bottom if s_cap else s.bottom) + GRID
                    lanes |= {_ceil_grid(floor) + k * GRID for k in range(_LANE_STEPS + 1)}
                lanes |= {p[1] for p in orig}
                if Q[0] >= xs[0] and t.y - P[1] >= _STUB:
                    shapes.append([(Q[0], P[1])])                      # L: run, drop in
                for cx in xs:
                    for ly in sorted(lanes):
                        if abs(cx - Q[0]) < AXIS_EPS or t.y - ly < _STUB:
                            continue
                        shapes.append([(cx, P[1]), (cx, ly), (Q[0], ly)])
            else:
                if abs(Q[1] - P[1]) < AXIS_EPS and t.x - P[0] >= _STUB:
                    shapes.append([])                                  # straight
                for cx in xs:
                    if t.x - cx >= _STUB:
                        shapes.append([(cx, P[1]), (cx, Q[1])])        # Z
                lanes = {p[1] for p in orig}
                floor = max(t.bottom, s_cap.bottom if s_cap else s.bottom) + GRID
                lanes |= {_ceil_grid(floor) + k * GRID for k in range(_LANE_STEPS + 1)}
                lanes |= {_floor_grid(min(s.y, t.y) - _STUB) - k * GRID
                          for k in range(_LANE_STEPS + 1)}
                for cx in xs:
                    for ly in sorted(lanes):
                        for k in range(3, 7):
                            lx = t.x - k * GRID
                            shapes.append([(cx, P[1]), (cx, ly), (lx, ly), (lx, Q[1])])
            # Prefix swap: right exit + corridor re-joining the original route.
            if orig and e.exit[1] is not None and e.exit[1] >= 1.0 - 1e-9:
                lane = orig[0][1]
                for cx in xs:
                    shapes.append([(cx, P[1]), (cx, lane)] + orig[1:])
                    if len(orig) >= 2 and leg_axis(orig[0], orig[1]) == "H":
                        for k in range(1, _LANE_STEPS + 1):
                            for ly in (lane - k * GRID, lane + k * GRID):
                                shapes.append([(cx, P[1]), (cx, ly), (orig[1][0], ly)] + orig[2:])
            for pts in shapes:
                out.append((P, pf, Q, qf, pts))
    # Re-entry: keep the exit and the route's lanes, but approach a different
    # (left / top) target face when the current entry strikes the target's own
    # caption (an arrival through the bottom face, e.g. a pinned callback).
    t_cap = _caption(geo, e.target)
    if None not in e.exit and None not in e.entry and orig and t_cap is not None:
        P0, pf0 = grid_resolve_contact(s, e.exit)
        Q0 = grid_resolve_contact(t, e.entry)[0]
        if any(segment_crosses_box(a, b, t_cap) for a, b in zip([P0] + orig, orig + [Q0])):
            for keep in range(len(orig), 0, -1):
                pre = orig[:keep]
                last = pre[-1]
                for Q, qf in _entry_options(geo, e):
                    if "top" in contact_faces(*qf):
                        for k in range(2, 2 + _LANE_STEPS + 1):
                            ly = _floor_grid(t.y - k * GRID)
                            out.append((P0, pf0, Q, qf, pre + [(last[0], ly), (Q[0], ly)]))
                    else:
                        for k in range(2, 2 + _LANE_STEPS + 1):
                            lx = _floor_grid(t.x - k * GRID)
                            out.append((P0, pf0, Q, qf, pre + [(lx, last[1]), (lx, Q[1])]))
    # Leg shift: keep both contacts, slide each interior leg that cuts an own
    # caption sideways by whole grid steps.
    if None not in e.exit and None not in e.entry:
        P0, pf0 = grid_resolve_contact(s, e.exit)
        Q0, qf0 = grid_resolve_contact(t, e.entry)
        poly = [P0] + orig + [Q0]
        caps = [c for c in (s_cap, _caption(geo, e.target)) if c is not None]
        for i in range(1, len(poly) - 2):
            a, b = poly[i], poly[i + 1]
            if not any(segment_crosses_box(a, b, c) for c in caps):
                continue
            axis = leg_axis(a, b)
            for k in range(1, _SHIFT_STEPS + 1):
                for d in (-k * GRID, k * GRID):
                    moved = list(orig)
                    if axis == "V":
                        moved[i - 1] = (a[0] + d, a[1])
                        moved[i] = (b[0] + d, b[1])
                    elif axis == "H":
                        moved[i - 1] = (a[0], a[1] + d)
                        moved[i] = (b[0], b[1] + d)
                    else:
                        continue
                    out.append((P0, pf0, Q0, qf0, moved))
    return out


def _corner_shapes(geo: DiagramGeometry, e: EdgeGeom) -> List[Shape]:
    """Corner-exit (D) shapes: drop from a bottom corner band past the caption
    band, then reach the target's top or left face."""
    s, t = geo.nodes[e.source], geo.nodes[e.target]
    cap = _caption(geo, e.source)
    below = _ceil_grid((cap.bottom if cap else s.bottom) + GRID)
    orig = list(e.points)
    out: List[Shape] = []
    exits = _corner_exit_options(geo, e)
    for P, pf in exits:
        for Q, qf in _entry_options(geo, e, extra_top_x=[P[0]]):
            shapes: List[List[Point]] = []
            if "top" in contact_faces(*qf):
                if abs(Q[0] - P[0]) < AXIS_EPS and t.y >= below:
                    shapes.append([])                                  # straight drop
                lanes = {_floor_grid(t.y - _STUB) - k * GRID for k in range(_LANE_STEPS + 1)}
                lanes |= {below + k * GRID for k in range(_LANE_STEPS + 1)}
                lanes |= {p[1] for p in orig}
                for ly in sorted(lanes):
                    if ly < below or t.y - ly < _STUB:
                        continue
                    shapes.append([(P[0], ly), (Q[0], ly)])
            else:
                if Q[1] >= below and (t.x - P[0] >= _STUB):
                    shapes.append([(P[0], Q[1])])                      # L: drop, run in
                for ly in sorted({below + k * GRID for k in range(_LANE_STEPS + 1)} | {p[1] for p in orig}):
                    if ly < below:
                        continue
                    for k in range(3, 7):
                        lx = t.x - k * GRID
                        shapes.append([(P[0], ly), (lx, ly), (lx, Q[1])])
            # Keep the allocated lanes: same route, first leg moved to the corner.
            if orig and orig[0][1] >= below:
                shapes.append([(P[0], orig[0][1])] + orig[1:])
            for pts in shapes:
                out.append((P, pf, Q, qf, pts))
    return out


def _normalised(P: Point, pf, Q: Point, qf, pts: Sequence[Point]) -> List[Point]:
    """Interior points with redundant midpoints and backtracks collapsed."""
    return collapse_collinear([tuple(P)] + [tuple(p) for p in pts] + [tuple(Q)])[1:-1]


#: A leg this long or longer is a corridor run (``corridor-sharing`` judges runs
#: longer than two grid steps); parallel runs closer than one grid step merge.
_RUN_MIN = 2 * GRID
#: A leg parallel to a container border within this distance rides it
#: (``geometry._BORDER_RIDE_TOL``).
_BORDER_TOL = 4.0


@dataclass
class _Ctx:
    """Per-edge obstacle context for :func:`_admissible`, built once."""

    obstacles: List[Box]
    captions: Dict[str, Box]
    #: Other edges' long legs: ``(axis, coord, lo, hi, source, target)``.
    runs: List[Tuple[str, float, float, float, str, str]]
    #: Containers holding both endpoints, innermost first (routes stay inside
    #: them, or they grow right/down to hold the route).
    chain: List[Box]
    #: Every other container (borders a route must not ride).
    others: List[Box]
    #: Containers holding neither endpoint: a route never cuts through them.
    foreign: List[Box]
    #: Corner-exit mode: the source caption is judged by its text extent.
    corner: bool
    #: Container captions the edge's CURRENT route already cuts (not new).
    cut_captions: frozenset = frozenset()
    #: Container id -> its caption geometry (:func:`geometry.container_caption_geom`).
    caption_geoms: Dict[str, tuple] = field(default_factory=dict)
    #: Nodes the edge's CURRENT route already runs a rail beside (not new).
    rail_nodes: frozenset = frozenset()
    #: Containers whose caption TEXT the current route already runs through.
    text_runs: frozenset = frozenset()
    #: ``(x, y, right, bottom, box, inset)`` of every obstacle and caption.
    bounds: List[tuple] = field(default_factory=list)

    def bounds_without(self, nid: str, own: Box) -> List[tuple]:
        """``bounds`` with ``nid``'s caption replaced by ``own`` (its text)."""
        out = [t for t in self.bounds if not (t[5] == 2.0 and t[4].id == nid and t[4] is self.captions.get(nid))]
        out.append((own.x, own.y, own.right, own.bottom, own, 0.0))
        return out


def _inside(n: Box, c: Box) -> bool:
    return c.x <= n.x and n.right <= c.right and c.y <= n.y and n.bottom <= c.bottom


def _ctx(geo: DiagramGeometry, e: EdgeGeom, skip: Iterable[str], corner: bool) -> _Ctx:
    skip = set(skip)
    # Text boxes grown one grid step: ``edge-crosses-legend`` also flags a run
    # within one step of the Flow/Legend box.
    texts = [Box(b.id, b.x - GRID, b.y - GRID, b.w + 2 * GRID, b.h + 2 * GRID)
             for b in geo.text_boxes.values()]
    obstacles = list(geo.nodes.values()) + texts
    captions = {nid: c for nid in sorted(geo.nodes) if (c := _caption(geo, nid)) is not None}
    runs = []
    for o in geo.edges:
        if o.id in skip:
            continue
        poly = edge_polyline(geo, o)
        for a, b in zip(poly, poly[1:]):
            ax = leg_axis(a, b)
            if ax == "H" and abs(b[0] - a[0]) > _RUN_MIN:
                runs.append(("H", a[1], min(a[0], b[0]), max(a[0], b[0]), o.source, o.target))
            elif ax == "V" and abs(b[1] - a[1]) > _RUN_MIN:
                runs.append(("V", a[0], min(a[1], b[1]), max(a[1], b[1]), o.source, o.target))
    s, t = geo.nodes[e.source], geo.nodes[e.target]
    chain, others, foreign = [], [], []
    for cid in sorted(geo.containers):
        c = geo.containers[cid]
        if _inside(s, c) and _inside(t, c):
            chain.append(c)
        else:
            others.append(c)
            if not _inside(s, c) and not _inside(t, c):
                foreign.append(c)
    chain.sort(key=lambda c: (c.w * c.h, c.id))
    # A container the current route already crosses is not a NEW finding.
    cur = edge_polyline(geo, e)
    foreign = [c for c in foreign
               if not any(segment_crosses_box(p, q, c) for p, q in zip(cur, cur[1:]))]
    cut = frozenset(cid for _, cid in check_edge_crosses_container_label(replace(geo, edges=[e])))
    geoms = {cid: container_caption_geom(geo.container_labels.get(cid, ""),
                                         geo.container_styles.get(cid), c)
             for cid, c in geo.containers.items()}
    rails = frozenset(nid for p, q in zip(cur, cur[1:]) for nid in _rail_nodes(geo, e, p, q))
    text_runs = frozenset(cid for cid, c in geo.containers.items()
                          if _runs_through_caption_text(cur, c, geoms[cid]))
    bounds = [(b.x, b.y, b.right, b.bottom, b, 2.0) for b in obstacles]
    bounds += [(c.x, c.y, c.right, c.bottom, c, 2.0) for _, c in sorted(captions.items())]
    return _Ctx(obstacles, captions, runs, chain, others, foreign, corner, cut, geoms, rails,
                text_runs, bounds)


def _runs_through_caption_text(poly: Sequence[Point], c: Box, caption) -> bool:
    """A horizontal leg runs through a container caption's real TEXT.

    ``check_edge_crosses_container_label`` sizes the horizontal-run test from
    the container's left edge (a left-aligned caption), so a run through a
    CENTRED caption ("az-a1" on the AWS zone box) is not seen; this uses the
    text extent the style actually draws."""
    extent = caption[1]
    if extent is None:
        return False
    tx0, tx1 = extent
    y0, y1 = c.y, c.y + CONTAINER_LABEL_BAND
    for p, q in zip(poly, poly[1:]):
        if abs(p[1] - q[1]) >= AXIS_EPS or not (y0 <= p[1] <= y1):
            continue
        if min(max(p[0], q[0]), tx1 + _TEXT_CLEARANCE_C) - max(min(p[0], q[0]), tx0 - _TEXT_CLEARANCE_C) > 0:
            return True
    return False


def _rail_nodes(geo: DiagramGeometry, e: EdgeGeom, p: Point, q: Point) -> List[str]:
    """Unrelated nodes a leg runs a parallel rail beside (``route_cost``): a
    vertical run of at least ``RAIL_MIN_SPAN`` within ``RAIL_CLEARANCE`` of the
    node's side, over the node's extent."""
    if abs(p[0] - q[0]) >= AXIS_EPS or abs(q[1] - p[1]) < RAIL_MIN_SPAN:
        return []
    lo, hi = min(p[1], q[1]), max(p[1], q[1])
    return [nid for nid, n in geo.nodes.items()
            if nid not in (e.source, e.target) and not (n.bottom < lo or n.y > hi)
            and min(abs(p[0] - n.x), abs(p[0] - n.right)) <= RAIL_CLEARANCE]


def _growth(chain: Sequence[Box], pts: Sequence[Point]) -> Optional[Dict[str, Box]]:
    """Grown chain boxes holding ``pts`` with padding, ``{}`` when none must
    grow, or None when a point leaves on the left/top or too far."""
    if not chain or not pts:
        return {}
    h = chain[0]
    if any(x <= h.x or y <= h.y for x, y in pts):
        return None
    need_r = max([h.right] + [x + CONTAINER_PAD for x, _ in pts if x > h.right - CONTAINER_PAD])
    need_b = max([h.bottom] + [y + CONTAINER_PAD for _, y in pts if y > h.bottom - CONTAINER_PAD])
    if need_r == h.right and need_b == h.bottom:
        if all(h.x < x < h.right and h.y < y < h.bottom for x, y in pts):
            return {}
    if need_r - h.right > _MAX_GROWTH or need_b - h.bottom > _MAX_GROWTH:
        return None
    if need_r <= h.right and need_b <= h.bottom:
        return {}
    out: Dict[str, Box] = {}
    child = Box(h.id, h.x, h.y, max(h.w, need_r - h.x), max(h.h, need_b - h.y))
    out[h.id] = child
    for c in chain[1:]:
        r = max(c.right, child.right + CONTAINER_PAD)
        b = max(c.bottom, child.bottom + CONTAINER_PAD)
        if (r, b) != (c.right, c.bottom):
            child = Box(c.id, c.x, c.y, r - c.x, b - c.y)
            out[c.id] = child
        else:
            child = c
    return out


def _admissible(
    geo: DiagramGeometry, e: EdgeGeom, poly: Sequence[Point], pf, qf, ctx: _Ctx,
) -> Optional[Tuple[int, Dict[str, Box]]]:
    """``(unrelated caption hits, container growth)`` for a clean candidate,
    else None.

    Rejects what the oracle would reject anyway, cheaply: a non-orthogonal or
    non-head-on leg, a leg through an icon or a Flow/Legend box, a strike of the
    edge's own caption (its text extent in corner mode), a detour hook, a long
    run on another edge's line, a run riding a container border, a cut through
    a container holding neither endpoint, and a point leaving the containers
    that hold both endpoints by more than they may grow."""
    legs = list(zip(poly, poly[1:]))
    if not legs or any(leg_axis(p, q) not in ("H", "V") for p, q in legs):
        return None
    # Both contact legs meet their face head-on (``edge-approach``).
    if any(want and leg_axis(*leg) != want for want, leg in (
        (required_leg_axis(contact_faces(*pf)) or ("V" if ctx.corner else None), legs[0]),
        (required_leg_axis(contact_faces(*qf)), legs[-1]),
    )):
        return None
    # Icons, text boxes, then captions (own caption in corner mode: its text).
    own_src = _text(geo, e.source) if ctx.corner else None
    boxes = ctx.bounds if own_src is None else ctx.bounds_without(e.source, own_src)
    for p, q in legs:
        lx, hx = (p[0], q[0]) if p[0] <= q[0] else (q[0], p[0])
        ly, hy = (p[1], q[1]) if p[1] <= q[1] else (q[1], p[1])
        for bx, by, br, bb, b, inset in boxes:
            if hx <= bx or lx >= br or hy <= by or ly >= bb:
                continue
            if segment_crosses_box(p, q, b, inset=inset):
                return None  # an icon, a text box, or a caption is struck
    hits = 0
    routed = sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in legs)
    direct = abs(poly[-1][0] - poly[0][0]) + abs(poly[-1][1] - poly[0][1])
    if direct > 2 * GRID and routed > _DETOUR_LIMIT * direct:
        return None
    grown = _growth(ctx.chain, poly[1:-1])
    if grown is None:
        return None
    for p, q in legs:
        if any(_near(p, q, c) and segment_crosses_box(p, q, c) for c in ctx.foreign):
            return None
        # A NEW parallel rail beside an unrelated node.
        if any(nid not in ctx.rail_nodes for nid in _rail_nodes(geo, e, p, q)):
            return None
    boxes = [grown.get(c.id, c) for c in ctx.chain] + ctx.others
    borders = []
    for c in boxes:
        borders += [("V", c.x, c.y, c.bottom), ("V", c.right, c.y, c.bottom),
                    ("H", c.y, c.x, c.right), ("H", c.bottom, c.x, c.right)]
    for p, q in legs:
        ax = leg_axis(p, q)
        if ax == "H":
            coord, lo, hi = p[1], min(p[0], q[0]), max(p[0], q[0])
        else:
            coord, lo, hi = p[0], min(p[1], q[1]), max(p[1], q[1])
        if hi - lo <= _RUN_MIN:
            continue
        for rax, rc, rlo, rhi, rs, rt in ctx.runs:
            if rax != ax or abs(rc - coord) >= COLLINEAR_OFFSET:
                continue
            # On the same line (< one grid step): a shared corridor. Closer than
            # two grid steps with overlapping extents: two lines that read as one
            # (``collinear_edge_pairs``; the score still judges the gap cases).
            if min(hi, rhi) - max(lo, rlo) > 0 and (
                    abs(rc - coord) < GRID or not ({rs, rt} & {e.source, e.target})):
                return None
        for bax, bc, blo, bhi in borders:
            if bax == ax and abs(bc - coord) <= _BORDER_TOL and min(hi, bhi) - max(lo, blo) >= 3 * GRID:
                return None
    # Container captions, judged by the lint's own predicate.
    for cid, c in geo.containers.items():
        if cid in ctx.cut_captions:
            continue
        if cid in grown:
            c = grown[cid]
            cap = container_caption_geom(geo.container_labels.get(cid, ""),
                                         geo.container_styles.get(cid), c)
        else:
            cap = ctx.caption_geoms[cid]
        if polyline_cuts_container_caption(poly, c, cap):
            return None
        if cid not in ctx.text_runs and _runs_through_caption_text(poly, c, cap):
            return None
    return hits, grown


def _near(p: Point, q: Point, b: Box) -> bool:
    return not (max(p[0], q[0]) <= b.x or min(p[0], q[0]) >= b.x + b.w
                or max(p[1], q[1]) <= b.y or min(p[1], q[1]) >= b.y + b.h)


def _with_route(geo: DiagramGeometry, eid: str, route: Route) -> DiagramGeometry:
    edges = [
        replace(o, exit=route[0], entry=route[1], points=list(route[2])) if o.id == eid else o
        for o in geo.edges
    ]
    return replace(geo, edges=edges)


def _with_growth(geo: DiagramGeometry, grown: Dict[str, Box]) -> Optional[Tuple[DiagramGeometry, float]]:
    """``geo`` with ``grown`` containers applied and the right-margin text boxes
    shifted clear, plus that shift; None when the growth would swallow a node,
    collide with a text box that is not in the right margin, or add a
    container overlap / dead-space finding."""
    if not grown:
        return geo, 0.0
    conts = dict(geo.containers)
    for cid, box in grown.items():
        old = conts[cid]
        for nid, n in geo.nodes.items():
            if not _inside(n, old) and not (n.right <= box.x or n.x >= box.right
                                            or n.bottom <= box.y or n.y >= box.bottom):
                return None
        conts[cid] = box
    old_right = max(c.right for c in geo.containers.values())
    new_right = max(c.right for c in conts.values())
    texts = {k: b for k, b in geo.text_boxes.items()
             if geo.text_headings.get(k, "").strip().lower() in ("flow", "legend")}
    dx = 0.0
    if texts:
        tx = min(b.x for b in texts.values())
        if tx >= old_right:
            dx = max(0.0, new_right + CONTAINER_PAD - tx)
        else:
            for b in texts.values():
                for c in grown.values():
                    if not (b.right + GRID <= c.x or b.x - GRID >= c.right
                            or b.bottom + GRID <= c.y or b.y - GRID >= c.bottom):
                        return None
    text_boxes = dict(geo.text_boxes)
    if dx:
        for k, b in texts.items():
            text_boxes[k] = Box(b.id, b.x + dx, b.y, b.w, b.h)
    trial = replace(geo, containers=conts, text_boxes=text_boxes)
    if len(check_container_overlap(trial)) > len(check_container_overlap(geo)):
        return None
    if len(check_container_dead_space(trial)) > len(check_container_dead_space(geo)):
        return None
    return trial, dx


def _without(geo: DiagramGeometry, eids: Iterable[str]) -> DiagramGeometry:
    """``geo`` with ``eids`` dropped, so their contacts no longer occupy a face."""
    drop = set(eids)
    return replace(geo, edges=[o for o in geo.edges if o.id not in drop])


#: A ranked candidate: ``(rank key, route, polyline, container growth)``.
Cand = Tuple[Tuple, Route, List[Point], Dict[str, Box]]


#: Collinear pairs of the diagram when the current plan started (see
#: :meth:`_Score.no_worse`); set by :func:`plan_caption_safe`.
_COLLINEAR_CAP = [0]

#: ``_ranked`` memo for the current plan: ``(id(geo), edge, free, corner)`` ->
#: ``(geo, full list)``; the geo is kept so its id cannot be reused.
_RANK_CACHE: Dict[tuple, Tuple[DiagramGeometry, List["Cand"]]] = {}


def _ranked(
    geo: DiagramGeometry, e: EdgeGeom, free: Sequence[str] = (), limit: int = _ORACLE_BUDGET,
    corner: bool = False,
) -> List[Cand]:
    key = (id(geo), e.id, tuple(sorted(free)), corner, _CORRIDOR_START[0])
    hit = _RANK_CACHE.get(key)
    if hit is None or hit[0] is not geo:
        hit = (geo, _ranked_uncached(geo, e, free, corner))
        _RANK_CACHE[key] = hit
    return hit[1][:limit] if limit else list(hit[1])


def _ranked_uncached(
    geo: DiagramGeometry, e: EdgeGeom, free: Sequence[str], corner: bool,
) -> List[Cand]:
    """Pre-filtered candidate routes for ``e``, best first.

    Edges in ``free`` are being re-routed together with ``e``: their contacts do
    not reserve a face slot and their routes are not counted as obstacles here
    (the joint search counts them itself). The rank key leads with the
    crossings against every other edge, then whether a container must grow."""
    view = _without(geo, free) if free else geo
    polys = _polylines(geo)
    skip = {e.id, *free}
    ctx = _ctx(geo, e, skip, corner)
    others = [_segs(polys[o]) for o in sorted(polys) if o not in skip]
    e_view = next((o for o in view.edges if o.id == e.id), e)
    shapes = _corner_shapes(view, e_view) if corner else _side_shapes(view, e_view)
    out: List[Cand] = []
    seen = set()
    for order, (P, pf, Q, qf, pts) in enumerate(shapes):
        interior = _normalised(P, pf, Q, qf, pts)
        poly = [tuple(P)] + interior + [tuple(Q)]
        key = (round(pf[0], 4), round(pf[1], 4), round(qf[0], 4), round(qf[1], 4),
               tuple((round(x), round(y)) for x, y in interior))
        if key in seen:
            continue
        seen.add(key)
        adm = _admissible(geo, e, poly, pf, qf, ctx)
        if adm is None:
            continue
        hits, grown = adm
        sp = _segs(poly)
        x = sum(_cross_segs(sp, o) for o in others)
        ink = sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in zip(poly, poly[1:]))
        grow = sum(b.w * b.h for b in grown.values())
        out.append(((x, grow, hits, len(interior), round(ink), order),
                    (tuple(pf), tuple(qf), tuple(interior)), poly, grown))
    out.sort(key=lambda r: r[0])
    return out


def _runs_collide(a, b) -> bool:
    """Two :func:`_segs` results have parallel long legs closer than
    ``COLLINEAR_OFFSET`` whose extents overlap or leave at most
    ``COLLINEAR_GAP`` between them: one shared corridor (``corridor-sharing``)
    or two lines that read as one (``collinear_edge_pairs``)."""
    for la, lb in ((a[0], b[0]), (a[1], b[1])):
        for c1, lo1, hi1 in la:
            if hi1 - lo1 <= _RUN_MIN:
                continue
            for c2, lo2, hi2 in lb:
                if (hi2 - lo2 > _RUN_MIN and abs(c1 - c2) < COLLINEAR_OFFSET
                        and max(lo1, lo2) - min(hi1, hi2) <= COLLINEAR_GAP):
                    return True
    return False


def _keep(geo: DiagramGeometry, o: EdgeGeom, rest_segs) -> Optional[Cand]:
    """A partner's current route as a candidate (it may stay where it is)."""
    poly = edge_polyline(geo, o)
    if len(poly) < 2:
        return None
    x = sum(_cross_segs(_segs(poly), r) for r in rest_segs)
    route = (tuple(o.exit), tuple(o.entry), tuple(tuple(p) for p in o.points))
    return ((x, 0, 0, len(o.points), 0, -1), route, poly, {})


def _accept(
    trial: DiagramGeometry, eid: str, base: _Score, corner: bool,
) -> Optional[_Score]:
    """The trial's score when it is acceptable against ``base``, else None.

    Side-corridor mode: ``eid`` no longer crosses its own caption and the
    own-caption count drops. Corner mode: ``eid`` no longer strikes its own
    caption TEXT and the visible-strike count drops (the icon-wide band may
    still be crossed). Either way errors, warnings, crossings, own-caption cuts
    and visible strikes never rise."""
    if corner:
        if eid in {x for x, _ in check_edge_strikes_own_text(trial)}:
            return None
    elif eid in {x for x, _ in check_edge_crosses_own_label(trial)}:
        return None
    sc = _score(trial)
    if not sc.no_worse(base, _COLLINEAR_CAP[0]):
        return None
    if (sc.own, sc.vis) >= (base.own, base.vis):
        return None
    return sc


def _merge_growth(*gs: Dict[str, Box]) -> Dict[str, Box]:
    out: Dict[str, Box] = {}
    for g in gs:
        for cid, b in g.items():
            if cid in out:
                o = out[cid]
                r, btm = max(o.right, b.right), max(o.bottom, b.bottom)
                b = Box(cid, o.x, o.y, r - o.x, btm - o.y)
            out[cid] = b
    return out


Move = Tuple[Dict[str, Route], Dict[str, Box], float, _Score]


def _try(
    geo: DiagramGeometry, combo: Sequence[Tuple[str, Cand]], eid: str, base: _Score, corner: bool,
) -> Optional[Move]:
    trial = geo
    for rid, cand in combo:
        trial = _with_route(trial, rid, cand[1])
    grown = _merge_growth(*(c[3] for _, c in combo))
    applied = _with_growth(trial, grown)
    if applied is None:
        return None
    trial, dx = applied
    sc = _accept(trial, eid, base, corner)
    if sc is None:
        return None
    return {rid: c[1] for rid, c in combo}, grown, dx, sc


def _better(a: Optional[Move], b: Optional[Move]) -> Optional[Move]:
    if b is None:
        return a
    if a is None:
        return b
    ka = a[3].key() + (sum(x.w * x.h for x in a[1].values()),)
    kb = b[3].key() + (sum(x.w * x.h for x in b[1].values()),)
    return b if kb < ka else a


def _best_single(geo: DiagramGeometry, e: EdgeGeom, base: _Score, corner: bool) -> Optional[Move]:
    polys = _polylines(geo)
    cur_x = sum(_pair_crossings(polys.get(e.id, []), polys[o]) for o in sorted(polys) if o != e.id)
    best: Optional[Move] = None
    ranked = [c for c in _ranked(geo, e, limit=0, corner=corner) if c[0][0] <= cur_x]
    for cand in ranked[:_ORACLE_BUDGET]:
        best = _better(best, _try(geo, [(e.id, cand)], e.id, base, corner))
    return best


_QUOTED = None


def _partners(geo: DiagramGeometry, e: EdgeGeom, corner: bool) -> List[EdgeGeom]:
    """Edges worth re-routing with ``e``: the ones the oracle names in the
    findings its best single candidates add, or that those candidates cross,
    then the edges sharing an endpoint with ``e``. Most frequent first."""
    import re
    from collections import Counter

    global _QUOTED
    if _QUOTED is None:
        _QUOTED = re.compile(r"'([^']+)'")
    by_id = {o.id: o for o in geo.edges}
    _, base_w = _violations(geo)
    base_e, _ = rule_violations(geo)
    seen_base = set(base_e) | set(base_w)
    votes: Counter = Counter()
    polys = _polylines(geo)
    for cand in _ranked(geo, e, limit=12, corner=corner):
        poly = cand[2]
        sp = _segs(poly)
        for oid in sorted(polys):
            if oid != e.id and _cross_segs(sp, _segs(polys[oid])):
                votes[oid] += 1
        trial = _with_route(geo, e.id, cand[1])
        te, tw = _violations(trial)
        for f in set(te) | set(tw):
            if f in seen_base:
                continue
            for tok in _QUOTED.findall(f[1]):
                if tok in by_id and tok != e.id:
                    votes[tok] += 1
    out = [by_id[oid] for oid, _ in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))]
    for o in geo.edges:
        if o.id != e.id and o not in out and (
            o.source in (e.source, e.target) or o.target in (e.source, e.target)
        ):
            out.append(o)
    return [o for o in out if None not in o.exit and None not in o.entry][:_MAX_PARTNERS]


def _distinct(ra: Route, rb: Route, a: EdgeGeom, b: EdgeGeom) -> bool:
    """Two re-routed edges do not share a contact slot on a common node face."""
    def slot(frac, exit: bool):
        faces = contact_faces(*frac)
        if exit:
            face = "right" if "right" in faces else "bottom"
        else:
            face = "top" if "top" in faces else "left"
        return face, (frac[1] if face in ("left", "right") else frac[0])

    for na, fa, ea in ((a.source, ra[0], True), (a.target, ra[1], False)):
        for nb, fb, eb in ((b.source, rb[0], True), (b.target, rb[1], False)):
            if na != nb or ea != eb:
                continue
            sa, sb = slot(fa, ea), slot(fb, eb)
            if sa[0] == sb[0] and abs(sa[1] - sb[1]) < _MIN_FACE_SEP:
                return False
    return True


def _assign(lists, segcache, members, lead: int, j0: int, order) -> Optional[Tuple[int, ...]]:
    """Greedy compatible assignment: ``members[lead]`` takes candidate ``j0``;
    then, in ``order``, every other member takes its candidate that keeps
    distinct face slots, shares no corridor with the picks so far, and adds the
    fewest crossings with them (ties: its own rank). None when one cannot."""
    n = len(members)
    idx: List[Optional[int]] = [None] * n
    idx[lead] = j0
    for i in order:
        best_j, best_x = None, None
        for j, cand in enumerate(lists[i]):
            xs = cand[0][0]
            clash = False
            for k in range(n):
                if idx[k] is None:
                    continue
                if (not _distinct(cand[1], lists[k][idx[k]][1], members[i], members[k])
                        or _runs_collide(segcache[i][j], segcache[k][idx[k]])):
                    clash = True
                    break
                xs += _cross_segs(segcache[i][j], segcache[k][idx[k]])
            if clash:
                continue
            if best_x is None or xs < best_x:
                best_j, best_x = j, xs
                if xs == 0:
                    break
        if best_j is None:
            return None
        idx[i] = best_j
    return tuple(idx)  # type: ignore[arg-type]


#: Plan the reverse edge order unconditionally only up to this many edges.
_REVERSE_MAX_EDGES = 12
#: 3-edge search: partner groups tried per edge.
_MAX_TRIPLES = 6


def _groups(geo: DiagramGeometry, e: EdgeGeom, partners: Sequence[EdgeGeom], size: int):
    """Partner groups for a joint move: single partners (``size == 2``), or
    pairs (``size == 3``) — two first-tier partners, or a first-tier partner
    with an edge sharing one of ITS endpoints (re-routing a partner can need its
    own neighbour moved). At most :data:`_MAX_TRIPLES` pairs, nearest first."""
    import itertools

    if size == 2:
        return [(o,) for o in partners]
    out: List[Tuple[EdgeGeom, EdgeGeom]] = []
    seen = set()

    def add(a: EdgeGeom, b: EdgeGeom) -> None:
        key = tuple(sorted((a.id, b.id)))
        if a.id != b.id and key not in seen and len(out) < _MAX_TRIPLES:
            seen.add(key)
            out.append((a, b))

    for a, b in itertools.combinations(partners[:3], 2):
        add(a, b)
    for a in partners[:2]:
        for o in geo.edges:
            if o.id in (e.id, a.id) or None in o.exit or None in o.entry:
                continue
            if {o.source, o.target} & {a.source, a.target}:
                add(a, o)
    return out


def _best_joint(
    geo: DiagramGeometry, e: EdgeGeom, base: _Score, corner: bool, size: int,
) -> Optional[Move]:
    """The best joint re-route of ``e`` with ``size - 1`` partner edges (2 or 3)."""
    import itertools

    polys = _polylines(geo)
    partners = _partners(geo, e, corner)
    best: Optional[Move] = None
    for group in _groups(geo, e, partners, size):
        members = [e, *group]
        ids = {m.id for m in members}
        rest = [_segs(polys[x]) for x in sorted(polys) if x not in ids]
        cur = sum(_cross_segs(_segs(polys.get(m.id, [])), r) for m in members for r in rest)
        cur += sum(_pair_crossings(polys.get(a.id, []), polys.get(b.id, []))
                   for a, b in itertools.combinations(members, 2))
        # Full candidate lists; the partners may also keep their current route.
        lists: List[List[Cand]] = []
        for m in members:
            cands = _ranked(geo, m, free=sorted(ids - {m.id}), limit=0,
                            corner=corner and m.id == e.id)
            if m.id != e.id:
                k = _keep(geo, m, rest)
                if k is not None:
                    cands = [k] + cands
            lists.append(cands[:_JOINT_POOL])
        if not lists[0]:
            continue
        segcache = [[_segs(c[2]) for c in lst] for lst in lists]
        n = len(members)
        combos = []
        seen_combo = set()
        # Seed a greedy compatible assignment (:func:`_assign`) from each
        # member's leading candidates, completing the others in every order.
        seeds = [(lead, j) for lead in range(n)
                 for j in range(min(len(lists[lead]), _JOINT_SEEDS))]
        for lead, j0 in seeds:
            for order in itertools.permutations([k for k in range(n) if k != lead]):
                idx = _assign(lists, segcache, members, lead, j0, order)
                if idx is None or idx in seen_combo:
                    continue
                seen_combo.add(idx)
                picks = [lists[i][j] for i, j in enumerate(idx)]
                x = sum(p[0][0] for p in picks)
                x += sum(_cross_segs(segcache[a][idx[a]], segcache[b][idx[b]])
                         for a, b in itertools.combinations(range(n), 2))
                if x > cur:
                    continue
                combos.append(((x, sum(p[0][1] for p in picks), [p[0][2:] for p in picks]), idx))
        combos.sort(key=lambda c: c[0])
        for _, idx in combos[:_ORACLE_BUDGET * 2]:
            combo = [(members[i].id, lists[i][j]) for i, j in enumerate(idx)]
            best = _better(best, _try(geo, combo, e.id, base, corner))
        if best is not None:
            return best
    return best


def _overloaded(geo: DiagramGeometry, e: EdgeGeom) -> bool:
    """The source's right face already holds three exits besides ``e``, so
    ``exit-thirds`` leaves ``e`` only the bottom face."""
    return len(_face_fractions(geo, e, e.source, "right", exit=True)) >= 3


def _layout_findings(geo: DiagramGeometry) -> int:
    """Findings a taller (wrapped) caption footprint can add that the routing
    score does not count: container padding, node overlap and a Flow/Legend
    box over a node."""
    return (len(check_container_padding(geo)) + len(check_node_overlap(geo))
            + len(check_legend_placement(geo)))


def _wrapped(geo: DiagramGeometry, e: EdgeGeom) -> Optional[Tuple[DiagramGeometry, str]]:
    """``geo`` with ``e``'s source caption wrapped onto two lines, or None.

    Only for the case decision 2 (amended, WS2) allows: the source is
    overloaded (three other right exits, so the bottom exit is unavoidable)
    and its one-line caption text is wider than the icon, so no bottom
    position lies outside the text. None when the label has no break point or
    the taller footprint adds a padding / overlap / legend finding (the node
    then keeps its masked bottom exit, an accepted residual)."""
    nid = e.source
    label = geo.node_labels.get(nid, "")
    if not _overloaded(geo, e) or len(caption_lines(label)) != 1:
        return None
    s = geo.nodes[nid]
    if caption_text_box(s, label).w <= s.w:
        return None
    wrapped = wrap_caption(label)
    if wrapped is None:
        return None
    trial = replace(geo, node_labels={**geo.node_labels, nid: wrapped})
    if _layout_findings(trial) > _layout_findings(geo):
        return None
    return trial, wrapped


def _find_move(work: DiagramGeometry, e: EdgeGeom, base: _Score) -> Optional[Move]:
    """The best acceptable re-route of ``e`` (side corridor, then joint
    moves, then — on an overloaded source whose caption TEXT it strikes — a
    corner exit), or None."""
    found = None
    for start in (2 * GRID, GRID):
        _CORRIDOR_START[0] = start
        found = (_best_single(work, e, base, False)
                 or _best_joint(work, e, base, False, 2)
                 or _best_joint(work, e, base, False, 3))
        if found is not None:
            break
    _CORRIDOR_START[0] = 2 * GRID
    if found is None and _overloaded(work, e) and e.id in {
            x for x, _ in check_edge_strikes_own_text(work)}:
        found = (_best_single(work, e, base, True)
                 or _best_joint(work, e, base, True, 2))
    return found


def _apply_move(
    work: DiagramGeometry, found: Move, routes: Dict[str, Route],
) -> Tuple[DiagramGeometry, Dict[str, Box], float]:
    """``work`` with ``found`` applied (``routes`` updated in place), the
    containers it grew and the right-margin shift."""
    moved, grown, _dx, _ = found
    for rid, route in moved.items():
        work = _with_route(work, rid, route)
        routes[rid] = route
    out: Dict[str, Box] = {}
    dx = 0.0
    if grown:
        work, dx = _with_growth(work, grown)
        out = {cid: work.containers[cid] for cid in grown}
    return work, out, dx


def _wrap_move(
    work: DiagramGeometry, e: EdgeGeom, base: _Score, order: Dict[str, int],
) -> Optional[Tuple[DiagramGeometry, Dict[str, Route], Dict[str, Box], float, str]]:
    """Wrap ``e``'s source caption (:func:`_wrapped`) and re-plan every edge
    of that node that then crosses its caption — the overloaded bottom exits
    take a corner past the narrower text, and a sibling run the taller caption
    now meets moves off it. Kept only when the whole result is no worse than
    ``base`` (the UNWRAPPED diagram) on every measure and has fewer own-caption
    cuts or visible strikes; otherwise None and the node keeps its masked
    bottom exit (an accepted residual)."""
    w = _wrapped(work, e)
    if w is None:
        return None
    trial, label = w
    nid = e.source
    routes: Dict[str, Route] = {}
    grown_all: Dict[str, Box] = {}
    text_dx = 0.0
    for _ in range(_MAX_PASSES):
        cut = sorted({eid for eid, n in check_edge_crosses_own_label(trial) if n == nid},
                     key=order.get)
        progressed = False
        for eid in cut:
            if eid not in {x for x, n in check_edge_crosses_own_label(trial) if n == nid}:
                continue
            o = next(x for x in trial.edges if x.id == eid)
            found = _find_move(trial, o, _score(trial))
            if found is None:
                continue
            trial, d_grown, d_dx = _apply_move(trial, found, routes)
            grown_all.update(d_grown)
            text_dx += d_dx
            progressed = True
        if not progressed:
            break
    if not routes:
        return None
    final = _score(trial)
    if not final.no_worse(base, _COLLINEAR_CAP[0]) or (final.own, final.vis) >= (base.own, base.vis):
        return None
    if _layout_findings(trial) > _layout_findings(work):
        return None
    return trial, routes, grown_all, text_dx, label


def _plan_once(geo: DiagramGeometry, reverse: bool) -> Tuple[CaptionPlan, DiagramGeometry]:
    """One greedy planning run over the offending edges in declared (or
    reverse) order; returns the plan and the geometry it produces."""
    _RANK_CACHE.clear()
    work = replace(geo, edges=list(geo.edges), containers=dict(geo.containers),
                   text_boxes=dict(geo.text_boxes))
    routes: Dict[str, Route] = {}
    grown_all: Dict[str, Box] = {}
    wraps: Dict[str, str] = {}
    text_dx = 0.0
    order = {e.id: (-i if reverse else i) for i, e in enumerate(geo.edges)}
    for _ in range(_MAX_PASSES):
        cut = sorted({eid for eid, _ in check_edge_crosses_own_label(work)}, key=order.get)
        if not cut:
            break
        progressed = False
        for eid in cut:
            e = next(o for o in work.edges if o.id == eid)
            if e.source not in work.nodes or e.target not in work.nodes:
                continue
            if eid not in {x for x, _ in check_edge_crosses_own_label(work)}:
                continue  # cleared by an earlier joint move
            base = _score(work)
            found = _find_move(work, e, base)
            if found is None and _overloaded(work, e) and eid in {
                    x for x, _ in check_edge_strikes_own_text(work)}:
                # No bottom position outside a caption wider than the icon:
                # wrap the caption onto two lines and re-plan that node's
                # edges, judged as a whole against the UNWRAPPED diagram.
                macro = _wrap_move(work, e, base, order)
                if macro is not None:
                    work, m_routes, m_grown, m_dx, label = macro
                    routes.update(m_routes)
                    grown_all.update(m_grown)
                    text_dx += m_dx
                    wraps[e.source] = label
                    progressed = True
                    continue
            if found is None:
                continue
            work, d_grown, d_dx = _apply_move(work, found, routes)
            text_dx += d_dx
            grown_all.update(d_grown)
            progressed = True
        if not progressed:
            break
    _RANK_CACHE.clear()
    return CaptionPlan(routes, grown_all, text_dx, wraps), work


def _unexplained(geo: DiagramGeometry) -> int:
    """Own-caption cuts NOT on an overloaded source face (the ones a plan must
    remove; an overloaded face may keep a masked residual)."""
    by_id = {e.id: e for e in geo.edges}
    return sum(1 for eid, _ in check_edge_crosses_own_label(geo)
               if not _overloaded(geo, by_id[eid]))


def plan_caption_safe(geo: DiagramGeometry) -> CaptionPlan:
    """Plan re-routes (and container growth) so no edge crosses its own
    source/target caption, or — on an overloaded source — at least never its
    caption text. ``geo`` is not modified; an empty plan means nothing could
    change without adding a crossing or a routing finding.

    The greedy plan depends on the order the offending edges are visited (an
    early move can take the corridor a later edge needed), so the reverse order
    is planned too — when the declared order leaves a cut on a face that is not
    overloaded, or on a flow-sized diagram (at most :data:`_REVERSE_MAX_EDGES`
    edges, where it is cheap) — and the better result kept: fewer cuts on faces
    that are not overloaded, then fewer visible strikes, then the lower
    :class:`_Score` (turns and ink break the tie). Deterministic: the declared
    order wins a full tie."""
    return plan_caption_safe_geo(geo)[0]


def plan_caption_safe_geo(geo: DiagramGeometry) -> Tuple[CaptionPlan, DiagramGeometry]:
    """:func:`plan_caption_safe` plus the geometry the plan produces (``geo``
    itself when the plan is empty), so a later finishing pass (the WS3
    crossing repair, :mod:`rule_engine.crossing_repair`) plans on the result."""
    _COLLINEAR_CAP[0] = len(collinear_edge_pairs(geo))
    if not check_edge_crosses_own_label(geo):
        return CaptionPlan({}, {}, 0.0), geo

    def rank(w: DiagramGeometry) -> Tuple:
        return (_unexplained(w), len(check_edge_strikes_own_text(w))) + _score(w).key()

    best, work = _plan_once(geo, reverse=False)
    if not _unexplained(work) and len(geo.edges) > _REVERSE_MAX_EDGES:
        return best, work
    alt, work2 = _plan_once(geo, reverse=True)
    return (alt, work2) if rank(work2) < rank(work) else (best, work)


def plan_caption_safe_routes(geo: DiagramGeometry) -> Dict[str, Route]:
    """The route part of :func:`plan_caption_safe`."""
    return plan_caption_safe(geo).routes


__all__ = ["plan_caption_safe", "plan_caption_safe_routes", "CaptionPlan", "Route"]
