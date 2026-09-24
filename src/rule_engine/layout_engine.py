"""Declarative lane-grid layout engine — module scaffold and declaration model.

This module turns a **coordinate-free declaration** of a diagram (nodes with a
role + lane + region + slot, edges with a source/target/type, and nested
containers) into placed geometry that ``diagram_layout.build_diagram`` can
serialize. This file is the first slice: the frozen-dataclass declaration model,
the canonical lane table, and the on-entry validator. Placement, routing, and
the repair loop are added by later tasks.

Design references: ``.kiro/specs/lane-grid-layout-engine/design.md`` ("Data
model", "Lane model") and ``requirements.md`` (Req 1, Req 2).

**Coordinates are the engine's output, never its input.** The declaration
dataclasses deliberately carry *no* ``x``/``y``/``w``/``h``/``exit``/``entry``/
``points`` fields, so a coordinate cannot be expressed in a declaration
(Req 1.4). The canonical layout constants are imported from
:mod:`rule_engine.diagram_layout` and never redefined here (Req 3.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout_engine``
    from .diagram_layout import (
        ICON_SIZE,
        GRID,
        COL_STEP,
        ROW_STEP,
        CONTAINER_PAD,
    )
    from .geometry import Box, LABEL_BAND, segment_crosses_box
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import (  # type: ignore[no-redef]
        ICON_SIZE,
        GRID,
        COL_STEP,
        ROW_STEP,
        CONTAINER_PAD,
    )
    from geometry import Box, LABEL_BAND, segment_crosses_box  # type: ignore[no-redef]

from typing import List


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


# ---------------------------------------------------------------------------
# Declaration data model (Req 1) — coordinate-free, frozen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeSpec:
    """A node declaration: role + lane + region + slot only (Req 1.1).

    No ``x``/``y``: placement is derived by the engine from ``(lane, region,
    slot, sub)`` and the canonical constants.
    """

    id: str
    role: str  # resolves to an icon via the provider skin / icon-index
    lane: str  # one of the eight canonical lanes (see LANES)
    region: str  # "a" | "b" | "" (account-level, e.g. an edge row)
    slot: int  # 0-indexed position within (lane, region)
    sub: int = 0  # optional secondary offset for a sub-row (api / monitoring)
    #: Optional **declared** container membership — the id of the leaf container
    #: this node belongs to (an ``az`` box, or a region ``vpc`` for a service-row
    #: node that sits in the VPC directly rather than any AZ). This is
    #: coordinate-free: it names a container, never geometry. When set, the
    #: node's container membership is authoritative (used by
    #: :func:`_assign_nodes_to_leaves`); when ``None`` the engine falls back to
    #: the geometric tier-band partition (preserving synthetic-spec behavior).
    #: Validated by :func:`_validate_spec` to name a real, region-matching leaf
    #: container.
    container: Optional[str] = None


@dataclass(frozen=True)
class EdgeSpec:
    """An edge declaration: source/target/marker only (Req 1.2).

    No ``exit``/``entry``/``points``: contact points and waypoints are the
    engine's output. The edge *class* is derived from the source/target lane +
    region relationship; ``kind_hint`` is an optional override, not a coordinate.
    """

    id: str
    source: str
    target: str
    marker: str
    dashed: bool = False
    kind_hint: Optional[str] = None


@dataclass(frozen=True)
class ContainerSpec:
    """A container declaration: kind + region + nesting only (Req 1.3).

    No ``x``/``y``/``w``/``h``: the engine sizes each container around its
    children's footprints.
    """

    id: str
    kind: str  # "account" | "vpc" | "az"
    region: str
    parent: Optional[str]  # nesting: az.parent = vpc, vpc.parent = account
    label_key: str  # the skin fills the concrete label


@dataclass(frozen=True)
class DiagramSpec:
    """A whole coordinate-free diagram declaration."""

    diagram_id: str
    diagram_name: str
    axis: str  # "north-south" | "left-right"
    nodes: Tuple[NodeSpec, ...]
    edges: Tuple[EdgeSpec, ...]
    containers: Tuple[ContainerSpec, ...]
    flow_lines: Tuple[str, ...]
    title: str
    #: Compact the primary axis for a small flow diagram: place the *occupied*
    #: lanes at **consecutive** steps rather than at their absolute lane index,
    #: so a ``lb → app → db`` chain reads as three adjacent rows with no empty
    #: tier bands between them (the hand-drawn summary composition). Off by
    #: default so the landscape and every synthetic spec keep absolute-lane
    #: placement byte-unchanged. Only affects **non-banded** nodes (a compact
    #: flow declares no az/vpc container membership).
    compact: bool = False


# ---------------------------------------------------------------------------
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


def _az_band_step(spec: DiagramSpec) -> int:
    """Deprecated alias retained for back-compat — see :func:`_band_packing`.

    Task 20 replaced the single uniform inter-band step with **per-band
    packing** (:func:`_band_packing`): each band starts at the previous band's
    real content bottom + one grid-padded gap, and within a band a node is placed
    at its lane index *relative to that band's own minimum lane* so the band is
    flush to its own top. There is therefore no longer one global step. This
    thin wrapper returns the delta between the first two bands' starts (the step
    that used to be uniform), so any external caller still gets a representative
    grid-aligned value; internal placement no longer uses it.
    """
    band_start, _ = _band_packing(spec)
    if len(band_start) < 2:
        return _snap(ICON_SIZE + LABEL_BAND + ROW_STEP)
    ordered = [band_start[b] for b in sorted(band_start)]
    return ordered[1] - ordered[0]


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
            start = _snap(lo * ROW_STEP)
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
                gap += CONTAINER_PAD
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

    The result passes ``check_container_padding`` and ``check_container_overlap``.
    """
    primary, secondary = _container_axes(spec)
    leaf_nodes = _assign_nodes_to_leaves(spec, placed)
    child_containers = _children_of(spec)
    kind_of = {c.id: c.kind for c in spec.containers}

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
        box = Box(cid, x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad)
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
    boxes[cid] = Box(cid, _snap(x0 - pad), _snap(y0 - pad),
                     _snap((x1 - x0) + 2 * pad), _snap((y1 - y0) + 2 * pad))


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


# ---------------------------------------------------------------------------
# Contact-point selection (Req 5) — exit/entry ladder + fan-out spread
# ---------------------------------------------------------------------------

#: A contact point is a unit-square fraction on a node face: ``(fx, fy)`` where
#: ``fx`` grows to the right and ``fy`` grows downward (draw.io convention).
Contact = Tuple[float, float]

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


# ---------------------------------------------------------------------------
# Corridor allocation (Req 6) — grid-step lanes in inter-column / inter-row gaps
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Edge classification and per-class routing (Req 7)
# ---------------------------------------------------------------------------

#: A waypoint is an absolute ``(x, y)`` model coordinate on a corridor line.
Point = Tuple[float, float]

#: The five edge classes the HA summary/landscape diagrams use. Any edge that
#: matches none of them is unclassifiable and :func:`classify_edge` raises
#: (fail-honest, no guessed route — matching the icon-resolution philosophy;
#: design.md → "Integration points & risks / Scope guard").
EDGE_KINDS = ("straight", "spine", "fan-out-row", "cross-region", "back-edge")

#: A rightward source→target separation at or beyond this distance reads as a
#: *cross-region* hop (A→B) rather than an in-region same-row fan-out. It must
#: sit **above** the widest in-region fan-out span and **below** the region-B
#: offset: with 4-column bands an in-region fan-out spans up to 3·COL_STEP (660),
#: while region B is region-A-extent + REGION_GAP away (~1180). ``REGION_GAP +
#: 2·COL_STEP`` (880) lands cleanly between them, so a 3-column in-region fan-out
#: (e.g. app→objstore) is NOT mistaken for a cross-region hop. Genuine
#: cross-region edges are additionally declared via ``kind_hint`` in the spec.
CROSS_REGION_SPAN = REGION_GAP + 2 * COL_STEP


class UnclassifiableEdgeError(ValueError):
    """Raised when an edge matches none of the five :data:`EDGE_KINDS`.

    The engine covers exactly the classes present in the HA diagrams; an edge
    that classifies as none raises rather than emitting a guessed route
    (fail-honest, Req 7.1 / design.md scope guard). The message names the edge
    and the source/target geometry so the gap is actionable."""


def _same_row(a: Box, b: Box) -> bool:
    """True when two boxes share a row (equal top edge)."""
    return a.y == b.y


def classify_edge(edge: EdgeSpec, placed: Dict[str, Box]) -> str:
    """Classify ``edge`` into one of the five :data:`EDGE_KINDS` (Req 7.1).

    Classification is pure geometry from the source/target boxes, applied in a
    fixed priority order so it is deterministic:

    1. ``back-edge`` — the target's column is **left of** the source
       (``target.x < source.x``): the edge must loop out the right and re-enter
       the target's left (Req 7.6). Checked first because a left-ward target is
       a back-edge regardless of row.
    2. ``straight`` — the target sits **directly opposite on the same row**, to
       the right and adjacent (one column step), with nothing between: a single
       centred segment (Req 7.2).
    3. ``cross-region`` — the target is **far** to the right (≥
       :data:`CROSS_REGION_SPAN`) on roughly the same tier: a region A→B hop
       that rises into its own over-row corridor and enters the target's top
       (Req 7.5).
    4. ``fan-out-row`` — the target is on the **same row**, to the right, but not
       adjacent (a later column on the row): the source fans out to several
       same-row targets, each in its own below-row lane (Req 7.4).
    5. ``spine`` — otherwise a tier hop within a region (a different row, to the
       right or same column-ish): route through a side corridor beside the
       column into the target's near face (Req 7.3).

    An ``edge.kind_hint`` that names a valid kind overrides the derivation
    (design.md — an optional hint, never a coordinate). An edge matching none of
    the five raises :class:`UnclassifiableEdgeError` (Req 7.1 scope guard).
    """
    if edge.kind_hint is not None:
        if edge.kind_hint not in EDGE_KINDS:
            raise UnclassifiableEdgeError(
                f"edge {edge.id!r} declares unknown kind_hint {edge.kind_hint!r}; "
                f"kind must be one of {EDGE_KINDS}"
            )
        return edge.kind_hint

    src = placed[edge.source]
    tgt = placed[edge.target]
    dx = tgt.x - src.x
    dy = tgt.y - src.y

    # 1. back-edge: target column strictly left of the source.
    if dx < 0:
        return "back-edge"

    # 2. straight: same row, adjacent to the right, nothing between.
    if _same_row(src, tgt) and 0 < dx <= COL_STEP + src.w:
        return "straight"

    # 3. cross-region: a large rightward hop at roughly the same tier.
    if dx >= CROSS_REGION_SPAN and abs(dy) <= ROW_STEP:
        return "cross-region"

    # 4. fan-out-row: same row, to the right, but not adjacent.
    if _same_row(src, tgt) and dx > 0:
        return "fan-out-row"

    # 5. spine: a tier hop within a region (different row, rightward/near column).
    if dy != 0 and dx >= 0:
        return "spine"

    raise UnclassifiableEdgeError(
        f"edge {edge.id!r} ({edge.source!r}->{edge.target!r}) matches no known "
        f"edge class (dx={dx}, dy={dy}); classes are {EDGE_KINDS}"
    )


# -- routing helpers --------------------------------------------------------


def _contact_point(box: Box, contact: Contact) -> Point:
    """Return the absolute ``(x, y)`` of a unit-square ``contact`` on ``box``."""
    fx, fy = contact
    return (box.x + fx * box.w, box.y + fy * box.h)


def _grid_contact(box: Box, contact: Contact) -> Contact:
    """Return ``contact`` adjusted so its ABSOLUTE point lands on the grid.

    An icon is 78px, so a face-centre fraction (0.5) resolves to ``x0+39`` — off
    the 10-grid — while routed waypoints are grid-snapped. That 1px mismatch is
    what skewed every arrowhead. Snapping the *fraction* so the absolute contact
    equals ``_snap(x0 + f·78)`` makes the arrow land exactly where the final
    grid-aligned waypoint sits: no kink, and every waypoint stays on the grid.
    The fraction is nudged by at most ~half a grid step, so the contact stays on
    the same face band (0.5 → ~0.513), preserving the directional contract and
    the distinct-exit spread."""
    fx, fy = contact
    ax = box.x + fx * box.w
    ay = box.y + fy * box.h
    nfx = (_snap(ax) - box.x) / box.w if box.w else fx
    nfy = (_snap(ay) - box.y) / box.h if box.h else fy
    return (nfx, nfy)


def _obstacles_between(
    p: Point, q: Point, obstacles: List[Box]
) -> List[Box]:
    """Return the obstacle boxes a straight ``p``→``q`` run would cross.

    Uses the **same** segment-sampling predicate the ``check_edge_routing``
    validator uses (:func:`geometry.segment_crosses_box`), so the router's
    obstacle test and the acceptance oracle agree by construction (Req 7.7)."""
    return [b for b in obstacles if segment_crosses_box(p, q, b)]


def _relevant_obstacles(edge: EdgeSpec, obstacles: List[Box]) -> List[Box]:
    """Drop the edge's own endpoints from the obstacle set."""
    return [b for b in obstacles if b.id not in (edge.source, edge.target)]


def route_straight(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Route a ``straight`` edge as a single centred segment (Req 7.2).

    A straight edge connects a directly-opposite adjacent target, so no
    intermediate waypoint is needed: draw.io draws the orthogonal segment from
    the pinned exit to the pinned entry. Returns ``[]`` (no interior waypoints)
    — the empty list *is* the single centred segment. The caller supplies the
    placed boxes only to assert the run crosses nothing (it cannot, by the
    adjacency precondition)."""
    return []


def _stair_first_waypoint(
    src: Box, exit_pt: Contact, toward_down: bool
) -> Point:
    """Return the first stair waypoint: a PURELY HORIZONTAL step off the exit.

    The stair rule (diagram-standards): step one grid corridor off the glyph
    **before** turning. The step-out must be **horizontal only** — it keeps the
    exit's own ``y`` and moves ``x`` right — so the first segment leaves the
    right face straight (not a diagonal), and the arrow/stub is not skewed at the
    glyph (the "перекошена стрілка" defect). The *next* waypoint (the corridor
    drop, set by each router) then moves ``y``, so the two waypoints together
    form a clean right-angle stair with neither axis collapsing.

    ``toward_down`` is retained for signature stability but no longer nudges
    ``y`` (that nudge is what skewed the stub); the vertical turn happens at the
    router's corridor waypoint instead. The exit ``y`` is grid-aligned because
    the contact fraction is grid-resolving (:func:`_grid_contact`), so the
    horizontal step-out is level and stays on the grid."""
    ex, ey = _contact_point(src, exit_pt)
    return (_snap(ex + GRID), _snap(ey))


def _gap_column_x(allocator: "CorridorAllocator", src: Box, edge_id: str) -> float:
    """Allocate a distinct vertical-corridor x in the gap right of ``src``.

    Every vertical leg (a spine drop, or a fan-out / cross-region step-out) that
    runs in the gap immediately right of a source column takes a line from the
    SAME physical gap namespace (``vcol:<gap-left-x>``), so unrelated vertical
    runs in one gap land on DISTINCT grid lines instead of all defaulting to
    ``src_right + GRID`` and merging. This is what keeps a tier-skipping spine
    (e.g. lb→app-az2) off the fan-out step-out lanes in the same gap without any
    repair pass (``check_corridor_sharing`` clean by construction)."""
    gap_left = int(src.right)
    gap_low, gap_high = allocator.column_gap(src.x, src.x + COL_STEP)
    return _snap(_allocate_or_first(allocator, f"vcol:{gap_left}", gap_low, gap_high))


def route_spine(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Route a ``spine`` tier hop through a side corridor beside the column (Req 7.3).

    Shape: exit the source's right, step one ``GRID`` into the inter-column gap
    (the stair), drop in a corridor **beside** the node column (never straight
    down the column), then turn into the target's near (top) face. The vertical
    drop x is an allocated corridor line in the gap immediately right of the
    source column, so the run clears the icons stacked in that column and stays
    distinct from any fan-out step-out sharing that gap."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    # Straight vertical drop (Exception I, compact flow): a bottom-centre exit
    # into a top-centre entry on the same column is a single clean vertical —
    # no side corridor, no hook. draw.io draws the orthogonal segment between the
    # two pinned contacts, so no interior waypoints are needed.
    if exit_pt[1] >= 1.0 and entry_pt[1] <= 0.0 and abs(src.x - tgt.x) < 1e-9:
        return []

    entry = _contact_point(tgt, entry_pt)
    down = tgt.y >= src.y
    first = _stair_first_waypoint(src, exit_pt, toward_down=down)

    # Side corridor x: an allocated grid line in the gap right of the source,
    # shared with every other vertical leg in that gap (see _gap_column_x).
    corridor_x = _gap_column_x(allocator, src, edge.id)
    # The stair's first waypoint moves onto the same allocated corridor x, so the
    # vertical leg and its step-out are one line (no doubled stub).
    first = (corridor_x, first[1])

    # Rule E: step INTO the target's corridor before entering its face — mirror
    # of the exit stair. A TOP entry (spine descending into a target below):
    # drop the corridor to one grid step above the target, step across to the
    # target's centre x, then descend into the top. A LEFT entry: drop to the
    # entry row, then run across into the left face.
    top_entry = entry_pt[1] <= 0.0
    if top_entry:
        step_y = _snap(entry[1] - GRID)         # one grid step above the top face
        waypoints = [
            first,
            (corridor_x, step_y),               # drop in the side corridor
            (_snap(entry[0]), step_y),          # step across above the target
            (_snap(entry[0]), _snap(entry[1])), # descend into the top face
        ]
    else:
        turn_y = _snap(entry[1])
        waypoints = [first, (corridor_x, first[1]), (corridor_x, turn_y)]
    waypoints = _dedupe_axis_collapse(waypoints, first)

    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    _detour_clockwise_if_blocked(route, others)
    return waypoints


def route_fan_out_row(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Route a ``fan-out-row`` edge in its own below-row lane (Req 7.4).

    Shape: exit the source right (the stair moves both axes), drop one ``GRID``
    into a below-row corridor allocated for this edge, run across **below the
    row** to the gap immediately left of the target, then turn **up** into the
    target's left face. Each fan-out edge takes its own below-row lane so
    parallel runs never merge (``check_corridor_sharing`` clean)."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    entry = _contact_point(tgt, entry_pt)
    first = _stair_first_waypoint(src, exit_pt, toward_down=True)

    # Step-out vertical leg: an allocated column line in the gap right of the
    # source, shared with every other vertical leg in that gap (see
    # _gap_column_x), so the fan-out step-out never coincides with a spine drop.
    step_x = _gap_column_x(allocator, src, edge.id)
    first = (step_x, first[1])

    # Below-row lane: an allocated grid line in the row gap under the source,
    # starting BELOW the source's LABEL BAND (Rule F). A fan-out run one grid step
    # under the icon would cross the service caption drawn beneath it; insetting
    # the lane past ``ICON_SIZE + LABEL_BAND`` keeps the run clear of every
    # caption in the row. Keyed by the physical row band so several fan-out edges
    # from the same row get distinct below-row lanes rather than merging on one.
    row_low = src.y + ICON_SIZE + LABEL_BAND + GRID
    row_high = src.y + ROW_STEP
    lane_y = _snap(_allocate_or_first(allocator, f"fanout-row:{int(src.y)}", row_low, row_high))

    # Turn up in the gap just LEFT of the target (target_x - ~half a gap).
    up_x = _snap(tgt.x - (COL_STEP - ICON_SIZE) // 2)

    waypoints = [
        first,
        (first[0], lane_y),
        (up_x, lane_y),
        (up_x, _snap(entry[1])),
    ]
    waypoints = _dedupe_axis_collapse(waypoints, first)
    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    _detour_clockwise_if_blocked(route, others)
    return waypoints


def route_cross_region(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Route a ``cross-region`` A→B hop through its own over-row corridor (Req 7.5).

    Shape: step out of the source's right into the gap (the stair moves both
    axes), rise into an over-row corridor allocated for this edge (one lane
    each), run across to above the target, then drop into the target's top
    face."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    entry = _contact_point(tgt, entry_pt)
    # Choose the horizontal corridor side: above the source by default, but
    # BELOW when the source is in the top band (no room above → the run would
    # leave the canvas / rise above the account box) or the target sits clearly
    # below the source (a downward hop like dns→passive-region-LB reads better
    # routed below). This keeps the corridor on the grid and inside the account.
    below = (src.y - ROW_STEP) <= CONTAINER_PAD or tgt.y >= src.y + ROW_STEP
    first = _stair_first_waypoint(src, exit_pt, toward_down=below)
    # Vertical leg in the gap right of the source, distinct per gap.
    rise_x = _gap_column_x(allocator, src, edge.id)
    first = (rise_x, first[1])

    # Cross-region corridor: an allocated grid line in the row gap above (default)
    # or below (top-band / downward hop) the source. Keyed by the physical row
    # band + side, so two cross-region runs leaving the same source row (e.g.
    # db_a1->db_b1 and obj_a1->obj_b1) get DISTINCT lanes from the shared
    # allocator instead of merging (the corridor-sharing regression this fixes).
    if below:
        # A BELOW corridor must clear the source's LABEL BAND (Rule F), else the
        # horizontal run crosses the caption drawn under the source icon (edge 1
        # crossing the dns / waf caption).
        row_low = src.y + ICON_SIZE + LABEL_BAND + GRID
        row_high = src.y + ROW_STEP
        side = "below"
    else:
        # An ABOVE corridor sits in the gap between the row above and the source
        # row; it must clear the UPPER row's LABEL BAND (Rule F), else it runs
        # along that row's captions (edge 10 over the service-row labels).
        row_low = (src.y - ROW_STEP) + ICON_SIZE + LABEL_BAND + GRID
        row_high = src.y
        side = "above"
    # Shared horizontal-corridor namespace (``hcorr``) keyed by the physical band
    # + side, so ANY long horizontal run in this band (cross-region OR back-edge)
    # gets a DISTINCT lane from the shared allocator — two edges in different
    # per-class namespaces used to both grab the first line and merge (e.g. edge
    # 1 back-edge and edge 2 cross-region both leaving dns).
    over_y = _snap(_allocate_or_first(allocator, f"hcorr-{side}:{int(src.y)}", row_low, row_high))

    across_x = _snap(entry[0])
    waypoints = [
        first,
        (first[0], over_y),
        (across_x, over_y),
        (across_x, _snap(entry[1])),
    ]
    waypoints = _dedupe_axis_collapse(waypoints, first)
    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    _detour_clockwise_if_blocked(route, others)
    return waypoints


def route_back_edge(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Route a ``back-edge`` (target left of source) out the right and back (Req 7.6).

    Shape: exit the source's **right** (never the side it enters), step into the
    gap (the stair moves both axes), rise into a dedicated loop corridor above
    the rows, run left past the target's column, then drop into the target's
    **left** face. Exiting right and entering left is the whole point of a
    back-edge (diagram-standards → directional back-edge)."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    entry = _contact_point(tgt, entry_pt)
    # Loop corridor above the source by default, but BELOW when the source is in
    # the top band (no room above → the loop would rise above the account box),
    # mirroring route_cross_region so a top-row back-edge stays inside the canvas.
    below = (src.y - ROW_STEP) <= CONTAINER_PAD
    first = _stair_first_waypoint(src, exit_pt, toward_down=below)
    # Vertical leg in the gap right of the source, distinct per gap.
    rise_x = _gap_column_x(allocator, src, edge.id)
    first = (rise_x, first[1])

    # Dedicated loop corridor in the row gap above (default) or below (top-band)
    # the source row, keyed by the physical row band + side so parallel back-edges
    # from the same row get distinct loop lanes rather than merging on one.
    if below:
        # Clear the source LABEL BAND (Rule F) so the loop run doesn't cross the
        # caption under the source icon.
        row_low = src.y + ICON_SIZE + LABEL_BAND + GRID
        row_high = src.y + ROW_STEP
        side = "below"
    else:
        # Clear the UPPER row's LABEL BAND (Rule F) so the loop doesn't run along
        # the captions of the row above.
        row_low = (src.y - ROW_STEP) + ICON_SIZE + LABEL_BAND + GRID
        row_high = src.y
        side = "above"
    # Shared horizontal-corridor namespace (see route_cross_region): a back-edge
    # and a cross-region run in the same band+side get distinct lanes.
    loop_y = _snap(_allocate_or_first(allocator, f"hcorr-{side}:{int(src.y)}", row_low, row_high))

    if entry_pt[1] <= 0.0:
        # TOP entry (Rule G: the target has no left gap — set by the pipeline):
        # run the loop corridor to above the target centre and drop into the top.
        across = _snap(entry[0])
        waypoints = [
            first,
            (first[0], loop_y),
            (across, loop_y),
            (across, _snap(entry[1])),
        ]
    else:
        # LEFT entry: run left in the loop corridor to the gap just left of the
        # target, then drop into its left face. Clamp so the turn stays on-canvas.
        left_x = _snap(max(tgt.x - (COL_STEP - ICON_SIZE) // 2, CONTAINER_PAD))
        waypoints = [
            first,
            (first[0], loop_y),
            (left_x, loop_y),
            (left_x, _snap(entry[1])),
        ]
    waypoints = _dedupe_axis_collapse(waypoints, first)
    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    _detour_clockwise_if_blocked(route, others)
    return waypoints


# ---------------------------------------------------------------------------
# Right-margin Flow/Legend placement (Req 8)
# ---------------------------------------------------------------------------

#: The pinned narrow width for the Flow/Legend blocks. A fixed narrow value so
#: the blocks wrap and grow *taller* rather than run wide into the diagram body
#: (Req 8.2). This is the exact width the shipped HA landscape passes to
#: ``build_diagram(..., legend_w=280)``; ``build_diagram``'s existing wrap-aware
#: ``_text_h`` grows each box's height from its wrapped line count at this width,
#: so the engine reuses that sizing rather than inventing new geometry.
LEGEND_W = 280


def place_legend(account_box: Box, flow_lines: Tuple[str, ...]) -> Tuple[int, int]:
    """Return ``(legend_x, legend_w)`` for the right-margin Flow/Legend blocks (Req 8).

    * ``legend_x = account_box.right + CONTAINER_PAD`` — the blocks start at
      least one container-pad step past the outermost container's right edge, so
      they sit in the clear right margin and never overlap the cloud (Req 8.1,
      8.3). Because the account box wraps every region band, any node or nested
      container box is fully left of ``account_box.right`` and therefore left of
      ``legend_x``.
    * ``legend_w = LEGEND_W`` — a fixed narrow width (Req 8.2). ``build_diagram``
      is passed this as its ``legend_w`` parameter and uses its existing
      wrap-aware ``_text_h`` to grow the boxes *taller* (wrapped line count)
      rather than wider, so a long legend line never runs back into the diagram
      body. The engine reuses that sizing — it only pins the narrow width and
      the past-the-account x, not any height computation.

    Both returned values are grid-aligned integers (``CONTAINER_PAD`` and
    ``LEGEND_W`` are whole ``GRID`` multiples and ``account_box.right`` is
    grid-aligned by construction), so the emitted coordinates stay on the grid
    (Req 11.4). ``flow_lines`` is accepted so the signature matches the
    declaration the caller already holds (the Flow block covers every marker in
    ascending order — that ordering is the caller's ``flow_lines`` content,
    which ``build_diagram`` renders verbatim, Req 8.4); the pinned width does not
    depend on the line contents.
    """
    legend_x = _snap(account_box.right + CONTAINER_PAD)
    return legend_x, LEGEND_W


#: Router dispatch table keyed by edge class.
ROUTERS = {
    "straight": route_straight,
    "spine": route_spine,
    "fan-out-row": route_fan_out_row,
    "cross-region": route_cross_region,
    "back-edge": route_back_edge,
}


def route_edge(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Classify ``edge`` and dispatch to the matching ``route_<kind>`` router.

    A thin convenience over :func:`classify_edge` + :data:`ROUTERS`. Raises
    :class:`UnclassifiableEdgeError` (via :func:`classify_edge`) for an edge that
    matches no class — the engine never guesses a route (Req 7.1)."""
    placed = {b.id: b for b in obstacles}
    kind = classify_edge(edge, placed)
    return ROUTERS[kind](edge, exit_pt, entry_pt, allocator, obstacles)


# -- small shared router utilities ------------------------------------------


def obstacle_box(node_id: str, obstacles: List[Box]) -> Box:
    """Return the placed box for ``node_id`` from the obstacle list."""
    for b in obstacles:
        if b.id == node_id:
            return b
    raise SpecError(f"router given no placed box for node {node_id!r}")


def _allocate_or_first(
    allocator: "CorridorAllocator", gap_id: str, low: float, high: float
) -> float:
    """Allocate a corridor line, tolerating a degenerate (empty) gap.

    A router occasionally faces a gap too narrow to hold a grid line (adjacent
    boxes). Rather than fail, fall back to the gap midpoint snapped to the grid
    — the repair loop (Task 8) widens genuinely exhausted gaps; here the router
    just needs a deterministic corridor coordinate to emit a waypoint on."""
    try:
        return allocator.allocate(gap_id, low, high)
    except CorridorExhaustedError:
        return _snap((low + high) / 2.0)


def _dedupe_axis_collapse(waypoints: List[Point], first: Point) -> List[Point]:
    """Drop consecutive duplicate waypoints while preserving the first stair step.

    The first waypoint (``first``) always changes both axes off the exit (the
    no-collapse rule); this only removes *later* points that coincide with their
    predecessor, keeping the emitted polyline minimal and orthogonal."""
    out: List[Point] = []
    for pt in waypoints:
        if not out or out[-1] != pt:
            out.append(pt)
    return out


def _detour_clockwise_if_blocked(route: List[Point], obstacles: List[Box]) -> None:
    """Nudge any blocked straight segment clockwise by one corridor, in place.

    Walks the emitted polyline; where a segment would cut an unrelated obstacle
    (tested with the *same* :func:`geometry.segment_crosses_box` predicate the
    validator uses), it shifts the segment's free axis by one ``GRID`` step
    clockwise (obstacle kept on the edge's left) and retries, up to a small
    bound. Deterministic: a fixed turn direction means two agents routing the
    same edge produce the same detour (Req 7.7)."""
    for i in range(len(route) - 1):
        for _ in range(4):  # bounded clockwise nudges
            blocked = _obstacles_between(route[i], route[i + 1], obstacles)
            if not blocked:
                break
            x0, y0 = route[i]
            x1, y1 = route[i + 1]
            if abs(x1 - x0) <= 1:  # vertical segment → shift x clockwise (right)
                route[i] = (_snap(x0 + GRID), y0)
                route[i + 1] = (_snap(x1 + GRID), y1)
            else:  # horizontal segment → shift y clockwise (up)
                route[i] = (x0, _snap(y0 - GRID))
                route[i + 1] = (x1, _snap(y1 - GRID))


# ---------------------------------------------------------------------------
# Oracle adapter, repair loop, and the ``layout`` entry point (Req 9, Req 11)
# ---------------------------------------------------------------------------

#: Upper bound on repair iterations (Req 9.4). The loop terminates in a fixed
#: number of passes: each pass either clears a blocking finding or the layout is
#: declared unfixable. A small bound is enough because every repair strictly
#: reduces the blocking-finding count (grow a container, bump a corridor lane,
#: re-centre a block) and the pipeline emits only a handful of fixable defects.
MAX_REPAIR_ITERS = 8

#: Import the assembler + validators lazily-at-module-load. ``diagram_layout``
#: (the assembler) and ``geometry`` (the validators) are the two collaborators
#: the oracle adapter drives; importing them here keeps the pipeline functions
#: above dependency-free (they operate on pure ``Box`` geometry).
try:  # package-relative
    from . import diagram_layout as _dl
    from . import geometry as _geo
except ImportError:  # pragma: no cover - flat-module execution
    import diagram_layout as _dl  # type: ignore[no-redef]
    import geometry as _geo  # type: ignore[no-redef]


class LayoutError(RuntimeError):
    """Raised when the repair loop cannot make a layout publication-eligible.

    Either a finding is *unfixable* (an over-connected node — the diagram must be
    split or re-laned, not nudged), or the bounded repair loop
    (:data:`MAX_REPAIR_ITERS`) exhausted its passes with a blocking finding still
    present. The message names the first unresolved finding so the fault is
    actionable (Req 9.3)."""


@dataclass
class PlacedEdge:
    """One fully-placed edge: its spec plus the engine's emitted geometry.

    ``exit``/``entry`` are the contact points the ladder chose and ``points`` the
    corridor-aligned waypoints the router emitted — exactly the fields
    :class:`diagram_layout.Edge` consumes, so a ``PlacedEdge`` serializes with no
    further geometry work (Req 1.2: geometry is the engine's output)."""

    spec: EdgeSpec
    exit: Contact
    entry: Contact
    points: List[Point]


@dataclass
class PlacedDiagram:
    """A fully-placed diagram, ready to hand to ``build_diagram`` (design.md §9).

    Holds the placed node boxes, the sized container boxes, the routed edges, and
    the right-margin ``legend_x``/``legend_w`` — everything ``build_diagram``
    needs, and everything the oracle adapter re-parses. The declaration
    (``spec``) is retained so a repair can re-run a pipeline step (e.g. re-centre
    a region's block) deterministically."""

    spec: DiagramSpec
    nodes: Dict[str, Box]
    containers: Dict[str, Box]
    edges: List[PlacedEdge]
    legend_x: int
    legend_w: int


@dataclass
class OracleFindings:
    """The oracle's verdict on a candidate: blocking vs fixable geometry findings.

    ``blocking`` are the findings that make the (landscape-class) artifact
    publication-ineligible — the ERROR/CRITICAL geometry rules the repair loop
    must clear. ``fixable`` is the subset of blocking findings the engine knows a
    deterministic repair for; an unfixable blocking finding (e.g. over-connected)
    stays in ``blocking`` but not in ``fixable`` and forces a :class:`LayoutError`.
    Each finding is ``(rule, payload)`` where ``payload`` is the validator's own
    offending-item tuple/id, so a repair can act on it."""

    blocking: List[Tuple[str, object]]
    fixable: List[Tuple[str, object]]

    @property
    def clean(self) -> bool:
        return not self.blocking

    @property
    def first_unresolved(self) -> Optional[Tuple[str, object]]:
        return self.blocking[0] if self.blocking else None


#: A neutral, non-boundary stub icon style for oracle serialization. It resolves
#: to a real built-in AWS resourceIcon shape (so ``build_geometry`` parses a node
#: with geometry) but names no ``group_``/``grIcon=``/``dashed=1;fillColor=none``
#: token, so ``is_boundary_container_style`` never mistakes a node for a
#: container. The oracle only cares about *geometry*, not which glyph renders —
#: the real provider skin is applied later by the caller's ``build_diagram``.
_STUB_ICON_STYLE = (
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)


def _stub_boundary_style(cand: "PlacedDiagram", cid: str) -> str:
    """Return a dashed-rectangle boundary style the geometry parser recognizes.

    Uses the standard dashed borderless rectangle (``dashed=1;fillColor=none``)
    so ``is_boundary_container_style`` classifies the cell as a Boundary /
    Network-Boundary container — the same detection the linter applies."""
    return (
        "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;"
        "strokeColor=#00A000;fillColor=none;verticalAlign=top;"
        "fontColor=#00A000;fontSize=12"
    )


def _serialize_candidate(cand: "PlacedDiagram") -> str:
    """Serialize a candidate to ``.drawio`` text via ``build_diagram`` (stub icons).

    Builds the ``Node`` / ``Edge`` / ``Boundary`` objects ``build_diagram``
    consumes straight from the candidate's placed boxes and routed edges, using a
    neutral stub icon renderer (the oracle judges *geometry*, not the glyph). The
    returned text is exactly what the linter would parse, so re-parsing it with
    ``build_geometry`` gives the oracle the linter's own view (design.md →
    "Integration points & risks / _run_oracle adapter")."""
    boundaries = [
        _dl.Boundary(
            id=c.id,
            label=c.id,
            x=int(box.x),
            y=int(box.y),
            w=int(box.w),
            h=int(box.h),
            style=_stub_boundary_style(cand, c.id),
        )
        for c in cand.spec.containers
        if (box := cand.containers.get(c.id)) is not None
    ]
    stub = _dl.builtin_icon(_STUB_ICON_STYLE)
    nodes = [
        _dl.Node(id=nid, label=nid, x=int(box.x), y=int(box.y), render=stub)
        for nid, box in sorted(cand.nodes.items())
    ]
    edges = [
        _dl.Edge(
            id=pe.spec.id,
            source=pe.spec.source,
            target=pe.spec.target,
            marker=pe.spec.marker,
            dashed=pe.spec.dashed,
            exit=pe.exit,
            entry=pe.entry,
            points=tuple((float(x), float(y)) for x, y in pe.points),
        )
        for pe in cand.edges
    ]
    return _dl.build_diagram(
        diagram_id=cand.spec.diagram_id,
        diagram_name=cand.spec.diagram_name,
        title=cand.spec.title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=cand.spec.flow_lines,
        legend_x=cand.legend_x,
        legend_w=cand.legend_w,
    )


#: The blocking geometry rules for a landscape-class diagram (diagram-lint →
#: Diagram Class): these are ERROR/CRITICAL and make the artifact
#: publication-ineligible, so the repair loop must clear them. Each entry pairs a
#: rule name with the validator that reports it; a non-empty result is a finding.
#: (``node-overlap`` is a WARNING in the ruleset but is treated as blocking here
#: because two icons drawn on top of each other is never acceptable output.)
def _collect_findings(geo: "_geo.DiagramGeometry") -> List[Tuple[str, object]]:
    """Run the geometry ``check_*`` set and return ``(rule, payload)`` findings.

    Deterministic ordering: the checks run in a fixed sequence and each check's
    own output is already sorted, so the finding list is stable for a given
    candidate (Req 9.4 / 11.1)."""
    findings: List[Tuple[str, object]] = []
    for cid, ccid, _pad in _geo.check_container_padding(geo, pad=CONTAINER_PAD):
        findings.append(("container-padding", (cid, ccid)))
    for pair in _geo.check_container_overlap(geo):
        findings.append(("container-overlap", pair))
    for pair in _geo.check_node_overlap(geo):
        findings.append(("node-overlap", pair))
    for eid, reason in _geo.check_edge_direction(geo):
        findings.append(("edge-direction", (eid, reason)))
    for eid in _geo.check_edge_float(geo):
        findings.append(("edge-float", eid))
    for pair in _geo.check_corridor_sharing(geo):
        findings.append(("corridor-sharing", pair))
    return findings


#: Blocking rule names (landscape severity). A finding under one of these blocks
#: publication and drives the repair loop; other rules are advisory WARNINGs.
_BLOCKING_RULES = frozenset(
    {
        "container-padding",
        "container-overlap",
        "node-overlap",
        "edge-direction",
        "edge-float",
        "corridor-sharing",
    }
)

#: Rules the engine knows a deterministic repair for (Req 9.2). A blocking
#: finding *not* in this set is unfixable and forces a :class:`LayoutError`.
_FIXABLE_RULES = frozenset({"container-padding", "corridor-sharing"})


def _run_oracle(candidate: "PlacedDiagram") -> "OracleFindings":
    """Serialize ``candidate``, re-parse it, and run the geometry oracle (Req 9.1).

    Cheapest correct adapter (design.md): serialize the candidate with
    ``build_diagram`` (stub icons), ``build_geometry`` it back, and run the
    ``check_*`` set — so the oracle sees exactly what the linter would. Findings
    are split into ``blocking`` (the landscape ERROR/CRITICAL rules) and the
    ``fixable`` subset the repair loop knows how to resolve."""
    text = _serialize_candidate(candidate)
    geo = _geo.build_geometry(text)
    all_findings = _collect_findings(geo)
    blocking = [f for f in all_findings if f[0] in _BLOCKING_RULES]
    fixable = [f for f in blocking if f[0] in _FIXABLE_RULES]
    return OracleFindings(blocking=blocking, fixable=fixable)


def _grow_container(box: Box, step: int = GRID) -> Box:
    """Grow a container box outward by ``step`` on every side (padding repair)."""
    return Box(box.id, _snap(box.x - step), _snap(box.y - step),
               _snap(box.w + 2 * step), _snap(box.h + 2 * step))


def _bump_edge_corridor(pe: "PlacedEdge", step: int = GRID) -> "PlacedEdge":
    """Move an edge's long run onto the next corridor lane (sharing repair).

    Shifts every interior waypoint by one ``GRID`` step along the axis of the
    edge's dominant run (x for a vertical run, y for a horizontal run), so the
    two previously-merged parallel runs land on distinct grid lines
    (``check_corridor_sharing`` clean). Endpoints (the pinned contact points) are
    untouched; only the interior corridor waypoints move, keeping the edge
    attached to both nodes."""
    if len(pe.points) < 2:
        return pe
    # Decide the run axis from the dominant interior segment.
    (x0, y0), (x1, y1) = pe.points[0], pe.points[-1]
    vertical = abs(x1 - x0) <= abs(y1 - y0)
    moved: List[Point] = []
    for (px, py) in pe.points:
        if vertical:
            moved.append((_snap(px + step), py))
        else:
            moved.append((px, _snap(py + step)))
    return PlacedEdge(spec=pe.spec, exit=pe.exit, entry=pe.entry, points=moved)


def _repair(
    candidate: "PlacedDiagram", findings: "OracleFindings"
) -> "PlacedDiagram":
    """Apply one deterministic fix per fixable finding type (Req 9.2, 9.4).

    Repairs, each named and deterministic (findings arrive in a stable order):

    * **container-padding** → *grow* the offending container one ``GRID`` step on
      every side, so its border clears the child footprint by ≥ ``CONTAINER_PAD``.
    * **corridor-sharing** → move the *later* (higher-id) of the two colliding
      edges onto the next corridor lane, so the two runs no longer share a line.
    * **over-connected / any unfixable blocking finding** → raise
      :class:`LayoutError` naming the finding (Req 9.3): the diagram must be split
      or re-laned, not nudged.

    Exactly one fix is applied per fixable finding in the current pass; the
    caller re-runs the oracle and repairs again until clean or the bound is hit.
    """
    # Any blocking finding with no known repair is unfixable — fail-honest.
    unfixable = [f for f in findings.blocking if f[0] not in _FIXABLE_RULES]
    if unfixable:
        rule, payload = unfixable[0]
        raise LayoutError(
            f"unfixable blocking finding {rule!r} on {payload!r}; the diagram "
            "must be split or re-laned (repair loop cannot resolve it)"
        )

    containers = dict(candidate.containers)
    edges = list(candidate.edges)
    edge_by_id = {pe.spec.id: i for i, pe in enumerate(edges)}

    for rule, payload in sorted(findings.fixable, key=lambda f: (f[0], repr(f[1]))):
        if rule == "container-padding":
            _node_id, ccid = payload  # type: ignore[misc]
            if ccid in containers:
                containers[ccid] = _grow_container(containers[ccid])
        elif rule == "corridor-sharing":
            a, b = payload  # type: ignore[misc]
            later = max(a, b)  # deterministic: the higher edge id yields
            idx = edge_by_id.get(later)
            if idx is not None:
                edges[idx] = _bump_edge_corridor(edges[idx])

    return PlacedDiagram(
        spec=candidate.spec,
        nodes=candidate.nodes,
        containers=containers,
        edges=edges,
        legend_x=candidate.legend_x,
        legend_w=candidate.legend_w,
    )


def _place_and_route(spec: DiagramSpec) -> "PlacedDiagram":
    """Run the pure pipeline (steps 1–8) into an initial candidate (design.md §9).

    place → size → centre → contacts (+ spread) → corridors → route → legend.
    No randomness, no time, dict iteration replaced by sorted/declared order, so
    the candidate is a deterministic function of ``spec`` (Req 11.1)."""
    placed = place_nodes(spec)
    containers = size_containers(placed, spec)
    placed = centre_block_in_vpc(placed, containers, spec)

    obstacles = [placed[n.id] for n in spec.nodes]

    # 1. Select each edge's contact points via the ladder.
    exits: Dict[str, Contact] = {}
    entries: Dict[str, Contact] = {}
    for edge in spec.edges:
        ex, en = select_contacts(edge, placed)
        exits[edge.id] = ex
        entries[edge.id] = en

    # 1b. Rule C: a cross-region hop runs over (or under) the row and descends
    #     into the target from ABOVE, so it enters the target's TOP face, not its
    #     left. Override the entry here where the edge class is known; the router
    #     (route_cross_region) then lands the final vertical on the top face.
    #     Rule G: a back-edge whose target sits against the canvas left (no room
    #     for a >= 1-grid-step gap to its left) also enters the TOP — a left
    #     entry there would land on the target's own edge with no offset.
    obstacles_all = list(placed.values())
    for edge in spec.edges:
        kind = classify_edge(edge, placed)
        if kind == "cross-region":
            entries[edge.id] = (0.5, 0.0)       # top-centre
        elif kind == "back-edge":
            tgt = placed[edge.target]
            left_gap_x = tgt.x - (COL_STEP - ICON_SIZE) // 2
            if left_gap_x < CONTAINER_PAD + GRID:
                entries[edge.id] = (0.5, 0.0)   # no left gap → top-centre (Rule G)
        elif kind == "spine" and spec.compact:
            # Exception I (compact flow only): a spine to a target DIRECTLY BELOW
            # in the same column with nothing between (the summary's lb→app→db
            # vertical chain) drops STRAIGHT — bottom-centre exit into top-centre
            # entry — instead of the exit-right → side-corridor → step-back-left
            # hook. A straight drop removes the excessive hook (a crossing-like
            # defect) and only grazes the source's OWN caption, which reads clean
            # at the summary's wide tier spacing. Scoped to ``compact`` so the
            # dense landscape keeps its caption-avoiding side corridor.
            src = placed[edge.source]
            tgt = placed[edge.target]
            others = [b for nid, b in placed.items()
                      if nid not in (edge.source, edge.target)]
            if _box_directly_below(src, tgt, others):
                exits[edge.id] = (0.5, 1.0)     # bottom-centre
                entries[edge.id] = (0.5, 0.0)   # top-centre → straight drop

    # 2. Spread same-side exits per source in EDGE-MARKER order: the first edge
    #    (lowest marker) keeps the face centre, the 2nd/3rd shift to the quarters
    #    (Req 5.3, "перший по центру"). Group by (source, exit-face).
    order_of = {e.id: i for i, e in enumerate(spec.edges)}
    marker_key = {e.id: e.marker for e in spec.edges}
    def _mk(eid: str):
        m = marker_key[eid]
        return (0, int(m)) if m.isdigit() else (1, m)  # numeric markers first, in order
    by_side: Dict[Tuple[str, str], List[str]] = {}
    for edge in spec.edges:
        side = _exit_side(exits[edge.id])
        by_side.setdefault((edge.source, side), []).append(edge.id)
    for eids in by_side.values():
        eids_sorted = sorted(eids, key=_mk)
        group = [(eid, exits[eid]) for eid in eids_sorted]
        for eid, pt in spread_contacts(group):
            exits[eid] = pt

    # 2b. Spread shared ENTRY faces per target the same way: the first edge (by
    #     marker) entering a given target face keeps its centre, the rest shift
    #     off it, so several arrivals on one face don't stack on one point.
    by_entry: Dict[Tuple[str, str], List[str]] = {}
    for edge in spec.edges:
        face = _entry_face(entries[edge.id])
        by_entry.setdefault((edge.target, face), []).append(edge.id)
    for eids in by_entry.values():
        if len(eids) < 2:
            continue
        eids_sorted = sorted(eids, key=_mk)
        group = [(eid, entries[eid]) for eid in eids_sorted]
        for eid, pt in spread_entries(group):
            entries[eid] = pt

    # 2b2. Rule H — for a long-haul exit that the spread ALREADY shifted OFF the
    #     centre (a 2nd/3rd edge on the side), choose WHICH quarter by its
    #     corridor side: a run rising into an ABOVE-row corridor takes the UPPER
    #     quarter, one dropping into a BELOW-row corridor the LOWER quarter, so
    #     its stub leaves toward the corridor it will run in and two long runs
    #     from one row don't cross each other's stubs (edge 2 "exit higher").
    #     The FIRST edge on the side (kept at centre 0.5 by the spread) is left
    #     untouched — "перший по центру" (edge 1 stays centred).
    for edge in spec.edges:
        kind = classify_edge(edge, placed)
        if kind not in ("cross-region", "back-edge"):
            continue
        ex, ey = exits[edge.id]
        if abs(ey - 0.5) < 1e-9:
            continue  # this is the centred first edge on its side — don't move it
        # A shifted long-haul exit leaves the UPPER quarter ("вийти вище") so its
        # stub sits clear ABOVE the centred first edge's down-path, then it drops
        # into its own (lower/over) corridor lane — the two stubs no longer merge
        # at the glyph (edge 2 above edge 1).
        exits[edge.id] = (ex, _UPPER_QUARTER)

    # 2c. Snap every contact FRACTION so its absolute point lands on the grid
    #     (icon centre 0.5 → x0+39 is off-grid; a grid-snapped waypoint would
    #     then meet it with a 1px kink that skews the arrowhead). After this the
    #     arrow lands exactly on the final grid waypoint — no skew, waypoints
    #     stay on the grid.
    for edge in spec.edges:
        exits[edge.id] = _grid_contact(placed[edge.source], exits[edge.id])
        entries[edge.id] = _grid_contact(placed[edge.target], entries[edge.id])

    # 3. Route every edge on its class, sharing one corridor allocator so no two
    #    runs collide by construction (Req 6).
    allocator = CorridorAllocator()
    placed_edges: List[PlacedEdge] = []
    for edge in spec.edges:
        pts = route_edge(edge, exits[edge.id], entries[edge.id], allocator, obstacles)
        placed_edges.append(
            PlacedEdge(spec=edge, exit=exits[edge.id], entry=entries[edge.id], points=list(pts))
        )

    # 4. Place the right-margin Flow/Legend past the account box (Req 8).
    account = next(
        (containers[c.id] for c in spec.containers if c.kind == "account" and c.id in containers),
        None,
    )
    if account is None:
        # No account container: fall back to the bounding box of all containers /
        # nodes so the legend still sits clear to the right.
        right = max(
            [b.right for b in containers.values()]
            + [placed[n.id].footprint(LABEL_BAND).right for n in spec.nodes],
            default=CONTAINER_PAD,
        )
        account = Box("_envelope", 0, 0, right, 0)
    legend_x, legend_w = place_legend(account, spec.flow_lines)

    return PlacedDiagram(
        spec=spec,
        nodes=placed,
        containers=containers,
        edges=placed_edges,
        legend_x=legend_x,
        legend_w=legend_w,
    )


def _normalise_origin(
    placed: "PlacedDiagram",
    margins: Tuple[int, int] = (CONTAINER_PAD, CONTAINER_PAD),
) -> "PlacedDiagram":
    """Translate the whole placed layout so its top-left sits at ``margins`` (Req 12.4).

    ``margins`` is ``(left_margin, top_margin)``; both default to
    :data:`CONTAINER_PAD` (the historical behaviour — ``min(x) == min(y) ==
    CONTAINER_PAD``, preserved for synthetic specs and callers that pass no
    margins). :func:`layout` passes a larger ``top_margin`` (``CONTAINER_PAD +
    TITLE_BAND``) so the outermost container clears the diagram title band drawn
    above it, matching the reference.

    The account-level edge row (region ``""``) is placed at the base origin and
    then centred / spread relative to the region bands, so a container band or an
    edge waypoint can end up at a **negative** coordinate (the reference regression
    saw ``boundary-account x=-220``). This final pass removes that: it anchors the
    translation on the **node and container boxes** — computing ``dx``/``dy`` so
    their minimum ``x``/``y`` lands exactly at :data:`CONTAINER_PAD` (the checked
    invariant, Req 12.4) — while also guaranteeing that **no edge waypoint** is
    pulled negative: the delta is at least large enough to lift the leftmost /
    topmost waypoint to the origin too, so nothing goes off-canvas after the shift.
    For these diagrams a box is the extreme on each axis, so the box-anchor already
    keeps every waypoint non-negative; the clamp is a safety net.

    Because it is one **uniform translation** applied to every coordinate, it
    preserves all relative geometry: grid alignment, overlaps, padding, direction,
    and corridor separation are unchanged, so an oracle-clean candidate stays clean
    (design.md §12 — "a single deterministic, grid-aligned shift"). Contact-point
    *fractions* (``exit``/``entry``) are unit-square face fractions, not absolute
    coordinates, so they are carried through untouched. ``legend_x`` is an absolute
    x, so it shifts by ``dx`` only.

    Deterministic and grid-aligned: every input coordinate is already a whole
    ``GRID`` multiple and ``CONTAINER_PAD`` is a whole ``GRID`` multiple, so the
    delta is grid-aligned; :func:`_snap` is applied for safety.
    """
    boxes = list(placed.nodes.values()) + list(placed.containers.values())
    if not boxes:  # a degenerate spec with no nodes/containers
        return placed

    left_margin, top_margin = margins
    box_min_x = min(b.x for b in boxes)
    box_min_y = min(b.y for b in boxes)

    # Every absolute coordinate (boxes + waypoints), so the shift can never pull a
    # waypoint off the top/left edge of the canvas.
    all_min_x = box_min_x
    all_min_y = box_min_y
    for pe in placed.edges:
        for px, py in pe.points:
            all_min_x = min(all_min_x, px)
            all_min_y = min(all_min_y, py)

    # Anchor on the box origins (so their min == the requested margin), but never
    # less than the shift needed to keep the leftmost/topmost waypoint non-negative.
    dx = _snap(max(left_margin - box_min_x, -all_min_x))
    dy = _snap(max(top_margin - box_min_y, -all_min_y))
    if dx == 0 and dy == 0:
        return placed  # already at the origin margin — nothing to translate

    nodes = {
        nid: Box(b.id, _snap(b.x + dx), _snap(b.y + dy), b.w, b.h)
        for nid, b in placed.nodes.items()
    }
    containers = {
        cid: Box(b.id, _snap(b.x + dx), _snap(b.y + dy), b.w, b.h)
        for cid, b in placed.containers.items()
    }
    edges = [
        PlacedEdge(
            spec=pe.spec,
            exit=pe.exit,
            entry=pe.entry,
            points=[(_snap(px + dx), _snap(py + dy)) for px, py in pe.points],
        )
        for pe in placed.edges
    ]
    return PlacedDiagram(
        spec=placed.spec,
        nodes=nodes,
        containers=containers,
        edges=edges,
        legend_x=_snap(placed.legend_x + dx),
        legend_w=placed.legend_w,
    )


def layout(spec: DiagramSpec) -> "PlacedDiagram":
    """Turn a coordinate-free ``spec`` into a placed, repaired diagram (Req 9).

    Runs the pure pipeline (:func:`_place_and_route`) then the bounded repair
    loop: on each pass, run the oracle (:func:`_run_oracle`); if it is clean
    (zero blocking findings), return the candidate; otherwise apply one
    deterministic repair per fixable finding (:func:`_repair`) and retry. After
    :data:`MAX_REPAIR_ITERS` passes with a blocking finding still present, raise
    :class:`LayoutError` naming the first unresolved finding (Req 9.3).

    Once the repair loop accepts a candidate, a final :func:`_normalise_origin`
    pass translates the whole layout by one grid-aligned delta so
    ``min(x) == min(y) == CONTAINER_PAD`` — the account-level edge row can never
    pull a coordinate negative (Req 12.4). Normalisation runs **after** repair (a
    pure uniform translation cannot change any relative geometry, so the accepted
    oracle-clean result stays clean, and the repair loop reasons about the
    un-normalised candidate consistently).

    The whole function is deterministic: the pipeline is a pure function of the
    spec, the oracle's finding order is stable, and each repair is a fixed
    transform — so the same spec yields byte-identical geometry every time
    (Req 11.1, 11.4). An over-connected node surfaces as an
    :class:`OverConnectedError` from the pipeline, re-raised as a
    :class:`LayoutError` (unfixable, Req 9.3)."""
    try:
        candidate = _place_and_route(spec)
    except OverConnectedError as exc:
        raise LayoutError(
            f"layout({spec.diagram_id!r}) has an over-connected node — the "
            f"diagram must be split or re-laned: {exc}"
        ) from exc

    # Reserve a title band above the top container so the diagram title never
    # overlaps the container border / its top-left badge (Req 12.4 + title cell).
    margins = (CONTAINER_PAD, CONTAINER_PAD + TITLE_BAND)

    findings = _run_oracle(candidate)
    for _ in range(MAX_REPAIR_ITERS):
        if findings.clean:
            return _normalise_origin(candidate, margins)
        candidate = _repair(candidate, findings)
        findings = _run_oracle(candidate)

    if findings.clean:
        return _normalise_origin(candidate, margins)
    rule, payload = findings.first_unresolved  # type: ignore[misc]
    raise LayoutError(
        f"layout({spec.diagram_id!r}) still has blocking finding {rule!r} on "
        f"{payload!r} after {MAX_REPAIR_ITERS} repair passes"
    )


__all__ = [
    "ICON_SIZE",
    "GRID",
    "COL_STEP",
    "ROW_STEP",
    "CONTAINER_PAD",
    "TITLE_BAND",
    "REGION_STEP",
    "REGION_GAP",
    "SUB_STEP",
    "MERGE_THRESHOLD",
    "MAX_SIDE_EXITS",
    "CROSS_REGION_SPAN",
    "LEGEND_W",
    "LABEL_BAND",
    "Box",
    "Contact",
    "Point",
    "LANES",
    "LANE_INDEX",
    "EDGE_KINDS",
    "NodeSpec",
    "EdgeSpec",
    "ContainerSpec",
    "DiagramSpec",
    "SpecError",
    "OverConnectedError",
    "UnclassifiableEdgeError",
    "_validate_spec",
    "place_nodes",
    "size_containers",
    "centre_block_in_vpc",
    "select_contacts",
    "spread_contacts",
    "CorridorAllocator",
    "CorridorExhaustedError",
    "classify_edge",
    "place_legend",
    "route_straight",
    "route_spine",
    "route_fan_out_row",
    "route_cross_region",
    "route_back_edge",
    "route_edge",
    "ROUTERS",
    "MAX_REPAIR_ITERS",
    "LayoutError",
    "PlacedEdge",
    "PlacedDiagram",
    "OracleFindings",
    "layout",
    "_run_oracle",
    "_repair",
    "_place_and_route",
    "_normalise_origin",
]
