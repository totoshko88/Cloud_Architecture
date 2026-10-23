"""Node placement, container sizing and in-VPC block centring (Req 3, Req 4).

This module is the placement slice of the ``layout/`` package split
(scored-router release 1.8.0, Phase A, task 1.2). It holds the three public
placement entry points — :func:`place_nodes`, :func:`size_containers` and
:func:`centre_block_in_vpc` — relocated **verbatim** from ``layout_engine.py``,
so ``layout_engine.place_nodes`` (re-imported by ``layout_engine``) keeps
resolving with no caller edit.

This is a **behavior-preserving mechanical relocation**: every function body is
identical to its pre-split definition. The *helpers* these three functions call
(``_place_base``, ``_region_secondary_offset``, ``_assign_nodes_to_leaves``,
``_stack_peer_azs_in_vpc``, ``_equalize_peer_widths``, ``_size_account``, the
axis/extent utilities, ``_validate_spec`` and the ``_ORIGIN`` constant) stay in
``layout_engine`` for now and are imported back here by name, so the moved
bodies reference them exactly as before.

No import cycle: ``layout_engine`` defines every symbol imported below **before**
it imports this module (the import-back statement sits at the tail of
``layout_engine`` after all the base helpers), so by the time ``place`` is
imported those names already exist on the partially-initialised
``layout_engine`` module.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from dataclasses import replace

try:  # package-relative import when used as ``rule_engine.layout.place``
    from ..diagram_layout import CONTAINER_PAD, GRID, ICON_SIZE, COL_STEP, ROW_STEP
    from ..geometry import (
        Box, LABEL_BAND, CONTAINER_LABEL_BAND, _CAPTION_TEXT_CHAR_W, _CONTAINER_LABEL_INSET, caption_lines,
        container_caption_need,
    )
    from .model import DiagramSpec
    from .base import (
        SpecError,
        TOP_LANE,
        _top_lane_containers,
        _ORIGIN,
        _snap,
        _grid_ceil,
        col_step,
        _validate_spec,
        _secondary_axis,
        _place_base,
        _region_secondary_offset,
        _region_primary_rebase,
        _extent,
        _with_extent,
        _container_axes,
        _children_of,
        _assign_nodes_to_leaves,
        _bbox,
        _stack_peer_azs_in_vpc,
        _equalize_peer_widths,
        _size_account,
    )
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import CONTAINER_PAD, GRID, ICON_SIZE, COL_STEP, ROW_STEP  # type: ignore[no-redef]
    from geometry import (  # type: ignore[no-redef]
        Box, LABEL_BAND, CONTAINER_LABEL_BAND, _CAPTION_TEXT_CHAR_W, _CONTAINER_LABEL_INSET, caption_lines,
        container_caption_need,
    )
    from layout.model import DiagramSpec  # type: ignore[no-redef]
    from layout.base import (  # type: ignore[no-redef]
        SpecError,
        TOP_LANE,
        _top_lane_containers,
        _ORIGIN,
        _snap,
        _grid_ceil,
        col_step,
        _validate_spec,
        _secondary_axis,
        _place_base,
        _region_secondary_offset,
        _region_primary_rebase,
        _extent,
        _with_extent,
        _container_axes,
        _children_of,
        _assign_nodes_to_leaves,
        _bbox,
        _stack_peer_azs_in_vpc,
        _equalize_peer_widths,
        _size_account,
    )


#: Theme 21/18 (1.10.10): the kinds that form the EXTERNAL band — a peer AWS
#: account or a peer cloud drawn as a disjoint sibling boundary outside the
#: primary account. Their member nodes are wrapped into multiple rows by
#: :func:`_wrap_external_bands` so a long row of peers stacks instead of running
#: the canvas ever wider (which `canvas-quality` → aspect-ratio penalises).
_EXTERNAL_BAND_KINDS = frozenset({"peer_account", "external_cloud"})

#: Horizontal gap between two external sibling boxes on one band, and the
#: vertical gap between stacked external bands. One region step keeps a clear
#: lane for a cross-boundary edge between peers; a whole GRID multiple. Scales
#: with the live column step (Theme 36) — resolved per ``layout()`` call, not at
#: import — so a widened spec spreads its external bands too.
def _external_band_gap() -> int:
    return _grid_ceil(col_step())


def _external_groups(spec: DiagramSpec) -> Dict[str, list]:
    """``boundary id -> member node ids`` (declared order) of the external
    sibling bands (peer_account / external_cloud), or ``{}`` when the spec
    declares fewer than two: one band is not a sibling group."""
    kind_of = {c.id: c.kind for c in spec.containers}
    groups: Dict[str, list] = {}
    for n in spec.nodes:
        if n.container is not None and kind_of.get(n.container) in _EXTERNAL_BAND_KINDS:
            groups.setdefault(n.container, []).append(n.id)
    return groups if len(groups) >= 2 else {}


def external_band_pitch(spec: DiagramSpec) -> int:
    """The one slot pitch every external sibling band uses (1.10.12 WS6, C8).

    Each band used to be sized from its own caption-aware footprint, so two
    3-node bands came out 618 and 660 wide (SEP 09) and their node columns did
    not line up. The group now shares one pitch: the widest node caption across
    ALL its bands (never narrower than the icon) plus two grid steps of air
    between neighbouring captions, never tighter than the live column step.
    A band is then ``n_slots x pitch + 2 x pad`` wide (:func:`size_containers`),
    so bands with the same slot count are identical, a band with fewer slots is
    proportionally narrower, and slot columns line up across bands. ``0`` when
    the spec has no external sibling group."""
    groups = _external_groups(spec)
    if not groups:
        return 0
    labels = dict(getattr(spec, "node_labels", ()) or ())
    widest = float(ICON_SIZE)
    for ids in groups.values():
        for nid in ids:
            lines = caption_lines(labels.get(nid, ""))
            if lines:
                widest = max(widest, max(len(ln) for ln in lines) * _CAPTION_TEXT_CHAR_W)
    return max(_grid_ceil(col_step()), _grid_ceil(widest + 2 * GRID))


def _repitch_external_bands(placed: Dict[str, Box], spec: DiagramSpec) -> Dict[str, Box]:
    """Re-space each external band's slot columns at :func:`external_band_pitch`,
    keeping its first column where it is (relative order and rows unchanged)."""
    groups = _external_groups(spec)
    pitch = external_band_pitch(spec)
    if not groups or not pitch:
        return placed
    out = dict(placed)
    for ids in groups.values():
        xs = sorted({placed[i].x for i in ids})
        rank = {x: k for k, x in enumerate(xs)}
        for i in ids:
            b = placed[i]
            out[i] = replace(b, x=_snap(xs[0] + rank[b.x] * pitch))
    return out


def _wrap_external_bands(placed: Dict[str, Box], spec: DiagramSpec) -> Dict[str, Box]:
    """Stack external sibling boxes (peer_account / external_cloud) into rows.

    Theme 21/18. A spec may declare several peer-account / external-cloud
    boundaries (a cross-cloud composition: the primary account plus N peer
    accounts, an Atlas project, a peer cloud). :func:`_place_base` lays their
    member nodes out along one external lane, so with enough peers the external
    band runs the canvas ever **wider** — a long single row that trips
    ``canvas-quality`` (aspect-ratio) and dwarfs the subject. This post-pass
    groups the external nodes by their boundary, measures each group's
    footprint, and **packs the groups left→right with a wrap**: when the next
    group would push the row past the primary subject's width, it drops to a new
    band one group-height below. Each group's nodes move together by one
    ``(dx, dy)`` translation, so their internal layout — and every routed
    waypoint relative to them — is preserved; :func:`size_containers` then wraps
    each boundary box around its (moved) members, and the bands read as a tidy
    grid of disjoint siblings rather than one over-wide strip.

    Scoped strictly to the two external-band kinds, so no diagram without a
    peer_account / external_cloud boundary (every shipped golden) is touched.
    """
    # Group external nodes by their boundary id, in a stable declared order.
    groups = _external_groups(spec)
    if not groups:
        return placed  # 0 or 1 external box never needs wrapping
    # 1.10.12 WS6: one shared slot pitch across the group (C8).
    placed = _repitch_external_bands(placed, spec)
    half = external_band_pitch(spec) / 2.0

    # Band extent of each group: its slot cells (pitch-wide, centred on each
    # column) across, icon + caption band down.
    def _footprint(box: Box) -> Tuple[int, int, int, int]:
        cx = box.x + box.w / 2.0
        return (cx - half, box.y, cx + half, box.y + box.h + LABEL_BAND)

    group_bbox: Dict[str, Tuple[int, int, int, int]] = {}
    for gid, ids in groups.items():
        xs1 = min(_footprint(placed[i])[0] for i in ids)
        ys1 = min(_footprint(placed[i])[1] for i in ids)
        xs2 = max(_footprint(placed[i])[2] for i in ids)
        ys2 = max(_footprint(placed[i])[3] for i in ids)
        group_bbox[gid] = (xs1, ys1, xs2, ys2)

    # Edge-aware ordering (Theme 37). A purely geometric x-sort packs the groups
    # left→right regardless of what each one connects to, so an account-linked
    # group can land far from its target and its cross-band edge rakes across
    # the grid (crossings-over-hard-cap). Instead order each group by the MEAN x
    # of the subject-side nodes its member edges reach: a group that feeds the
    # account sits above the columns it links to, so its edge drops almost
    # straight down. Groups with NO account/SEP edge (pure external-context
    # clusters — identity / integrations / sandbox here) have no edge to cross
    # anything, so they sort LAST (by their own x) and fill the remaining grid
    # cells without affecting the crossing count.
    external_ids_all = {i for ids in groups.values() for i in ids}
    _node_x = {nid: b.x for nid, b in placed.items()}

    def _affinity(gid: str) -> Tuple[int, float, int]:
        members = set(groups[gid])
        targets = []
        for e in spec.edges:
            if e.source in members and e.target not in external_ids_all:
                targets.append(_node_x.get(e.target))
            elif e.target in members and e.source not in external_ids_all:
                targets.append(_node_x.get(e.source))
        targets = [x for x in targets if x is not None]
        if targets:
            return (0, sum(targets) / len(targets), group_bbox[gid][0])
        # No account/SEP edge: sort after all linked groups, by own x.
        return (1, float(group_bbox[gid][0]), group_bbox[gid][0])

    order = sorted(groups, key=_affinity)

    # Width budget: the primary subject's horizontal extent (the account/region/
    # vpc/non-external nodes). The external grid wraps to stay within it so the
    # canvas does not grow wider than the subject it annotates. Fall back to two
    # region steps when there is no inner subject to measure against.
    external_ids = {i for ids in groups.values() for i in ids}
    inner = [b for nid, b in placed.items() if nid not in external_ids]
    if inner:
        subj_left = min(b.x for b in inner)
        subj_right = max(b.x + b.w for b in inner)
        subj_top = min(b.y for b in inner)
        subj_bottom = max(b.y + b.h for b in inner)
        band_left = subj_left
        max_right = max(subj_right, subj_left + 2 * col_step())
    else:  # pragma: no cover - external-only spec is not a real diagram
        band_left = _ORIGIN[0]
        max_right = band_left + 2 * col_step()
        subj_top = subj_bottom = None

    # The external band starts one gap below the lowest external row as placed
    # (``_place_base`` already drops it below the account); keep that top.
    band_top = min(group_bbox[g][1] for g in order)
    row_h = max((group_bbox[g][3] - group_bbox[g][1]) for g in order)

    # Height budget (Theme 37, tall-account fix). When the external bands sit
    # ABOVE the subject (band_top < subj_top -- the landscape case, where the
    # externals live in the top `actors` row and the account is a tall body
    # below), a long VERTICAL stack of bands runs down INTO the account
    # (container-overlap). Cap the stack to the clear vertical gap above the
    # subject and, when it is exhausted, start a NEW COLUMN of bands to the
    # right instead of descending. This keeps the external grid tucked in the
    # dead space above the account and never overlapping it. The budget is only
    # armed in that above-subject case; when the externals sit BELOW the subject
    # (the 1.10.10 cross-cloud behaviour) band_height stays None and the stack
    # grows downward unbounded exactly as before -- backward-safe.
    band_height = None
    if subj_top is not None and band_top < subj_top:
        clear = subj_top - band_top - _external_band_gap()
        # Only arm the budget when a single band already fits the gap; otherwise
        # there is no room above the subject and we leave the legacy layout
        # (a degraded candidate the caller already flags) rather than crush it.
        if clear >= row_h:
            band_height = clear
    # Column pitch for the grid wrap: one subject-width-or-wider block plus a
    # gap, so a second column of bands clears the first.
    col_pitch = _snap((max_right - band_left) + _external_band_gap())

    # Theme 41: single-column stack for the pure-external bands. The groups in
    # affinity bucket 1 (``_affinity`` returns 0 for account-linked groups and
    # 1 for groups with NO cross-band edge — pure external-context clusters:
    # identity / integrations / sandbox on 09) have no edge that can cross
    # anything, so scattering them through the shared left→right wrap only to
    # fill grid cells reads as noise: the owner wants them lined up one under
    # another, grid-aligned. When the bands sit ABOVE the subject (the
    # landscape case) the clear top gap holds only one or two bands, so the wrap
    # spills the rest into far-right columns at mismatched x — exactly the
    # scatter the owner flagged. Instead, when there are ≥ 2 such pure-external
    # groups above a subject, lift them OUT of the wrap and stack them in one
    # dedicated column to the RIGHT of the subject, sharing a single left edge
    # and descending top→bottom. A right-of-subject column has the subject's
    # full height to grow into (it never descends INTO the account the way an
    # above-subject stack would), so no height budget is needed and three bands
    # line up cleanly. Zero crossings are added because none of these groups has
    # a cross-band edge (proven by the affinity bucket). Linked groups keep the
    # existing wrap untouched. Armed only in the above-subject landscape case
    # with ≥ 2 pure-external groups, so every other diagram — and the whole
    # shipped golden corpus, which declares no external bands at all — is inert.
    pure_groups = [g for g in order if _affinity(g)[0] == 1]
    stack_pure = (
        subj_top is not None
        and band_top < subj_top
        and len(pure_groups) >= 2
    )
    linked_order = [g for g in order if g not in pure_groups] if stack_pure else order

    cur_x = band_left
    cur_y = band_top
    col_base_x = band_left
    moves: Dict[str, Tuple[int, int]] = {}
    for gid in linked_order:
        gx1, gy1, gx2, gy2 = group_bbox[gid]
        gw = gx2 - gx1
        # Horizontal wrap: if this group would overrun the subject width, drop
        # to a new band one row-height down within the current column.
        if cur_x != col_base_x and cur_x + gw > col_base_x + (max_right - band_left):
            cur_x = col_base_x
            cur_y = _snap(cur_y + row_h + _external_band_gap())
        # Vertical (height) wrap: if armed and this new band would push the
        # stack past the clear gap above the subject, start a new COLUMN to the
        # right at the top band row instead of descending into the subject.
        if (
            band_height is not None
            and cur_y != band_top
            and (cur_y + row_h) - band_top > band_height
        ):
            col_base_x = _snap(col_base_x + col_pitch)
            cur_x = col_base_x
            cur_y = band_top
        moves[gid] = (_snap(cur_x - gx1), _snap(cur_y - gy1))
        cur_x = _snap(cur_x + gw + _external_band_gap())

    if stack_pure:
        # Place the pure-external bands as one left-aligned vertical column to
        # the right of everything laid so far (the linked bands + the subject),
        # keeping a clear gap. The column's left edge is a single shared x; each
        # band drops one footprint-height below the previous. Order top→bottom
        # by declared order (stable), so the stack reads in the spec's intent.
        linked_right = max(
            (group_bbox[g][2] + moves[g][0]) for g in linked_order
        ) if linked_order else max_right
        stack_x = _snap(max(linked_right, max_right) + _external_band_gap())
        stack_y = band_top
        for gid in pure_groups:
            gx1, gy1, gx2, gy2 = group_bbox[gid]
            moves[gid] = (_snap(stack_x - gx1), _snap(stack_y - gy1))
            stack_y = _snap(stack_y + (gy2 - gy1) + _external_band_gap())

    out = dict(placed)
    for gid, ids in groups.items():
        dx, dy = moves[gid]
        if dx == 0 and dy == 0:
            continue
        for i in ids:
            b = out[i]
            out[i] = replace(b, x=_snap(b.x + dx), y=_snap(b.y + dy))

    # Theme 42: lift the subject up to the bands that actually sit ABOVE it.
    # `_place_base` drops the account/subject below the WHOLE external-lane
    # extent, which is correct when every external band is a row above it. But
    # once the pure-external bands are stacked into a side column (Theme 41) or
    # otherwise moved beside the subject, the bands that forced the drop no
    # longer sit over the subject's columns — only the account-linked ingress
    # row does — so the subject hangs far below its one real overhead band,
    # leaving a tall dead-space gap and raking its cross-band edges (e.g. the
    # ingress CloudFront→API-Gateway drop and the Lambda→Atlas return) across
    # it. Lift every inner (subject) node UP by the slack between the subject
    # top and the lowest bottom of the bands that genuinely x-overlap the
    # subject's columns (plus one gap). Scoped hard: armed only when the subject
    # sits BELOW the external bands (band_top < subj_top — the landscape case)
    # AND at least one band does NOT x-overlap the subject (so there is slack to
    # reclaim; a plain single-row-above layout has every band overlapping and is
    # untouched). The lift never moves a node to a NEGATIVE y, and because the
    # non-overlapping bands are by definition clear of the subject's x-span,
    # raising the subject into their y-range collides with none of them.
    if inner and subj_top is not None and band_top < subj_top:
        def _band_box(gid):
            gx1, gy1, gx2, gy2 = group_bbox[gid]
            dx, dy = moves[gid]
            return (gx1 + dx, gy1 + dy, gx2 + dx, gy2 + dy)

        over = []  # bands whose final x-span overlaps the subject's columns
        side = []  # bands entirely beside the subject
        for gid in order:
            bx1, by1, bx2, by2 = _band_box(gid)
            if not (bx2 <= subj_left or subj_right <= bx1):
                over.append((bx1, by1, bx2, by2))
            else:
                side.append((bx1, by1, bx2, by2))
        if over and side:
            overhead_bottom = max(by2 for _, _, _, by2 in over)
            new_top = _snap(overhead_bottom + _external_band_gap())
            # `placed` holds NODES only (containers are sized later), so subj_top
            # is the topmost in-subject NODE, which sits inside its container
            # chrome: size_containers will wrap the subject box ~CONTAINER_PAD
            # per nesting level ABOVE that node. Reserve that chrome so the
            # resized BOX — not just the node — clears the overhead band. The
            # subject here is a nested envelope (account ⊃ region ⊃ vpc at most),
            # so three top pads is a safe, slightly-conservative margin: the
            # box lands at or just below new_top, never overlapping the band.
            nest_margin = 3 * CONTAINER_PAD
            lift = (subj_top - new_top) - nest_margin
            if lift > 0:
                external_set = external_ids
                for nid, b in list(out.items()):
                    if nid in external_set:
                        continue
                    out[nid] = replace(b, y=_snap(max(0, b.y - lift)))

    return out


def lift_subject_over_external_lane(
    placed: Dict[str, Box], containers: Dict[str, Box], spec: DiagramSpec
) -> Tuple[Dict[str, Box], Dict[str, Box]]:
    """Theme 44: lift an account subject that hangs too far below its overhead
    external lane (SEP 03/08). The companion of Theme 42 for the PLAIN external-
    lane case (externals as ordinary ``actors``-lane nodes above an ``account``
    envelope, not peer_account bands). ``_place_base`` drops the in-account lanes
    clear of the WHOLE external-lane extent, over-clearing when the external row
    is a single short band — a tall dead-space gap above the account.

    Runs AFTER ``size_containers`` so the REAL account box is known: it computes
    the lift from the account box top (not an estimate of the nesting chrome),
    then translates the account's container boxes AND its in-boundary nodes up by
    one uniform delta. A pure translation preserves every internal coordinate and
    routed waypoint, so no re-size is needed and nothing can overlap by
    construction. Scoped hard: armed only with an account envelope whose top sits
    more than one gap below the lowest overhead external node that x-overlaps its
    columns; the lift is the exact excess, never makes a coordinate negative, and
    leaves the external row and every non-account box untouched. A diagram already
    tight above the account sees excess <= 0 and is byte-inert (the shipped
    goldens; the k8s cluster, whose Ingress actor sits a full drop above it, is
    the one that legitimately tightens)."""
    from .base import EXTERNAL_LANES
    acct_ids = [c.id for c in spec.containers if c.kind == "account"]
    if not acct_ids:
        return placed, containers
    acct_id = acct_ids[0]
    acct = containers.get(acct_id)
    if acct is None:
        return placed, containers
    ext_ids = {n.id for n in spec.nodes if n.lane in EXTERNAL_LANES}
    exts = [placed[i] for i in ext_ids if i in placed]
    if not exts:
        return placed, containers
    # External nodes above the account box that x-overlap its columns.
    overhead = [
        b for b in exts
        if b.y + b.h <= acct.y
        and not (b.x + b.w <= acct.x or acct.x + acct.w <= b.x)
    ]
    if not overhead:
        return placed, containers
    overhead_bottom = max(b.y + b.h for b in overhead)
    new_top = _snap(overhead_bottom + _external_band_gap())
    lift = acct.y - new_top
    if lift <= 0:
        return placed, containers
    # Everything inside the account envelope: its descendant containers + the
    # nodes they hold. Translate them AND the account box up by `lift`.
    acct_descendants = {acct_id}
    changed = True
    parent_of = {c.id: c.parent for c in spec.containers}
    while changed:
        changed = False
        for cid, par in parent_of.items():
            if par in acct_descendants and cid not in acct_descendants:
                acct_descendants.add(cid); changed = True
    inner_node_ids = {
        n.id for n in spec.nodes
        if n.lane not in EXTERNAL_LANES
    }
    out_nodes = dict(placed)
    for nid in inner_node_ids:
        b = out_nodes.get(nid)
        if b is not None:
            out_nodes[nid] = replace(b, y=_snap(max(0, b.y - lift)))
    out_conts = dict(containers)
    for cid in acct_descendants:
        b = out_conts.get(cid)
        if b is not None:
            out_conts[cid] = replace(b, y=_snap(max(0, b.y - lift)))
    return out_nodes, out_conts


def place_nodes(spec: DiagramSpec) -> Dict[str, Box]:
    """Place every node on the lane grid, returning ``id -> Box`` (Req 3).

    Placement is pure and coordinate-free in its input: each node's ``x``/``y``
    is derived only from its ``(lane, region, slot, sub)`` indices and the
    canonical constants (Req 3.1). The lane's ordinal index is the **primary**
    axis and the slot is the **secondary** axis; which of x/y each maps to is
    chosen from ``spec.axis`` (Req 2.2, 2.3):

    * ``north-south`` (infra/landscape) — lane index → **row** (``y``, top→bottom),
      slot → **column** (``x``, left→right).
    * ``left-right`` (flow/summary) — lane index → **column** (``x``), slot →
      **row** (``y``).

    Region B's block is region A translated along the **secondary** axis by a
    *content-derived* step (:func:`_region_secondary_offset` — region A's own
    footprint extent + :data:`REGION_GAP`), so the two peer regions sit
    side-by-side and never overlap, and B is a mirror-symmetric copy of A
    (Req 3.3). Placing peers along the secondary axis (not the primary tier
    axis) is what keeps the peer VPC containers disjoint. Account-level ("")
    nodes stay at the base origin. ``sub`` nudges a node along the secondary
    axis by :data:`SUB_STEP` for a sub-row. Every emitted origin is a whole
    ``GRID`` multiple (Req 3.2), so ``check_grid_alignment`` is clean by
    construction, and unique ``(lane, region, slot)`` keys (enforced by
    :func:`_validate_spec`) keep footprints non-overlapping (Req 2.5, 3.5).

    Raises :class:`SpecError` (via :func:`_validate_spec`) for an unknown lane,
    a duplicate slot, or a dangling edge before any placement is attempted.
    """
    _validate_spec(spec)

    base_x, base_y = _ORIGIN
    # Pass 1: place everything with no region offset (region A/B/"" overlapping).
    base = _place_base(spec, base_x, base_y)

    # Pass 2: translate region B off along the secondary axis by the
    # content-derived step, so peers sit side-by-side and never overlap. Theme 45:
    # also lift region B along the PRIMARY (tier) axis so its topmost tier is
    # level with region A's — a no-op (delta 0) when the peers share lanes (every
    # symmetric HA golden), and the fix for a disjoint-lane peer (k8s ns-data)
    # that would otherwise land diagonally below A and bloat the outer envelope.
    secondary = _secondary_axis(spec.axis)
    primary = "y" if spec.axis == "north-south" else "x"
    offset = _region_secondary_offset(spec, base)
    primary_lift = _region_primary_rebase(spec, base)

    placed: Dict[str, Box] = {}
    for node in spec.nodes:
        box = base[node.id]
        if node.region == "b":
            low, size = _extent(box, secondary)
            box = _with_extent(box, secondary, _snap(low + offset), size)
            if primary_lift:
                plo, psize = _extent(box, primary)
                box = _with_extent(box, primary, _snap(plo + primary_lift), psize)
        placed[node.id] = box

    # Compact flow only: centre each account-level ("") node over the SECONDARY
    # span of the region blocks, so a DNS that fans to both regions sits above
    # their midpoint rather than hugging region A's column (the summary
    # reference's top-centred DNS). Scoped to compact so the landscape edge row
    # — which the reference pins at the top-left — is unchanged.
    if spec.compact:
        region_boxes = [placed[n.id] for n in spec.nodes if n.region in ("a", "b")]
        acct_nodes = [n for n in spec.nodes if n.region == ""]
        if region_boxes and acct_nodes:
            lo = min(_extent(b, secondary)[0] for b in region_boxes)
            hi = max(_extent(b, secondary)[0] + _extent(b, secondary)[1] for b in region_boxes)
            span_centre = (lo + hi) / 2.0
            for n in acct_nodes:
                box = placed[n.id]
                _low, size = _extent(box, secondary)
                new_low = _snap(span_centre - size / 2.0)
                placed[n.id] = _with_extent(box, secondary, new_low, size)

    # Theme 21/18: stack external sibling boxes (peer_account / external_cloud)
    # into multiple bands when a single external row would run the canvas too
    # wide. Inert unless the spec declares ≥ 2 external-band boundaries.
    placed = _wrap_external_bands(placed, spec)
    return placed


def size_containers(
    placed: Dict[str, Box],
    spec: DiagramSpec,
    pad: int = CONTAINER_PAD,
    min_w: Optional[Dict[str, int]] = None,
) -> Dict[str, Box]:
    """Size every container bottom-up, returning ``id -> Box`` (Req 4).

    * **Bottom-up footprint bounding box + pad** — each container's box wraps
      the bounding box of its children's footprints (icon + LABEL_BAND) expanded
      by ``pad`` on every side. Deepest containers (az) are sized first, then
      their parent (vpc) wraps the az boxes, then the account wraps the vpc
      bands — so a parent's bottom/right clears its deepest child's footprint by
      ≥ ``pad`` by construction (Req 4.1, 4.4).
    * **Equal-width bands** — peer containers (same kind, region-siblings) take
      the pair's **max** extent along the secondary axis, widened toward the
      shared centre so outer edges stay put and the two bands read as one
      mirror-symmetric row (Req 4.3).
    * **Account envelope** — the outermost container wraps every region band +
      ``pad``, with no trailing empty margin (Req 4.5).
    * **Caption strip on the top edge (v1.6.0)** — the top padding is ``pad +
      CONTAINER_LABEL_BAND``, not ``pad``. A draw.io group draws its caption
      *inside* its own top edge, so a uniform ``pad`` made the caption band and
      the top padding the same 30px strip: the first content row began exactly
      where the caption ended, leaving **no corridor lane inside the container
      above its first row**. Any edge descending into the container then had to
      run through the caption — which is precisely what
      ``edge-crosses-container-label`` flags, and what four edges on the
      re-connected landscape did (an account-row edge and a CDN→LB origin fetch
      slicing ``vpc-primary us-east-1``). Reserving the caption its own strip
      restores ``pad`` as real clearance and gives every container an entry
      corridor below its caption.

    * **Shared slot pitch (1.10.12 WS6)** — an external sibling band
      (peer_account / external_cloud, two or more declared) is ``n_slots x
      pitch + 2 x pad`` wide, centred on its slot columns
      (:func:`external_band_pitch`), not its own caption-aware footprint.
    * **Caption fit (1.10.12 WS6)** — ``min_w`` (from
      :func:`fit_container_captions`) widens a container to the right to hold
      its caption.

    The result passes ``check_container_padding`` and ``check_container_overlap``.
    """
    primary, secondary = _container_axes(spec)
    leaf_nodes = _assign_nodes_to_leaves(spec, placed)
    child_containers = _children_of(spec)
    kind_of = {c.id: c.kind for c in spec.containers}
    # 1.10.6: containers whose first row is entered from the side reserve one
    # corridor lane below their caption strip (``_top_lane_containers``).
    lane_containers = _top_lane_containers(spec)
    bands = _external_groups(spec)
    pitch = external_band_pitch(spec)
    min_w = min_w or {}

    boxes: Dict[str, Box] = {}

    def _size(cid: str) -> Box:
        if cid in boxes:
            return boxes[cid]
        child_boxes: list = []
        for child in child_containers.get(cid, []):
            child_boxes.append(_size(child.id))
        child_boxes.extend(placed[nid] for nid in leaf_nodes.get(cid, []))
        if not child_boxes:
            raise SpecError(
                f"container {cid!r} has no children to size around "
                "(empty region band)"
            )
        x0, y0, x1, y1 = _bbox(child_boxes)
        top = pad + CONTAINER_LABEL_BAND  # reserve the caption strip (see below)
        if cid in lane_containers:
            top += TOP_LANE
        box = Box(cid, x0 - pad, y0 - top, (x1 - x0) + 2 * pad, (y1 - y0) + top + pad)
        members = bands.get(cid)
        if members and pitch and not child_containers.get(cid):
            xs = sorted({placed[i].x for i in members})
            left = _snap(xs[0] + ICON_SIZE / 2.0 - pitch / 2.0 - pad)
            # Width is the slot-pitch grid (``len(xs) * pitch``) OR the actual
            # member extent, whichever is WIDER, so the band box always encloses
            # its rightmost member. A scored placement can spread a band's slots
            # wider than the nominal pitch (SEP 09's ingress row: actorsbox 40,
            # cloudfront 480, dns 700, atlas 920 — gaps of 440/220/220, not a
            # uniform pitch), and a pitch-only width then clips the last node
            # OUTSIDE its own box. An orphaned node (outside every container)
            # trips ``container-padding`` against the account it x-overlaps, and
            # the repair loop grows the account to "pad" it — stretching the
            # account into the external bands (``container-overlap``). Enclosing
            # the member keeps the node housed, so neither finding fires.
            right_members = max(_snap(placed[i].x + ICON_SIZE) for i in members) + pad
            width = max(len(xs) * pitch + 2 * pad, right_members - left)
            box = Box(cid, left, box.y, width, box.h)
        if box.w < min_w.get(cid, 0):
            box = Box(cid, box.x, box.y, min_w[cid], box.h)
        boxes[cid] = box
        return box

    # Size the deepest (az) containers first, around their own node footprints.
    for c in spec.containers:
        if c.kind == "az":
            _size(c.id)

    # Stack peer AZs of one VPC on a shared secondary-axis range: the two AZ
    # boxes of a VPC get the SAME secondary low/size (equal width + shared
    # x-range for a North–South diagram), so they read as one stacked column
    # (Req 12.1, 12.2). Their primary-axis ranges are already disjoint from the
    # AZ-band offset applied at placement. This runs BEFORE the vpc is sized so
    # the vpc wraps the (widened) az boxes, never clips them.
    _stack_peer_azs_in_vpc(boxes, spec, secondary)

    # Now size the vpc bands (reading the stacked az boxes) and any other
    # non-account, non-az containers.
    for c in spec.containers:
        if c.kind not in ("account", "az"):
            _size(c.id)

    # Equal-width bands: peer containers (same kind) get the pair's max
    # secondary-axis extent, widened toward the shared centre. Runs after the
    # in-VPC AZ stacking so cross-region AZ peers (az-a* / az-b*) also match.
    _equalize_peer_widths(boxes, spec, secondary)

    # Account envelope wraps every already-sized child band + pad, snug.
    for c in spec.containers:
        if c.kind == "account":
            _size_account(c.id, child_containers, leaf_nodes, placed, boxes, pad)
            if boxes[c.id].w < min_w.get(c.id, 0):
                b = boxes[c.id]
                boxes[c.id] = Box(c.id, b.x, b.y, min_w[c.id], b.h)

    return boxes


#: Bound on the caption-fit passes (each pass widens at least one container).
_CAPTION_FIT_PASSES = 8


def fit_container_captions(
    placed: Dict[str, Box], spec: DiagramSpec, pad: int = CONTAINER_PAD
) -> Tuple[Dict[str, Box], Dict[str, Box]]:
    """Size the containers so every caption fits its box (1.10.12 WS6, C4).

    A container is sized from its children, so a one-node VPC with a long
    caption (``se vpc-05cd5663a70d3a65c (192.168.128.0/20)`` on SEP 03 / 09) is
    138px wide under a 335px caption, and the text runs across the next
    column's icons and names. Each pass finds the narrowest container whose
    caption (:func:`rule_engine.geometry.container_caption_need`, from
    ``spec.container_captions`` / ``container_styles``) does not fit, inserts
    the missing width as a column to the right of it (every node whose left
    edge is at or past the box's right edge moves right by that amount, a
    whole grid multiple, so the columns stay aligned) and widens the box to
    the right; the parents then wrap it. Containers with no declared caption
    are never touched, so a spec without captions is byte-identical.

    Returns ``(placed, containers)``."""
    captions = dict(getattr(spec, "container_captions", ()) or ())
    styles = dict(getattr(spec, "container_styles", ()) or ())
    min_w: Dict[str, int] = {}
    containers = size_containers(placed, spec, pad, min_w)
    if not captions:
        return placed, containers
    for _ in range(_CAPTION_FIT_PASSES):
        short = []
        for c in spec.containers:
            box = containers.get(c.id)
            label = captions.get(c.id, "")
            if box is None or not label:
                continue
            style = styles.get(c.id)
            if style is None:
                # The skin's style is unknown: budget the group badge +
                # spacingLeft every provider caption carries (geometry's
                # conservative caption inset) instead of a bare text width.
                style = f"spacingLeft={int(_CONTAINER_LABEL_INSET)}"
            need = _grid_ceil(container_caption_need(label, style))
            if need > box.w:
                short.append((box.w * box.h, c.id, need))
        if not short:
            break
        _, cid, need = min(short)
        box = containers[cid]
        delta = _grid_ceil(need - box.w)
        edge = box.x + box.w
        placed = {
            nid: (replace(b, x=_snap(b.x + delta)) if b.x >= edge else b)
            for nid, b in placed.items()
        }
        min_w[cid] = need
        containers = size_containers(placed, spec, pad, min_w)
    return placed, containers


def _translate(box: Box, dx: float, dy: float) -> Box:
    return replace(box, x=_snap(box.x + dx), y=_snap(box.y + dy))


def compact_external_bands(
    placed: Dict[str, Box], containers: Dict[str, Box], spec: DiagramSpec,
    pad: int = CONTAINER_PAD,
) -> Tuple[Dict[str, Box], Dict[str, Box]]:
    """Pull the external bands to one pad from the account (1.10.12 WS6, C9).

    Two cases, both pure translations of whole bands (box + member nodes), so
    no band's inner layout changes:

    * **Bands above the account** (members in the ``actors`` lane, and no
      plain node in that lane). The Theme 21/37/41 wrap packed them by a
      subject-width budget with a column-step gap and spilled the overflow
      into far-right columns, which on SEP 09 left a 1710x1250 void. Now: the
      first band in edge-affinity order, plus any that still fit the account
      width, form ONE row one pad above the account, left-aligned with it,
      one pad apart; the rest stack in ONE column one pad right of the account,
      top-aligned with it, one pad apart, ordered by the mean y of the account
      nodes they link to (bands with no account edge last, declared order).
    * **Bands below the account** (members in the ``on-premises`` lane, and
      no plain node in that lane): rows one pad below the account,
      left-aligned with it, one pad apart, wrapped at the account width (or
      the widest band), in edge-affinity order.

    A plain external row (actors / on-premises nodes in no band) is not moved:
    an orphan node closer than one row step to a container it lines up with is
    a ``container-padding`` spill, so its clearance stays the Theme 44 one.
    Inert for every spec without an external band."""
    from .base import EXTERNAL_LANES
    band_ids = [c.id for c in spec.containers
                if c.kind in _EXTERNAL_BAND_KINDS and c.id in containers]
    acct_id = next((c.id for c in spec.containers
                    if c.kind == "account" and c.id in containers), None)
    if not band_ids or acct_id is None:
        return placed, containers
    acct = containers[acct_id]
    members: Dict[str, list] = {b: [] for b in band_ids}
    for n in spec.nodes:
        if n.container in members:
            members[n.container].append(n.id)
    ext_free = [n.id for n in spec.nodes
                if n.lane in EXTERNAL_LANES and n.container not in members]
    out_n, out_c = dict(placed), dict(containers)

    def _move(bid: str, dx: float, dy: float) -> None:
        out_c[bid] = _translate(out_c[bid], dx, dy)
        for nid in members[bid]:
            out_n[nid] = _translate(out_n[nid], dx, dy)

    lane_of = {n.id: n.lane for n in spec.nodes}

    def _side(bid: str) -> str:
        lanes = {lane_of[i] for i in members[bid]}
        if lanes == {"actors"}:
            return "above"
        if lanes == {"on-premises"}:
            return "below"
        return ""

    above = [b for b in band_ids if _side(b) == "above"]
    below = [b for b in band_ids if _side(b) == "below"]
    free_lanes = {lane_of[i] for i in ext_free}
    inner = {n.id for n in spec.nodes if n.container not in members}
    declared = {b: k for k, b in enumerate(band_ids)}

    def _targets(bid: str) -> list:
        mine = set(members[bid])
        out = []
        for e in spec.edges:
            if e.source in mine and e.target in inner:
                out.append(placed[e.target])
            elif e.target in mine and e.source in inner:
                out.append(placed[e.source])
        return out

    def _key(bid: str, axis: str):
        t = _targets(bid)
        if t:
            return (0, sum(getattr(b, axis) for b in t) / len(t), declared[bid])
        return (1, 0.0, declared[bid])

    def _rows(order: list, budget: float) -> list:
        rows, cur, used = [], [], 0.0
        for bid in order:
            w = containers[bid].w
            if cur and used + pad + w > budget:
                rows.append(cur)
                cur, used = [], 0.0
            used += (pad if cur else 0) + w
            cur.append(bid)
        if cur:
            rows.append(cur)
        return rows

    # --- bands below the account: rows one pad below it, left-aligned ------ #
    if below and "on-premises" not in free_lanes:
        order = sorted(below, key=lambda b: _key(b, "x"))
        budget = max([acct.w] + [containers[b].w for b in below])
        y = acct.y + acct.h + pad
        for row in _rows(order, budget):
            x = acct.x
            for bid in row:
                c = containers[bid]
                _move(bid, x - c.x, y - c.y)
                x += c.w + pad
            y += max(containers[b].h for b in row) + pad

    # --- bands above the account: one row + one side column ---------------- #
    if above and "actors" not in free_lanes:
        order = sorted(above, key=lambda b: _key(b, "x"))
        row = _rows(order, max(acct.w, containers[order[0]].w))[0]
        column = sorted((b for b in above if b not in row), key=lambda b: _key(b, "y"))
        row_h = max(containers[b].h for b in row)
        x = acct.x
        for bid in row:
            c = containers[bid]
            _move(bid, x - c.x, (acct.y - pad - row_h) - c.y)
            x += c.w + pad
        y = acct.y
        col_x = acct.x + acct.w + pad
        for bid in column:
            c = containers[bid]
            _move(bid, col_x - c.x, y - c.y)
            y += c.h + pad
    return out_n, out_c


def place_and_size(spec: DiagramSpec) -> Tuple[Dict[str, Box], Dict[str, Box]]:
    """``place → size (+ caption fit) → Theme 44 lift → external-band
    compaction → in-VPC centring``: the placement stage every layout path shares
    (the scored and legacy pipelines and the ordering proxy)."""
    placed = place_nodes(spec)
    placed, containers = fit_container_captions(placed, spec)
    placed, containers = lift_subject_over_external_lane(placed, containers, spec)
    placed, containers = compact_external_bands(placed, containers, spec)
    placed = centre_block_in_vpc(placed, containers, spec)
    return placed, containers


def centre_block_in_vpc(
    placed: Dict[str, Box], containers: Dict[str, Box], spec: DiagramSpec
) -> Dict[str, Box]:
    """Centre each region's node block inside its VPC box (Req 3.4).

    For each ``vpc`` container, compute its member nodes' block centre along the
    secondary axis and the VPC-box centre, then shift the whole block by the
    grid-rounded delta so the block sits with equal left/right padding, snapped
    to the grid. Whole-block shift keeps the block's internal geometry intact.

    Returns a new ``id -> Box`` node map (the input is not mutated).
    """
    _, secondary = _container_axes(spec)
    leaf_nodes = _assign_nodes_to_leaves(spec, placed)
    child_containers = _children_of(spec)
    kind_of = {c.id: c.kind for c in spec.containers}

    # Members of a vpc = every node the vpc wraps: nodes in its az children,
    # PLUS any node assigned to the vpc directly (a service-row node that sits in
    # the VPC above the AZ boxes). When the vpc has no az children, its own
    # directly-assigned nodes are the members.
    def _vpc_members(vpc_id: str) -> list:
        az_children = [c.id for c in child_containers.get(vpc_id, [])
                       if kind_of.get(c.id) == "az"]
        members: list = list(leaf_nodes.get(vpc_id, []))
        for az in az_children:
            members.extend(leaf_nodes.get(az, []))
        return members

    shifted = dict(placed)
    for c in spec.containers:
        if c.kind != "vpc" or c.id not in containers:
            continue
        members = _vpc_members(c.id)
        if not members:
            continue
        vpc = containers[c.id]
        lows = [_extent(shifted[nid].footprint(LABEL_BAND), secondary)[0] for nid in members]
        highs = [
            _extent(shifted[nid].footprint(LABEL_BAND), secondary)[0]
            + _extent(shifted[nid].footprint(LABEL_BAND), secondary)[1]
            for nid in members
        ]
        block_centre = (min(lows) + max(highs)) / 2.0
        v_low, v_size = _extent(vpc, secondary)
        vpc_centre = v_low + v_size / 2.0
        delta = _snap(vpc_centre - block_centre)
        if delta == 0:
            continue
        for nid in members:
            low, size = _extent(shifted[nid], secondary)
            shifted[nid] = _with_extent(shifted[nid], secondary, low + delta, size)
    return shifted
