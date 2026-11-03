#!/usr/bin/env python3
"""Generate the **kubernetes** golden pair (summary + landscape) — 1.13.0 (v2).

The ``kubernetes`` Provider Profile (1.10.11) is an orchestrator-platform
profile, not a cloud account. This golden is the canonical demonstration of its
structural model, re-baselined ``v1 -> v2`` in 1.13.0 into a richer, realistic
multi-namespace cluster that still keeps the geometry the engine's (coordinate-
free specs only):

    Cluster  (boundary envelope, k8s-blue #326CE5)
      ├ Namespace: kube-system (control plane) ⊃ api / etcd / scheduler / cm
      ├ Namespace: ingress     ⊃ ingress Service / ingress controller
      ├ Namespace: app         ⊃ Service / Deployment / ReplicaSet / 2 Pods
      │                           + HPA / ConfigMap / ServiceAccount (supporting)
      └ Namespace: data        ⊃ Service / StatefulSet / PVC / Secret (supporting)

An external **client** (Ingress glyph) sits in the ``actors`` lane ABOVE the
cluster (the k8s profile draws cluster-edge ingress as an external actor,
cleared from the cluster top by the Theme 18 external-row fix — NOT in the
``edge`` lane, which is an in-boundary lane).

Control-plane objects and the per-namespace config/scaling/identity/secret
objects are marked ``overlay="supporting"`` — a dotted outline, documented in
the Legend, EXEMPT from ``node-connectivity`` and ``graph-islands`` — so they
need not sit on the numbered data-flow spine. The numbered spine traces the
request end-to-end: client -> ingress Service -> ingress controller -> app
Service -> Deployment -> ReplicaSet -> Pod -> data Service -> StatefulSet -> PVC.

Two artifacts, cross-linked (the sanctioned summary+landscape pair):

- ``01-kubernetes-architecture-summary.drawio`` — a ``flow`` summary (<= 12
  nodes): the shape of the system plus a supporting api-server node.
- ``01-kubernetes-architecture-landscape.drawio`` — a ``landscape`` as-built:
  four namespace bands with their full workload/config/storage objects.

Both are coordinate-free: the specs below declare only ``(role, lane, region,
slot, container, overlay)`` and ``layout()`` computes all geometry — so the
geometry is the engine's, not hand-placed (the 02-09 corpus convention). Icons
resolve through ``mappings/kubernetes-icons.yaml`` (official Kubernetes Icons
Set, file paths), container styles through its ``containers`` block.

Usage::

    python scripts/build_kubernetes_example.py                 # write both .drawio
    python scripts/build_kubernetes_example.py --stdout-summary
    python scripts/build_kubernetes_example.py --stdout-landscape
    python scripts/build_kubernetes_example.py --check          # compare, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine import draw_cli as dc  # noqa: E402
from rule_engine.diagram_layout import (  # noqa: E402
    build_diagram,
    legend_lines_for,
    OVERLAY_LEGEND_LINES,
)
from rule_engine.icon_resolver import resolve_container  # noqa: E402
from rule_engine.layout_engine import layout  # noqa: E402
from rule_engine.layout.model import (  # noqa: E402
    ContainerSpec as CS,
    DiagramSpec as DS,
    EdgeSpec as ES,
    NodeSpec as NS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "examples" / "kubernetes"
SUMMARY_OUT = OUT_DIR / "01-kubernetes-architecture-summary.drawio"
LANDSCAPE_OUT = OUT_DIR / "01-kubernetes-architecture-landscape.drawio"

PROVIDER = "kubernetes"


# --------------------------------------------------------------------------- #
# Summary spec (flow, <= 12 nodes) — the shape plus a supporting api-server.
# --------------------------------------------------------------------------- #

SUMMARY_TITLE = "kubernetes architecture — cluster-prod / default | 2026-10-29 | v2"


def summary_spec() -> DS:
    return DS(
        diagram_id="k8s-summary",
        diagram_name="kubernetes-architecture-summary",
        axis="north-south",
        nodes=(
            NS(id="client", role="k8s_ingress", lane="actors", region="", slot=0),
            # Namespace: app (region a) — the request path's compute tier.
            NS(id="ing", role="k8s_service", lane="router", region="a", slot=0, container="ns-app"),
            NS(id="app-svc", role="k8s_service", lane="router", region="a", slot=1, container="ns-app"),
            NS(id="deploy", role="k8s_deployment", lane="workers", region="a", slot=0, container="ns-app"),
            # Namespace: data (region b) — a disjoint peer band beside app.
            NS(id="data-svc", role="k8s_service", lane="router", region="b", slot=0, container="ns-data"),
            NS(id="sts", role="k8s_statefulset", lane="data", region="b", slot=0, container="ns-data"),
            NS(id="pvc", role="k8s_pvc", lane="data", region="b", slot=1, container="ns-data"),
            # Namespace: kube-system (region c) — one visible control-plane node,
            # supporting (dotted outline, off the numbered spine).
            NS(id="api", role="k8s_api", lane="platform", region="c", slot=0,
               container="ns-system", overlay="supporting"),
        ),
        edges=(
            ES(id="e1", source="client", target="ing", marker="1"),
            ES(id="e2", source="ing", target="app-svc", marker="2"),
            ES(id="e3", source="app-svc", target="deploy", marker="3"),
            ES(id="e4", source="deploy", target="data-svc", marker="4", kind_hint="cross-region"),
            ES(id="e5", source="data-svc", target="sts", marker="5"),
            ES(id="e6", source="sts", target="pvc", marker="6"),
            # The supporting api-server admits the Deployment (light edge; the
            # overlay already exempts it from connectivity, but an edge reads
            # better and keeps the control plane related to the workload).
            ES(id="e7", source="api", target="deploy", marker="7"),
        ),
        containers=(
            CS(id="cluster", kind="account", region="", parent=None, label_key="cluster"),
            # Namespaces are NOT mirror peers (unlike an HA active/passive pair),
            # so each sizes to its own content (fit_content) rather than being
            # equalized to a common width — which keeps three/four disjoint bands
            # snug and non-overlapping.
            CS(id="ns-app", kind="namespace", region="a", parent="cluster", label_key="ns-app", fit_content=True),
            CS(id="ns-data", kind="namespace", region="b", parent="cluster", label_key="ns-data", fit_content=True),
            CS(id="ns-system", kind="namespace", region="c", parent="cluster", label_key="ns-system", fit_content=True),
        ),
        flow_lines=(
            "Flow",
            "1. External client enters via the ingress Service",
            "2. Ingress Service routes to the app Service",
            "3. App Service to the Deployment",
            "4. App Deployment calls the data Service",
            "5. Data Service to the StatefulSet",
            "6. StatefulSet persists to its PersistentVolumeClaim",
            "7. API server admits the Deployment",
        ),
        title=SUMMARY_TITLE,
    )


# --------------------------------------------------------------------------- #
# Landscape spec (landscape, full as-built).
# --------------------------------------------------------------------------- #

LANDSCAPE_TITLE = "kubernetes architecture — cluster-prod / default | 2026-10-29 | v2"


def landscape_spec() -> DS:
    return DS(
        diagram_id="k8s-landscape",
        diagram_name="kubernetes-architecture-landscape",
        axis="north-south",
        nodes=(
            NS(id="client", role="k8s_ingress", lane="actors", region="", slot=0),
            # Bands read left -> right along the request flow: ingress (a) -> app
            # (b) -> data (c); the kube-system control plane (d) is a side
            # subsystem drawn rightmost. The client enters the LEFTMOST band, so
            # its drop into the ingress Service is a short, near-vertical run.
            # Namespace: ingress (region a)
            NS(id="ing-svc", role="k8s_service", lane="router", region="a", slot=0,
               container="ns-ingress"),
            NS(id="ing-ctrl", role="k8s_deployment", lane="workers", region="a", slot=0,
               container="ns-ingress"),
            # Namespace: app (region b)
            NS(id="app-svc", role="k8s_service", lane="router", region="b", slot=0,
               container="ns-app"),
            NS(id="app-deploy", role="k8s_deployment", lane="workers", region="b", slot=0,
               container="ns-app"),
            NS(id="app-rs", role="k8s_replicaset", lane="workers", region="b", slot=1,
               container="ns-app"),
            NS(id="pod1", role="k8s_pod", lane="workers", region="b", slot=2,
               container="ns-app"),
            NS(id="pod2", role="k8s_pod", lane="workers", region="b", slot=3,
               container="ns-app"),
            NS(id="app-hpa", role="k8s_hpa", lane="platform", region="b", slot=0,
               container="ns-app", overlay="supporting"),
            NS(id="app-cm", role="k8s_configmap", lane="platform", region="b", slot=1,
               container="ns-app", overlay="supporting"),
            NS(id="app-sa", role="k8s_sa", lane="platform", region="b", slot=2,
               container="ns-app", overlay="supporting"),
            # Namespace: data (region c)
            NS(id="data-svc", role="k8s_service", lane="router", region="c", slot=0,
               container="ns-data"),
            NS(id="data-sts", role="k8s_statefulset", lane="data", region="c", slot=0,
               container="ns-data"),
            NS(id="data-pvc", role="k8s_pvc", lane="data", region="c", slot=1,
               container="ns-data"),
            # secret at platform slot 0; its edge enters data-sts on a distinct
            # face from the spine edge (data-svc -> data-sts), avoiding an
            # entry-thirds merge on the StatefulSet top face.
            NS(id="data-secret", role="k8s_secret", lane="platform", region="c", slot=0,
               container="ns-data", overlay="supporting"),
            # Namespace: kube-system (region d) — the control plane, rightmost.
            # Every node is supporting (dotted outline), off the numbered spine;
            # only api<->etcd carries a light edge.
            NS(id="api", role="k8s_api", lane="platform", region="d", slot=0,
               container="ns-system", overlay="supporting"),
            NS(id="etcd", role="k8s_etcd", lane="data", region="d", slot=0,
               container="ns-system", overlay="supporting"),
            NS(id="sched", role="k8s_scheduler", lane="platform", region="d", slot=1,
               container="ns-system", overlay="supporting"),
            NS(id="cm-ctrl", role="k8s_controller_manager", lane="platform", region="d", slot=2,
               container="ns-system", overlay="supporting"),
        ),
        edges=(
            # Primary numbered spine 1-9: client enters the ingress namespace,
            # the ingress controller hands off to the app namespace, the app
            # Deployment runs its ReplicaSet/Pod, the app Pod calls the data
            # namespace Service, which backs the StatefulSet + PVC.
            ES(id="e1", source="client", target="ing-svc", marker="1"),
            ES(id="e2", source="ing-svc", target="ing-ctrl", marker="2"),
            # Cross-namespace handoffs carry kind_hint="cross-region" so the
            # router allocates each its OWN corridor instead of riding a
            # namespace border (a namespace is a region boundary here).
            ES(id="e3", source="ing-ctrl", target="app-svc", marker="3", kind_hint="cross-region"),
            ES(id="e4", source="app-svc", target="app-deploy", marker="4"),
            ES(id="e5", source="app-deploy", target="app-rs", marker="5"),
            ES(id="e6", source="app-rs", target="pod1", marker="6"),
            # The ReplicaSet runs BOTH pods — pod2 is on the spine too, so it is
            # not an island (app-sa is supporting and excluded from the island
            # calculation, so a supporting attachment alone would leave pod2
            # orphaned).
            ES(id="e7", source="app-rs", target="pod2", marker="7"),
            ES(id="e8", source="pod1", target="data-svc", marker="8", kind_hint="cross-region"),
            ES(id="e9", source="data-svc", target="data-sts", marker="9"),
            ES(id="e10", source="data-sts", target="data-pvc", marker="10"),
            # Supporting edges 11-14: each attaches ONE supporting node to one
            # spine node on a distinct target face, so no face carries merged
            # entries. The nodes are overlay=supporting, so they are exempt from
            # node-connectivity / graph-islands regardless of these edges.
            ES(id="e11", source="app-cm", target="app-deploy", marker="11"),
            ES(id="e12", source="app-hpa", target="app-rs", marker="12"),
            ES(id="e13", source="app-sa", target="pod2", marker="13"),
            ES(id="e14", source="data-secret", target="data-sts", marker="14"),
            # The only control-plane edge: the API server stores state in etcd.
            # scheduler + controller-manager stay edge-less (supporting exempts
            # them); the control plane is a legitimately separate component.
            ES(id="e15", source="api", target="etcd", marker="15"),
        ),
        containers=(
            CS(id="cluster", kind="account", region="", parent=None, label_key="cluster"),
            # Namespaces size to their own content (fit_content) — they are not
            # mirror peers, so four disjoint bands of different widths stay snug
            # and non-overlapping instead of being equalized to a common width.
            # Band order a..d reads ingress -> app -> data -> kube-system.
            CS(id="ns-ingress", kind="namespace", region="a", parent="cluster", label_key="ns-ingress", fit_content=True),
            CS(id="ns-app", kind="namespace", region="b", parent="cluster", label_key="ns-app", fit_content=True),
            CS(id="ns-data", kind="namespace", region="c", parent="cluster", label_key="ns-data", fit_content=True),
            CS(id="ns-system", kind="namespace", region="d", parent="cluster", label_key="ns-system", fit_content=True),
        ),
        flow_lines=(
            "Flow",
            "1. External client enters via the ingress Service",
            "2. Ingress Service routes to the ingress controller",
            "3. Ingress controller to the app Service",
            "4. App Service to the app Deployment",
            "5. Deployment manages its ReplicaSet",
            "6. ReplicaSet runs the first Pod",
            "7. ReplicaSet runs the second Pod",
            "8. App Pod calls the data Service",
            "9. Data Service to the StatefulSet",
            "10. StatefulSet persists to its PersistentVolumeClaim",
            "11. ConfigMap configures the Deployment",
            "12. HPA scales the ReplicaSet",
            "13. ServiceAccount identity for the second Pod",
            "14. Secret mounted by the StatefulSet",
            "15. API server stores state in etcd",
        ),
        title=LANDSCAPE_TITLE,
    )


# --------------------------------------------------------------------------- #
# Build via the shared placed → build_diagram path (draw_cli helpers).
# --------------------------------------------------------------------------- #

# Container labels keyed by container id (the k8s cluster + its namespaces).
_CONTAINER_LABELS = {
    "cluster": "Cluster: prod",
    "ns-system": "Namespace: kube-system",
    "ns-ingress": "Namespace: ingress",
    "ns-app": "Namespace: app",
    "ns-data": "Namespace: data",
}


def _build(spec: DS, *, extra_legend=()) -> str:
    placed = layout(spec)
    for warning in placed.layout_warnings:
        print(f"build_kubernetes_example: layout WARNING: {warning}", file=sys.stderr)

    renderers = dc._skin_renderers(PROVIDER, spec.nodes)
    nodes = dc._nodes_from(placed, renderers)
    edges = dc._edges_from(placed)
    boundaries = dc._boundaries_from(placed, PROVIDER, _CONTAINER_LABELS)
    page_w, page_h = dc._page_size(placed)

    # Preserve the auto-derived Legend (keeps the Outer-boundary line for the
    # cluster kind="account", drops the Inner-boundary line since namespaces are
    # kind="namespace", not "vpc") and append the supporting overlay line so
    # overlay-legend-coverage is satisfied.
    legend = legend_lines_for(boundaries) + tuple(extra_legend)

    return build_diagram(
        diagram_id=spec.diagram_id,
        diagram_name=spec.diagram_name,
        title=spec.title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=spec.flow_lines,
        legend_lines=legend,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        page_w=page_w,
        page_h=page_h,
        pinned_ids=(),  # layout()-routed edges, none hand-pinned
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the kubernetes golden pair.")
    ap.add_argument("--stdout-summary", action="store_true")
    ap.add_argument("--stdout-landscape", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    supporting = (OVERLAY_LEGEND_LINES["supporting"],)
    summary_xml = _build(summary_spec(), extra_legend=supporting)
    landscape_xml = _build(landscape_spec(), extra_legend=supporting)

    if args.stdout_summary:
        sys.stdout.write(summary_xml)
        return 0
    if args.stdout_landscape:
        sys.stdout.write(landscape_xml)
        return 0

    if args.check:
        ok = True
        for out, xml in ((SUMMARY_OUT, summary_xml), (LANDSCAPE_OUT, landscape_xml)):
            cur = out.read_text(encoding="utf-8") if out.exists() else None
            status = "ok" if cur == xml else "STALE"
            if cur != xml:
                ok = False
            print(f"  {status:8} {out.name}")
        return 0 if ok else 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUT.write_text(summary_xml, encoding="utf-8")
    LANDSCAPE_OUT.write_text(landscape_xml, encoding="utf-8")
    print(f"wrote {SUMMARY_OUT}")
    print(f"wrote {LANDSCAPE_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
