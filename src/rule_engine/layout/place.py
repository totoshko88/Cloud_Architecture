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

from typing import Dict

try:  # package-relative import when used as ``rule_engine.layout.place``
    from ..diagram_layout import CONTAINER_PAD
    from ..geometry import Box, LABEL_BAND, CONTAINER_LABEL_BAND
    from .model import DiagramSpec
    from .base import (
        SpecError,
        TOP_LANE,
        _top_lane_containers,
        _ORIGIN,
        _snap,
        _validate_spec,
        _secondary_axis,
        _place_base,
        _region_secondary_offset,
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
    from diagram_layout import CONTAINER_PAD  # type: ignore[no-redef]
    from geometry import Box, LABEL_BAND, CONTAINER_LABEL_BAND  # type: ignore[no-redef]
    from layout.model import DiagramSpec  # type: ignore[no-redef]
    from layout.base import (  # type: ignore[no-redef]
        SpecError,
        TOP_LANE,
        _top_lane_containers,
        _ORIGIN,
        _snap,
        _validate_spec,
        _secondary_axis,
        _place_base,
        _region_secondary_offset,
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
    # content-derived step, so peers sit side-by-side and never overlap.
    secondary = _secondary_axis(spec.axis)
    offset = _region_secondary_offset(spec, base)

    placed: Dict[str, Box] = {}
    for node in spec.nodes:
        box = base[node.id]
        if node.region == "b":
            low, size = _extent(box, secondary)
            box = _with_extent(box, secondary, _snap(low + offset), size)
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
    return placed


def size_containers(
    placed: Dict[str, Box], spec: DiagramSpec, pad: int = CONTAINER_PAD
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

    The result passes ``check_container_padding`` and ``check_container_overlap``.
    """
    primary, secondary = _container_axes(spec)
    leaf_nodes = _assign_nodes_to_leaves(spec, placed)
    child_containers = _children_of(spec)
    kind_of = {c.id: c.kind for c in spec.containers}
    # 1.10.6: containers whose first row is entered from the side reserve one
    # corridor lane below their caption strip (``_top_lane_containers``).
    lane_containers = _top_lane_containers(spec)

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

    return boxes


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
