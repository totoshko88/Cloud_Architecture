#!/usr/bin/env python3
"""Shared builder for the HA multi-region golden **pair** (v1.3.0).

Every provider (AWS, Azure, GCP, OCI) ships the *same* highly available,
active-passive multi-region reference workload as a cross-linked pair:

- a **`flow`** summary (<= 12 nodes) — ``NN-<prov>-ha-multiregion-summary.drawio``
- a **`landscape`** as-built (~34 nodes) — ``NN-<prov>-ha-multiregion-landscape.drawio``

This module is the single source of truth for the *numeric layout* of both
diagrams (node coordinates, nested container boxes, and orthogonally-routed edge
waypoints), verified against the geometry rules in
``rule_engine.geometry`` — the summary and landscape both place every node on the
grid, keep >= one grid step of container padding (an **ERROR** for the landscape
class), and route every parallel run in its own waypoint corridor. Per-provider
generators supply only an *icon renderer per neutral role* (how to draw one
node's glyph) and the provider's region/account labels; the geometry never forks.

The class contract (see ``.kiro/steering/diagram-standards.md`` -> Diagram Class)
is carried in the companion ``.diagram.md`` frontmatter, not here: the summary
declares ``diagram_class: flow`` + ``detailed_view``, the landscape declares
``diagram_class: landscape`` + ``summary_of``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

# Make the package importable when run as a plain script (mirrors the other
# build_*_example.py scripts).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json  # noqa: E402

from rule_engine.diagram_layout import (  # noqa: E402
    Boundary,
    Edge,
    Node,
    build_diagram,
    image_icon,
    OciStencilIcon,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ICON_INDEX = REPO_ROOT / "mappings" / "icon-index.json"


def _load_icon_index() -> dict:
    """Load the committed icon index (role → resolved icon per provider)."""
    return json.loads(ICON_INDEX.read_text(encoding="utf-8"))


def index_renderer(role: str, provider: str, brand_hex: str = "#000000"):
    """Return an icon renderer for ``role``/``provider`` from the committed index.

    Image providers (aws/azure/gcp) render the resolved official pack file via a
    file-path ``image`` shape (inlined at raster export). OCI embeds the resolved
    stencil by slug. This is how generators resolve a role→icon through the index
    instead of hand-written paths (see the icon-set standardisation rules)."""
    idx = _load_icon_index()
    entry = idx["roles"].get(role, {}).get(provider)
    if not entry or entry.get("source") == "unresolved" or not entry.get("ref"):
        raise KeyError(f"icon-index has no resolved icon for role={role!r} provider={provider!r}")
    ref = entry["ref"]
    if provider == "oci":
        slug = ref.split("#", 1)[1] if "#" in ref else ref
        stencils = json.loads((REPO_ROOT / "assets" / "vendor" / "oci-stencils" / "stencils.json").read_text(encoding="utf-8"))
        return OciStencilIcon(stencils, slug, brand_hex)
    return image_icon(ref)

# --------------------------------------------------------------------------- #
# Verified layout geometry (shared across all four providers).
# node tuple:      (id, role, x, y)          role selects the provider icon
# boundary tuple:  (id, label, x, y, w, h)   label overridden per provider below
# edge tuple:      (id, src, tgt, marker, dashed, exit(x,y), entry(x,y), points)
# --------------------------------------------------------------------------- #

# ---- SUMMARY (flow, 9 nodes) ---------------------------------------------- #
# Every node footprint is icon (78) + a label band (~30) below it; the region
# frames are sized so each node's *footprint* keeps >= one grid step of padding
# inside the boundary, and every edge obeys the directional contract (exit
# right/bottom, enter left/top).
SUMMARY_NODES: List[Tuple[str, str, int, int]] = [
    ("dns", "dns", 700, 100),
    ("lb_a", "lb", 360, 320), ("app_a", "k8s", 360, 520), ("db_a", "sql", 360, 720),
    ("obj_a", "obj", 120, 520),
    ("lb_b", "lb", 1040, 320), ("app_b", "k8s", 1040, 520), ("db_b", "sql", 1040, 720),
    ("obj_b", "obj", 1280, 520),
]
# Region (network-boundary) frames; labels are filled per provider in build().
SUMMARY_BOUNDARY_BOXES: List[Tuple[str, int, int, int, int]] = [
    ("nb_a", 90, 270, 490, 620),
    ("nb_b", 1010, 270, 490, 620),
]
SUMMARY_EDGES: List[tuple] = [
    # DNS fans out to both regions: each edge exits DNS's bottom at a DISTINCT
    # point and drops STRAIGHT DOWN (waypoint at the same x as the exit) before
    # turning, so there is no diagonal kink; the two use different corridor rows
    # (y=230 / y=250) so their horizontals never merge.
    # DNS fans out DOWN to both regions; two exits on the bottom face take the
    # canonical even-thirds split for two (0.25 / 0.75), each dropping straight
    # down before turning into its own corridor row (y=230 / y=250).
    ("s1", "dns", "lb_a", "1", False, (0.25, 1.0), (0.5, 0.0), [(720, 230), (399, 230)]),
    ("s2", "lb_a", "app_a", "2", False, (0.5, 1.0), (0.5, 0.0), []),
    # db_a sits DIRECTLY BELOW app_a (both at x=360), so edge 3 is a STRAIGHT
    # vertical straight down the centre — the shortest, most readable path (a
    # straight-line target keeps the centre; see diagram-standards → Distinct
    # same-side exits). The object-store back-edge (edge 4) exits the distinct
    # left-third 0.25, so the two bottom exits do not merge.
    ("s3", "app_a", "db_a", "3", False, (0.5, 1.0), (0.5, 0.0), []),
    # app -> object-store sits to app's LEFT (a back-reference). Loop CLOCKWISE
    # UNDER the row: exit app's bottom-left third (0.25, distinct from edge 3's
    # 0.75), drop below the row, run left in a corridor (x=100, in the boundary|obj
    # gap), rise to the object-store's mid, and enter its LEFT face. Stays clear of
    # app's icon and does not overlap the app->db spine (edge 3).
    ("s4", "app_a", "obj_a", "4", False, (0.25, 1.0), (0.0, 0.5), [(379, 650), (100, 650), (100, 559)]),
    ("s5", "dns", "lb_b", "5", True, (0.75, 1.0), (0.5, 0.0), [(758, 250), (1079, 250)]),
    ("s6", "lb_b", "app_b", "6", False, (0.5, 1.0), (0.5, 0.0), []),
    ("s7", "app_b", "db_b", "7", False, (0.5, 1.0), (0.5, 0.0), []),
    ("s8", "app_b", "obj_b", "8", False, (1.0, 0.5), (0.0, 0.5), []),
    # Cross-region DB replication is a straight horizontal: same exit/entry Y,
    # no mid waypoint (a single offset waypoint made a needless zig).
    ("s9", "db_a", "db_b", "9", True, (1.0, 0.5), (0.0, 0.5), []),
]
SUMMARY_FLOW = [
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
]

# ---- LANDSCAPE (landscape, 34 nodes) -------------------------------------- #
# Spacious as-built geometry (column step 240, row step 210) sized so a node's
# icon+label footprint (78x108) never crowds a boundary border or the row below,
# with the two region VPCs on disjoint horizontal bands (no sibling overlap),
# each nesting two availability-zone boxes. Every edge obeys the directional
# contract (exit right/bottom, enter left/top). Exported wide (landscape raster
# budget) so all 34 nodes stay legible — see .kiro/steering/diagram-standards.md
# -> Raster Export Dimensions.
LANDSCAPE_NODES: List[Tuple[str, str, int, int]] = [
    # edge / account row (above the region VPCs). Each distinct edge service uses
    # its OWN role (waf / dns / cdn), never a look-alike, so the icon is correct
    # per provider (see .kiro/steering/diagram-standards.md → one role per service).
    ("wafedge", "waf", 120, 120), ("dns", "dns", 360, 120),
    ("cdn", "cdn", 600, 120), ("audit", "obj", 840, 120),
    # region A — VPC service row
    ("lb_a", "lb", 120, 420), ("queue_a", "queue", 360, 420),
    ("fn_a", "fn", 600, 420), ("sec_a", "sec", 840, 420),
    # region A — AZ-1 (main row + sub row)
    ("app_a1", "k8s", 120, 720), ("cache_a1", "cache", 360, 720),
    ("db_a1", "sql", 600, 720), ("obj_a1", "obj", 840, 720),
    ("api_a1", "k8s", 120, 930), ("mon_a", "fn", 840, 930),
    # region A — AZ-2 (main row + sub row)
    ("app_a2", "k8s", 120, 1200), ("cache_a2", "cache", 360, 1200),
    ("db_a2", "sql", 600, 1200), ("obj_a2", "obj", 840, 1200),
    ("api_a2", "k8s", 120, 1410),
    # region B — VPC service row (offset +1300)
    ("lb_b", "lb", 1420, 420), ("queue_b", "queue", 1660, 420),
    ("fn_b", "fn", 1900, 420), ("sec_b", "sec", 2140, 420),
    # region B — AZ-1
    ("app_b1", "k8s", 1420, 720), ("cache_b1", "cache", 1660, 720),
    ("db_b1", "sql", 1900, 720), ("obj_b1", "obj", 2140, 720),
    ("api_b1", "k8s", 1420, 930), ("mon_b", "fn", 2140, 930),
    # region B — AZ-2
    ("app_b2", "k8s", 1420, 1200), ("cache_b2", "cache", 1660, 1200),
    ("db_b2", "sql", 1900, 1200), ("obj_b2", "obj", 2140, 1200),
    ("api_b2", "k8s", 1420, 1410),
]
# Nested container boxes: account (outer) -> region VPC -> availability zone.
# Strictly nested and non-overlapping between sibling VPCs / AZs (grid-clean
# dimensions; padding measured against the icon+label footprint).
# (id, kind, x, y, w, h) — kind selects the provider container style.
LANDSCAPE_BOUNDARY_BOXES: List[Tuple[str, str, int, int, int, int]] = [
    # Vertical envelope sized so AZ-2 (top 1170, height 380, bottom 1550) clears
    # its parent VPC border by >= 1 grid step: vpc bottom = 390+1190 = 1580
    # (30px gap below az-2); account bottom = 60+1560 = 1620 (40px below vpc).
    ("boundary-account", "account", 30, 60, 2280, 1560),
    ("boundary-vpc-a", "vpc", 60, 390, 920, 1190),
    ("boundary-vpc-b", "vpc", 1360, 390, 920, 1190),
    ("boundary-az-a1", "az", 90, 690, 860, 380),
    ("boundary-az-a2", "az", 90, 1170, 860, 380),
    ("boundary-az-b1", "az", 1390, 690, 860, 380),
    ("boundary-az-b2", "az", 1390, 1170, 860, 380),
]
LANDSCAPE_EDGES: List[tuple] = [
    # Waypoints below are authored in RAW (pre-region-shift) coordinates and are
    # moved into place by _compact_landscape's _shift_x, exactly like the nodes —
    # so they reproduce the reviewer's hand-corrected copy after the shift. RAW
    # region-A: app_a1@120(r198), cache@360, db@600, obj@840, lb_a@120(r198).
    # l1: DNS → primary LB. Exit RIGHT (label-safe) with a minimal step out, one
    # turn down into the pre-LB corridor y=330, and into lb_a's top.
    ("l1", "dns", "lb_a", "1", False, (1.0, 0.62), (0.5, 0.0), [(360, 168), (360, 330), (159, 330)]),
    # l2: standby back-edge to the passive LB, in a corridor ABOVE l1 (y=250) that
    # clears the cdn icon: its vertical sits LEFT of cdn and its horizontal BELOW
    # cdn, so it never rides over cdn. Exits dns's upper-right (0.32, distinct from
    # l1's 0.62 so the two do not merge) and enters lb_b's top.
    ("l2", "dns", "lb_b", "2", True, (1.0, 0.32), (0.5, 0.0), [(400, 145), (400, 250), (1459, 250)]),
    # l3: spine hop lb_a → app_a1. Exit RIGHT, drop in the gap corridor beside the
    # LB column (RAW x=280, the lb|cache gap), turn LEFT in the roomy band ABOVE
    # az-a1 (y=640) and enter app_a1's top — the left turn where there is space.
    ("l3", "lb_a", "app_a1", "3", False, (1.0, 0.5), (0.5, 0.0), [(280, 459), (280, 640), (159, 640)]),
    # l4: lb_a → app_a2 (two tiers below, same column blocked by app_a1/api_a1).
    # Exit RIGHT below l3 (0.72), step further LEFT into the reserved corridor
    # (RAW x=80, the vpc|app gap) — the one lane crossing none of app_a1's fan-out
    # — drop the full height, enter app_a2's LEFT. Turn over az (y=600).
    ("l4", "lb_a", "app_a2", "4", False, (1.0, 0.72), (0.0, 0.5), [(240, 476), (240, 600), (80, 600), (80, 1239)]),
    # In-AZ edges use distinct below-row corridors (y 830 / 850) so no two share
    # a lane; app_a1 fans out to cache (adjacent, direct) and to db/obj via a
    # side corridor below the icon row rather than straight through cache/db.
    # app_a1 fans out right along the row to cache (adjacent, direct), db and obj.
    # Each far edge runs its OWN below-row lane and makes its vertical up-turn in
    # the gap immediately LEFT of its target (db@600 -> turn x=560; obj@840 ->
    # turn x=800), entering the target's LEFT face — the verticals spread across
    # the row (one per target) instead of stacking beside the source, and each
    # horizontal is only as long as it must be (see diagram-standards → Fan-out
    # along a row).
    # app_a1 fans out along its RIGHT side, top→bottom, matching the reviewer's
    # copy: cache (nearest) exits the upper third and runs a STRAIGHT horizontal;
    # db exits the middle and obj exits the lower third, each in its OWN below-row
    # lane, turning DOWN into the gap immediately LEFT of its target (late turn,
    # close to the target — not early beside the source). The three exits are
    # distinct (≥ ⅕ apart) so they never merge; the straight cache line reads
    # cleanest at the glyph (see diagram-standards → Distinct same-side exits).
    #   cache: upper third (0.25) → straight into cache's left (same row).
    ("l6", "app_a1", "cache_a1", "6", False, (1.0, 0.25), (0.0, 0.25), []),
    #   db: middle (0.5) → drop in the app|cache gap corridor (RAW x=280) → lane
    #   y=845 → down-turn RAW x=560 (gap just before db@600) → enter db left.
    ("l5", "app_a1", "db_a1", "5", False, (1.02, 0.5), (0.0, 0.5), [(280, 760), (280, 845), (560, 845), (560, 759)]),
    #   in-region standby replication: near-straight down, vertical nudged one px
    #   off db's centre (RAW x=640) so it reads distinct from db's own glyph column.
    ("l7", "db_a1", "db_a2", "7", True, (0.5, 1.0), (0.5, 0.0), [(639, 1130), (640, 1130), (640, 1200)]),
    #   obj: lower third (0.75) → step down into corridor RAW x=240 (distinct from
    #   l5's x=280) → own lane y=880 (below l5's 845) → down-turn RAW x=800 (gap
    #   just before obj@840) → enter obj left.
    ("l8", "app_a1", "obj_a1", "8", False, (1.0, 0.75), (0.0, 0.5), [(198, 780), (240, 780), (240, 880), (800, 880), (800, 759)]),
    # l9: spine hop mirror in region B (RAW x=1540, the lb_b|cache_b1 gap), same
    # right-exit / drop / turn-left-over-az (y=600) / enter-top shape as l3.
    ("l9", "lb_b", "app_b1", "9", False, (1.0, 0.5), (0.5, 0.0), [(1540, 459), (1540, 600), (1459, 600)]),
    # Cross-region replication edges exit the source's RIGHT MIDDLE (0.5), step
    # out into the gap, rise into their own corridor (y=670 / y=650, one lane
    # each), run across, and enter the target's TOP. RAW: db_a1@600(r678) steps to
    # x=720; obj_a1@840(r918) steps to x=1040; targets db_b1@1900 (top-c 1939),
    # obj_b1@2140 (top-c 2179). l11 makes its final drop into obj_b1's top.
    ("l10", "db_a1", "db_b1", "10", True, (1.0, 0.5), (0.5, 0.0), [(720, 759), (720, 670), (1939, 670)]),
    ("l11", "obj_a1", "obj_b1", "11", True, (1.0, 0.5), (0.5, 0.0), [(1040, 759), (1040, 650), (2179, 650), (2179, 720)]),
    ("l12", "queue_a", "fn_a", "12", True, (1.0, 0.5), (0.0, 0.5), []),
]
LANDSCAPE_FLOW = [
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
]

# --------------------------------------------------------------------------- #
# Space-optimisation transform (reviewer, 2026-09-23):
#
# Balance the horizontal space rather than leaving a large dead gap between the
# two region bands while the nodes hug the left of each VPC. Region A's inner
# nodes are nudged RIGHT so they centre within their VPC (even left/right
# padding), and region B's whole band is pulled LEFT so the inter-region gap
# shrinks to one consistent step. Both shifts are a whole grid multiple
# (``REGION_SHIFT`` = 120) so every origin stays on the grid; the region divide
# ``REGION_SPLIT_X`` classifies which x belongs to region A vs B (nodes,
# container boxes, and each edge waypoint independently, so a cross-region edge
# keeps each end anchored to its shifted node). This encodes the rule "centre
# nodes within their boundary; keep sibling region bands one consistent gap
# apart" (see diagram-standards → Container Nesting).
REGION_SHIFT = 120
REGION_SPLIT_X = 1150  # region A < this <= region B


def _shift_x(x: float) -> float:
    return x - REGION_SHIFT if x >= REGION_SPLIT_X else x + REGION_SHIFT


def _compact_landscape():
    """Apply the region-balance transform in place to the landscape tables."""
    global LANDSCAPE_NODES, LANDSCAPE_BOUNDARY_BOXES, LANDSCAPE_EDGES
    # Edge / account row (wafedge/dns/cdn/audit) is account-level, above the
    # VPCs, and is NOT shifted — only the in-VPC region nodes move.
    _edge_row = {"wafedge", "dns", "cdn", "audit"}
    LANDSCAPE_NODES = [
        (nid, role, (x if nid in _edge_row else int(_shift_x(x))), y)
        for nid, role, x, y in LANDSCAPE_NODES
    ]
    # Symmetric widen-toward-the-centre so BOTH region bands end the SAME width
    # (the reviewer's goal: equal-size VPC/AZ boxes, not a narrower passive
    # region). Region A keeps its left edge and grows its right edge by
    # REGION_SHIFT; region B keeps its right edge and grows its left edge by
    # REGION_SHIFT (move left AND widen). Each region's inner nodes were shifted
    # toward the centre by REGION_SHIFT, so both stay centred with equal padding,
    # and the two bands are mirror images of identical width.
    def _shift_box(cid, kind, x, y, w, h):
        if cid == "boundary-account":
            return None  # recomputed below to wrap the shifted VPC bands snugly
        if x >= REGION_SPLIT_X:
            # region B: keep the right edge, grow the left edge inward.
            return (cid, kind, int(x - REGION_SHIFT), y, int(w + REGION_SHIFT), h)
        # region A: keep the left edge, grow the right edge inward.
        return (cid, kind, x, y, int(w + REGION_SHIFT), h)
    _acct = next(b for b in LANDSCAPE_BOUNDARY_BOXES if b[0] == "boundary-account")
    shifted = [_shift_box(*b) for b in LANDSCAPE_BOUNDARY_BOXES if b[0] != "boundary-account"]
    # Account wraps every VPC band + one grid step of padding on each side.
    _left = min(x for _, _, x, _, _, _ in shifted)
    _right = max(x + w for _, _, x, _, w, _ in shifted)
    _acct = ("boundary-account", "account", _left - 30, _acct[3],
             (_right + 30) - (_left - 30), _acct[5])
    LANDSCAPE_BOUNDARY_BOXES = [_acct] + shifted
    LANDSCAPE_EDGES = [
        (eid, src, tgt, marker, dashed, exit_, entry,
         [(int(_shift_x(px)), py) for px, py in points])
        for eid, src, tgt, marker, dashed, exit_, entry, points in LANDSCAPE_EDGES
    ]
    _centre_regions_in_vpc()


# Icon footprint (must match diagram_layout.ICON size) and grid step; used to
# centre nodes on the grid.
_ICON = 78
_GRID = 10


def _centre_regions_in_vpc():
    """Slide each region's service nodes (and its edge waypoints) so the block of
    nodes is symmetric inside its VPC box, snapped to the grid.

    The region-balance widen leaves each region's nodes hugging one side of its
    VPC (region A to the left, region B to the right). Here every region is
    re-centred as a whole: compute the block's node centre and the VPC-box
    centre, and shift the block by the grid-rounded delta. Whole-block shift keeps
    every hand-tuned edge shape intact (nodes and their waypoints move together),
    and both regions become mirror-symmetric with equal left/right padding.
    (Reviewer goal 2026-09-23: symmetric node placement in the VPC, on-grid.)"""
    global LANDSCAPE_NODES, LANDSCAPE_EDGES
    _edge_row = {"wafedge", "dns", "cdn", "audit"}
    vpc = {b[0]: b for b in LANDSCAPE_BOUNDARY_BOXES if b[0].startswith("boundary-vpc")}

    def _region_dx(vpc_box, in_region):
        xs = [x for nid, _, x, _ in LANDSCAPE_NODES
              if nid not in _edge_row and in_region(x)]
        if not xs:
            return 0
        block_centre = (min(xs) + (max(xs) + _ICON)) / 2.0
        _, _, bx, _, bw, _ = vpc_box
        vpc_centre = bx + bw / 2.0
        return int(round((vpc_centre - block_centre) / _GRID)) * _GRID

    dx_a = _region_dx(vpc["boundary-vpc-a"], lambda x: x < REGION_SPLIT_X)
    dx_b = _region_dx(vpc["boundary-vpc-b"], lambda x: x >= REGION_SPLIT_X)

    def _dx_for(x):
        return dx_a if x < REGION_SPLIT_X else dx_b

    LANDSCAPE_NODES = [
        (nid, role, (x if nid in _edge_row else x + _dx_for(x)), y)
        for nid, role, x, y in LANDSCAPE_NODES
    ]
    LANDSCAPE_EDGES = [
        (eid, src, tgt, marker, dashed, exit_, entry,
         [(px + _dx_for(px), py) for px, py in points])
        for eid, src, tgt, marker, dashed, exit_, entry, points in LANDSCAPE_EDGES
    ]


_compact_landscape()

# Node display labels (provider-neutral role names; concrete service names live
# in the companion prose).
LABELS: Dict[str, str] = {
    "dns": "global-dns-failover", "cdn": "edge-cdn", "wafedge": "edge-waf-policy",
    "audit": "audit-log-bucket",
    "lb_a": "lb-primary", "app_a": "app-primary", "db_a": "db-primary", "obj_a": "objstore-primary",
    "lb_b": "lb-passive", "app_b": "app-passive", "db_b": "db-passive", "obj_b": "objstore-passive",
    "queue_a": "queue-primary", "fn_a": "worker-primary", "sec_a": "secrets-primary",
    "app_a1": "app-az1", "cache_a1": "cache-az1", "db_a1": "db-writer-az1", "obj_a1": "objstore-az1",
    "api_a1": "api-az1", "app_a2": "app-az2", "cache_a2": "cache-az2", "db_a2": "db-standby-az2",
    "obj_a2": "objstore-az2", "api_a2": "api-az2", "mon_a": "observability-primary",
    "queue_b": "queue-passive", "fn_b": "worker-passive", "sec_b": "secrets-passive",
    "app_b1": "app-az1", "cache_b1": "cache-az1", "db_b1": "db-writer-az1", "obj_b1": "objstore-az1",
    "api_b1": "api-az1", "app_b2": "app-az2", "cache_b2": "cache-az2", "db_b2": "db-standby-az2",
    "obj_b2": "objstore-az2", "api_b2": "api-az2", "mon_b": "observability-passive",
}

# A provider skin: role -> icon renderer, plus the three container styles and
# region/account labels.
IconRenderer = Callable[[Node, str], str]


class ProviderSkin:
    def __init__(
        self,
        provider: str,
        renderers: Dict[str, IconRenderer],
        container_styles: Dict[str, str],
        account_label: str,
        region_primary: str,
        region_passive: str,
    ) -> None:
        self.provider = provider
        self.renderers = renderers
        self.container_styles = container_styles
        self.account_label = account_label
        self.region_primary = region_primary
        self.region_passive = region_passive


def _boundary(cid: str, label: str, box: Tuple[int, int, int, int], style: str) -> Boundary:
    x, y, w, h = box
    return Boundary(id=cid, label=label, x=x, y=y, w=w, h=h, style=style)


def _edges(specs: Sequence[tuple]) -> List[Edge]:
    out: List[Edge] = []
    for eid, src, tgt, marker, dashed, exit_, entry, points in specs:
        out.append(
            Edge(id=eid, source=src, target=tgt, marker=marker, dashed=dashed,
                 exit=tuple(exit_), entry=tuple(entry),
                 points=[tuple(p) for p in points])
        )
    return out


def build_summary(skin: ProviderSkin) -> str:
    """Build the <=12-node flow summary .drawio for ``skin``."""
    region_labels = {
        "nb_a": f"region-primary ({skin.region_primary})",
        "nb_b": f"region-passive ({skin.region_passive})",
    }
    boundaries = [
        _boundary(cid, region_labels[cid], (x, y, w, h), skin.container_styles["vpc"])
        for cid, x, y, w, h in SUMMARY_BOUNDARY_BOXES
    ]
    nodes = [
        Node(id=nid, label=LABELS[nid], x=x, y=y, render=skin.renderers[role])
        for nid, role, x, y in SUMMARY_NODES
    ]
    title = (f"{skin.provider} ha-multiregion-summary — {skin.account_label} / "
             f"{skin.region_primary}+{skin.region_passive} | 2026-09-23 | v1")
    return build_diagram(
        diagram_id=f"{skin.provider}-ha-summary",
        diagram_name=f"{skin.provider}-ha-multiregion-summary",
        title=title, boundaries=boundaries, nodes=nodes, edges=_edges(SUMMARY_EDGES),
        flow_lines=SUMMARY_FLOW, legend_x=1600, page_w=2120, page_h=980,
    )


def build_landscape(skin: ProviderSkin) -> str:
    """Build the ~34-node landscape as-built .drawio for ``skin``."""
    az_labels = {
        "boundary-az-a1": "az-a1", "boundary-az-a2": "az-a2",
        "boundary-az-b1": "az-b1", "boundary-az-b2": "az-b2",
    }
    vpc_labels = {
        "boundary-vpc-a": f"vpc-primary {skin.region_primary}",
        "boundary-vpc-b": f"vpc-passive {skin.region_passive}",
    }
    boundaries: List[Boundary] = []
    for cid, kind, x, y, w, h in LANDSCAPE_BOUNDARY_BOXES:
        if cid == "boundary-account":
            label = skin.account_label
        elif cid in vpc_labels:
            label = vpc_labels[cid]
        else:
            label = az_labels[cid]
        boundaries.append(_boundary(cid, label, (x, y, w, h), skin.container_styles[kind]))
    nodes = [
        Node(id=nid, label=LABELS.get(nid, nid), x=x, y=y, render=skin.renderers[role])
        for nid, role, x, y in LANDSCAPE_NODES
    ]
    title = (f"{skin.provider} ha-multiregion-landscape — {skin.account_label} / "
             f"{skin.region_primary}+{skin.region_passive} | 2026-09-23 | v1")
    return build_diagram(
        diagram_id=f"{skin.provider}-ha-landscape",
        diagram_name=f"{skin.provider}-ha-multiregion-landscape",
        title=title, boundaries=boundaries, nodes=nodes, edges=_edges(LANDSCAPE_EDGES),
        # Flow/Legend sit in the right margin, clear of the account box (right
        # edge 2310): x=2340 (30px gap past the account), pinned narrow (280) so
        # they wrap taller instead of running wide — no overlap with the cloud.
        flow_lines=LANDSCAPE_FLOW, legend_x=2340, legend_y_flow=120,
        legend_y_legend=460, legend_w=280, page_w=2760, page_h=1680,
    )


def write_pair(skin: ProviderSkin, out_dir: Path, stem: str) -> List[Path]:
    """Write both .drawio files of the pair; return the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = out_dir / f"{stem}-summary.drawio"
    lp = out_dir / f"{stem}-landscape.drawio"
    sp.write_text(build_summary(skin), encoding="utf-8")
    lp.write_text(build_landscape(skin), encoding="utf-8")
    return [sp, lp]
