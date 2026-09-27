"""Corridor allocation — grid-step lanes in inter-column / inter-row gaps.

This module is the corridors slice of the ``layout/`` package split
(scored-router release 1.8.0, Phase A, task 1.2). It holds
:class:`CorridorExhaustedError` (the "needs widen" signal) and
:class:`CorridorAllocator`, relocated **verbatim** from ``layout_engine.py``.

The allocation core is a **behavior-preserving mechanical relocation**: every
method name, default and body is identical to its pre-split definition, so
``layout_engine.CorridorAllocator`` (re-imported by ``layout_engine``) keeps
resolving with no caller edit. Phase C (task 5.1) adds :meth:`CorridorAllocator.snapshot`
and :meth:`CorridorAllocator.restore` — a snapshot/restore pair over the three
occupancy dicts — so the scored solver can try a variant then undo it, leaving
no lane consumed by a rejected variant. That addition changes no existing
allocate / register_gap / capacity behavior.

The allocator depends only on the canonical layout constants (``GRID``,
``ICON_SIZE``), imported directly from :mod:`rule_engine.diagram_layout`, so it
has no dependency on the rest of the layout engine and never participates in an
import cycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

try:  # package-relative import when used as ``rule_engine.layout.corridors``
    from ..diagram_layout import ICON_SIZE, GRID
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import ICON_SIZE, GRID  # type: ignore[no-redef]


class CorridorExhaustedError(RuntimeError):
    """The "needs widen" signal: a gap has no free grid-aligned corridor left.

    Raised by :meth:`CorridorAllocator.allocate` when every grid line strictly
    inside a gap is already handed out (Req 6.4). The repair loop consumes this
    signal to push the neighbouring column / container out one ``COL_STEP`` /
    ``GRID`` step and retry, rather than placing two runs closer than one
    ``GRID`` step apart. The message names the exhausted gap and its capacity so
    the widen is actionable.
    """

    def __init__(self, gap_id: str, low: float, high: float, capacity: int):
        self.gap_id = gap_id
        self.low = low
        self.high = high
        self.capacity = capacity
        super().__init__(
            f"corridor gap {gap_id!r} (span {low}..{high}) is exhausted: all "
            f"{capacity} grid-aligned corridor line(s) are taken — widen the gap"
        )


@dataclass(frozen=True)
class AllocatorState:
    """Opaque, deep-copied snapshot token of all :class:`CorridorAllocator` occupancy.

    Produced only by :meth:`CorridorAllocator.snapshot` and consumed only by
    :meth:`CorridorAllocator.restore` (scored-router 1.8.0, Phase C, task 5.1).
    It is a full deep copy of the allocator's three mutable occupancy dicts, so
    it never aliases live state: mutating the allocator after taking a snapshot
    cannot corrupt the token, and restoring the token cannot let later live
    mutation reach through it (Req 3.1).

    ``free`` preserves list **order** exactly, because :meth:`CorridorAllocator.allocate`
    pops from the front — restoring a shuffled ``free`` would hand out lines in a
    different order and break determinism.

    The immutable config (``_grid``, ``_stride``) is intentionally *not* captured:
    it is set once in ``__init__`` and never mutated, so occupancy is the only
    state a snapshot needs to carry.
    """

    #: gap id -> (low, high) span (deep copy of ``_spans``).
    spans: Dict[str, Tuple[float, float]]
    #: gap id -> ordered list of free grid lines (deep copy of ``_free``, order preserved).
    free: Dict[str, List[int]]
    #: gap id -> set of lines already handed out (deep copy of ``_taken``).
    taken: Dict[str, Set[int]]


class CorridorAllocator:
    """Hand out distinct, grid-aligned corridor lines within inter-node gaps.

    A *gap* is the plane between two adjacent columns (or rows): a span
    ``(low, high)`` whose usable corridor lines are the whole ``GRID`` multiples
    lying **strictly inside** it — ``low`` rounded up to the next grid line,
    then every ``+ GRID`` step below ``high`` (Req 6.2). The default column gap
    is ``COL_STEP - ICON_SIZE`` wide (:meth:`column_gap` builds it from the two
    neighbouring column origins); a row gap is built the same way with
    :meth:`row_gap`.

    Each edge segment that must run through a shared gap calls
    :meth:`allocate`; the allocator returns the **next free** line and marks it
    taken, so two segments in the same gap always land on distinct lines ≥ one
    ``GRID`` step apart — the exact condition ``check_corridor_sharing`` needs to
    stay clean (Req 6.1, 6.3). When a gap has no free line left it raises
    :class:`CorridorExhaustedError`, the "needs widen" signal (Req 6.4).

    The allocator is deterministic: lines are handed out low→high in call order,
    so the same sequence of requests always yields the same assignment
    (Req 11.1). Occupancy is tracked per gap id, keyed by identity supplied by
    the caller (e.g. ``"col:2-3"`` or ``"row:edge-router:a"``).
    """

    def __init__(self, grid: int = GRID, stride: int = 2 * GRID):
        self._grid = grid
        #: Spacing between successive corridor lines in a gap (Rule D). A
        #: ``2·GRID`` stride keeps two parallel long runs visibly apart on the
        #: raster — one grid step reads as a single doubled line when scaled down
        #: — matching the hand-routed reference (edges 7/10 sit two steps apart,
        #: not one). Lines stay whole ``GRID`` multiples; the stride only widens
        #: the gap between chosen lanes (diagram-standards: widen, never narrow).
        self._stride = stride
        #: gap id -> (low, high) span registered for that gap.
        self._spans: Dict[str, Tuple[float, float]] = {}
        #: gap id -> ordered list of the free grid lines still available.
        self._free: Dict[str, list] = {}
        #: gap id -> set of lines already handed out (for occupancy queries).
        self._taken: Dict[str, set] = {}

    # -- gap construction helpers ------------------------------------------

    @staticmethod
    def column_gap(left_col_x: float, right_col_x: float) -> Tuple[float, float]:
        """Return the ``(low, high)`` span of the gap between two node columns.

        The gap is the clear plane between the **right edge** of the left column
        icon and the **left edge** of the right column icon, INSET by one
        ``GRID`` step off the left glyph so the first corridor lane is a clean
        step away from the icon (not glued 0–2px to its edge — the "no step-out"
        defect): ``left_col_x + ICON_SIZE + GRID`` … ``right_col_x``."""
        return (left_col_x + ICON_SIZE + GRID, right_col_x)

    @staticmethod
    def row_gap(top_row_y: float, bottom_row_y: float) -> Tuple[float, float]:
        """Return the ``(low, high)`` span of the gap between two node rows.

        The plane between the **bottom edge** of the upper row icon and the
        **top edge** of the lower row icon, INSET by one ``GRID`` step off the
        upper glyph so the first lane clears the icon: ``top_row_y + ICON_SIZE +
        GRID`` … ``bottom_row_y``."""
        return (top_row_y + ICON_SIZE + GRID, bottom_row_y)

    # -- allocation ---------------------------------------------------------

    def _grid_lines(self, low: float, high: float) -> list:
        """Return the corridor lines strictly inside ``(low, high)``.

        Lines start at ``ceil(low/GRID + 1)*GRID`` and step by ``self._stride``
        (default ``2·GRID``, Rule D) below ``high`` — every line is a whole
        ``GRID`` multiple (Req 6.2), offset from the gap edges by ≥ one ``GRID``
        step and from each other by the stride so two parallel runs stay visibly
        separate (Req 6.1). A gap too narrow for a stride-spaced line still
        yields at least the single first line when one fits."""
        first_k = int(math.floor(low / self._grid)) + 1
        lines: list = []
        line = first_k * self._grid
        while line < high:
            lines.append(int(line))
            line += self._stride
        return lines

    def register_gap(self, gap_id: str, low: float, high: float) -> int:
        """Register (or re-register) a gap's span; return its corridor capacity.

        Idempotent for a given ``(gap_id, low, high)``; registering the same id
        with a **wider** span (after a widen repair) refreshes its free lines
        while preserving already-taken lines. Returns the number of free
        grid-aligned corridor lines the gap can still hand out."""
        prev = self._spans.get(gap_id)
        if prev == (low, high) and gap_id in self._free:
            return len(self._free[gap_id])
        self._spans[gap_id] = (low, high)
        taken = self._taken.setdefault(gap_id, set())
        self._free[gap_id] = [ln for ln in self._grid_lines(low, high) if ln not in taken]
        return len(self._free[gap_id])

    def capacity(self, gap_id: str) -> int:
        """Return how many free corridor lines ``gap_id`` still has."""
        return len(self._free.get(gap_id, []))

    def allocate(self, gap_id: str, low: float, high: float) -> int:
        """Reserve and return the next free grid-aligned corridor line in a gap.

        Lines are handed out low→high in call order; each is a whole ``GRID``
        multiple strictly inside ``(low, high)`` (Req 6.1, 6.2). Two allocations
        for the same gap never return the same line, so unrelated edges routed
        on allocated lines never share a straight corridor
        (``check_corridor_sharing`` clean, Req 6.3).

        Raises :class:`CorridorExhaustedError` — the "needs widen" signal — when
        the gap has no free line left (Req 6.4)."""
        self.register_gap(gap_id, low, high)
        free = self._free[gap_id]
        if not free:
            cap = len(self._grid_lines(low, high))
            raise CorridorExhaustedError(gap_id, low, high, cap)
        line = free.pop(0)
        self._taken[gap_id].add(line)
        return line

    def allocate_dense(self, gap_id: str, low: float, high: float) -> int:
        """Reserve the next free line at **GRID** spacing rather than the stride.

        The stride (``2·GRID``) keeps two parallel long runs visibly apart, which
        is the right default — but a narrow band (a 30px row gap left by a
        container caption strip) then holds exactly one strided line, and a third
        run in that band has nowhere to go. One grid step apart is still a legal
        separation (``check_corridor_sharing`` asks for ≥ one step); it is merely
        tighter. So this is the fallback between the strided allocation and giving
        up: still distinct, still grid-aligned, never a silent merge.

        Raises :class:`CorridorExhaustedError` when even GRID spacing is full.
        """
        self.register_gap(gap_id, low, high)
        taken = self._taken.setdefault(gap_id, set())
        first_k = int(math.floor(low / self._grid)) + 1
        line = first_k * self._grid
        while line < high:
            if int(line) not in taken:
                taken.add(int(line))
                if gap_id in self._free:
                    self._free[gap_id] = [
                        ln for ln in self._free[gap_id] if ln != int(line)
                    ]
                return int(line)
            line += self._grid
        raise CorridorExhaustedError(
            gap_id, low, high, int(max(0, (high - low) // self._grid))
        )

    # -- snapshot / restore -------------------------------------------------

    def snapshot(self) -> AllocatorState:
        """Return an opaque, deep-copied token of all lane occupancy.

        The token captures ``_spans``, ``_free`` (order preserved) and
        ``_taken`` as a fresh deep copy — each inner list and set is copied, not
        just the outer dict — so it never aliases live state (Req 3.1). The scored
        solver snapshots before trying a variant and :meth:`restore`\\ s afterwards
        so a rejected variant consumes no lanes. ``O(state)``; the immutable grid
        / stride config is not captured because it never changes."""
        return AllocatorState(
            spans={gid: span for gid, span in self._spans.items()},
            free={gid: list(lines) for gid, lines in self._free.items()},
            taken={gid: set(lines) for gid, lines in self._taken.items()},
        )

    def restore(self, token: AllocatorState) -> None:
        """Reset occupancy wholesale to ``token``.

        Replaces ``_spans``, ``_free`` and ``_taken`` with fresh deep copies of
        the token's contents, so after ``restore`` :meth:`capacity` and every
        subsequent :meth:`allocate` behave as if the calls made since the snapshot
        never happened (Req 3.2). The reset is **total** — it overwrites the three
        dicts rather than reconciling them — so a variant that widened a gap,
        allocated several lanes, then raised :class:`CorridorExhaustedError`
        mid-way still restores cleanly. Copying out of the token (rather than
        adopting its objects) keeps the token reusable: the same token may be
        restored to any number of times, and later live mutation can never reach
        back through it."""
        self._spans = {gid: span for gid, span in token.spans.items()}
        self._free = {gid: list(lines) for gid, lines in token.free.items()}
        self._taken = {gid: set(lines) for gid, lines in token.taken.items()}
