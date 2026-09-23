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
    ("s1", "dns", "lb_a", "1", False, (0.35, 1.0), (0.5, 0.0), [(727, 230), (399, 230)]),
    ("s2", "lb_a", "app_a", "2", False, (0.5, 1.0), (0.5, 0.0), []),
    ("s3", "app_a", "db_a", "3", False, (0.5, 1.0), (0.5, 0.0), []),
    # app -> object-store sits to app's LEFT (a back-reference). Loop CLOCKWISE
    # UNDER the row: exit app's bottom-left (distinct from edge 3's bottom-centre
    # exit), drop below the row, run left in a corridor (x=100, in the boundary|obj
    # gap), rise to the object-store's mid, and enter its LEFT face. Stays clear of
    # app's icon and does not overlap the app->db spine (edge 3).
    ("s4", "app_a", "obj_a", "4", False, (0.25, 1.0), (0.0, 0.5), [(379, 650), (100, 650), (100, 559)]),
    ("s5", "dns", "lb_b", "5", True, (0.65, 1.0), (0.5, 0.0), [(751, 250), (1079, 250)]),
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
    ("l1", "dns", "lb_a", "1", False, (0.5, 1.0), (0.5, 0.0), [(399, 330), (159, 330)]),
    # Standby back-edge turns ONE column beyond its source (x=480, just right of
    # dns@360) and crosses in a mid corridor (y=300) — not at the far passive
    # column — so it is not the longest, most border-crossing line on the canvas.
    ("l2", "dns", "lb_b", "2", True, (1.0, 0.5), (0.5, 0.0), [(480, 159), (480, 300), (1459, 300)]),
    # Spine hop: lb_a exits its RIGHT into the gap corridor one column beside the
    # LB column (x=240, between lb@120 and cache@360), drops to the app row, and
    # enters app_a1's top — never a straight vertical down the node column.
    ("l3", "lb_a", "app_a1", "3", False, (1.0, 0.5), (0.5, 0.0), [(240, 459), (240, 700), (159, 700)]),
    # lb_a -> app_a2 (AZ-2, two tiers down): step sideways into the app|cache gap
    # corridor (x=280, distinct from the x=240 spine lane) BEFORE the long drop,
    # then one clean vertical to the AZ-2 row and enter app_a2's top — the vertical
    # sits in a column gap, not glued to the VPC border as a rail parallel to the
    # app column, and the edge makes the fewest turns (step, drop, step-in).
    # lb_a -> app_a2 (two tiers down). The whole app_a1 fan-out (5/6/8) occupies
    # the gaps and below-row lanes to the RIGHT of the app column (x >= 159), so
    # this spine takes the RESERVED LEFT corridor (x=100, centered in the vpc|app
    # gap 60..120) straight down — the only lane that crosses none of the fan-out
    # horizontals — and enters app_a2 from the LEFT. One vertical, one step in.
    ("l4", "lb_a", "app_a2", "4", False, (0.25, 1.0), (0.0, 0.5), [(100, 540), (100, 1239)]),
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
    # app_a1 fans out with DISTINCT exit points so no two edges leave glued
    # together: cache (adjacent) exits right-top third (1.0,0.33); db exits
    # right-bottom third (1.0,0.66); obj exits the BOTTOM. Each is >= a third
    # apart, so the eye separates them at the source.
    ("l6", "app_a1", "cache_a1", "6", False, (1.0, 0.33), (0.0, 0.5), []),
    # db: exit right-bottom third, step into the gap (x=240), drop to lane y=845,
    # across, up-turn x=560 (gap before db@600), enter db left.
    ("l5", "app_a1", "db_a1", "5", False, (1.0, 0.66), (0.0, 0.5), [(240, 771), (240, 845), (560, 845), (560, 759)]),
    ("l7", "db_a1", "db_a2", "7", True, (0.5, 1.0), (0.5, 0.0), [(639, 1130)]),
    # obj: exit the BOTTOM (0.5,1.0) and go straight DOWN first, THEN turn right
    # (stair from the bottom, not a corner) — own lane y=880 (distinct from l5's
    # 845), up-turn x=800 (gap before obj@840), enter obj left.
    ("l8", "app_a1", "obj_a1", "8", False, (0.5, 1.0), (0.0, 0.5), [(159, 880), (800, 880), (800, 759)]),
    # Spine hop mirror in region B: corridor at x=1540 (between lb_b@1420 and
    # cache_b1@1660), same right-exit / drop / enter-top shape as l3.
    ("l9", "lb_b", "app_b1", "9", False, (1.0, 0.5), (0.5, 0.0), [(1540, 459), (1540, 700), (1459, 700)]),
    # Cross-region replication edges run in their OWN dedicated corridors above
    # the AZ boxes (y 650 / 670), one lane each, never sharing an in-AZ lane.
    # They exit the source's right (contract), rise into their corridor, run
    # across, and enter the target's top (left/top-compliant).
    # Cross-region edges step OUT sideways from the source's right (into the gap:
    # db@600 right=678 -> x=720; obj@840 right=918 -> x=960) BEFORE turning up into
    # their corridor — the vertical is not glued to the node edge (stair), and the
    # two corridors (y=670 / y=650) stay one lane each.
    ("l10", "db_a1", "db_b1", "10", True, (1.0, 0.25), (0.5, 0.0), [(720, 739), (720, 670), (1939, 670)]),
    ("l11", "obj_a1", "obj_b1", "11", True, (1.0, 0.25), (0.5, 0.0), [(960, 739), (960, 650), (2179, 650)]),
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
        flow_lines=LANDSCAPE_FLOW, legend_x=2400, legend_y_flow=120,
        legend_y_legend=460, page_w=2860, page_h=1680,
    )


def write_pair(skin: ProviderSkin, out_dir: Path, stem: str) -> List[Path]:
    """Write both .drawio files of the pair; return the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = out_dir / f"{stem}-summary.drawio"
    lp = out_dir / f"{stem}-landscape.drawio"
    sp.write_text(build_summary(skin), encoding="utf-8")
    lp.write_text(build_landscape(skin), encoding="utf-8")
    return [sp, lp]
