"""Placement base kernel — lane model, spec validation, and the pure geometry
helpers the placement / router stages build on (scored-router 1.8.0, Phase A,
task 1.4).

This module holds the ``layout_engine`` base helpers that the ``layout/``
submodules (``place``, ``routers``) previously imported *back* from
``layout_engine`` — the lane table, :class:`SpecError`, :func:`_validate_spec`,
the canonical region/title constants, :func:`_snap`, and the placement kernel
(``_place_base`` … ``_size_account``). Relocating them here turns the old
bidirectional dependency (``layout_engine`` ⇄ ``layout/*``) into a clean
one-directional graph:

    diagram_layout / geometry / layout.model  →  layout.base  →  place / routers

so ``layout_engine`` can become a pure re-export shim over the package
(design.md §``layout/`` package seam, Component 5).

**Behavior-preserving.** Every definition here is relocated *verbatim* from
``layout_engine.py``; no field, default, name, or line of logic changed. The
module depends only on :mod:`rule_engine.diagram_layout`,
:mod:`rule_engine.geometry` and :mod:`rule_engine.layout.model` — none of which
import back — so there is no import cycle and the placement geometry is
byte-identical to the pre-split output (R1.1, R1.2).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout.base``
    from ..diagram_layout import (
        ICON_SIZE,
        GRID,
        COL_STEP,
        ROW_STEP,
        CONTAINER_PAD,
    )
    from ..geometry import (
        Box,
        LABEL_BAND,
        CONTAINER_LABEL_BAND,
    )
    from .model import DiagramSpec
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import (  # type: ignore[no-redef]
        ICON_SIZE,
        GRID,
        COL_STEP,
        ROW_STEP,
        CONTAINER_PAD,
    )
    from geometry import (  # type: ignore[no-redef]
        Box,
        LABEL_BAND,
        CONTAINER_LABEL_BAND,
    )
    from layout.model import DiagramSpec  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Lane model (Req 2)
# ---------------------------------------------------------------------------

#: The eight canonical lanes, in the fixed convention order (diagram-standards
#: → Lane Order). The lane's position in this tuple is its stable index; that
#: index maps to the primary layout axis (row for North–South, column for
#: left→right), while a node's ``slot`` maps to the secondary axis.
LANES: Tuple[str, ...] = (
    "actors",
    "edge",
    "router",
    "async",
    "workers",
    "platform",
    "data",
    "on-premises",
)

#: Lane name → stable ordinal index (Req 2.1).
LANE_INDEX = {name: i for i, name in enumerate(LANES)}


# On-entry validation (Req 1.4, Req 2.4)
# ---------------------------------------------------------------------------


class SpecError(ValueError):
    """Raised when a :class:`DiagramSpec` is invalid.

    The message always names the offending field (the unknown lane, the
    duplicated ``(lane, region, slot)`` key, or the dangling edge endpoint), so
    the failure is actionable without inspecting geometry.
    """


def _validate_spec(spec: DiagramSpec) -> None:
    """Validate a declaration on entry; raise :class:`SpecError` naming the fault.

    Checks, in order:

    1. **Unknown lane** — a node whose ``lane`` is not in :data:`LANES`
       (Req 2.4).
    2. **Duplicate slot** — two nodes sharing the same ``(lane, region, slot)``
       placement key (Req 2.5 relies on unique slots).
    3. **Dangling edge endpoint** — an edge whose ``source`` or ``target`` is
       not a declared node id (Req 1.2 integrity).
    """
    # A node may declare membership of any **non-account** container: an ``az``
    # box (a node inside an availability zone), or a region ``vpc`` (a
    # service-row node that sits in the VPC directly, above the AZ boxes, and so
    # must NOT be wrapped by any AZ box). The account envelope is never a valid
    # membership — nodes live in a region band, never loose in the account.
    container_by_id = {c.id: c for c in spec.containers}
    membership_ids = {c.id for c in spec.containers if c.kind != "account"}
    # A node's AZ tier band (its declared AZ's ordinal within its VPC) is part of
    # its placement key: peer AZs stack along the primary axis (Req 12.1), so two
    # AZ nodes at the same (lane, region, slot) but in *different* AZ bands do not
    # collide — they land in successive tier bands. A node in no AZ is band 0, so
    # for container-free synthetic specs the key is exactly (lane, region, slot)
    # as before.
    az_band = _node_az_band(spec)

    node_ids = set()
    seen_slots: dict[Tuple[str, str, int, int], str] = {}
    for node in spec.nodes:
        if node.lane not in LANE_INDEX:
            raise SpecError(
                f"node {node.id!r} declares unknown lane {node.lane!r}; "
                f"lane must be one of {LANES}"
            )
        key = (node.lane, node.region, node.slot, az_band[node.id])
        if key in seen_slots:
            raise SpecError(
                f"duplicate slot (lane={node.lane!r}, region={node.region!r}, "
                f"slot={node.slot}) for nodes {seen_slots[key]!r} and {node.id!r}"
            )
        seen_slots[key] = node.id
        node_ids.add(node.id)

        # Declared container membership must name a real, leaf, region-matching
        # container (fail-honest — coordinate-free membership, Req 1.3).
        if node.container is not None:
            target = container_by_id.get(node.container)
            if target is None:
                raise SpecError(
                    f"node {node.id!r} declares unknown container "
                    f"{node.container!r} (not a declared container id)"
                )
            if node.container not in membership_ids:
                raise SpecError(
                    f"node {node.id!r} declares non-membership container "
                    f"{node.container!r} (kind={target.kind!r}); a node may only "
                    "belong to a region container (an az or a vpc), never the "
                    "account envelope"
                )
            if target.region != node.region:
                raise SpecError(
                    f"node {node.id!r} (region {node.region!r}) declares container "
                    f"{node.container!r} of region {target.region!r}; a node's "
                    "declared container must be in the node's own region"
                )

    for edge in spec.edges:
        if edge.source not in node_ids:
            raise SpecError(
                f"edge {edge.id!r} has dangling source {edge.source!r} "
                "(not a declared node id)"
            )
        if edge.target not in node_ids:
            raise SpecError(
                f"edge {edge.id!r} has dangling target {edge.target!r} "
                "(not a declared node id)"
            )


# ---------------------------------------------------------------------------
# Node placement (Req 3)
# ---------------------------------------------------------------------------

#: Minimum grid-aligned clear gap between region A's node block and region B's,
#: along the **secondary** axis (peer regions sit side-by-side, not stacked
#: along the tier/lane axis). The actual region step is *content-derived* — it
#: is region A's secondary extent plus this gap — so region B always clears
#: region A's real footprint no matter how many slots/AZs region A spans. This
#: gap is a whole GRID multiple and large enough to seat ``CONTAINER_PAD`` on
#: both peer VPC borders plus a lane of clear space between them.
REGION_GAP = 2 * COL_STEP  # 440, a whole GRID multiple

#: Retained for API/back-compat and for tests/callers that reference a nominal
#: region step. The *effective* offset used at placement is content-derived
#: (see :func:`_region_secondary_offset`); this constant is the floor a region
#: step can never fall below (region B is always at least this far from A).
REGION_STEP = 3 * COL_STEP  # 660, a whole GRID multiple

#: Secondary-axis offset for a node's ``sub`` (a sub-row: api / monitoring band).
#: A whole GRID multiple so ``sub`` never knocks a node off the grid.
SUB_STEP = ROW_STEP // 2  # 80, a whole GRID multiple

#: The account-level origin (region ""), on the grid. Region A starts here; a
#: node's slot / lane index step out from it. Region B = this + REGION_STEP.
_ORIGIN = (CONTAINER_PAD, CONTAINER_PAD)  # (30, 30), both GRID multiples

#: Vertical band reserved ABOVE the top container for the diagram title cell.
#: ``diagram_layout.build_diagram`` draws the title at y=20 height=30 (bottom at
#: 50); the outermost container top is lifted to ``CONTAINER_PAD + TITLE_BAND``
#: (60) so the title never overlaps the container border or its top-left badge
#: (the AWS ``group_account`` glyph) — matching the reference, whose account box
#: starts at y=60. A whole GRID multiple.
TITLE_BAND = 30


def _snap(value: float, grid: int = GRID) -> int:
    """Round ``value`` to the nearest whole ``grid`` multiple (Req 3.2)."""
    return int(round(value / grid) * grid)


def _secondary_axis(axis: str) -> str:
    """Return the secondary axis letter ('x'|'y') peer regions spread along.

    Peer regions sit **side-by-side** along the secondary axis (never stacked
    along the tier/lane primary axis): for ``north-south`` the secondary axis is
    ``x`` (region B to the right of A), for ``left-right`` it is ``y`` (region B
    below A). Mirrors :func:`_container_axes` — kept as a small standalone helper
    so :func:`place_nodes` can compute the offset before any container exists."""
    if axis == "north-south":
        return "x"
    if axis == "left-right":
        return "y"
    raise SpecError(
        f"diagram declares unknown axis {axis!r}; "
        "axis must be 'north-south' or 'left-right'"
    )


def _az_ordinals(spec: DiagramSpec) -> Dict[str, int]:
    """Map each ``az`` container id → its 0-indexed ordinal within its parent VPC.

    The AZ boxes of one VPC are ordered by their declaration order (the same
    order :func:`_leaf_region_containers` preserves), so ``az-1`` → band 0,
    ``az-2`` → band 1, … . This is a pure, deterministic function of the spec:
    the ordinal is what maps a declared AZ membership to a distinct primary-axis
    **tier band** so peer AZs of one VPC stack (one below the other for a
    North–South diagram) rather than spreading side-by-side (Req 12.1, 12.5)."""
    ordinal: Dict[str, int] = {}
    seen: Dict[Optional[str], int] = {}
    for c in spec.containers:
        if c.kind != "az":
            continue
        ordinal[c.id] = seen.get(c.parent, 0)
        seen[c.parent] = ordinal[c.id] + 1
    return ordinal


def _vpcs_with_service_row(spec: DiagramSpec) -> set:
    """Return the set of ``vpc`` container ids that carry VPC-direct service-row
    nodes (a node whose declared ``container`` is the VPC itself, not an AZ).

    A VPC-direct node sits in the VPC **above** its AZ boxes and forms a distinct
    service-row tier (Req 12.3). When a VPC has such nodes, its AZ bands are
    pushed down by one band so the service row occupies the top (band 0) tier and
    the AZs descend below it. A VPC with no service-row node keeps its AZ bands
    at ``0, 1, …`` unchanged, so any container-free (synthetic) spec is
    untouched."""
    kind_of = {c.id: c.kind for c in spec.containers}
    return {
        n.container
        for n in spec.nodes
        if n.container is not None and kind_of.get(n.container) == "vpc"
    }


def _node_az_band(spec: DiagramSpec) -> Dict[str, int]:
    """Map each node id → its primary-axis tier band (0 when it has none).

    Bands stack a region's content down the primary axis (North–South: top→bottom)
    so distinct tiers never intermix on the same rows:

    * A **VPC-direct service-row node** (declared ``container`` is the region VPC)
      takes band ``0`` — the top region tier, between the VPC border and the AZs
      (Req 12.3).
    * An **AZ node** (declared ``container`` is an ``az`` box) takes that AZ's
      ordinal within its parent VPC (:func:`_az_ordinals`), **offset by one band
      when its VPC has a service row** so the AZs descend *below* the service-row
      tier (band ``0`` reserved for the service row): ``az-1`` → band 1, ``az-2``
      → band 2, and so on. A VPC with no service row keeps ``az-1`` → band 0,
      ``az-2`` → band 1 (Req 12.1, unchanged).
    * Every other node — an account-level edge node, or any node in a spec that
      declares no containers (the synthetic-spec geometric-fallback case) — is
      band 0 and gets no primary-axis offset, so its placement is unchanged.
    """
    az_ord = _az_ordinals(spec)
    kind_of = {c.id: c.kind for c in spec.containers}
    parent_of = {c.id: c.parent for c in spec.containers}
    svc_vpcs = _vpcs_with_service_row(spec)
    band: Dict[str, int] = {}
    for node in spec.nodes:
        cid = node.container
        if cid is not None and kind_of.get(cid) == "az":
            offset = 1 if parent_of.get(cid) in svc_vpcs else 0
            band[node.id] = az_ord.get(cid, 0) + offset
        else:
            band[node.id] = 0
    return band


def _band_within(spec: DiagramSpec) -> Dict[str, Tuple[int, int]]:
    """Map each **banded** node id → its ``(column, sub_row)`` within its band.

    A north-south landscape reads each tier band **horizontally**: one column per
    node, ordered left→right by ``(lane, slot)``, so the VPC service row is
    ``lb → queue → worker → secrets`` across and each AZ is
    ``app → cache → db → obj`` across — not a vertical stack of same-slot nodes
    (the regression this fixes). A node's ``sub`` selects the row *within* the
    band (main row ``sub=0``; api/observability drop to ``sub=1``). Columns are
    ranked **per sub-row** so both the main row and the sub-row pack from column
    0. Regions ``a``/``b`` share the same band structure, so the ranking is done
    per ``(band, region, sub)`` group and is mirror-symmetric by construction.

    Only banded nodes (declared members of an ``az`` or region ``vpc``) get an
    entry; non-banded nodes (the account-level edge row, synthetic-spec nodes)
    keep the absolute-lane placement in :func:`_place_base` unchanged.
    """
    band_of = _node_az_band(spec)
    kind_of = {c.id: c.kind for c in spec.containers}
    banded_kinds = {"az", "vpc"}
    # Group banded nodes by (band, region, sub); within each group, rank by
    # (lane, slot) to assign the column. Region is part of the key so A and B
    # rank independently (identical structure → identical ranks → symmetric).
    groups: Dict[Tuple[int, str, int], list] = {}
    for n in spec.nodes:
        if n.container is not None and kind_of.get(n.container) in banded_kinds:
            key = (band_of[n.id], n.region, n.sub)
            groups.setdefault(key, []).append(n)
    within: Dict[str, Tuple[int, int]] = {}
    for (_band, _region, sub), members in groups.items():
        for col, n in enumerate(sorted(members, key=lambda m: (LANE_INDEX[m.lane], m.slot))):
            within[n.id] = (col, sub)
    return within


def _band_packing(spec: DiagramSpec) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Return ``(band_start, band_min_lane)`` for per-band primary-axis packing.

    **Per-band packing (Req 12.5 quality refinement, Task 20).** The Task-19
    model shifted every band by ``band * uniform_step`` and placed a node at its
    *absolute* lane index within the band. Both compound to waste vertical space:
    the uniform step is dictated by the *tallest* band (the 4-lane service row),
    so shorter AZ bands inherit an oversized interval; and the absolute lane
    index reserves the empty lanes *above* a band's own minimum lane (the service
    row occupies lanes 2..5, so az-1 — lanes 4..6 — started at ``4·ROW_STEP`` past
    its band base, not flush to it). Together they left a ~500px empty gap between
    the VPC service row and az-1.

    This function packs each band tight instead. For every tier band (band index
    from :func:`_node_az_band`) it computes, over the band's **banded** nodes
    (AZ nodes and VPC-direct service-row nodes — mirror-symmetric across regions,
    so metrics are identical per band index):

    * ``band_min_lane[band]`` — the band's minimum lane index; a node's
      within-band primary offset is ``(lane_i - band_min_lane) * ROW_STEP`` so the
      band is **flush to its own top** (no empty lanes reserved above it);
    * ``content_height`` — ``(max_lane - min_lane) * ROW_STEP + ICON_SIZE +
      LABEL_BAND``, the band's real primary-axis footprint extent;
    * ``band_start[band]`` — the band's start offset relative to the base origin,
      accumulated as ``prev_start + prev_content_height + 3·CONTAINER_PAD``. The
      ``3·CONTAINER_PAD`` clears the previous band's own box padding (top+bottom)
      plus one inter-tier gap, so each AZ's own ``az`` box (content + pad) stays
      disjoint from its neighbour with one grid-padded gap between the boxes —
      exactly the geometry the old ``3·CONTAINER_PAD`` term guaranteed, but now
      against the *previous* band's own (variable) height rather than a global
      max.

    Bands are ordered by band index (0, 1, 2, …). The **first** band is anchored
    at ``band_min_lane[first] * ROW_STEP`` — the absolute primary position its top
    lane occupied before packing — so the banded region content still sits *below*
    the account-level edge row (which is placed at its own absolute lane index,
    the North–South convention: external/edge tier at the top, service row and
    zones descending below it). Subsequent bands then pack tight relative to that
    anchor. The result is a pure, deterministic function of the spec (Req 11.1)
    and every value is grid-aligned. A spec that declares no banded region nodes
    (a container-free synthetic spec) yields ``{0: 0}`` / ``{0: 0}`` — band 0 with
    a zero start and a zero min-lane — so its placement is byte-unchanged (a
    relative lane index against ``band_min_lane == 0`` equals the absolute index,
    and the zero start adds no offset)."""
    band_of = _node_az_band(spec)
    kind_of = {c.id: c.kind for c in spec.containers}
    banded_kinds = {"az", "vpc"}
    lanes_by_band: Dict[int, list] = {}
    # Whether a band's content is wrapped by its own container box. AZ nodes sit
    # inside an ``az`` box (top+bottom padding of their own); a VPC-direct
    # service-row band has NO box of its own (it lives loose in the VPC above the
    # AZ boxes), so it contributes no box padding to an inter-band gap.
    band_has_box: Dict[int, bool] = {}
    #: max sub-row index per band — a horizontal band is one row per ``sub``
    #: (main row sub=0, api/observability sub=1), so a band's vertical extent is
    #: driven by its sub-row count, NOT by how many lanes it spans (lanes now read
    #: horizontally across the band; see :func:`_band_within`).
    sub_rows_by_band: Dict[int, int] = {}
    for n in spec.nodes:
        if n.container is not None and kind_of.get(n.container) in banded_kinds:
            b = band_of[n.id]
            lanes_by_band.setdefault(b, []).append(LANE_INDEX[n.lane])
            band_has_box[b] = band_has_box.get(b, False) or kind_of.get(n.container) == "az"
            sub_rows_by_band[b] = max(sub_rows_by_band.get(b, 0), n.sub)

    band_min_lane: Dict[int, int] = {}
    band_start: Dict[int, int] = {}
    if not lanes_by_band:
        # Container-free synthetic spec: a single band 0, no packing offset, and
        # a zero min-lane so relative == absolute lane index (byte-unchanged).
        return {0: 0}, {0: 0}

    prev_end = 0
    prev_has_box = False
    for band in sorted(lanes_by_band):
        lanes = lanes_by_band[band]
        lo, hi = min(lanes), max(lanes)
        band_min_lane[band] = lo
        has_box = band_has_box.get(band, False)
        if not band_start:
            # Anchor the first banded band at its top lane's natural tier row so
            # the banded region content sits BELOW the account-level edge row
            # (which is placed at its own absolute lane index, edge lane = row 1).
            #
            # v1.6.0: plus ``CONTAINER_LABEL_BAND``, because the enclosing region
            # container now reserves a caption strip on its top edge
            # (``size_containers``). Without this the container would grow UPWARD
            # into the account-level edge row's label band, and the first thing
            # the oracle saw was a container-padding spill on every edge-row node.
            # Pushing the banded region down by exactly the strip keeps the gap
            # between the edge row and the region band the same as before, while
            # the strip itself becomes a usable entry corridor below the caption.
            #
            # The extra ``CONTAINER_PAD`` on top of the strip is the standard's own
            # tie-breaker — "when space is tight, widen, never narrow, the
            # corridor". Without it the lane between the account edge row's label
            # band and the region container's top edge is ~12px: too narrow to hold
            # a single grid line, so the allocator fell back into the caption band
            # and the account-row runs (WAF→CDN, DNS→passive-LB) sliced the
            # ``vpc-…`` captions no matter how the band was narrowed.
            start = _snap(lo * ROW_STEP + CONTAINER_LABEL_BAND + CONTAINER_PAD)
            if any(c.kind == "region" for c in spec.containers):
                start += CONTAINER_LABEL_BAND + CONTAINER_PAD
        else:
            # The gap between the previous band's content bottom and this band's
            # content top clears the previous band's own bottom box-padding (only
            # if it HAS a box), this band's own top box-padding (only if it HAS a
            # box), plus one inter-tier gap — so two boxed AZ bands sit
            # ``3·CONTAINER_PAD`` apart (2 box pads + 1 gap), while an unboxed
            # service-row band → boxed AZ band sits ``2·CONTAINER_PAD`` apart
            # (1 box pad + 1 gap), leaving each real box exactly one grid-padded
            # gap from its neighbour rather than an extra phantom box-pad.
            gap = CONTAINER_PAD  # one inter-tier gap, always
            if prev_has_box:
                gap += CONTAINER_PAD
            if has_box:
                # This band's own box contributes its TOP padding, which since
                # v1.6.0 is ``CONTAINER_PAD + CONTAINER_LABEL_BAND`` (the caption
                # strip) rather than a bare pad — so the next box's caption cannot
                # eat into the previous band's footprint.
                gap += CONTAINER_PAD + CONTAINER_LABEL_BAND
            start = _snap(prev_end + gap)
        band_start[band] = start
        # A horizontal band is (max_sub_row + 1) rows tall (main row + any
        # sub-rows), each ROW_STEP apart, plus the icon + label footprint.
        rows = sub_rows_by_band.get(band, 0)
        content_height = rows * ROW_STEP + ICON_SIZE + LABEL_BAND
        prev_end = start + content_height
        prev_has_box = has_box
    return band_start, band_min_lane


def _place_base(spec: DiagramSpec, base_x: int, base_y: int) -> Dict[str, Box]:
    """Place every node with **no** region offset, at the base origin.

    Pure index→coordinate mapping from ``(lane, region, slot, sub)`` and the
    canonical constants — the shared kernel of :func:`place_nodes`. Region A,
    region B, and the account-level ("") nodes all land in one overlapping block
    here; :func:`place_nodes` then translates region B off along the secondary
    axis by the content-derived step.

    **Horizontal bands (North–South landscape).** A banded node (an AZ node, or
    a VPC-direct service-row node) reads **across** its tier band, not down it:
    :func:`_band_within` gives its ``(column, sub_row)`` within the band, so its
    ``x = base_x + column·COL_STEP`` and its ``y = base_y + band_start[band] +
    sub_row·ROW_STEP``. ``band_start`` (:func:`_band_packing`) stacks the tier
    bands down the primary (y) axis, packed flush to the previous band's real
    content bottom + one grid-padded gap. This is the fix for the vertical-stack
    regression: same-slot service-row nodes (lb/queue/worker/secrets) used to
    collapse into one column because lane drove the row; they now spread across
    columns by ``(lane, slot)`` order and the band is one horizontal row.

    A **non-banded** node — an account-level ("") edge node, or any node in a
    container-free synthetic spec — keeps the original absolute-lane placement
    (lane → primary axis, slot → secondary axis, ``sub`` nudges the secondary),
    byte-unchanged. The account edge row is a single lane at distinct slots, so
    absolute-lane placement already lays it out horizontally.
    """
    az_band = _node_az_band(spec)
    band_start, _band_min_lane = _band_packing(spec)
    band_within = _band_within(spec)
    kind_of = {c.id: c.kind for c in spec.containers}
    banded_kinds = {"az", "vpc"}
    # The primary axis (the one lanes/tiers step along) is y (ROW_STEP) for a
    # North–South diagram and x (COL_STEP) for a left→right diagram.
    primary_step = ROW_STEP if spec.axis == "north-south" else COL_STEP
    # Compact mode (small flow): map each OCCUPIED lane to a consecutive rank so
    # the flow's tiers sit on adjacent rows with no empty lane bands between them
    # (e.g. router/workers/data → ranks 0/1/2). Shared across regions so peers
    # stay mirror-symmetric. Absolute lane index otherwise (byte-unchanged).
    compact_rank: Dict[int, int] = {}
    if spec.compact:
        occupied = sorted({LANE_INDEX[n.lane] for n in spec.nodes})
        compact_rank = {li: r for r, li in enumerate(occupied)}
    placed: Dict[str, Box] = {}
    for node in spec.nodes:
        lane_i = LANE_INDEX[node.lane]
        banded = node.container is not None and kind_of.get(node.container) in banded_kinds
        if banded and spec.axis == "north-south":
            # Horizontal band: column across (x), tier band + sub-row down (y).
            band = az_band[node.id]
            col, sub_row = band_within[node.id]
            x = base_x + col * COL_STEP
            y = base_y + band_start[band] + sub_row * ROW_STEP
        else:
            # Non-banded, or the left→right axis: lane → primary, slot →
            # secondary, sub nudges secondary. In compact mode the lane's
            # consecutive rank replaces its absolute index on the primary axis.
            eff_lane = compact_rank.get(lane_i, lane_i) if spec.compact else lane_i
            primary_offset = eff_lane * primary_step
            if spec.axis == "north-south":
                x = base_x + node.slot * COL_STEP + node.sub * SUB_STEP
                y = base_y + primary_offset
            elif spec.axis == "left-right":
                x = base_x + primary_offset
                y = base_y + node.slot * ROW_STEP + node.sub * SUB_STEP
            else:
                raise SpecError(
                    f"diagram {spec.diagram_id!r} declares unknown axis "
                    f"{spec.axis!r}; axis must be 'north-south' or 'left-right'"
                )
        placed[node.id] = Box(node.id, _snap(x), _snap(y), ICON_SIZE, ICON_SIZE)
    return placed


def _region_secondary_offset(spec: DiagramSpec, base: Dict[str, Box]) -> int:
    """Return the content-derived, grid-aligned secondary-axis step for region B.

    Region B is region A **translated along the secondary axis** so the two
    peer regions sit side-by-side and never overlap (Req 3.3, mirror-symmetric).
    The step is a *pure function of the spec* (determinism, Req 11.1): it is
    region A's own secondary-axis **footprint extent** (icon + label band, so
    labels are cleared too) plus :data:`REGION_GAP`, snapped to the grid. A
    fixed nominal step (the old ``3·COL_STEP``) cannot clear a region that spans
    several slots/AZs — this derives the clearance from region A's real extent,
    and is never smaller than :data:`REGION_GAP`.
    """
    secondary = _secondary_axis(spec.axis)
    a_boxes = [
        base[n.id].footprint(LABEL_BAND) for n in spec.nodes if n.region == "a"
    ]
    if not a_boxes:
        return _snap(REGION_GAP)
    lo = min(_extent(b, secondary)[0] for b in a_boxes)
    hi = max(_extent(b, secondary)[0] + _extent(b, secondary)[1] for b in a_boxes)
    extent = hi - lo
    return _snap(extent + REGION_GAP)




# ---------------------------------------------------------------------------
# Container sizing, equal-width bands, and block centring (Req 3.4, Req 4)
# ---------------------------------------------------------------------------


def _container_axes(spec: DiagramSpec) -> Tuple[str, str]:
    """Return ``(primary, secondary)`` axis letters for the diagram.

    The **primary** axis is the one lanes/tiers step along (so az/tier bands
    stack along it); the **secondary** axis is the one a region's node block
    spreads along (so peer regions differ, and centring happens, along it):

    * ``north-south`` — primary ``y`` (tiers top→bottom), secondary ``x``.
    * ``left-right``  — primary ``x`` (tiers left→right), secondary ``y``.
    """
    if spec.axis == "north-south":
        return "y", "x"
    if spec.axis == "left-right":
        return "x", "y"
    raise SpecError(
        f"diagram {spec.diagram_id!r} declares unknown axis {spec.axis!r}; "
        "axis must be 'north-south' or 'left-right'"
    )


def _children_of(spec: DiagramSpec) -> Dict[Optional[str], list]:
    """Map each container id (and ``None`` for the roots) to its child container
    specs, via the declared ``parent`` links."""
    kids: Dict[Optional[str], list] = {}
    for c in spec.containers:
        kids.setdefault(c.parent, []).append(c)
    return kids


def _leaf_region_containers(spec: DiagramSpec) -> Dict[str, list]:
    """Return, per region, the ordered list of its **deepest** containers.

    A node of region *r* is wrapped by the deepest container of region *r*. When
    a region has ``az`` containers, those are the leaves (nodes partition across
    them by tier band); otherwise the region's ``vpc`` is the leaf. Declaration
    order is preserved so az bands map deterministically to tier bands.
    """
    by_region_kind: Dict[Tuple[str, str], list] = {}
    for c in spec.containers:
        by_region_kind.setdefault((c.region, c.kind), []).append(c)
    leaves: Dict[str, list] = {}
    for c in spec.containers:
        if c.kind == "account":
            continue
        azs = by_region_kind.get((c.region, "az"))
        if azs is not None:
            leaves[c.region] = list(azs)
        elif c.kind == "vpc":
            leaves[c.region] = [c]
    return leaves


def _assign_nodes_to_leaves(
    spec: DiagramSpec, placed: Dict[str, Box]
) -> Dict[str, list]:
    """Assign each region-scoped node to its owning container id.

    Membership is **declared-first, geometric-fallback**:

    * A node that declares a ``container`` (an ``az`` box, or a region ``vpc``
      for a service-row node that sits in the VPC directly) is assigned to
      exactly that container — no geometry is inferred. This is what lets the
      real landscape place its service row in the VPC and its AZ nodes in the
      AZ boxes without the AZ boxes overlapping (the old geometric partition
      guessed AZ membership from vertically-overlapping tier bands, which
      produced overlapping AZ boxes).
    * A node that declares **no** ``container`` falls back to the geometric
      tier-band partition across the region's leaf (az) containers: sort the
      region's undeclared-node tiers along the primary axis, then split them
      evenly across the leaves in declaration order (az-1 wraps the upper tiers,
      az-2 the lower). This preserves the behavior every synthetic-spec test
      relies on (those specs declare no containers).

    Region "" (account-level) nodes are **account-scoped cloud services** — the
    top edge row (waf / dns / cdn / audit) — so they are wrapped by the
    **account** container (inside the Account boundary, above the region VPCs),
    matching the reference where the edge row sits at the top of the Account box.
    The exceptions are the ``actors`` and ``on-premises`` lanes: those are
    genuinely external (diagram-standards: external actors / on-premises sit
    OUTSIDE the cloud boundaries), so they are assigned to no container.
    """
    primary, _ = _container_axes(spec)
    leaves = _leaf_region_containers(spec)
    box_of = {n.id: placed[n.id] for n in spec.nodes}
    region_of = {n.id: n.region for n in spec.nodes}
    declared_of = {n.id: n.container for n in spec.nodes}
    account_id = next((c.id for c in spec.containers if c.kind == "account"), None)
    external_lanes = {"actors", "on-premises"}

    assignment: Dict[str, list] = {c.id: [] for c in spec.containers}

    # 1. Declared membership is authoritative — assign those nodes directly.
    for n in spec.nodes:
        if n.container is not None:
            assignment[n.container].append(n.id)

    # 1b. Account-level (region "") cloud services are wrapped by the account
    #     envelope so it contains its own top edge row — except the genuinely
    #     external actors / on-premises lanes, which stay outside every boundary.
    if account_id is not None:
        for n in spec.nodes:
            if (
                n.region == ""
                and n.container is None
                and n.lane not in external_lanes
            ):
                assignment[account_id].append(n.id)

    # 2. Geometric fallback for region-scoped nodes that declare no container.
    for region, leaf_list in leaves.items():
        members = [
            n.id
            for n in spec.nodes
            if region_of[n.id] == region and declared_of[n.id] is None
        ]
        if not members:
            continue
        # Distinct tier coordinates (primary axis), ordered.
        tiers = sorted({getattr(box_of[nid], primary) for nid in members})
        n_leaves = len(leaf_list)
        # Partition the tier coordinates evenly across the leaves (ceil split).
        per = (len(tiers) + n_leaves - 1) // n_leaves
        tier_to_leaf: Dict[float, str] = {}
        for i, tier in enumerate(tiers):
            leaf_i = min(i // per, n_leaves - 1)
            tier_to_leaf[tier] = leaf_list[leaf_i].id
        for nid in members:
            assignment[tier_to_leaf[getattr(box_of[nid], primary)]].append(nid)
    return assignment


def _bbox(boxes: list) -> Tuple[float, float, float, float]:
    """Return ``(x, y, right, bottom)`` bounding box of node **footprints**
    (icon + LABEL_BAND), matching the label-aware geometry validators."""
    fps = [b.footprint(LABEL_BAND) for b in boxes]
    return (
        min(f.x for f in fps),
        min(f.y for f in fps),
        max(f.right for f in fps),
        max(f.bottom for f in fps),
    )




def _extent(box: Box, axis: str) -> Tuple[float, float]:
    """Return ``(low, size)`` of a box along ``axis`` ('x' or 'y')."""
    if axis == "x":
        return box.x, box.w
    return box.y, box.h


def _with_extent(box: Box, axis: str, low: float, size: float) -> Box:
    """Return a copy of ``box`` with its ``axis`` low/size replaced."""
    if axis == "x":
        return Box(box.id, low, box.y, size, box.h)
    return Box(box.id, box.x, low, box.w, size)


def _stack_peer_azs_in_vpc(boxes: Dict[str, Box], spec: DiagramSpec, axis: str) -> None:
    """Give the peer AZ boxes of one VPC a shared secondary-axis range (Req 12.1/2).

    Peer AZs of a VPC are stacked along the **primary** axis (the AZ-band offset
    applied at placement makes their primary-axis ranges disjoint). For them to
    read as one vertical stack rather than a diagonal, they must share the SAME
    **secondary**-axis low and size (equal width and a common x-range for a
    North–South diagram). This pass sets every AZ box of a VPC to the union of
    its AZ children's secondary extents, so ``az-a1`` and ``az-a2`` end up with
    identical secondary low/size (and likewise ``az-b1`` / ``az-b2``). The
    subsequent :func:`_equalize_peer_widths` then reconciles region A vs region B
    so all four AZ boxes share one width."""
    kind_of = {c.id: c.kind for c in spec.containers}
    child_containers = _children_of(spec)
    for c in spec.containers:
        if c.kind != "vpc":
            continue
        az_ids = [
            ch.id for ch in child_containers.get(c.id, [])
            if kind_of.get(ch.id) == "az" and ch.id in boxes
        ]
        if len(az_ids) < 2:
            continue
        lo = min(_extent(boxes[a], axis)[0] for a in az_ids)
        hi = max(_extent(boxes[a], axis)[0] + _extent(boxes[a], axis)[1] for a in az_ids)
        low, size = _snap(lo), _snap(hi - lo)
        for a in az_ids:
            boxes[a] = _with_extent(boxes[a], axis, low, size)


def _equalize_peer_widths(boxes: Dict[str, Box], spec: DiagramSpec, axis: str) -> None:
    """Give peer containers (same ``kind``, region-siblings) equal secondary-axis
    size (Req 4.3), widening the smaller band toward the pair's shared centre so
    each band's outer edge stays put.

    Peers are grouped by ``(kind, parent-kind)`` so vpc-a/vpc-b match, and az-a*
    matches az-b* at the same tier ordinal. The larger of the pair sets the
    common size; each smaller band grows outward from the pair's midpoint toward
    the larger one, keeping the two mirror-symmetric.
    """
    kind_of = {c.id: c.kind for c in spec.containers}
    region_of = {c.id: c.region for c in spec.containers}
    parent_of = {c.id: c.parent for c in spec.containers}

    # Group peers: same kind, and the same "role" within the region so az bands
    # pair by tier ordinal. Use (kind, ordinal-within-region-kind).
    ordinal: Dict[str, int] = {}
    seen: Dict[Tuple[str, str], int] = {}
    for c in spec.containers:
        key = (c.kind, c.region)
        ordinal[c.id] = seen.get(key, 0)
        seen[key] = ordinal[c.id] + 1

    groups: Dict[Tuple[str, int], list] = {}
    for cid, box in boxes.items():
        if kind_of.get(cid) == "account":
            continue
        groups.setdefault((kind_of[cid], ordinal[cid]), []).append(cid)

    for peers in groups.values():
        if len(peers) < 2:
            continue
        target = max(_extent(boxes[cid], axis)[1] for cid in peers)
        # Overall pair centre along the axis (mean of member centres).
        centres = [
            _extent(boxes[cid], axis)[0] + _extent(boxes[cid], axis)[1] / 2.0
            for cid in peers
        ]
        pair_centre = (min(centres) + max(centres)) / 2.0
        for cid in peers:
            low, size = _extent(boxes[cid], axis)
            if size == target:
                continue
            centre = low + size / 2.0
            grow = target - size
            # Grow outward from the pair centre: a band left of centre keeps its
            # right edge (moves its low edge out); right of centre keeps its low.
            if centre <= pair_centre:
                new_low = low - grow  # keep right edge (low + size) fixed
            else:
                new_low = low         # keep low edge fixed, extend outward
            new_low = _snap(new_low)
            boxes[cid] = _with_extent(boxes[cid], axis, new_low, target)


def _size_account(
    cid: str,
    child_containers: Dict[Optional[str], list],
    leaf_nodes: Dict[str, list],
    placed: Dict[str, Box],
    boxes: Dict[str, Box],
    pad: int,
) -> None:
    """Size the account envelope to wrap every child band + ``pad``, snug (Req 4.5).

    Uses the already-sized (and width-equalized) child container boxes plus any
    account-level direct nodes, so there is no trailing empty margin: the box is
    exactly the children's bounding box grown by ``pad`` on every side.
    """
    child_boxes: list = [boxes[c.id] for c in child_containers.get(cid, [])]
    child_boxes.extend(placed[nid] for nid in leaf_nodes.get(cid, []))
    if not child_boxes:
        raise SpecError(f"account container {cid!r} has no child bands to wrap")
    # Child containers already include their own padding; account-level nodes are
    # measured by footprint. Use raw container boxes and node footprints.
    xs0, ys0, xs1, ys1 = [], [], [], []
    for b in child_boxes:
        fp = b.footprint(LABEL_BAND) if b.id in placed else b
        xs0.append(fp.x)
        ys0.append(fp.y)
        xs1.append(fp.right)
        ys1.append(fp.bottom)
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    # Same caption strip as ``_size`` (v1.6.0): the account's own caption is drawn
    # inside its top edge, so the top pad reserves the band plus real clearance.
    top = pad + CONTAINER_LABEL_BAND
    boxes[cid] = Box(cid, _snap(x0 - pad), _snap(y0 - top),
                     _snap((x1 - x0) + 2 * pad), _snap((y1 - y0) + top + pad))
