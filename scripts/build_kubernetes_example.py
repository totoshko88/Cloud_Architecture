#!/usr/bin/env python3
"""Generate the **kubernetes** golden pair (summary + landscape) — 1.10.11.

The ``kubernetes`` Provider Profile (1.10.11) is an orchestrator-platform
profile, not a cloud account. This golden is the canonical demonstration of its
structural model:

    Cluster  (boundary envelope, k8s-blue #326CE5)
      ├ Namespace: app   (leaf boundary)  ⊃ ingress-svc / deployment / pods
      └ Namespace: data  (leaf boundary)  ⊃ service / statefulset / pvc

An external **Ingress** actor sits in the ``actors`` lane ABOVE the cluster
(the k8s profile draws cluster-edge ingress as an external actor, cleared from
the cluster top by the Theme 18 external-row fix added in 1.10.11 — NOT in the
``edge`` lane, which is an in-boundary lane).

Two artifacts, cross-linked (the sanctioned summary+landscape pair):

- ``01-kubernetes-architecture-summary.drawio`` — a ``flow`` summary (<= 12
  nodes): the shape of the system (ingress -> service -> deployment -> data).
- ``01-kubernetes-architecture-landscape.drawio`` — a ``landscape`` as-built:
  both namespaces with their full workload/config/storage objects.

Both are coordinate-free: the specs below declare only ``(role, lane, region,
slot, container)`` and ``layout()`` computes all geometry — so the geometry is
the engine's, not hand-placed (the 02-09 corpus convention). Icons resolve
through ``mappings/kubernetes-icons.yaml`` (official Kubernetes Icons Set, file
paths), container styles through its ``containers`` block.

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
from rule_engine.diagram_layout import build_diagram  # noqa: E402
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
# Icon + container-style resolution (via mappings/kubernetes-icons.yaml), reusing
# the shared draw_cli helpers so the k8s golden follows the exact placed→
# build_diagram path every snapshot-driven diagram uses.
# --------------------------------------------------------------------------- #


def _container_styles():
    return {
        "boundary": resolve_container("boundary", PROVIDER)["style_string"],
        "namespace": resolve_container("namespace", PROVIDER)["style_string"],
    }


# --------------------------------------------------------------------------- #
# Summary spec (flow, <= 12 nodes) — the shape.
# --------------------------------------------------------------------------- #

SUMMARY_TITLE = "kubernetes architecture — cluster prod / ns app+data | 2026-10-14 | v1"


def summary_spec() -> DS:
    return DS(
        diagram_id="k8s-summary",
        diagram_name="kubernetes-architecture-summary",
        axis="north-south",
        nodes=(
            NS(id="ingress", role="k8s_ingress", lane="actors", region="", slot=0),
            NS(id="svc", role="k8s_service", lane="router", region="a", slot=0, container="ns-app"),
            NS(id="deploy", role="k8s_deployment", lane="workers", region="a", slot=0, container="ns-app"),
            NS(id="sts", role="k8s_statefulset", lane="data", region="a", slot=0, container="ns-data"),
            NS(id="pvc", role="k8s_pvc", lane="data", region="a", slot=1, container="ns-data"),
        ),
        edges=(
            ES(id="e1", source="ingress", target="svc", marker="1"),
            ES(id="e2", source="svc", target="deploy", marker="2"),
            ES(id="e3", source="deploy", target="sts", marker="3"),
            ES(id="e4", source="sts", target="pvc", marker="4"),
        ),
        containers=(
            CS(id="cluster", kind="account", region="", parent=None, label_key="cluster"),
            CS(id="ns-app", kind="namespace", region="a", parent="cluster", label_key="ns-app"),
            CS(id="ns-data", kind="namespace", region="a", parent="cluster", label_key="ns-data"),
        ),
        flow_lines=(
            "Flow",
            "1. External traffic enters via the Ingress",
            "2. Service routes to the app Deployment",
            "3. App reads/writes the data StatefulSet",
            "4. StatefulSet persists to its PersistentVolumeClaim",
        ),
        title=SUMMARY_TITLE,
    )


# --------------------------------------------------------------------------- #
# Landscape spec (landscape, full as-built).
# --------------------------------------------------------------------------- #

LANDSCAPE_TITLE = "kubernetes architecture — cluster prod / ns app+data | 2026-10-14 | v1"


def landscape_spec() -> DS:
    return DS(
        diagram_id="k8s-landscape",
        diagram_name="kubernetes-architecture-landscape",
        axis="north-south",
        nodes=(
            NS(id="ingress", role="k8s_ingress", lane="actors", region="", slot=0),
            # Namespace: app
            NS(id="svc-app", role="k8s_service", lane="router", region="a", slot=0, container="ns-app"),
            NS(id="deploy", role="k8s_deployment", lane="workers", region="a", slot=0, container="ns-app"),
            NS(id="pod1", role="k8s_pod", lane="workers", region="a", slot=1, container="ns-app"),
            NS(id="pod2", role="k8s_pod", lane="workers", region="a", slot=2, container="ns-app"),
            NS(id="hpa", role="k8s_hpa", lane="platform", region="a", slot=0, container="ns-app"),
            NS(id="cm", role="k8s_configmap", lane="platform", region="a", slot=1, container="ns-app"),
            # Namespace: data (distinct slots within each shared lane/region)
            NS(id="svc-data", role="k8s_service", lane="router", region="a", slot=1, container="ns-data"),
            NS(id="sts", role="k8s_statefulset", lane="data", region="a", slot=0, container="ns-data"),
            NS(id="pvc", role="k8s_pvc", lane="data", region="a", slot=1, container="ns-data"),
            NS(id="secret", role="k8s_secret", lane="platform", region="a", slot=2, container="ns-data"),
        ),
        edges=(
            ES(id="e1", source="ingress", target="svc-app", marker="1"),
            ES(id="e2", source="svc-app", target="deploy", marker="2"),
            ES(id="e3", source="deploy", target="pod1", marker="3"),
            ES(id="e4", source="deploy", target="pod2", marker="4"),
            ES(id="e5", source="hpa", target="deploy", marker="5"),
            ES(id="e6", source="cm", target="deploy", marker="6"),
            ES(id="e7", source="deploy", target="svc-data", marker="7"),
            ES(id="e8", source="svc-data", target="sts", marker="8"),
            ES(id="e9", source="sts", target="pvc", marker="9"),
            ES(id="e10", source="secret", target="sts", marker="10"),
        ),
        containers=(
            CS(id="cluster", kind="account", region="", parent=None, label_key="cluster"),
            CS(id="ns-app", kind="namespace", region="a", parent="cluster", label_key="ns-app"),
            CS(id="ns-data", kind="namespace", region="a", parent="cluster", label_key="ns-data"),
        ),
        flow_lines=(
            "Flow",
            "1. Ingress -> app Service",
            "2. Service -> Deployment",
            "3-4. Deployment manages its Pods",
            "5. HPA scales the Deployment",
            "6. ConfigMap configures the Deployment",
            "7. App -> data Service",
            "8. Service -> StatefulSet",
            "9. StatefulSet -> PersistentVolumeClaim",
            "10. Secret mounted by the StatefulSet",
        ),
        title=LANDSCAPE_TITLE,
    )


# --------------------------------------------------------------------------- #
# Build via the shared placed → build_diagram path (draw_cli helpers).
# --------------------------------------------------------------------------- #

# Container labels keyed by container id (the k8s cluster + its two namespaces).
_CONTAINER_LABELS = {
    "cluster": "Cluster: prod",
    "ns-app": "Namespace: app",
    "ns-data": "Namespace: data",
}


def _build(spec: DS) -> str:
    placed = layout(spec)
    for warning in placed.layout_warnings:
        print(f"build_kubernetes_example: layout WARNING: {warning}", file=sys.stderr)

    renderers = dc._skin_renderers(PROVIDER, [n.role for n in spec.nodes])
    nodes = dc._nodes_from(placed, renderers)
    edges = dc._edges_from(placed)
    boundaries = dc._boundaries_from(placed, PROVIDER, _CONTAINER_LABELS)
    page_w, page_h = dc._page_size(placed)

    return build_diagram(
        diagram_id=spec.diagram_id,
        diagram_name=spec.diagram_name,
        title=spec.title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=spec.flow_lines,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        page_w=page_w,
        page_h=page_h,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the kubernetes golden pair.")
    ap.add_argument("--stdout-summary", action="store_true")
    ap.add_argument("--stdout-landscape", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    summary_xml = _build(summary_spec())
    landscape_xml = _build(landscape_spec())

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
