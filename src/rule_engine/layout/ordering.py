"""Automatic flow-aware ordering (1.10.12 WS4, defect class C6).

A spec's ``slot`` values are the author's *seed* order. Laid out as written, a
flow-blind order produces back-edges (a target drawn left of its source),
upward loops and long hooks: SQS declared left of the Lambda that feeds it,
Route 53 right of the CloudFront it resolves to, a peer band whose order does
not follow the nodes that feed it. This module reorders the spec before
placement, Sugiyama style, and keeps the reorder only when the finished diagram
is measurably better.

**Moves** (all coordinate-free spec transforms; ``sub`` is never changed):

* ``reorder`` — permute the slots of the unpinned nodes of one ordering group
  (same lane, sub-row and container; peer regions ``a``/``b`` are permuted
  jointly so the mirror holds). Seeded by neighbour barycentre, refined by
  pairwise swaps.
* ``shift`` — open a one-slot gap in a North–South lane of account-level nodes
  (an external band moves right under the node that feeds it). At most two
  gaps per lane.
* ``relane`` — move an account-level node of a left→right flow to another
  occupied in-boundary lane. Accepted only when it removes a back-edge (the
  SQS-left-of-Lambda case: a lane is a column there, so no slot order fixes it).
* ``vpc_side`` — put a region's regional column left of its network block
  (``vpc_side="right"``) when the flow runs from regional services into the VPC.

**Objective.** Back-edges first, crossings second (decision 3). The search runs
on a cheap proxy — the placement-only pipeline (place → size → lift → centre,
a few milliseconds per candidate) with straight centre-to-centre edges, keyed
``(back-edges, hooks, lines through an icon, crossings, length)``. When
the proxy finds an order with fewer back-edges, up to three such orders (the
proxy optimum, the best one adding no proxy crossing, the one with the fewest
proxy crossings) are laid out in full next to the declared order, screened on
their raw geometry, and the best two (:data:`MAX_FINISHED`) are measured after
the ``build_diagram`` finishing passes. The best one is kept only when the
FINISHED diagram has no more back-edges, no more crossings, no new rule error,
own-caption cut or collinear pair, and strictly fewer back-edges or crossings.
A declared order with more than :data:`FINISH_BUDGET` raw crossings is kept as
is: the finishing measurement is too slow to run per candidate there. So no diagram gets worse than its
declared order (the decision-3 guard): the declared order is always a
candidate, and wins every tie. A spec whose proxy finds no back-edge to remove
costs one cheap search and is laid out exactly as declared.

**Opt-outs.** ``DiagramSpec.order="manual"`` skips the whole module;
``NodeSpec.pinned=True`` (or a non-zero ``sub``) keeps a node at its declared
slot; an explicit ``vpc_side`` of ``"left"`` / ``"right"`` is never changed.

Deterministic: every iteration is in declared / sorted order, no randomness, no
wall clock.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

try:  # package-relative import when used as ``rule_engine.layout.ordering``
    from ..geometry import GRID, Box, segment_crosses_box, segments_cross
    from .model import DiagramSpec, NodeSpec, PlacedDiagram
    from .base import LANE_INDEX, EXTERNAL_LANES, SpecError, _az_ordinals, _validate_spec
except ImportError:  # pragma: no cover - flat-module execution fallback
    from geometry import GRID, Box, segment_crosses_box, segments_cross  # type: ignore[no-redef]
    from layout.model import DiagramSpec, NodeSpec, PlacedDiagram  # type: ignore[no-redef]
    from layout.base import (  # type: ignore[no-redef]
        LANE_INDEX, EXTERNAL_LANES, SpecError, _az_ordinals, _validate_spec,
    )

#: Local-search budget: refinement sweeps over every group, and the most
#: one-slot gaps the ``shift`` move may open in one lane.
MAX_SWEEPS = 4
MAX_GAPS_PER_LANE = 2
#: Groups up to this size are ordered exhaustively; larger ones by swaps only.
EXHAUSTIVE_GROUP = 5
#: At most this many candidate orders are measured after the (costly)
#: ``build_diagram`` finishing passes, best raw geometry first.
MAX_FINISHED = 2
#: Above this many raw crossings in the declared order the finishing
#: measurement is too slow to run per candidate; the declared order is kept.
FINISH_BUDGET = 20

ProxyKey = Tuple[int, int, int, int, int]


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------

def is_pinned(node: NodeSpec) -> bool:
    """A node keeps its declared slot when pinned or nudged onto a sub-row."""
    return bool(getattr(node, "pinned", False)) or node.sub != 0


def _with_nodes(spec: DiagramSpec, changes: Dict[str, Dict[str, object]]) -> DiagramSpec:
    nodes = tuple(
        dataclasses.replace(n, **changes[n.id]) if n.id in changes else n
        for n in spec.nodes
    )
    return dataclasses.replace(spec, nodes=nodes)


def _set_slots(spec: DiagramSpec, slots: Dict[str, int]) -> DiagramSpec:
    return _with_nodes(spec, {nid: {"slot": s} for nid, s in slots.items()})


class _Group:
    """One ordering group: the members of each region, in slot order."""

    def __init__(self, key: Tuple, by_region: Dict[str, List[NodeSpec]]):
        self.key = key
        self.by_region = by_region
        self.ref = sorted(by_region)[0]


def _groups(spec: DiagramSpec) -> List[_Group]:
    """Ordering groups of ``spec``: nodes sharing lane, sub-row and container.

    Regions ``a``/``b`` share one group so they are permuted jointly; a group
    whose regions disagree on slots or roles is frozen (the peer mirror copies
    positions by ``(role, lane, slot, sub)``)."""
    kind_of = {c.id: c.kind for c in spec.containers}
    az_ord = _az_ordinals(spec)

    def cont_key(n: NodeSpec) -> Tuple:
        kind = kind_of.get(n.container) if n.container else None
        if kind == "az":
            return ("az", az_ord.get(n.container, 0))
        if kind in ("vpc", "region"):
            return (kind, "")
        return ("c", n.container or "")

    raw: Dict[Tuple, Dict[str, List[NodeSpec]]] = {}
    for n in spec.nodes:
        key = (n.lane, n.sub, cont_key(n))
        raw.setdefault(key, {}).setdefault(n.region, []).append(n)
    out: List[_Group] = []
    for key in sorted(raw, key=lambda k: (LANE_INDEX.get(k[0], 99), k[1], str(k[2]))):
        by_region = {r: sorted(ms, key=lambda m: (m.slot, m.id)) for r, ms in raw[key].items()}
        regions = sorted(by_region)
        if len(regions) > 1:
            if "" in regions:
                continue
            sig = [tuple((m.slot, m.role) for m in by_region[r]) for r in regions]
            if any(s != sig[0] for s in sig):
                continue
        g = _Group(key, by_region)
        if sum(1 for i in range(len(by_region[g.ref])) if not _pinned_at(g, i)) >= 2:
            out.append(g)
    return out


def _pinned_at(g: _Group, i: int) -> bool:
    return any(is_pinned(ms[i]) for ms in g.by_region.values())


def _apply_order(spec: DiagramSpec, g: _Group, order: Sequence[int]) -> DiagramSpec:
    """Give member ``order[k]`` (reference index) the k-th slot value of the
    group, in every region."""
    values = [m.slot for m in g.by_region[g.ref]]
    slots: Dict[str, int] = {}
    for ms in g.by_region.values():
        for k, i in enumerate(order):
            slots[ms[i].id] = values[k]
    return _set_slots(spec, slots)


def _current_group(spec: DiagramSpec, g: _Group) -> _Group:
    """Re-read ``g``'s members from ``spec`` (slots move between iterations)."""
    by_id = {n.id: n for n in spec.nodes}
    return _Group(g.key, {
        r: sorted((by_id[m.id] for m in ms), key=lambda m: (m.slot, m.id))
        for r, ms in g.by_region.items()
    })


# ---------------------------------------------------------------------------
# Proxy evaluation (placement only)
# ---------------------------------------------------------------------------

def _positions(spec: DiagramSpec) -> Optional[Dict[str, Box]]:
    try:
        from .place import (place_nodes, size_containers,
                            lift_subject_over_external_lane, centre_block_in_vpc)
    except ImportError:  # pragma: no cover - flat-module fallback
        from layout.place import (place_nodes, size_containers,  # type: ignore[no-redef]
                                  lift_subject_over_external_lane, centre_block_in_vpc)
    try:
        _validate_spec(spec)
        placed = place_nodes(spec)
        containers = size_containers(placed, spec)
        placed, containers = lift_subject_over_external_lane(placed, containers, spec)
        return centre_block_in_vpc(placed, containers, spec)
    except (SpecError, KeyError, ValueError):
        return None


def _centre(b: Box) -> Tuple[float, float]:
    return (b.x + b.w / 2.0, b.y + b.h / 2.0)


def back_edges_of(spec: DiagramSpec, boxes: Dict[str, Box]) -> List[str]:
    """Edges whose target centre lies left of the source centre by more than
    one grid step (the ``canvas_metrics`` definition)."""
    out = []
    for e in spec.edges:
        s, t = boxes.get(e.source), boxes.get(e.target)
        if s and t and _centre(t)[0] < _centre(s)[0] - GRID:
            out.append(e.id)
    return out


def proxy_key(spec: DiagramSpec, boxes: Dict[str, Box]) -> ProxyKey:
    """``(back-edges, hooks, lines through an icon, straight-line crossings,
    Manhattan length)`` over straight centre-to-centre edges.

    A hook (an edge rising against the flow) ranks right after a back-edge: the
    router has to loop over the target's top. A straight line through an
    unrelated icon comes next: the router turns it into a detour, or into a
    through-icon route (an ERROR)."""
    back = len(back_edges_of(spec, boxes))
    segs = []
    up = 0
    length = 0
    for e in spec.edges:
        s, t = boxes.get(e.source), boxes.get(e.target)
        if not s or not t:
            continue
        a, b = _centre(s), _centre(t)
        segs.append((e.source, e.target, (a, b)))
        length += int(abs(a[0] - b[0]) + abs(a[1] - b[1]))
        # Against the flow: any rise on a North–South diagram; on a left→right
        # one, a target straight above in the same column (a hook over its
        # top, where the target below would be a straight drop).
        if b[1] < a[1] - GRID and (spec.axis == "north-south" or abs(b[0] - a[0]) <= GRID):
            up += 1
    cross = 0
    for (s1, t1, g1), (s2, t2, g2) in itertools.combinations(segs, 2):
        if {s1, t1} & {s2, t2}:
            continue
        if _proper_cross(g1, g2):
            cross += 1
    through = 0
    for s, t, (a, b) in segs:
        for nid, box in boxes.items():
            if nid not in (s, t) and segment_crosses_box(a, b, box):
                through += 1
    return (back, up, through, cross, length)


def _proper_cross(g1, g2) -> bool:
    """True when two straight segments cross at a point interior to both."""
    (p1, p2), (p3, p4) = g1, g2

    def orient(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4))


def _evaluate(spec: DiagramSpec) -> Optional[ProxyKey]:
    boxes = _positions(spec)
    return None if boxes is None else proxy_key(spec, boxes)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _secondary(spec: DiagramSpec, b: Box) -> float:
    c = _centre(b)
    return c[0] if spec.axis == "north-south" else c[1]


def _barycentre_order(spec: DiagramSpec, g: _Group, boxes: Dict[str, Box]) -> List[int]:
    ref = g.by_region[g.ref]
    nbrs: Dict[str, List[str]] = {m.id: [] for m in ref}
    for e in spec.edges:
        if e.source in nbrs and e.target != e.source:
            nbrs[e.source].append(e.target)
        if e.target in nbrs and e.target != e.source:
            nbrs[e.target].append(e.source)
    free = [i for i in range(len(ref)) if not _pinned_at(g, i)]
    members = {m.id for m in ref}

    def bary(i: int) -> float:
        m = ref[i]
        xs = [_secondary(spec, boxes[o]) for o in nbrs[m.id] if o in boxes and o not in members]
        return sum(xs) / len(xs) if xs else _secondary(spec, boxes[m.id])

    ranked = sorted(free, key=lambda i: (bary(i), ref[i].slot, ref[i].id))
    order = list(range(len(ref)))
    for pos, i in zip(free, ranked):
        order[pos] = i
    return order


def _reseed_others(spec: DiagramSpec, fixed: _Group) -> DiagramSpec:
    """Barycentre-order every group except ``fixed`` against ``spec``'s
    placement (one pass)."""
    boxes = _positions(spec)
    if boxes is None:
        return spec
    out = spec
    for g in _groups(spec):
        if g.key == fixed.key:
            continue
        cur = _current_group(out, g)
        out = _apply_order(out, cur, _barycentre_order(out, cur, boxes))
    return out


def _orders_to_try(g: _Group) -> List[List[int]]:
    n = len(g.by_region[g.ref])
    free = [i for i in range(n) if not _pinned_at(g, i)]
    out: List[List[int]] = []
    if len(free) <= EXHAUSTIVE_GROUP:
        for perm in itertools.permutations(free):
            order = list(range(n))
            for pos, i in zip(free, perm):
                order[pos] = i
            out.append(order)
    else:
        for a, b in itertools.combinations(free, 2):
            order = list(range(n))
            order[a], order[b] = b, a
            out.append(order)
    return out


def _vpc_flippable(spec: DiagramSpec) -> bool:
    if spec.axis != "north-south" or getattr(spec, "vpc_side", "auto") != "auto":
        return False
    kinds = {c.id: c.kind for c in spec.containers}
    has_region = any(n.container and kinds.get(n.container) == "region" for n in spec.nodes)
    has_net = any(n.container and kinds.get(n.container) in ("vpc", "az") for n in spec.nodes)
    return has_region and has_net


def _account_only(spec: DiagramSpec) -> bool:
    return bool(spec.containers) and all(c.kind == "account" for c in spec.containers)


def _shift_moves(spec: DiagramSpec, gaps: Dict[str, int]) -> List[Tuple[str, DiagramSpec]]:
    """Open a one-slot gap before each unpinned account-level node of a
    North–South lane (every node at or after it in the lane moves one slot)."""
    if spec.axis != "north-south" or _account_only(spec):
        return []
    kinds = {c.id: c.kind for c in spec.containers}
    out = []
    lanes = sorted({n.lane for n in spec.nodes if n.region == ""}, key=lambda l: LANE_INDEX[l])
    for lane in lanes:
        if gaps.get(lane, 0) >= MAX_GAPS_PER_LANE:
            continue
        members = sorted(
            (n for n in spec.nodes if n.lane == lane and n.region == ""
             and not (n.container and kinds.get(n.container) in ("vpc", "az", "region"))),
            key=lambda n: (n.slot, n.id),
        )
        if not members or any(is_pinned(n) for n in members):
            continue
        for d in range(1, MAX_GAPS_PER_LANE - gaps.get(lane, 0) + 1):
            for n in members:
                moved = {m.id: m.slot + d for m in members if m.slot >= n.slot}
                out.append((f"shift {lane}: {d} {n.id}", _set_slots(spec, moved)))
    return out


def _relane_moves(spec: DiagramSpec) -> List[Tuple[str, DiagramSpec]]:
    """Move one unpinned account-level node of a left→right flow to another
    occupied in-boundary lane, at the end of that lane."""
    if spec.axis != "left-right":
        return []
    kinds = {c.id: c.kind for c in spec.containers}
    occupied = sorted({n.lane for n in spec.nodes if n.lane not in EXTERNAL_LANES},
                      key=lambda l: LANE_INDEX[l])
    lane_of = {n.id: n.lane for n in spec.nodes}
    out = []
    for n in spec.nodes:
        if (n.region != "" or n.lane in EXTERNAL_LANES or is_pinned(n)
                or (n.container and kinds.get(n.container) in ("vpc", "az", "region"))):
            continue
        preds = [LANE_INDEX[lane_of[e.source]] for e in spec.edges
                 if e.target == n.id and e.source != n.id]
        succs = [LANE_INDEX[lane_of[e.target]] for e in spec.edges
                 if e.source == n.id and e.target != n.id]
        lo = max(preds, default=-1)
        hi = min(succs, default=len(LANE_INDEX))
        if lo < LANE_INDEX[n.lane] < hi:
            continue  # already between its producers and its consumers
        # The nearest occupied lane after every producer and before every
        # consumer: a sink fed from a later lane moves just past its producer.
        fits = [l for l in occupied if lo < LANE_INDEX[l] < hi and l != n.lane]
        if not fits:
            continue
        lane = fits[0]
        slot = 1 + max((m.slot for m in spec.nodes if m.lane == lane and m.region == ""),
                       default=-1)
        out.append((f"relane {n.id}: {n.lane} -> {lane}",
                    _with_nodes(spec, {n.id: {"lane": lane, "slot": slot}})))
    return out


def _describe(before: DiagramSpec, after: DiagramSpec) -> List[str]:
    """Human-readable diff of two specs (slots, lanes, vpc_side)."""
    old = {n.id: n for n in before.nodes}
    lines = []
    for n in after.nodes:
        o = old[n.id]
        if o.lane != n.lane:
            lines.append(f"relane {n.id}: lane {o.lane} -> {n.lane} (slot {o.slot} -> {n.slot})")
        elif o.slot != n.slot:
            lines.append(f"slot {n.id}: {o.slot} -> {n.slot} (lane {n.lane})")
    if before.vpc_side != after.vpc_side:
        lines.append(f"vpc_side: {before.vpc_side} -> {after.vpc_side}")
    return lines


def _why(spec: DiagramSpec, base: PlacedDiagram, cand_spec: DiagramSpec,
         cand: PlacedDiagram) -> str:
    """Name the back-edges a reorder removes (and any it introduces)."""
    ends = {e.id: f"{e.source} -> {e.target}" for e in spec.edges}
    before = set(back_edges_of(spec, base.nodes))
    after = set(back_edges_of(cand_spec, cand.nodes))
    parts = []
    if before - after:
        parts.append("removes back-edge(s) " + ", ".join(
            f"{e} ({ends[e]})" for e in sorted(before - after)))
    if after - before:
        parts.append("introduces " + ", ".join(
            f"{e} ({ends[e]})" for e in sorted(after - before)))
    return "why: " + ("; ".join(parts) if parts else "no back-edge change")


def search(spec: DiagramSpec) -> Tuple[DiagramSpec, ProxyKey, ProxyKey]:
    """Return ``(best spec, declared proxy key, best proxy key)``.

    Barycentre seed, then sweeps of exhaustive/swap reordering per group, gap
    shifts, left→right re-lanes and the ``vpc_side`` flip, each accepted only
    when it lowers the proxy key. Re-lanes must lower the back-edge count."""
    ranked = search_candidates(spec)
    base_key = ranked[0][1]
    best, best_key = ranked[1] if len(ranked) > 1 else ranked[0]
    return best, base_key, best_key


def search_candidates(spec: DiagramSpec) -> List[Tuple[DiagramSpec, ProxyKey]]:
    """``[(declared spec, key), (best, key), (alternative, key)?]``.

    The second entry is the proxy optimum (back-edges first). The third, when
    it differs, is the best candidate seen that removes back-edges WITHOUT
    raising the proxy crossing count — the fallback when the optimum's extra
    crossings survive the finishing passes."""
    base_key = _evaluate(spec)
    if base_key is None:
        return [(spec, (0, 0, 0, 0, 0))]
    if base_key[0] == 0:
        # Nothing to remove: only an order with FEWER back-edges is ever laid
        # out in full (below), so a declared order without back-edges is kept
        # as is. Skipping the refinement here changes no result; it keeps
        # ``layout()`` on a flow-forward spec as cheap as before WS4.
        return [(spec, base_key)]
    seen: List[Tuple[ProxyKey, int, DiagramSpec]] = []
    # Two starting points when the VPC side is free: the flip moves whole
    # blocks, so it may only pay off once the slot order has followed it.
    best, best_key = _refine(spec, base_key, seen)
    if _vpc_flippable(spec):
        flipped = dataclasses.replace(spec, vpc_side="right")
        fkey = _evaluate(flipped)
        if fkey is not None:
            seen.append((fkey, len(seen), flipped))
            cand, ckey = _refine(flipped, fkey, seen)
            if ckey < best_key:
                best, best_key = cand, ckey
    out = [(spec, base_key)]
    # Only an order that removes back-edges (the primary objective) is worth a
    # full layout: crossings alone are the finishing crossing repair's job, and
    # a full candidate layout plus its finishing passes is the costly step.
    if best_key[0] < base_key[0]:
        out.append((best, best_key))
        better = [(k, i, s) for k, i, s in seen if k[0] < base_key[0]]
        # Alternatives: the best order that removes back-edges without adding
        # proxy crossings, and the one with the fewest proxy crossings.
        for rank in (
            lambda t: (_guarded(t[0])[1] > _guarded(base_key)[1], t[0], t[1]),
            lambda t: (_guarded(t[0])[1], t[0], t[1]),
        ):
            if not better:
                break
            k, _i, s = min(better, key=rank)
            if all(_signature(s) != _signature(o) for o, _ in out):
                out.append((s, k))
    return out


def _guarded(key: ProxyKey) -> Tuple[int, int]:
    """The proxy's view of the guarded metrics: ``(back-edges, crossings)``,
    a line through an icon counted as a crossing."""
    return (key[0], key[2] + key[3])


def _signature(spec: DiagramSpec) -> Tuple:
    return (tuple((n.id, n.lane, n.slot) for n in spec.nodes), spec.vpc_side)


def _refine(spec: DiagramSpec, start_key: ProxyKey,
            seen: List[Tuple[ProxyKey, int, DiagramSpec]]) -> Tuple[DiagramSpec, ProxyKey]:
    best, best_key = spec, start_key

    def consider(cand: DiagramSpec, need_fewer_back: bool = False) -> bool:
        nonlocal best, best_key
        key = _evaluate(cand)
        if key is not None:
            seen.append((key, len(seen), cand))
        if key is None or key >= best_key:
            return False
        if need_fewer_back and key[0] >= best_key[0]:
            return False
        best, best_key = cand, key
        return True

    # Barycentre seed (two passes, each over every group at once).
    for _ in range(2):
        boxes = _positions(best)
        if boxes is None:
            break
        cand = best
        for g in _groups(best):
            cand = _apply_order(cand, _current_group(cand, g), _barycentre_order(
                cand, _current_group(cand, g), boxes))
        if not consider(cand):
            break

    gaps: Dict[str, int] = {}
    for _sweep in range(MAX_SWEEPS):
        improved = False
        for g in _groups(best):
            g = _current_group(best, g)
            identity = list(range(len(g.by_region[g.ref])))
            for order in _orders_to_try(g):
                if order == identity:
                    continue
                cand = _apply_order(best, g, order)
                # One-step lookahead: a reorder that only pays off once the
                # neighbouring groups follow it (Route 53 moves left of
                # CloudFront, so the node CloudFront feeds must move right).
                if consider(cand) or consider(_reseed_others(cand, g)):
                    improved = True
                    g = _current_group(best, g)
        for desc, cand in _relane_moves(best):
            if consider(cand, need_fewer_back=True):
                improved = True
        for desc, cand in _shift_moves(best, gaps):
            if consider(cand):
                _, lane, d, _n = desc.split()
                lane = lane.rstrip(":")
                gaps[lane] = gaps.get(lane, 0) + int(d)
                improved = True
                break  # the move list is stale once a lane has shifted
        if not improved:
            break
    return best, best_key


# ---------------------------------------------------------------------------
# Finished-diagram measurement and selection
# ---------------------------------------------------------------------------

class Finished(NamedTuple):
    """The guarded metrics of a finished diagram (``canvas_metrics`` definitions)."""

    back: int          #: back-edges
    crossings: int     #: edge-edge crossings
    own_cuts: int      #: edges cutting their own source/target caption (WS2)
    collinear: int     #: collinear unrelated edge pairs (WS8)
    cost: Tuple        #: ``route_cost(...).as_tuple()``; ``cost[0]`` = rule errors


def measure_finished(placed: PlacedDiagram, finishing: bool = True) -> Finished:
    """Measure a finished diagram exactly as ``scripts/canvas_metrics.py`` does
    (model space), after the ``build_diagram`` finishing passes when
    ``finishing``. Captions carry the spec's display labels."""
    from ..drawio_model import parse_drawio
    from ..geometry import (build_geometry, check_edge_crosses_own_label,
                            collinear_edge_pairs, edge_polyline, route_cost)
    from .repair import _serialize_candidate

    labels = dict(getattr(placed.spec, "node_labels", ()) or ())
    geo = build_geometry(parse_drawio(_serialize_candidate(placed, labels),
                                      path="<ordering>.drawio")[0])
    if finishing:
        # The finishing passes every ``build_diagram`` call applies (Variant A
        # caption-safe re-routes, then the WS3 crossing repair), so the
        # candidates are compared as they will be published.
        from ..caption_routing import plan_caption_safe_geo
        from ..crossing_repair import plan_crossing_repair_geo
        _plan, geo = plan_caption_safe_geo(geo)
        _plan, geo = plan_crossing_repair_geo(geo)
    back = 0
    for e in geo.edges:
        s, t = geo.nodes.get(e.source), geo.nodes.get(e.target)
        if s and t and t.center()[0] < s.center()[0] - GRID:
            back += 1
    polys = [p for p in (edge_polyline(geo, e) for e in geo.edges) if len(p) >= 2]
    cross = 0
    for a, b in itertools.combinations(polys, 2):
        cross += sum(1 for s1 in zip(a, a[1:]) for s2 in zip(b, b[1:]) if segments_cross(s1, s2))
    return Finished(back, cross, len(check_edge_crosses_own_label(geo)),
                    len(collinear_edge_pairs(geo)), route_cost(geo).as_tuple())


def order_and_place(
    spec: DiagramSpec, run: Callable[[DiagramSpec], PlacedDiagram]
) -> PlacedDiagram:
    """Lay ``spec`` out with automatic ordering (the default ``layout()`` path).

    ``run`` lays a spec out to a finished diagram (the scored placement loop).
    With ``order="manual"`` this is exactly ``run(spec)``."""
    if getattr(spec, "order", "auto") == "manual":
        return run(spec)
    ranked = search_candidates(spec)
    base_key = ranked[0][1]
    base = run(spec)
    if len(ranked) == 1:
        return dataclasses.replace(base, order_report=(
            f"auto-order: declared order kept (no better order found; "
            f"back-edges {base_key[0]})",))
    report: List[str] = []
    base_raw = measure_finished(base, finishing=False)
    if base_raw.crossings > FINISH_BUDGET:
        # The finishing passes' cost grows with the crossing count; past the
        # budget the guard cannot be measured cheaply, so keep the declared order.
        return dataclasses.replace(base, order_report=(
            f"auto-order: skipped — {base_raw.crossings} raw crossings exceed the "
            f"finishing-measurement budget ({FINISH_BUDGET}); declared order kept",))
    # Phase 1 — lay every candidate out and screen it on the raw (pre-
    # finishing) geometry. Node positions are final before the finishing
    # passes, so the back-edge count is exact here.
    survivors: List[Tuple[Tuple, PlacedDiagram, List[str]]] = []
    for cand_spec, _key in ranked[1:]:
        changes = _describe(spec, cand_spec)
        cand = run(cand_spec)
        changes.append(_why(spec, base, cand_spec, cand))
        raw = measure_finished(cand, finishing=False)
        if (cand.degraded, len(cand.layout_warnings)) > (base.degraded, len(base.layout_warnings)) \
                or raw.back > base_raw.back:
            report.append(f"auto-order: rejected — back-edges {base_raw.back} -> {raw.back}"
                          f"{', degraded' if cand.degraded and not base.degraded else ''}")
            report.extend("  not applied: " + c for c in changes)
            continue
        survivors.append(((raw.back, raw.crossings, raw.own_cuts, raw.collinear, raw.cost),
                          cand, changes))
    survivors.sort(key=lambda s: s[0])
    # Phase 2 — measure the best survivors after the finishing passes and
    # apply the guard.
    base_fin: Optional[Finished] = None
    winner: Optional[Tuple[Tuple, PlacedDiagram, List[str], str]] = None
    for _raw_key, cand, changes in survivors[:MAX_FINISHED]:
        if base_fin is None:
            base_fin = measure_finished(base)
        f0, f1 = base_fin, measure_finished(cand)
        # The decision-3 guard (no more back-edges, no more crossings, one of
        # them strictly fewer), and nothing the earlier workstreams fixed comes
        # back: no new rule ERROR, own-caption cut (WS2) or collinear pair (WS8).
        ok = (f1.cost[0] <= f0.cost[0]
              and f1.own_cuts <= f0.own_cuts and f1.collinear <= f0.collinear
              and f1.back <= f0.back and f1.crossings <= f0.crossings
              and (f1.back, f1.crossings) < (f0.back, f0.crossings))
        verdict = (
            f"auto-order: {'applied' if ok else 'rejected'} — finished back-edges "
            f"{f0.back} -> {f1.back}, crossings {f0.crossings} -> {f1.crossings}, "
            f"rule errors {f0.cost[0]} -> {f1.cost[0]}, own-caption cuts "
            f"{f0.own_cuts} -> {f1.own_cuts}, collinear pairs {f0.collinear} -> {f1.collinear}"
        )
        if ok:
            score = (f1.back, f1.crossings, f1.cost)
            if winner is None or score < winner[0]:
                if winner is not None:
                    report.append(winner[3].replace("applied", "superseded", 1))
                winner = (score, cand, changes, verdict)
            else:
                report.append(verdict.replace("applied", "superseded", 1))
            continue
        report.append(verdict)
        report.extend("  not applied: " + c for c in changes)
    if winner is not None:
        _score, cand, changes, verdict = winner
        return dataclasses.replace(
            cand, order_report=tuple(changes) + (verdict,) + tuple(report))
    return dataclasses.replace(base, order_report=tuple(report))
