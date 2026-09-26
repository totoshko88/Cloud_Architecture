"""Coordinate-free declarations for the HA multi-region golden **pair**.

This module is the declarative source of truth for the topology of the two
shipped HA diagrams — the ``flow`` summary and the ``landscape`` as-built — as
:class:`~rule_engine.layout_engine.DiagramSpec` values with **no coordinates**.
It encodes exactly the same nodes, edges, and containers the hand-authored
coordinate tables in ``scripts/ha_multiregion_common.py`` express today; only
the *geometry* (node x/y, container boxes, edge waypoints) is dropped, because
that is the layout engine's output, never its input (Req 1.5).

Task 11 scope: author :data:`SUMMARY_SPEC` and :data:`LANDSCAPE_SPEC` and prove
both pass ``layout_engine._validate_spec``. Task 12 wires them into
``build_summary`` / ``build_landscape`` via ``layout_engine.layout(...)`` and
removes the coordinate tables; the ``ProviderSkin`` (icons + labels) is
unchanged.

Topology fidelity (must match ``ha_multiregion_common.py``):

* **Summary** — 9 nodes: ``dns`` (account-level) fanning out to two mirror
  regions, each ``lb → app → db`` with an ``obj`` object store, plus the
  cross-region DB replication edge. Two network-boundary frames (``nb_a`` /
  ``nb_b``). Edges ``s1``..``s9``. Class ``flow``, north-south axis (the flow
  reads DOWN each region column, the two regions side-by-side, DNS centred above).
* **Landscape** — 34 nodes: an account-level edge row (waf / dns / cdn / audit)
  above two mirror region VPCs, each VPC carrying a service row and two
  availability zones (main row + api/mon sub-row). Containers
  account ⊃ vpc-a/vpc-b ⊃ az-a1/az-a2/az-b1/az-b2. Edges ``l1``..``l12``. Class
  ``landscape`` → north-south axis.

Lane assignments are chosen to be faithful to the tiering (lb → edge/router,
queue → async, fn/app → workers, cache/secrets → platform, db/obj → data) and
so that every ``(lane, region, slot)`` placement key is unique — the invariant
``_validate_spec`` enforces.
"""

from __future__ import annotations

try:  # package-relative import when used as ``rule_engine.ha_multiregion_spec``
    from .layout_engine import (
        ContainerSpec,
        DiagramSpec,
        EdgeSpec,
        NodeSpec,
    )
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from layout_engine import (  # type: ignore[no-redef]
        ContainerSpec,
        DiagramSpec,
        EdgeSpec,
        NodeSpec,
    )


# ---------------------------------------------------------------------------
# SUMMARY (flow class, 9 nodes) — north-south axis.
# ---------------------------------------------------------------------------
# dns is account-level (region "") and fans out to two mirror regions. Within a
# region the tier progression lb → app → db reads DOWN the column (the lane
# order router → workers → data maps to top→bottom on the north-south axis);
# the object store shares the data lane at a
# distinct slot. The two network-boundary frames (nb_a / nb_b) are the region
# VPC containers. Roles match the tables: dns→dns, lb→lb, app→k8s (managed_k8s),
# db→sql (managed_sql), obj→obj (object_store).

_SUMMARY_NODES = (
    # account-level DNS (outside both region frames).
    NodeSpec(id="dns", role="dns", lane="edge", region="", slot=0),
    # region A: lb → app → db, plus obj object store.
    NodeSpec(id="lb_a", role="lb", lane="router", region="a", slot=0),
    NodeSpec(id="app_a", role="k8s", lane="workers", region="a", slot=0),
    NodeSpec(id="db_a", role="sql", lane="data", region="a", slot=0),
    NodeSpec(id="obj_a", role="obj", lane="data", region="a", slot=1),
    # region B mirror.
    NodeSpec(id="lb_b", role="lb", lane="router", region="b", slot=0),
    NodeSpec(id="app_b", role="k8s", lane="workers", region="b", slot=0),
    NodeSpec(id="db_b", role="sql", lane="data", region="b", slot=0),
    NodeSpec(id="obj_b", role="obj", lane="data", region="b", slot=1),
)

_SUMMARY_EDGES = (
    EdgeSpec(id="s1", source="dns", target="lb_a", marker="1"),
    EdgeSpec(id="s2", source="lb_a", target="app_a", marker="2"),
    EdgeSpec(id="s3", source="app_a", target="db_a", marker="3"),
    EdgeSpec(id="s4", source="app_a", target="obj_a", marker="4"),
    EdgeSpec(id="s5", source="dns", target="lb_b", marker="5", dashed=True),
    EdgeSpec(id="s6", source="lb_b", target="app_b", marker="6"),
    EdgeSpec(id="s7", source="app_b", target="db_b", marker="7"),
    EdgeSpec(id="s8", source="app_b", target="obj_b", marker="8"),
    EdgeSpec(id="s9", source="db_a", target="db_b", marker="9", dashed=True),
)

# The two region (network-boundary) frames. No account container in the summary
# — the frames are the only boundaries, and dns sits outside them.
_SUMMARY_CONTAINERS = (
    ContainerSpec(id="nb_a", kind="vpc", region="a", parent=None, label_key="nb_a"),
    ContainerSpec(id="nb_b", kind="vpc", region="b", parent=None, label_key="nb_b"),
)

_SUMMARY_FLOW = (
    "Flow",
    "1. DNS routes users to the active (primary) region",
    "2. Primary load balancer forwards to the app tier",
    "3. App tier reads/writes the primary database",
    "4. App tier stores objects in the primary object store",
    "5. DNS holds the passive region on standby (health-checked)",
    "6. Passive load balancer forwards to its app tier",
    "7. Passive app tier uses its regional database",
    "8. Passive app tier uses its regional object store",
    "9. Primary database replicates cross-region to the passive database",
)

SUMMARY_SPEC = DiagramSpec(
    diagram_id="ha-summary",
    diagram_name="ha-multiregion-summary",
    # North–south: the flow reads DOWN each region column (lb → app → db) with
    # the two regions side-by-side and DNS centred above them — the composition
    # of the hand-drawn summary reference. (Was left-right, which laid the regions
    # out as full-width horizontal bands.)
    axis="north-south",
    nodes=_SUMMARY_NODES,
    edges=_SUMMARY_EDGES,
    containers=_SUMMARY_CONTAINERS,
    flow_lines=_SUMMARY_FLOW,
    title="ha-multiregion-summary | 2026-09-23 | v1",
    # Compact the flow: lb → app → db sit on three adjacent rows (no empty tier
    # bands between router/workers/data), matching the tight vertical columns of
    # the summary reference.
    compact=True,
)


# ---------------------------------------------------------------------------
# LANDSCAPE (landscape class, 34 nodes) — north-south axis.
# ---------------------------------------------------------------------------
# lane index → row (top→bottom), slot → column (left→right), sub → sub-row.
# The account-level edge row (waf / dns / cdn / audit) sits in the `edge` lane
# above both region VPCs. Each region carries a service row (lb → queue → fn →
# secrets) and two availability zones; the AZ main rows hold app / cache / db /
# obj and the api/mon sub-rows use `sub=1`. Lane assignments track the tiering
# (lb→router, queue→async, fn/app/api→workers, cache/secrets→platform,
# db/obj→data) and every (lane, region, slot) key is unique per region.

_LANDSCAPE_NODES = (
    # account-level edge row (region "") — outside the region VPCs.
    NodeSpec(id="wafedge", role="waf", lane="edge", region="", slot=0),
    NodeSpec(id="dns", role="dns", lane="edge", region="", slot=1),
    NodeSpec(id="cdn", role="cdn", lane="edge", region="", slot=2),
    NodeSpec(id="audit", role="obj", lane="edge", region="", slot=3),
    # region A — VPC service row. These sit in the VPC directly, ABOVE the AZ
    # boxes, so they declare the VPC as their container (never an AZ) — the AZ
    # boxes wrap only their own AZ nodes, not the service row.
    #
    # The two availability zones are STACKED vertically (Req 12.1): AZ-1 sits in
    # an upper primary-axis tier band and AZ-2 in the band directly below it, so
    # both AZs reuse the SAME slot columns (their boxes stay disjoint on the
    # primary axis via the engine's AZ-band offset, not by a secondary-axis slot
    # gap). AZ-1 and AZ-2 therefore share one x-range and one width. Membership
    # is declared, so the AZ boxes wrap exactly their declared nodes regardless
    # of geometry.
    NodeSpec(id="lb_a", role="lb", lane="router", region="a", slot=0, container="boundary-vpc-a"),
    NodeSpec(id="queue_a", role="queue", lane="async", region="a", slot=0, container="boundary-vpc-a"),
    NodeSpec(id="fn_a", role="fn", lane="workers", region="a", slot=0, container="boundary-vpc-a"),
    NodeSpec(id="sec_a", role="sec", lane="platform", region="a", slot=0, container="boundary-vpc-a"),
    # region A — AZ-1 (slots 0..2) — declared members of az-a1.
    NodeSpec(id="db_a1", role="sql", lane="data", region="a", slot=0, container="boundary-az-a1"),
    NodeSpec(id="obj_a1", role="obj", lane="data", region="a", slot=1, container="boundary-az-a1"),
    NodeSpec(id="app_a1", role="k8s", lane="workers", region="a", slot=1, container="boundary-az-a1"),
    # api / observability form the AZ's SECOND row (sub=1): the engine lays each
    # band out horizontally (one column per lane) and drops sub=1 nodes to a
    # sub-row beneath the main row, reproducing the reference's app/cache/db/obj
    # main row + api/mon sub-row (see layout_engine._place_base north-south).
    NodeSpec(id="api_a1", role="k8s", lane="workers", region="a", slot=2, sub=1, container="boundary-az-a1"),
    NodeSpec(id="cache_a1", role="cache", lane="platform", region="a", slot=1, container="boundary-az-a1"),
    NodeSpec(id="mon_a", role="fn", lane="platform", region="a", slot=2, sub=1, container="boundary-az-a1"),
    # region A — AZ-2 (same slots as AZ-1; distinguished by its lower tier band).
    NodeSpec(id="db_a2", role="sql", lane="data", region="a", slot=0, container="boundary-az-a2"),
    NodeSpec(id="obj_a2", role="obj", lane="data", region="a", slot=1, container="boundary-az-a2"),
    NodeSpec(id="app_a2", role="k8s", lane="workers", region="a", slot=1, container="boundary-az-a2"),
    NodeSpec(id="api_a2", role="k8s", lane="workers", region="a", slot=2, sub=1, container="boundary-az-a2"),
    NodeSpec(id="cache_a2", role="cache", lane="platform", region="a", slot=1, container="boundary-az-a2"),
    # region B — VPC service row.
    #
    # The PASSIVE region is an active-passive mirror of the primary: every peer
    # exists, but drawing its full edge set would duplicate the primary region's
    # topology and double the ink for no new information. The four peers that
    # carry a genuine cross-region relationship (``lb_b`` ← DNS standby,
    # ``app_b1`` ← passive LB, ``db_b1`` / ``obj_b1`` ← replication) keep their
    # real edges; the rest declare ``overlay="standby"``, the Overlay Vocabulary
    # marker that states "mirrors the active peer; edges omitted for clarity".
    # That is the sanctioned alternative to real edges under
    # ``node-connectivity`` — double-encoded as a dashed outline, a ``-standby``
    # label token, and a Legend entry, so it survives grayscale and colour-vision
    # deficiency.
    NodeSpec(id="lb_b", role="lb", lane="router", region="b", slot=0, container="boundary-vpc-b"),
    NodeSpec(id="queue_b", role="queue", lane="async", region="b", slot=0, container="boundary-vpc-b", overlay="standby"),
    NodeSpec(id="fn_b", role="fn", lane="workers", region="b", slot=0, container="boundary-vpc-b", overlay="standby"),
    NodeSpec(id="sec_b", role="sec", lane="platform", region="b", slot=0, container="boundary-vpc-b", overlay="standby"),
    # region B — AZ-1 (slots 0..2).
    NodeSpec(id="db_b1", role="sql", lane="data", region="b", slot=0, container="boundary-az-b1"),
    NodeSpec(id="obj_b1", role="obj", lane="data", region="b", slot=1, container="boundary-az-b1"),
    NodeSpec(id="app_b1", role="k8s", lane="workers", region="b", slot=1, container="boundary-az-b1"),
    NodeSpec(id="api_b1", role="k8s", lane="workers", region="b", slot=2, sub=1, container="boundary-az-b1", overlay="standby"),
    NodeSpec(id="cache_b1", role="cache", lane="platform", region="b", slot=1, container="boundary-az-b1", overlay="standby"),
    NodeSpec(id="mon_b", role="fn", lane="platform", region="b", slot=2, sub=1, container="boundary-az-b1", overlay="standby"),
    # region B — AZ-2 (same slots as AZ-1; distinguished by its lower tier band).
    NodeSpec(id="db_b2", role="sql", lane="data", region="b", slot=0, container="boundary-az-b2", overlay="standby"),
    NodeSpec(id="obj_b2", role="obj", lane="data", region="b", slot=1, container="boundary-az-b2", overlay="standby"),
    NodeSpec(id="app_b2", role="k8s", lane="workers", region="b", slot=1, container="boundary-az-b2", overlay="standby"),
    NodeSpec(id="api_b2", role="k8s", lane="workers", region="b", slot=2, sub=1, container="boundary-az-b2", overlay="standby"),
    NodeSpec(id="cache_b2", role="cache", lane="platform", region="b", slot=1, container="boundary-az-b2", overlay="standby"),
)

_LANDSCAPE_EDGES = (
    EdgeSpec(id="l1", source="dns", target="lb_a", marker="1"),
    # Cross-region A→B hops are declared via kind_hint: region membership is a
    # spec fact, not something geometry can read from box coordinates (region B's
    # absolute offset is content-derived), and a 4-column-wide AZ band makes an
    # in-region fan-out span the same raw dx as the old cross-region threshold.
    # Hinting the three genuine cross-region edges keeps classify_edge's geometric
    # fallback for everything else (diagram-standards: no guessed route).
    EdgeSpec(id="l2", source="dns", target="lb_b", marker="2", dashed=True, kind_hint="cross-region"),
    EdgeSpec(id="l3", source="lb_a", target="app_a1", marker="3"),
    EdgeSpec(id="l4", source="lb_a", target="app_a2", marker="4"),
    EdgeSpec(id="l5", source="app_a1", target="db_a1", marker="5"),
    EdgeSpec(id="l6", source="app_a1", target="cache_a1", marker="6"),
    EdgeSpec(id="l7", source="db_a1", target="db_a2", marker="7", dashed=True),
    EdgeSpec(id="l8", source="app_a1", target="obj_a1", marker="8"),
    EdgeSpec(id="l9", source="lb_b", target="app_b1", marker="9"),
    EdgeSpec(id="l10", source="db_a1", target="db_b1", marker="10", dashed=True, kind_hint="cross-region"),
    EdgeSpec(id="l11", source="obj_a1", target="obj_b1", marker="11", dashed=True, kind_hint="cross-region"),
    EdgeSpec(id="l12", source="queue_a", target="fn_a", marker="12", dashed=True),
    # --- v1.6.0: connect the account edge tier and the primary region --------
    # Before 1.6.0 this landscape drew 34 nodes joined by 12 edges, leaving 20
    # nodes with no incident edge at all — the 2026-09-25 audit's headline
    # finding, and the reason ``node-connectivity`` could not ship as a rule
    # until the examples it judges were connected. The nine edges below are the
    # relationships the companion document already described in prose, so this
    # also closes a doc/diagram mismatch. The remaining unconnected nodes are
    # the PASSIVE region's mirror peers, which now carry the ``standby`` overlay
    # marker instead (see ``_LANDSCAPE_NODES``).
    EdgeSpec(id="l13", source="wafedge", target="cdn", marker="13"),
    EdgeSpec(id="l14", source="cdn", target="audit", marker="14", dashed=True),
    EdgeSpec(id="l15", source="cdn", target="lb_a", marker="15"),
    # The API tier hangs off the WORKER, not the load balancer: giving ``lb_a`` a
    # third downward branch put three exits on one bottom face, which the
    # contact-spread cannot keep distinct (``exit-thirds``). diagram-standards is
    # explicit that an over-connected side means "split or re-lane", so the edge
    # is re-sourced rather than the spread being bent to accommodate it. ``fn_a``
    # then has exactly one straight-down branch (``sec_a``) plus this one, the
    # two-face fan-out shape the engine handles cleanly.
    EdgeSpec(id="l16", source="fn_a", target="api_a1", marker="16"),
    EdgeSpec(id="l17", source="api_a1", target="mon_a", marker="17", dashed=True),
    EdgeSpec(id="l18", source="fn_a", target="sec_a", marker="18"),
    EdgeSpec(id="l19", source="app_a2", target="cache_a2", marker="19"),
    EdgeSpec(id="l20", source="app_a2", target="obj_a2", marker="20"),
    EdgeSpec(id="l21", source="app_a2", target="api_a2", marker="21"),
)

# Nested containers: account ⊃ region VPC ⊃ availability zone.
_LANDSCAPE_CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None, label_key="account"),
    ContainerSpec(id="boundary-vpc-a", kind="vpc", region="a", parent="boundary-account", label_key="vpc_a"),
    ContainerSpec(id="boundary-vpc-b", kind="vpc", region="b", parent="boundary-account", label_key="vpc_b"),
    ContainerSpec(id="boundary-az-a1", kind="az", region="a", parent="boundary-vpc-a", label_key="az_a1"),
    ContainerSpec(id="boundary-az-a2", kind="az", region="a", parent="boundary-vpc-a", label_key="az_a2"),
    ContainerSpec(id="boundary-az-b1", kind="az", region="b", parent="boundary-vpc-b", label_key="az_b1"),
    ContainerSpec(id="boundary-az-b2", kind="az", region="b", parent="boundary-vpc-b", label_key="az_b2"),
)

_LANDSCAPE_FLOW = (
    "Flow",
    "1. DNS routes to the active region",
    "2. DNS holds the passive region on standby",
    "3. Primary LB to AZ-1 app",
    "4. Primary LB to AZ-2 app",
    "5. AZ-1 app to AZ-1 writer DB",
    "6. AZ-1 app to AZ-1 cache",
    "7. In-region standby DB replication (AZ-1 to AZ-2)",
    "8. AZ-1 app writes AZ-1 object store",
    "9. Passive LB to AZ-1 app",
    "10. Cross-region DB replication (primary to passive)",
    "11. Cross-region object-store replication (CRR)",
    "12. Regional queue drives the worker (async)",
    "13. Edge WAF policy fronts the CDN",
    "14. CDN access logs to the audit bucket (async)",
    "15. CDN origin fetch to the primary LB",
    "16. Primary LB to the AZ-1 API tier",
    "17. API tier emits telemetry to observability (async)",
    "18. Primary worker reads the secrets store",
    "19. AZ-2 app to AZ-2 cache",
    "20. AZ-2 app writes AZ-2 object store",
    "21. AZ-2 app to the AZ-2 API tier",
)

#: The landscape's Legend documents the ``standby`` overlay it uses, so
#: ``overlay-legend-coverage`` is satisfied by a real legend entry rather than by
#: the marker merely appearing twice in the file.
LANDSCAPE_LEGEND_EXTRA = (
    "standby (dashed outline, -standby label) = passive peer mirrors the active "
    "one; edges omitted for clarity",
)

LANDSCAPE_SPEC = DiagramSpec(
    diagram_id="ha-landscape",
    diagram_name="ha-multiregion-landscape",
    axis="north-south",
    nodes=_LANDSCAPE_NODES,
    edges=_LANDSCAPE_EDGES,
    containers=_LANDSCAPE_CONTAINERS,
    flow_lines=_LANDSCAPE_FLOW,
    title="ha-multiregion-landscape | 2026-09-23 | v1",
)
