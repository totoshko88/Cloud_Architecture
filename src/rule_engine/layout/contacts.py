"""Contact-point selection — exit/entry ladder + fan-out spread (Req 5).

This module is the contacts slice of the ``layout/`` package split
(scored-router release 1.8.0, Phase A, task 1.2). It holds the exit/entry
contact-ladder — :func:`select_contacts` and its helpers, the same-side spread
(:func:`spread_contacts` / :func:`spread_entries`), and the ladder constants
(:data:`MERGE_THRESHOLD`, :data:`MAX_SIDE_EXITS`) plus
:class:`OverConnectedError` — relocated **verbatim** from ``layout_engine.py``.

This is a **behavior-preserving mechanical relocation**: every symbol name,
default and body is identical to its pre-split definition, so
``layout_engine.select_contacts`` (and every other ladder symbol, re-imported
by ``layout_engine``) keeps resolving with no caller edit.

The ladder depends only on the canonical constant ``COL_STEP`` and the model
types (:data:`Contact`, :class:`EdgeSpec`, :class:`Box`), imported directly
from their leaf modules, so it never participates in an import cycle.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout.contacts``
    from ..diagram_layout import COL_STEP
    from ..geometry import Box
    from .model import Contact, EdgeSpec
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import COL_STEP  # type: ignore[no-redef]
    from geometry import Box  # type: ignore[no-redef]
    from layout.model import Contact, EdgeSpec  # type: ignore[no-redef]


#: ``Contact`` (a unit-square fraction on a node face) is defined in
#: :mod:`rule_engine.layout.model` and re-imported above.

#: The minimum separation between two contact-point band coordinates on one
#: node side before they read as a single doubled line at the glyph. This is the
#: *same* threshold ``geometry.check_exit_thirds`` uses (its ``min_sep`` default,
#: 0.2 ≈ 16px on a 78px side); the spread keeps its assignments >= this so the
#: validator stays clean by construction (Req 5.3).
MERGE_THRESHOLD = 0.2

#: The maximum number of edges the engine will emit on a single node side. A
#: fourth is an over-connected node (Req 5.4) — split or re-lane the diagram —
#: and :func:`spread_contacts` raises rather than emit a fourth contact point.
MAX_SIDE_EXITS = 3

#: The right-face band coordinate for a biased (second/third) exit: toward the
#: **free** side — the upper quarter when the target is above (or the upper
#: corridor is the clear one), the lower quarter otherwise. The centre (0.5) is
#: reserved for the first / straight-line exit. These match the hand-routed
#: reference (a second right-exit sits at 0.25, not 0.66), and stay
#: >= MERGE_THRESHOLD (0.2) from the centre so two same-side exits never merge.
_UPPER_QUARTER = 0.25
_LOWER_QUARTER = 0.75


class OverConnectedError(ValueError):
    """Raised when a node would need a fourth contact point on one side.

    The exit-priority ladder fans at most :data:`MAX_SIDE_EXITS` edges out of a
    single side while keeping them distinct; a fourth means the node is
    over-connected and the diagram should be split or re-laned (Req 5.4). The
    message names the offending node and side so the fault is actionable.
    """


def _boxes_adjacent(a: Box, b: Box) -> bool:
    """Return True when ``b`` sits directly to the right of ``a`` on the same
    row with nothing between them (one column step apart, same y).

    Used to detect the *straight-line* exit case: a target directly opposite on
    the same row and adjacent takes the right-centre exit (Req 5.1)."""
    return a.y == b.y and 0 < (b.x - a.x) <= COL_STEP + a.w


def _box_directly_below(a: Box, b: Box, others: Optional[list] = None) -> bool:
    """Return True when ``b`` sits directly below ``a`` (same column, lower) and
    no other node lies in the vertical corridor between them (Req 5.1).

    ``others`` is the set of *other* node boxes to test for an obstruction in the
    shared column between the source's bottom and the target's top."""
    same_column = a.x == b.x
    below = b.y > a.y
    if not (same_column and below):
        return False
    if not others:
        return True
    lo, hi = a.y + a.h, b.y
    left, right = a.x, a.right
    for o in others:
        if o.id in (a.id, b.id):
            continue
        # An obstacle overlaps the column horizontally and sits in the gap band.
        if o.right > left and o.x < right and lo <= o.y < hi:
            return False
    return True


def select_contacts(
    edge: EdgeSpec, placed: Dict[str, Box]
) -> Tuple[Contact, Contact]:
    """Return ``(exit, entry)`` contact points for ``edge`` via the ladder (Req 5).

    **Rule A — always exit RIGHT, never the bottom.** The service name renders
    in a caption band *below* the icon (``verticalLabelPosition=bottom``), so a
    bottom exit crosses the node's own label. Every edge therefore leaves the
    **right** face; a target that sits directly below is reached by exiting
    right, stepping into a side corridor, and descending — not by a bottom stub.
    This is the hand-routed reference's rule (edges 3/7/9 exit right, not bottom).

    **Exit ladder** (right face only):

    1. **right-centre** ``(1.0, 0.5)`` — the first exit from a side (and the
       straight-line case: a same-row adjacent target, or a target directly
       below reached via the side corridor). A single edge always keeps the
       centre.

    2. **right, biased toward the FREE side** ``(1.0, 0.25|0.75)`` (Rule B) — a
       second/third exit leans toward the side with fewer crossings: the **upper**
       quarter when the target is above the source (or level), the **lower**
       quarter when it is clearly below. :func:`spread_contacts` then finalises
       the exact bands so several same-side exits stay distinct.

    **Entry rule** (Req 5.2): a run arriving **horizontally** enters the target's
    **left** ``(0.0, 0.5)``; a run **descending** into a target below (the spine
    case) enters its **top** ``(0.5, 0.0)``. Cross-region / long over-row entries
    are set to the top by their router (Rule C), overriding this default.

    Both contact points are always explicitly set (never ``None``), so
    ``check_edge_float`` is clean; every exit leans right and every entry leans
    left/top, so ``check_edge_direction`` is clean (Req 5.5).
    """
    src = placed[edge.source]
    tgt = placed[edge.target]
    others = [b for nid, b in placed.items() if nid not in (edge.source, edge.target)]

    directly_below = _box_directly_below(src, tgt, others)
    # A target in the SAME COLUMN and lower — even when an intermediate node
    # blocks the straight drop (so ``_box_directly_below`` is False). The run
    # descends in a side corridor and must enter the target's TOP: entering the
    # LEFT would force the corridor (which is right of the column) to cross the
    # target's own glyph to reach its left face (the "edge through app-az2"
    # defect). Same-column ⇒ top entry, obstacle or not.
    same_column_below = (src.x == tgt.x) and (tgt.y > src.y)

    # --- Exit: ALWAYS the right-CENTRE face (Rule A). --------------------------
    # The exit is centred here regardless of how many edges leave this side; the
    # spread pass (:func:`spread_contacts`, driven by edge-marker order in
    # :func:`_place_and_route`) keeps the FIRST edge centred and shifts only the
    # 2nd/3rd off-centre (Rule B). Returning a pre-shifted 0.25/0.75 here was the
    # defect that pushed even a single/first exit off-centre and made its stub
    # cross the node's own caption.
    exit_pt: Contact = (1.0, 0.5)

    # --- Entry: CENTRE of the chosen face. ------------------------------------
    # A target that sits BELOW the source is descended into from its TOP-centre
    # (the run arrives vertically): a directly-below spine, a same-column chain,
    # OR a below-and-to-the-side spine (e.g. app→objstore one row down). Entering
    # the top of a lower target keeps the run off that row's centre line, where a
    # sibling edge (e.g. db→db' replication) also runs — avoiding an overlap
    # (the summary's s4×s9 corridor share). A SAME-ROW target (arriving
    # horizontally) enters the LEFT-centre. Cross-region / back-edge routers
    # override to a top entry (Rules C/G). The spread pass shifts a shared face
    # off-centre; the first stays centred.
    below_target = tgt.y > src.y
    entry_pt: Contact = (0.5, 0.0) if (directly_below or same_column_below or below_target) else (0.0, 0.5)

    return exit_pt, entry_pt


def _exit_side(exit_pt: Contact) -> str:
    """Classify an exit contact point's face, mirroring ``check_exit_thirds``.

    A bottom exit (``fy >= 1``) groups by its ``fx`` band; a top exit
    (``fy <= 0``) by ``fx``; a right exit (``fx >= 0.5``) by its ``fy`` band.
    The band coordinate is the one that varies along the face."""
    fx, fy = exit_pt
    if fy >= 1.0:
        return "bottom"
    if fy <= 0.0:
        return "top"
    return "right"


def _band_coord(exit_pt: Contact, side: str) -> float:
    """Return the coordinate that varies along ``side`` for an exit point."""
    fx, fy = exit_pt
    return fx if side in ("bottom", "top") else fy


def _with_band(exit_pt: Contact, side: str, coord: float) -> Contact:
    """Return ``exit_pt`` with its along-face band coordinate replaced."""
    fx, fy = exit_pt
    if side in ("bottom", "top"):
        return (coord, fy)
    return (fx, coord)


def _entry_face(entry_pt: Contact) -> str:
    """Classify an entry contact point's face: ``left`` (entryX<=0) or ``top``
    (entryY<=0). The band coordinate varies along the face (entryY on the left
    face, entryX on the top face)."""
    fx, fy = entry_pt
    if fy is not None and fy <= 0.0:
        return "top"
    return "left"


def _entry_band(entry_pt: Contact, face: str) -> float:
    fx, fy = entry_pt
    return (fx if fx is not None else 0.5) if face == "top" else (fy if fy is not None else 0.5)


def _with_entry_band(entry_pt: Contact, face: str, coord: float) -> Contact:
    fx, fy = entry_pt
    return (coord, fy) if face == "top" else (fx, coord)


#: The adjacent contract-legal face an over-connected face spills onto (1.10.7):
#: exits move between the right and bottom faces, entries between left and top.
_EXIT_SPILL = {"right": "bottom", "bottom": "right"}
_ENTRY_SPILL = {"left": "top", "top": "left"}
#: The centre contact of each face; the spread then distributes the band.
_FACE_CENTRE: Dict[str, Contact] = {
    "right": (1.0, 0.5), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "top": (0.5, 0.0),
}


def spill_over_connected_faces(
    edges: "list",
    placed: Dict[str, Box],
    exits: Dict[str, Contact],
    entries: Dict[str, Contact],
) -> None:
    """Move the surplus of an over-connected face onto its adjacent legal face.

    In place, on ``exits`` / ``entries`` (1.10.7, M3). A face carrying more than
    :data:`MAX_SIDE_EXITS` contacts would make :func:`spread_contacts` /
    :func:`spread_entries` raise :class:`OverConnectedError`. Instead, the
    surplus moves to the adjacent contract-legal face when it has room — exits
    right ↔ bottom, entries left ↔ top — and lands on that face's centre, so the
    spread then distributes it. The edges whose OTHER endpoint is farthest
    (Manhattan distance between box centres, edge id tiebreak) move first: a
    long run tolerates the extra turn a second face costs, a short hop does not.

    Only a face that would have raised is touched, so every layout that
    succeeded before is unchanged. When the adjacent face cannot take the
    surplus either, :class:`OverConnectedError` is raised naming both faces.
    """
    by_id = {e.id: e for e in edges}

    def _distance(eid: str) -> float:
        e = by_id[eid]
        s, t = placed[e.source], placed[e.target]
        return (abs((s.x + s.w / 2.0) - (t.x + t.w / 2.0))
                + abs((s.y + s.h / 2.0) - (t.y + t.h / 2.0)))

    for contacts, face_of, spill_to, end in (
        (exits, _exit_side, _EXIT_SPILL, "source"),
        (entries, _entry_face, _ENTRY_SPILL, "target"),
    ):
        groups: Dict[Tuple[str, str], list] = {}
        for e in edges:
            groups.setdefault((getattr(e, end), face_of(contacts[e.id])), []).append(e.id)
        for (node_id, face), eids in sorted(groups.items()):
            surplus = len(eids) - MAX_SIDE_EXITS
            if surplus <= 0 or face not in spill_to:
                continue
            other = spill_to[face]
            room = MAX_SIDE_EXITS - len(groups.get((node_id, other), []))
            if room < surplus:
                raise OverConnectedError(
                    f"node {node_id!r} has {len(eids)} edges on its {face!r} face "
                    f"and its adjacent {other!r} face has room for {max(room, 0)} "
                    f"(max {MAX_SIDE_EXITS} each); split or re-lane the diagram"
                )
            moved = sorted(eids, key=lambda eid: (-_distance(eid), eid))[:surplus]
            for eid in moved:
                contacts[eid] = _FACE_CENTRE[other]
                eids.remove(eid)
            groups.setdefault((node_id, other), []).extend(moved)


def spread_entries(edges_on_face: list) -> list:
    """Spread several arrivals on ONE target face to distinct band coordinates.

    Mirror of :func:`spread_contacts` for the entry side: the FIRST edge (marker
    order) keeps the face centre (0.5), the 2nd/3rd shift to the quarters, each
    ≥ :data:`MERGE_THRESHOLD` apart, so multiple lines entering one face don't
    stack on a single point. The face (left/top) is preserved."""
    if not edges_on_face:
        return []
    face = _entry_face(edges_on_face[0][1])
    if len(edges_on_face) == 1:
        eid, pt = edges_on_face[0]
        return [(eid, _with_entry_band(pt, face, 0.5))]
    if len(edges_on_face) > MAX_SIDE_EXITS:
        raise OverConnectedError(
            f"node has {len(edges_on_face)} edges on its {face!r} entry face "
            f"(max {MAX_SIDE_EXITS}); split or re-lane the diagram"
        )
    n = len(edges_on_face)
    bands = [0.5, _LOWER_QUARTER] if n == 2 else [0.5, _UPPER_QUARTER, _LOWER_QUARTER]
    return [
        (eid, _with_entry_band(pt, face, band))
        for (eid, pt), band in zip(edges_on_face, bands)
    ]


def spread_contacts(edges_on_side: list) -> list:
    """Spread several same-side exits to distinct band coordinates (Req 5.3, 5.4).

    ``edges_on_side`` is a list of ``(edge_id, exit_pt)`` pairs that all leave
    the *same* node on the *same* side, **in edge-marker order** (the caller
    sorts them). It returns a list of ``(edge_id, exit_pt)`` with the band
    coordinates reassigned so that:

    * the **FIRST** edge (index 0, the lowest marker) keeps the face **centre**
      (0.5) — "перший вихід по середині"; only the 2nd/3rd are shifted off it;
    * the others spread to the quarters (0.25 / 0.75), each ≥
      :data:`MERGE_THRESHOLD` from its neighbours so no two lines merge at the
      glyph (``check_exit_thirds`` clean);
    * the exit *face* is preserved (a right exit stays ``fx=1.0``; only its
      ``fy`` band moves), so the directional contract still holds.

    A side carrying more than :data:`MAX_SIDE_EXITS` edges raises
    :class:`OverConnectedError` naming the node and side rather than emitting a
    fourth contact point (Req 5.4).
    """
    if not edges_on_side:
        return []

    side = _exit_side(edges_on_side[0][1])
    if len(edges_on_side) == 1:
        # A single edge on a side always keeps the CENTRE (never a quarter).
        eid, pt = edges_on_side[0]
        return [(eid, _with_band(pt, side, 0.5))]
    if len(edges_on_side) > MAX_SIDE_EXITS:
        raise OverConnectedError(
            f"node has {len(edges_on_side)} edges on its {side!r} side "
            f"(max {MAX_SIDE_EXITS}); split or re-lane the diagram"
        )

    n = len(edges_on_side)
    # The first edge (marker order) keeps the centre; the rest take the quarters.
    # n==2 → [0.5, 0.75]; n==3 → [0.5, 0.25, 0.75]. Every pair is ≥ 0.25 apart
    # (>= MERGE_THRESHOLD), and the first is always exactly centred.
    if n == 2:
        bands = [0.5, _LOWER_QUARTER]
    else:  # n == 3
        bands = [0.5, _UPPER_QUARTER, _LOWER_QUARTER]

    return [
        (eid, _with_band(pt, side, band))
        for (eid, pt), band in zip(edges_on_side, bands)
    ]
