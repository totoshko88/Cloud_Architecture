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
        _SPILL_REACH,
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
        _SPILL_REACH,
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


#: Service scope per diagram role (provider-profiles → Service Scope
#: Classification). ``network`` services need a subnet and are drawn inside the
#: Network Boundary; ``regional`` managed services are reached over endpoints
#: and are drawn inside the region but OUTSIDE the Network Boundary; ``global``
#: services sit at the edge. Keys are the neutral/presentation role names plus
#: the short role aliases the shipped specs use. A role not listed is not
#: judged (a spec may use roles this table has not classified yet).
ROLE_SCOPE: Dict[str, str] = {
    # network-scoped (VPC / VNet / VCN)
    "managed_sql": "network", "sql": "network",
    "managed_k8s": "network", "k8s": "network",
    "compute_instance": "network", "lb": "network",
    "cache": "network", "file_system": "network",
    # regional managed services
    "object_store": "regional", "obj": "regional",
    "message_queue": "regional", "queue": "regional",
    "serverless_fn": "regional", "fn": "regional",
    "secrets_store": "regional", "sec": "regional",
    "llm_platform": "regional",
    # global / edge
    "cdn": "global", "dns": "global", "waf": "global",
}


def role_scope(role: str) -> Optional[str]:
    """Return ``network`` / ``regional`` / ``global`` for ``role`` (else None)."""
    return ROLE_SCOPE.get(role)


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
            # Scope is enforced once the spec models the region level: only then
            # does a regional service have a legal home (the region container,
            # outside the network). A spec without region containers (every
            # synthetic layout spec) keeps its pre-1.10.3 behaviour.
            if (
                target.kind in ("vpc", "az")
                and role_scope(node.role) in ("regional", "global")
                and any(c.kind == "region" and c.region == node.region for c in spec.containers)
            ):
                raise SpecError(
                    f"node {node.id!r} (role {node.role!r}, scope "
                    f"{role_scope(node.role)!r}) declares network-boundary container "
                    f"{node.container!r}; a {role_scope(node.role)} service is not "
                    "deployed in a subnet — declare the region container instead "
                    "(provider-profiles → Service Scope Classification)"
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

#: The lanes drawn OUTSIDE every cloud boundary (diagram-standards → external
#: actors and on-premises sit outside the cloud boundaries).
EXTERNAL_LANES = frozenset({"actors", "on-premises"})


def _grid_ceil(value: float) -> int:
    """Round ``value`` UP to a whole ``GRID`` multiple."""
    return int(-(-value // GRID) * GRID)


#: Account-only compaction (1.10.7, M4), North–South: the primary-axis distance
#: from an external row to the in-account row beside it. Two consecutive rank
#: steps (160) would put the external node's caption on the account border (a
#: straddle), and anything closer than ``_SPILL_REACH`` past the border reads as
#: a tier that spilled out of the account (``container-padding``). So the
#: external row keeps its footprint (icon + caption) plus the spill reach plus
#: one grid step clear of the account's border — the top border carries the
#: caption strip (pad + label band), the bottom border one pad.
_EXTERNAL_TOP_STEP = _grid_ceil(
    ICON_SIZE + LABEL_BAND + _SPILL_REACH + CONTAINER_PAD + CONTAINER_LABEL_BAND + GRID
)
_EXTERNAL_BOTTOM_STEP = _grid_ceil(
    ICON_SIZE + LABEL_BAND + _SPILL_REACH + CONTAINER_PAD + GRID
)


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
    # 1.10.3: a VPC-direct service row narrower than the region's widest AZ row
    # is CENTRED over it (the way vendor references draw a load balancer that
    # spans its zones). A row pinned to column 0 put every top-entry drop into
    # it right under the left-aligned region / VPC captions.
    widest: Dict[str, int] = {}
    for (_band, region, _sub), members in groups.items():
        if any(kind_of.get(m.container) == "az" for m in members):
            widest[region] = max(widest.get(region, 0), len(members))
    within: Dict[str, Tuple[int, int]] = {}
    for (_band, region, sub), members in groups.items():
        offset = 0
        if all(kind_of.get(m.container) == "vpc" for m in members):
            offset = max(0, (widest.get(region, 0) - len(members)) // 2)
        for col, n in enumerate(sorted(members, key=lambda m: (LANE_INDEX[m.lane], m.slot))):
            within[n.id] = (col + offset, sub)
    return within


#: One corridor lane reserved below a container's caption strip (1.10.6), two
#: grid steps — the allocator's lane stride.
TOP_LANE = 2 * GRID


def _top_lane_containers(spec: DiagramSpec) -> set:
    """Return the ids of containers whose first row needs a lane below the caption.

    A container's top padding is its caption strip plus one pad (60px), and a
    route entering a first-row node from ABOVE needs a full stair (30px) over the
    node — so a loop that reaches the node from the side (a back-edge from a node
    on the same row, or from the regional column beside the box) has exactly one
    line left for its horizontal run: the caption strip's bottom edge. That run
    slices the caption (``edge-crosses-container-label`` on ``eks → alb`` and
    ``api-gateway → load-balancer``), and no route variant avoids it, because the
    strip and the stair together use the whole band.

    diagram-standards' tie-breaker settles it: *widen, never narrow, the
    corridor*. Such a container reserves :data:`TOP_LANE` between its caption
    strip and its first row (``size_containers``), and its band starts that much
    lower (``_band_packing``), so the container's top border does not move and
    nothing above it is disturbed.

    A container qualifies when an edge TARGETS a node on its first row from a
    source in the SAME region that does not arrive from above: a banded node on
    the same band to the target's right or below it, or a regional node (the
    regional column stands beside the network block). An account-level source
    sits above the region and drops in through the band above it, so it does not
    qualify. Empty unless the spec enables ``caption_lanes`` — the scored
    placement loop's ``caption-lane`` move, kept only when the finished diagram
    scores better. A pure function of the spec."""
    if not getattr(spec, "caption_lanes", False):
        return set()
    kind_of = {c.id: c.kind for c in spec.containers}
    band_of = _node_az_band(spec)
    within = _band_within(spec)
    nodes = {n.id: n for n in spec.nodes}
    top_sub: Dict[Tuple[str, int], int] = {}
    for n in spec.nodes:
        if n.id in within and n.container is not None:
            key = (n.container, band_of[n.id])
            top_sub[key] = min(top_sub.get(key, within[n.id][1]), within[n.id][1])
    out: set = set()
    # A spec whose region nodes declare no container (the compact HA summary) is
    # judged by lane: a region's first row is its lowest lane, and its box is the
    # region's single leaf container.
    leaves = _leaf_region_containers(spec)
    free_first: Dict[str, int] = {}
    for n in spec.nodes:
        if n.region and n.container is None and n.id not in within:
            free_first[n.region] = min(free_first.get(n.region, LANE_INDEX[n.lane]),
                                       LANE_INDEX[n.lane])
    if spec.axis == "north-south":
        for e in spec.edges:
            s, t = nodes.get(e.source), nodes.get(e.target)
            if s is None or t is None or t.id in within or t.container is not None:
                continue
            leaf = leaves.get(t.region) or []
            if len(leaf) != 1 or LANE_INDEX[t.lane] != free_first.get(t.region):
                continue
            if not s.region:
                if s.lane not in ("actors", "on-premises"):
                    out.add(leaf[0].id)
            elif s.region == t.region and s.container is None and (
                LANE_INDEX[s.lane] > LANE_INDEX[t.lane]
                or (s.lane == t.lane and s.slot > t.slot)
            ):
                out.add(leaf[0].id)
    for e in spec.edges:
        s, t = nodes.get(e.source), nodes.get(e.target)
        if s is None or t is None or t.id not in within or t.container is None:
            continue
        if within[t.id][1] != top_sub.get((t.container, band_of[t.id])):
            continue                                   # not the container's first row
        if not s.region:
            # An account-level source (the edge row above the regions) reaches the
            # row from above; when it sits to the side it loops into the target's
            # top through the band the caption occupies (the HA summary's DNS).
            if s.lane in ("actors", "on-premises"):
                continue
            out.add(t.container)
            continue
        if s.region != t.region:
            continue                                   # another region: cross-region
        if s.id in within:
            if band_of[s.id] != band_of[t.id]:
                continue
            s_col, s_sub = within[s.id]
            t_col, t_sub = within[t.id]
            if s_sub == t_sub and s_col <= t_col:
                continue                               # a forward hop along the row
        elif kind_of.get(s.container) != "region":
            continue
        out.add(t.container)
    return out


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
    # 1.10.6: a band whose container reserves a lane below its caption strip
    # (``_top_lane_containers``) starts that lane lower, so the container's top
    # border stays where it was and the lane opens INSIDE it.
    lane_containers = _top_lane_containers(spec)
    band_lane: Dict[int, int] = {}
    for n in spec.nodes:
        if n.container in lane_containers:
            band_lane[band_of[n.id]] = TOP_LANE

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
            start += band_lane.get(band, 0)
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
            gap += band_lane.get(band, 0)
            start = _snap(prev_end + gap)
        band_start[band] = start
        # A horizontal band is (max_sub_row + 1) rows tall (main row + any
        # sub-rows), each ROW_STEP apart, plus the icon + label footprint.
        rows = sub_rows_by_band.get(band, 0)
        content_height = rows * ROW_STEP + ICON_SIZE + LABEL_BAND
        prev_end = start + content_height
        prev_has_box = has_box
    return band_start, band_min_lane


#: Prices for placing an UNANCHORED regional node next to its placed neighbours
#: (1.10.6, REVIEW.md D24). A candidate cell is priced by the route every incident
#: edge would need: the Manhattan distance between the two node origins plus a
#: penalty per shape the router would have to draw for it. A straight, forward,
#: unobstructed run costs only its length, so a node lands where its edges are
#: straight drops or level hops — the shape a reviewer drags it to by hand (the
#: ``agent-task-queue`` dragged under its Lambda, the OCI ``streaming-events``
#: dragged from the column bottom up to the row its feeds arrive on).
CELL_TURN = 80        # one corner the route must make
CELL_BLOCKED = 400    # aligned, but another node stands on the straight line
CELL_BACK = 250       # target left of its source → a back-edge loop
CELL_UP = 400         # target above its source → against the North–South flow
CELL_ABOVE = 40       # a row above the region's first banded row (grows it up)
CELL_EXTRA_COL = 300  # a third regional column (widens the region)
CELL_SPLIT = 400      # the cell sits on another placed pair's straight line

#: Regional column offsets past the widest banded column: inner, outer, extra.
_REGIONAL_COLS = (1, 2, 3)

#: How far above the region's first banded row a regional entry point stands
#: when it is placed directly over its network-boundary anchor (1.10.6): its
#: footprint (icon + caption) plus one pad must clear the network boundary's own
#: top band (caption strip + pad), on the grid — 78 + 30 + 30 + 30 + 30 → 200.
FEEDER_RISE = 200


def _link_cost(
    s: Tuple[int, int], t: Tuple[int, int], occupied: List[Tuple[int, int]]
) -> int:
    """Price one edge ``s → t`` between two node origins (see :data:`CELL_TURN`).

    The corner count is the route the router must draw under the directional
    contract (exit right/bottom, enter left/top): a forward level hop or a
    straight drop needs none, a hop down-right (or up-right into the left face)
    one, a back-edge two, and a target straight above three — a hook over its
    own top."""
    dx, dy = t[0] - s[0], t[1] - s[1]
    cost = abs(dx) + abs(dy)
    if (dx > 0 and dy == 0) or (dx == 0 and dy > 0):
        turns = 0
    elif dx > 0:
        turns = 1
    elif dx == 0:
        turns = 3
    else:
        turns = 2
    cost += turns * CELL_TURN
    if dx == 0 or dy == 0:
        lo_x, hi_x = sorted((s[0], t[0]))
        lo_y, hi_y = sorted((s[1], t[1]))
        for ox, oy in occupied:
            if (ox, oy) in (s, t):
                continue
            if dx == 0 and ox == s[0] and lo_y < oy < hi_y:
                cost += CELL_BLOCKED
                break
            if dy == 0 and oy == s[1] and lo_x < ox < hi_x:
                cost += CELL_BLOCKED
                break
    if dx < 0:
        cost += CELL_BACK
    if dy < 0:
        cost += CELL_UP
    return cost


def _place_loose_regional(
    loose: list,
    edges: tuple,
    known: Dict[str, Tuple[int, int]],
    col_x: Dict[int, int],
    rows: List[int],
    above_row: Optional[int],
    default_col: int,
    fallback_y: int,
) -> Dict[str, Tuple[int, int]]:
    """Place unanchored regional nodes beside their placed neighbours (1.10.6).

    ``loose`` are the region's regional nodes with no banded anchor, in ``slot``
    order; ``known`` maps every already-placed node id (the region's banded and
    anchored regional nodes plus account-level nodes) to its origin. Returns
    ``{node_id: (column_offset, y)}``.

    **Order (depth-first).** The first edge in declared order that links a placed
    node to a loose one picks the next node to place; after each placement its own
    first loose neighbour (edge order) is placed next, so a node's chain stays
    together (``bedrock → secrets`` is placed right after ``bedrock``, before the
    hub's next branch). A loose node with no placed neighbour at all (an isolated
    ``queue → worker → secrets`` chain) falls back to the pre-1.10.6 stacking: the
    next free row of ``default_col`` below everything, one ``ROW_STEP`` apart.

    **Cell.** Every free cell of the three regional columns on the candidate
    ``rows`` (plus ``above_row``, the row above the region's first banded row,
    when the caller allows it) is priced by :func:`_link_cost` over the node's
    edges to placed neighbours, plus :data:`CELL_SPLIT` when the cell would sit on
    the straight line of an already-placed pair, :data:`CELL_EXTRA_COL` for the
    third column and :data:`CELL_ABOVE` for the row above. The cheapest cell wins;
    ties prefer the inner column, then the higher row. A pure, deterministic
    function of its inputs: every iteration is over declared or sorted order.
    """
    pos: Dict[str, Tuple[int, int]] = dict(known)
    out: Dict[str, Tuple[int, int]] = {}
    loose_ids = [m.id for m in loose]
    remaining = list(loose_ids)
    placed_stack: List[str] = []

    def _neighbours(nid: str) -> List[Tuple[int, "object"]]:
        return [
            (i, e) for i, e in enumerate(edges) if nid in (e.source, e.target)
        ]

    def _other(e, nid: str) -> str:
        return e.target if e.source == nid else e.source

    def _free(x: int, y: int) -> bool:
        return all(not (ox == x and abs(oy - y) < ROW_STEP) for ox, oy in pos.values())

    base_rows = set(rows) | ({above_row} if above_row is not None else set())
    min_row = min(base_rows) if base_rows else fallback_y
    regional_xs = set(col_x.values())

    def _candidate_rows() -> List[int]:
        # The lattice rows, plus one ROW_STEP either side of every node already in
        # a regional column — so a chain grows in straight drops from a node the
        # fallback stacked off the lattice (an AZ band row is not on it).
        extra = {
            y + d * ROW_STEP
            for (x, y) in pos.values() if x in regional_xs
            for d in (-1, 1)
        }
        return sorted(r for r in base_rows | extra if r >= min_row)

    def _cell_cost(nid: str, x: int, y: int) -> int:
        occupied = list(pos.values()) + [(x, y)]
        cost = 0
        for _i, e in _neighbours(nid):
            other = _other(e, nid)
            if other not in pos:
                continue
            s, t = ((x, y), pos[other]) if e.source == nid else (pos[other], (x, y))
            cost += _link_cost(s, t, occupied)
        for e in edges:
            if nid in (e.source, e.target):
                continue
            a, b = pos.get(e.source), pos.get(e.target)
            if a is None or b is None:
                continue
            if a[0] == b[0] == x and min(a[1], b[1]) < y < max(a[1], b[1]):
                cost += CELL_SPLIT
            elif a[1] == b[1] == y and min(a[0], b[0]) < x < max(a[0], b[0]):
                cost += CELL_SPLIT
        return cost

    while remaining:
        pick: Optional[str] = None
        for anchor in reversed(placed_stack):          # depth-first: keep a chain together
            for _i, e in _neighbours(anchor):
                other = _other(e, anchor)
                if other in remaining:
                    pick = other
                    break
            if pick is not None:
                break
        if pick is None:                                # next edge from the placed set
            for e in edges:
                for a, b in ((e.source, e.target), (e.target, e.source)):
                    if a in pos and b in remaining:
                        pick = b
                        break
                if pick is not None:
                    break
        if pick is None:                                # isolated chain: stack below
            pick = remaining[0]
            x = col_x[default_col]
            y = fallback_y
            while not _free(x, y):
                y += ROW_STEP
            out[pick] = (default_col, y)
        else:
            best: Optional[Tuple[int, int, int]] = None
            candidate_rows = _candidate_rows()
            for col in _REGIONAL_COLS:
                x = col_x[col]
                for y in candidate_rows:
                    if not _free(x, y):
                        continue
                    cost = _cell_cost(pick, x, y)
                    if col == _REGIONAL_COLS[-1]:
                        cost += CELL_EXTRA_COL
                    if above_row is not None and y == above_row:
                        cost += CELL_ABOVE
                    key = (cost, col, y)
                    if best is None or key < best:
                        best = key
            assert best is not None  # rows always extend below every placed node
            out[pick] = (best[1], best[2])
        pos[pick] = (col_x[out[pick][0]], out[pick][1])
        remaining.remove(pick)
        placed_stack.append(pick)
    return out


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
    #
    # 1.10.7 (M4): an ACCOUNT-ONLY spec (an account container and no other — a
    # serverless account, or anything ``rule-engine-draw`` emits) compacts the
    # same way, and also closes the gaps in each lane's slots: the occupied
    # slots of a lane's non-banded nodes take consecutive ranks 0..k-1 in their
    # declared order. An author's slot gap (6 → 9) or an empty lane then no
    # longer leaves an empty column or row band in the account box. Every spec
    # that declares a region container keeps absolute placement byte-unchanged.
    # "Account-only" means the account is the ONLY container kind: a spec with
    # vpc / az boxes but no region container (the pre-1.10.3 nesting) sizes its
    # zone boxes around tier bands, and compacting those bands would stack the
    # zone boxes on top of each other.
    account_only = (
        any(c.kind == "account" for c in spec.containers)
        and all(c.kind == "account" for c in spec.containers)
    )
    compact = spec.compact or account_only
    #: Primary-axis offset of each occupied lane when compacting: its rank times
    #: the primary step, except that on an account-only North–South diagram an
    #: external lane (actors / on-premises) next to an in-account lane is held
    #: ``_EXTERNAL_TOP_STEP`` / ``_EXTERNAL_BOTTOM_STEP`` away, so the external
    #: row stays clear of the account border (no straddle, no spill). A spec that
    #: is not account-only gets exactly ``rank * primary_step``.
    lane_offset: Dict[int, int] = {}
    if compact:
        occupied = sorted({LANE_INDEX[n.lane] for n in spec.nodes})
        offset, prev = 0, None
        for li in occupied:
            if prev is not None:
                step = primary_step
                prev_ext, cur_ext = LANES[prev] in EXTERNAL_LANES, LANES[li] in EXTERNAL_LANES
                if account_only and spec.axis == "north-south" and prev_ext != cur_ext:
                    step = max(step, _EXTERNAL_TOP_STEP if prev_ext else _EXTERNAL_BOTTOM_STEP)
                offset += step
            lane_offset[li] = offset
            prev = li
    # 1.10.3: REGIONAL services (declared members of a ``region`` container)
    # stand in their own column right of the region's network block — inside
    # the region, outside the VPC (provider-profiles → Service Scope). The
    # column starts one column past the widest banded row plus two pads, so the
    # VPC's own right padding and a vertical corridor fit between them.
    #
    # Rows are the region's OWN banded rows (so an edge between the network and
    # the column runs straight along a row). Assignment is deterministic:
    #   * a regional node linked to exactly ONE banded row sits in the INNER
    #     column, on that row;
    #   * a node linked to SEVERAL banded rows (an object store written by every
    #     zone) sits in the OUTER column, on its topmost linked row — its feeds
    #     rise and fall in the gap beyond the inner column, so they never cut the
    #     single-row feeds that end at the inner column;
    #   * an unanchored node (no banded neighbour) is placed next to the nodes it
    #     IS linked to — a regional hub, or an account-level front door above the
    #     region — on the cheapest free cell of the regional columns
    #     (:func:`_place_loose_regional`, 1.10.6): directly below its source when
    #     that drop is clear, level beside it otherwise, a row above the region's
    #     first banded row when its feed arrives from above. Only a node with no
    #     placed neighbour at all (an isolated queue → worker → secrets chain)
    #     still stacks below everything, one ROW_STEP apart, as straight drops.
    # When one of the two columns is empty the other takes the inner position.
    region_direct = {
        n.id for n in spec.nodes
        if n.container is not None and kind_of.get(n.container) == "region"
    }
    regional_col_x: Dict[str, int] = {}
    regional_y: Dict[str, int] = {}
    #: Regional column offset past the widest banded column (1 inner, 2 outer,
    #: 3 extra), per regional node; 0 for a node placed at an absolute x.
    regional_col: Dict[str, int] = {}
    #: 1.10.6: regional nodes placed directly above a banded anchor (absolute x).
    regional_abs_x: Dict[str, int] = {}

    # 1.10.7 (M4): per-lane slot ranks for an account-only spec (see above).
    # Only non-banded, non-region-direct nodes are ranked; every other node keeps
    # its declared slot.
    slot_rank: Dict[str, int] = {}
    if account_only:
        lane_slots: Dict[Tuple[str, str], List[int]] = {}
        free_nodes = [
            n for n in spec.nodes
            if n.id not in region_direct
            and not (n.container is not None and kind_of.get(n.container) in banded_kinds)
        ]
        for n in free_nodes:
            lane_slots.setdefault((n.lane, n.region), []).append(n.slot)
        rank_of = {
            key: {s: r for r, s in enumerate(sorted(set(slots)))}
            for key, slots in lane_slots.items()
        }
        slot_rank = {n.id: rank_of[(n.lane, n.region)][n.slot] for n in free_nodes}

    def _free_origin(node) -> Tuple[int, int]:
        """The non-banded (lane → primary, slot → secondary) origin of ``node``."""
        lane_i = LANE_INDEX[node.lane]
        primary = lane_offset[lane_i] if compact else lane_i * primary_step
        slot = slot_rank.get(node.id, node.slot)
        if spec.axis == "north-south":
            return (base_x + slot * COL_STEP + node.sub * SUB_STEP,
                    base_y + primary)
        return (base_x + primary,
                base_y + slot * ROW_STEP + node.sub * SUB_STEP)

    if region_direct and spec.axis == "north-south":
        banded_y: Dict[str, int] = {}
        banded_x: Dict[str, int] = {}
        for n in spec.nodes:
            if n.id in band_within and n.container is not None:
                regional_col_x[n.region] = max(
                    regional_col_x.get(n.region, 0), band_within[n.id][0]
                )
                banded_y[n.id] = base_y + band_start[az_band[n.id]] + band_within[n.id][1] * ROW_STEP
                banded_x[n.id] = base_x + band_within[n.id][0] * COL_STEP
        # Account-level / external nodes keep their lane-grid origin; they are
        # known positions a regional node may be placed next to.
        free_xy = {
            n.id: _free_origin(n) for n in spec.nodes
            if n.region == "" and n.id not in band_within and n.id not in region_direct
        }
        region_of = {n.id: n.region for n in spec.nodes}
        by_region: Dict[str, list] = {}
        for n in spec.nodes:
            if n.id in region_direct:
                by_region.setdefault(n.region, []).append(n)
        anchored_count: Dict[str, int] = {}
        for region, members in by_region.items():
            member_ids = {m.id for m in members}
            anchors: Dict[str, List[int]] = {m.id: [] for m in members}
            for e in spec.edges:
                for reg, other in ((e.source, e.target), (e.target, e.source)):
                    if reg in member_ids and other in banded_y and region_of.get(other) == region:
                        if banded_y[other] not in anchors[reg]:
                            anchors[reg].append(banded_y[other])
            ordered = sorted(members, key=lambda m: (LANE_INDEX[m.lane], m.slot, m.sub, m.id))
            single = [m for m in ordered if len(anchors[m.id]) == 1]
            multi = [m for m in ordered if len(anchors[m.id]) >= 2]
            # Loose nodes stack by ``slot`` first: the column is one vertical
            # stack, so lanes carry no position there and ``slot`` is the
            # author's order down the stack (lane breaks ties).
            loose = sorted(
                (m for m in members if not anchors[m.id]),
                key=lambda m: (m.slot, LANE_INDEX[m.lane], m.sub, m.id),
            )
            # 1.10.6: a single-anchored regional node that only FEEDS its anchor
            # on the region's first banded row (an API front door in front of
            # the load balancer) stands directly ABOVE that anchor — in the
            # band between the region's caption and the network boundary, which
            # is inside the region and outside the VPC, as its scope requires.
            # Its feed is then a straight drop instead of a back-edge looping in
            # from the regional column. Free cell and room above required.
            region_rows_all = sorted(
                {banded_y[n.id] for n in spec.nodes if n.id in banded_y and n.region == region}
            )
            first_banded = region_rows_all[0] if region_rows_all else None
            # Directly above a banded node the feeder must also clear the network
            # boundary's own top band (caption strip + pad) with its footprint.
            feeder_y = None if first_banded is None else first_banded - FEEDER_RISE
            above_ok = feeder_y is not None and all(
                feeder_y - (CONTAINER_PAD + CONTAINER_LABEL_BAND)
                >= y + ICON_SIZE + LABEL_BAND + 2 * CONTAINER_PAD
                for (_x, y) in free_xy.values() if y < first_banded
            )
            feeder: List = []
            for m in list(single):
                if any(e.target == m.id for e in spec.edges):
                    continue                    # not an entry point of the flow
                partners = [
                    (e.source, e.target) for e in spec.edges
                    if m.id in (e.source, e.target)
                    and (e.target if e.source == m.id else e.source) in banded_y
                    and region_of.get(e.target if e.source == m.id else e.source) == region
                ]
                anchor_ids = {t for s, t in partners if s == m.id}
                if (above_ok and partners and all(s == m.id for s, _t in partners)
                        and len(anchor_ids) == 1
                        and banded_y[next(iter(anchor_ids))] == first_banded):
                    feeder.append((m, next(iter(anchor_ids))))
            taken_above: set = set()
            for m, anchor in feeder:
                if banded_x[anchor] in taken_above:
                    continue
                taken_above.add(banded_x[anchor])
                regional_y[m.id] = feeder_y
                regional_abs_x[m.id] = banded_x[anchor]
                regional_col[m.id] = 0
                single.remove(m)
            two_cols = bool(single) and bool(multi or loose)
            inner_used: set = set()
            for m in single:
                # Two single-row nodes anchored on one row cannot share a cell:
                # the later one (lane/slot order) steps down to the next free row.
                y = anchors[m.id][0]
                while y in inner_used:
                    y += ROW_STEP
                inner_used.add(y)
                regional_y[m.id] = y
                regional_col[m.id] = 1
            used: set = set()
            for m in multi:
                y = min(anchors[m.id])
                while y in used:
                    y += ROW_STEP
                regional_y[m.id] = y
                used.add(y)
                regional_col[m.id] = 2 if two_cols else 1
            if not two_cols:
                used |= {regional_y[m.id] for m in single}
            nxt = (max(used) + ROW_STEP) if used else (
                base_y + (min(band_start.values()) if band_start else 0))
            if loose:
                # 1.10.6: place the unanchored nodes beside their placed
                # neighbours instead of stacking them all under the column.
                col_x = {
                    off: base_x + (regional_col_x.get(region, 0) + off) * COL_STEP
                    + 2 * CONTAINER_PAD
                    for off in _REGIONAL_COLS
                }
                known: Dict[str, Tuple[int, int]] = dict(free_xy)
                for n in spec.nodes:
                    if n.id in banded_x and n.region == region:
                        known[n.id] = (banded_x[n.id], banded_y[n.id])
                for m in single + multi:
                    known[m.id] = (col_x[regional_col[m.id]], regional_y[m.id])
                for m, _anchor in feeder:
                    if m.id in regional_abs_x:
                        known[m.id] = (regional_abs_x[m.id], regional_y[m.id])
                region_rows = sorted(
                    {banded_y[n.id] for n in spec.nodes
                     if n.id in banded_y and n.region == region}
                    | {regional_y[m.id] for m in single + multi}
                )
                feeder_rows = {regional_y[m.id] for m, _a in feeder if m.id in regional_abs_x}
                first_row = region_rows[0] if region_rows else nxt
                last_row = max(region_rows + [nxt])
                rows = sorted(
                    set(region_rows) | feeder_rows
                    | {first_row + k * ROW_STEP
                       for k in range(0, (last_row - first_row) // ROW_STEP + len(loose) + 2)}
                )
                # The row above the first banded row is usable only when the
                # region can grow up into it and still clear every account-level
                # node above it (its footprint) by two pads — the region's caption
                # strip and one free corridor lane.
                above = first_row - ROW_STEP
                above_top = above - (CONTAINER_PAD + CONTAINER_LABEL_BAND)
                ceiling = max(
                    (y + ICON_SIZE + LABEL_BAND for (_x, y) in free_xy.values() if y < first_row),
                    default=None,
                )
                above_row = above if (
                    region_rows and (ceiling is None or above_top >= ceiling + 2 * CONTAINER_PAD)
                ) else None
                cells = _place_loose_regional(
                    loose, spec.edges, known, col_x, rows, above_row,
                    default_col=2 if two_cols else 1, fallback_y=nxt,
                )
                for m in loose:
                    regional_col[m.id], regional_y[m.id] = cells[m.id]
            anchored_count[region] = sum(1 for m in members if anchors[m.id])

        # Peer regions are mirror images (Req 3.3): a passive region whose
        # peers carry no edges must not get a different arrangement. Every
        # region copies the (row, column) of its structural peer — same
        # (role, lane, slot, sub) — from the region with the most edge anchors.
        if anchored_count:
            ref = max(sorted(anchored_count), key=lambda r: anchored_count[r])
            ref_pos = {
                (m.role, m.lane, m.slot, m.sub): (
                    regional_y[m.id], regional_col[m.id], regional_abs_x.get(m.id))
                for m in by_region[ref]
            }
            for region, members in by_region.items():
                for m in members:
                    key = (m.role, m.lane, m.slot, m.sub)
                    if key in ref_pos:
                        regional_y[m.id], regional_col[m.id], abs_x = ref_pos[key]
                        if abs_x is None:
                            regional_abs_x.pop(m.id, None)
                        else:
                            regional_abs_x[m.id] = abs_x

    # 1.10.6: a region of container-free nodes whose box reserves a caption lane
    # (``_top_lane_containers``) starts its rows one lane lower, so the box's top
    # border stays put and the lane opens inside it.
    lane_ids = _top_lane_containers(spec)
    free_lane_shift: Dict[str, int] = {
        region: TOP_LANE
        for region, leaf in _leaf_region_containers(spec).items()
        if len(leaf) == 1 and leaf[0].id in lane_ids
        and any(n.region == region and n.container is None for n in spec.nodes)
    }

    placed: Dict[str, Box] = {}
    for node in spec.nodes:
        lane_i = LANE_INDEX[node.lane]
        banded = node.container is not None and kind_of.get(node.container) in banded_kinds
        if node.id in regional_y:
            col = regional_col_x.get(node.region, 0) + regional_col[node.id]
            x = regional_abs_x.get(node.id, base_x + col * COL_STEP + 2 * CONTAINER_PAD)
            y = regional_y[node.id]
        elif banded and spec.axis == "north-south":
            # Horizontal band: column across (x), tier band + sub-row down (y).
            band = az_band[node.id]
            col, sub_row = band_within[node.id]
            x = base_x + col * COL_STEP
            y = base_y + band_start[band] + sub_row * ROW_STEP
        else:
            # Non-banded, or the left→right axis: lane → primary, slot →
            # secondary, sub nudges secondary. In compact mode the lane's
            # consecutive rank replaces its absolute index on the primary axis.
            primary_offset = lane_offset[lane_i] if compact else lane_i * primary_step
            slot = slot_rank.get(node.id, node.slot)
            if spec.axis == "north-south":
                x = base_x + slot * COL_STEP + node.sub * SUB_STEP
                y = base_y + primary_offset + free_lane_shift.get(node.region, 0)
            elif spec.axis == "left-right":
                x = base_x + primary_offset
                y = base_y + slot * ROW_STEP + node.sub * SUB_STEP
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
