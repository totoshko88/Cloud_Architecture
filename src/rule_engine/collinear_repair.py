"""Shift one of two unrelated collinear edges apart (1.10.12 WS8, defect C5).

Why this exists
---------------
Two unrelated edges whose parallel legs sit on the same grid line (or within a
grid step of it) with overlapping extents read as **one line**: the viewer
cannot tell there are two flows. :func:`rule_engine.geometry.collinear_edge_pairs`
is the measuring side (``scripts/canvas_metrics.py`` ``col`` and the
``collinear-edges`` lint rule); SEP 03 (``e2`` + ``e11`` at model y=127) and SEP
08 (``e4`` / ``e5`` / ``e10`` at y=789) are the canonical cases. The earlier
routing passes (WS2 caption-safe, WS3 crossing repair) and the flow-aware
ordering (WS4) only **guard** against adding a collinear pair (their score
counts them); none actively separates a pair the layout produced.

What it does
------------
:func:`plan_collinear_shift_geo` takes the parsed geometry of a finished
diagram (the linter's view: real caption widths, wrapped captions, every
obstacle) and, for each collinear pair, re-routes ONE of the two edges onto a
contract-legal alternative that no longer shares the line — a different exit /
entry face pair, a side corridor, or the same faces with the offending parallel
leg shifted onto its own lane. Candidates come from the shared crossing-repair
generator (:func:`rule_engine.crossing_repair._ranked` →
:func:`rule_engine.caption_routing._admissible`: head-on axis-aligned legs, no
icon / caption / text box / foreign container / container caption crossed, no
detour hook, no shared corridor, no border ride), so an admitted route already
clears every obstacle. A move is kept **only** when the collinear-pair count
drops and nothing else the oracle or the route-quality ratchet measures rises:
no routing error, warning, crossing, rail, own-caption cut or caption strike is
added, and no finding absent before shows up. In particular crossings and
back-edges never increase, so the WS8 acceptance (03 / 08 reach zero collinear
pairs) cannot trade one defect for another.

Pure and deterministic: candidates are enumerated in a fixed order, ties break
on that order, and nothing depends on unordered iteration.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from rule_engine import caption_routing as _cr
from rule_engine import crossing_repair as _xr
from rule_engine.caption_routing import CaptionPlan, Route
from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    collinear_edge_pairs,
    is_node_edge,
)

#: Candidates per edge (fewest crossings first) that reach the full oracle.
_ORACLE_BUDGET = 24
#: Passes over the collinear pairs (a later move can free a lane for an earlier
#: one, or reveal a pair hidden behind one just resolved).
_MAX_PASSES = 4


# --------------------------------------------------------------------------- #
# Collinear pairs
# --------------------------------------------------------------------------- #


def collinear_pairs(geo: DiagramGeometry) -> List[Tuple[str, str]]:
    """Every unrelated collinear edge pair (ids sorted), declared-order stable."""
    return sorted(collinear_edge_pairs(geo))


# --------------------------------------------------------------------------- #
# Acceptance: collinear pairs drop, nothing else worsens
# --------------------------------------------------------------------------- #


class _Base:
    """The diagram before a move: its score and its finding set."""

    def __init__(self, geo: DiagramGeometry, collinear_cap: int):
        self.score = _cr._score(geo)
        errors, warnings = _cr._violations(geo)
        self.findings: FrozenSet = frozenset(errors) | frozenset(warnings)
        self.collinear_cap = collinear_cap


def _accept(trial: DiagramGeometry, base: _Base) -> Optional[_cr._Score]:
    """The trial's score when it has fewer collinear pairs than ``base`` and
    adds nothing the oracle or the route-quality ratchet reports, else None."""
    sc = _cr._score(trial)
    b = base.score
    if sc.collinear >= b.collinear:
        return None
    if (sc.errors > b.errors or sc.warnings > b.warnings or sc.crossings > b.crossings
            or sc.rails > b.rails or sc.own > b.own or sc.vis > b.vis):
        return None
    errors, warnings = _cr._violations(trial)
    if (frozenset(errors) | frozenset(warnings)) - base.findings:
        return None
    return sc


Move = Tuple[Dict[str, Route], Dict[str, Box], float, _cr._Score]


def _try(geo: DiagramGeometry, eid: str, route: Route, grown, base: _Base) -> Optional[Move]:
    applied = _xr._apply(geo, [(eid, route)], grown)
    if applied is None:
        return None
    trial, dx = applied
    sc = _accept(trial, base)
    if sc is None:
        return None
    return {eid: route}, grown, dx, sc


def _better(a: Optional[Move], b: Optional[Move]) -> Optional[Move]:
    if b is None:
        return a
    if a is None:
        return b
    ka = a[3].key() + (sum(x.w * x.h for x in a[1].values()),)
    kb = b[3].key() + (sum(x.w * x.h for x in b[1].values()),)
    return b if kb < ka else a


def _best_single(geo: DiagramGeometry, eid: str, base: _Base) -> Optional[Move]:
    """Re-route ``eid`` onto any admissible legal route (face swap, side
    corridor, return bus) that lowers the collinear-pair count the most."""
    e = _xr._edge(geo, eid)
    best: Optional[Move] = None
    for cand in _xr._ranked(geo, e)[:_ORACLE_BUDGET]:
        best = _better(best, _try(geo, eid, cand[1], cand[3], base))
    return best


# --------------------------------------------------------------------------- #
# The planner
# --------------------------------------------------------------------------- #


def plan_collinear_shift_geo(geo: DiagramGeometry) -> Tuple[CaptionPlan, DiagramGeometry]:
    """Plan re-routes so every collinear pair a legal single-edge re-route can
    separate — without adding any other finding — is separated. Returns the
    plan and the geometry it produces; ``geo`` is not modified."""
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
        pairs = collinear_pairs(work)
        if not pairs:
            break
        progressed = False
        for a, b in sorted(pairs, key=lambda p: (min(order.get(p[0], 0), order.get(p[1], 0)), p)):
            if (a, b) not in set(collinear_pairs(work)):
                continue  # separated by an earlier move
            ea, eb = _xr._edge(work, a), _xr._edge(work, b)
            if None in ea.exit or None in ea.entry or None in eb.exit or None in eb.entry:
                continue
            # WS10: neither end of a container-endpoint edge is a node to
            # re-anchor, so the collinear-shift pass never reroutes such a pair.
            if not is_node_edge(work, ea) or not is_node_edge(work, eb):
                continue
            key = (a, b, len(routes))
            if key in tried:
                continue
            tried.add(key)
            base = _Base(work, cap)
            # Try moving either edge of the pair; keep the better result.
            found = _better(_best_single(work, a, base), _best_single(work, b, base))
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


def plan_collinear_shift(geo: DiagramGeometry) -> CaptionPlan:
    """The plan part of :func:`plan_collinear_shift_geo`."""
    return plan_collinear_shift_geo(geo)[0]


__all__ = ["plan_collinear_shift", "plan_collinear_shift_geo", "collinear_pairs"]
