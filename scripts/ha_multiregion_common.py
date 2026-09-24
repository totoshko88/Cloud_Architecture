#!/usr/bin/env python3
"""Shared builder for the HA multi-region golden **pair** (v1.3.0).

Every provider (AWS, Azure, GCP, OCI) ships the *same* highly available,
active-passive multi-region reference workload as a cross-linked pair:

- a **`flow`** summary (<= 12 nodes) — ``NN-<prov>-ha-multiregion-summary.drawio``
- a **`landscape`** as-built (~34 nodes) — ``NN-<prov>-ha-multiregion-landscape.drawio``

The *numeric layout* of both diagrams is no longer hand-authored here. It is
computed by the declarative lane-grid layout engine
(:mod:`rule_engine.layout_engine`) from the two coordinate-free
:class:`~rule_engine.layout_engine.DiagramSpec` declarations in
:mod:`rule_engine.ha_multiregion_spec`. ``layout(spec)`` places every node on the
grid, sizes the nested containers with >= one grid step of padding, selects
contact points, and routes every edge in its own corridor — the geometry a
generator used to encode by hand. This module maps that placed geometry onto the
provider skin (icons + labels + container styles) and calls
:func:`rule_engine.diagram_layout.build_diagram`.

Per-provider generators supply only a :class:`ProviderSkin` — an *icon renderer
per neutral role* (how to draw one node's glyph), the three container styles, and
the provider's region/account labels. The geometry never forks: all four
providers share byte-identical node boxes, container boxes, and edge waypoints
(only icons/labels differ). This is verified by ``tests/test_ha_generator_parity.py``.

The class contract (see ``.kiro/steering/diagram-standards.md`` -> Diagram Class)
is carried in the companion ``.diagram.md`` frontmatter, not here: the summary
declares ``diagram_class: flow`` + ``detailed_view``, the landscape declares
``diagram_class: landscape`` + ``summary_of``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict, List

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
    CONTAINER_PAD,
)
from rule_engine.layout_engine import PlacedDiagram, layout  # noqa: E402
from rule_engine.ha_multiregion_spec import (  # noqa: E402
    LANDSCAPE_SPEC,
    SUMMARY_SPEC,
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
# Node display labels (provider-neutral role names; concrete service names live
# in the companion prose). Keyed by the node id declared in the two DiagramSpecs.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Placed-geometry → build_diagram mapping.
#
# ``layout(spec)`` returns a ``PlacedDiagram`` whose ``.nodes`` / ``.containers``
# / ``.edges`` carry the engine's computed geometry. The helpers below map that
# geometry onto the provider skin — the *same* mapping the engine's own oracle
# adapter (``layout_engine._serialize_candidate``) uses for stub icons, but with
# the REAL renderers, labels, and container styles.
# --------------------------------------------------------------------------- #

# Page margin past the rightmost/bottommost placed geometry (and past the
# right-margin Flow/Legend column), so the canvas fits with a small border.
_PAGE_MARGIN = 2 * CONTAINER_PAD  # 60, a whole grid multiple


def _nodes_from(placed: PlacedDiagram, skin: ProviderSkin) -> List[Node]:
    """Build the skinned ``Node`` list from the placed node boxes.

    Each node's role (which chooses the provider icon renderer) comes from its
    ``NodeSpec.role``; its coordinates come from the engine's placement."""
    role_of = {n.id: n.role for n in placed.spec.nodes}
    return [
        Node(
            id=n.id,
            label=LABELS.get(n.id, n.id),
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=skin.renderers[role_of[n.id]],
        )
        for n in placed.spec.nodes
    ]


def _boundaries_from(
    placed: PlacedDiagram, skin: ProviderSkin, labels: Dict[str, str]
) -> List[Boundary]:
    """Build the skinned ``Boundary`` list from the placed container boxes.

    The container box (x/y/w/h) comes from the engine; the concrete label
    (``labels`` keyed by container id) and the container style (keyed by the
    ``ContainerSpec.kind`` — account/vpc/az) come from the provider skin."""
    kind_of = {c.id: c.kind for c in placed.spec.containers}
    out: List[Boundary] = []
    for c in placed.spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        out.append(
            Boundary(
                id=c.id,
                label=labels[c.id],
                x=int(box.x),
                y=int(box.y),
                w=int(box.w),
                h=int(box.h),
                style=skin.container_styles[kind_of[c.id]],
            )
        )
    return out


def _edges_from(placed: PlacedDiagram) -> List[Edge]:
    """Build the ``Edge`` list from the placed edges (geometry-only; no skin)."""
    return [
        Edge(
            id=pe.spec.id,
            source=pe.spec.source,
            target=pe.spec.target,
            marker=pe.spec.marker,
            dashed=pe.spec.dashed,
            exit=pe.exit,
            entry=pe.entry,
            points=tuple((int(x), int(y)) for x, y in pe.points),
        )
        for pe in placed.edges
    ]


def _page_size(placed: PlacedDiagram) -> "tuple[int, int]":
    """Derive ``(page_w, page_h)`` from the placed geometry extent + margin.

    Width fits the rightmost of (every container/node right edge, the
    right-margin Flow/Legend column); height fits the lowest footprint. The
    Flow/Legend boxes grow *taller* (wrap) at the pinned ``legend_w``; a generous
    height margin leaves room for them below their start y."""
    rights = [b.right for b in placed.containers.values()]
    rights += [b.x + b.w for b in placed.nodes.values()]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.bottom for b in placed.containers.values()]
    bottoms += [b.y + b.h for b in placed.nodes.values()]
    page_w = int(max(rights)) + _PAGE_MARGIN
    page_h = int(max(bottoms)) + _PAGE_MARGIN
    return page_w, page_h


def build_summary(skin: ProviderSkin) -> str:
    """Build the <=12-node flow summary .drawio for ``skin``.

    The geometry is computed by ``layout(SUMMARY_SPEC)``; this only applies the
    provider skin (icons, region labels, container styles) and the provider
    title."""
    placed = layout(SUMMARY_SPEC)
    region_labels = {
        "nb_a": f"region-primary ({skin.region_primary})",
        "nb_b": f"region-passive ({skin.region_passive})",
    }
    boundaries = _boundaries_from(placed, skin, region_labels)
    nodes = _nodes_from(placed, skin)
    edges = _edges_from(placed)
    page_w, page_h = _page_size(placed)
    title = (f"{skin.provider} ha-multiregion-summary — {skin.account_label} / "
             f"{skin.region_primary}+{skin.region_passive} | 2026-09-23 | v1")
    return build_diagram(
        diagram_id=f"{skin.provider}-ha-summary",
        diagram_name=f"{skin.provider}-ha-multiregion-summary",
        title=title, boundaries=boundaries, nodes=nodes, edges=edges,
        flow_lines=placed.spec.flow_lines,
        legend_x=placed.legend_x, legend_w=placed.legend_w,
        page_w=page_w, page_h=page_h,
    )


def build_landscape(skin: ProviderSkin) -> str:
    """Build the ~34-node landscape as-built .drawio for ``skin``.

    The geometry is computed by ``layout(LANDSCAPE_SPEC)``; this only applies the
    provider skin (icons, account/vpc/az labels, container styles) and title."""
    placed = layout(LANDSCAPE_SPEC)
    labels = {
        "boundary-account": skin.account_label,
        "boundary-vpc-a": f"vpc-primary {skin.region_primary}",
        "boundary-vpc-b": f"vpc-passive {skin.region_passive}",
        "boundary-az-a1": "az-a1", "boundary-az-a2": "az-a2",
        "boundary-az-b1": "az-b1", "boundary-az-b2": "az-b2",
    }
    boundaries = _boundaries_from(placed, skin, labels)
    nodes = _nodes_from(placed, skin)
    edges = _edges_from(placed)
    page_w, page_h = _page_size(placed)
    title = (f"{skin.provider} ha-multiregion-landscape — {skin.account_label} / "
             f"{skin.region_primary}+{skin.region_passive} | 2026-09-23 | v1")
    return build_diagram(
        diagram_id=f"{skin.provider}-ha-landscape",
        diagram_name=f"{skin.provider}-ha-multiregion-landscape",
        title=title, boundaries=boundaries, nodes=nodes, edges=edges,
        flow_lines=placed.spec.flow_lines,
        legend_x=placed.legend_x, legend_y_flow=120, legend_y_legend=460,
        legend_w=placed.legend_w, page_w=page_w, page_h=page_h,
    )


def write_pair(skin: ProviderSkin, out_dir: Path, stem: str) -> List[Path]:
    """Write both .drawio files of the pair; return the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = out_dir / f"{stem}-summary.drawio"
    lp = out_dir / f"{stem}-landscape.drawio"
    sp.write_text(build_summary(skin), encoding="utf-8")
    lp.write_text(build_landscape(skin), encoding="utf-8")
    return [sp, lp]
