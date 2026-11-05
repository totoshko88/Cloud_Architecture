---
id: kubernetes-architecture-landscape-v2
title: Kubernetes Architecture — Landscape
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-10-29
owner: platform-engineering
author: rule-engine
next_review_date: 2027-04-29
diagram_class: landscape
summary_of: 01-kubernetes-architecture-summary
diagram_type: deployment
tags:
  - kubernetes
  - k8s
  - namespace
  - workloads
  - control-plane
  - golden-example
  - landscape
related_docs:
  - 01-kubernetes-architecture-summary.diagram.md
---

# Kubernetes Architecture — Landscape

## Overview

This is the `landscape`-class as-built of the `kubernetes` Provider Profile
golden — the full inventory of a cluster on one canvas, the companion to the flow
summary it cross-links via `summary_of`. It answers what is actually deployed and
how it relates at once. The Cluster envelope holds four disjoint Namespace peer
bands drawn side by side: ingress, with its Service and ingress controller; app,
with a Service, Deployment, ReplicaSet, two Pods, a HorizontalPodAutoscaler, a
ConfigMap and a ServiceAccount; data, with a Service, StatefulSet,
PersistentVolumeClaim and a Secret; and kube-system, the control plane, with the
API server, etcd, scheduler and controller-manager. An external client enters at
the ingress band above the cluster. This v2 re-baseline replaces the earlier
sparse two-namespace shape with nineteen objects across four namespaces,
including a first-class control-plane band.

## Main Content

The layout is North–South by tier, East–West by namespace, so the four bands read
left to right along the request flow: ingress, then app, then data, with the
kube-system control plane drawn rightmost as a side subsystem. A numbered spine of
markers one through ten traces the request: client to the ingress Service, the
ingress controller handing off to the app Service, the Deployment managing its
ReplicaSet and two Pods, then the app Pod reaching the data Service, its
StatefulSet and the PersistentVolumeClaim. Supporting markers eleven through
fifteen attach the ConfigMap, HPA, ServiceAccount, Secret and the API-server /
etcd pair. The control-plane nodes and the per-namespace config, scaling,
identity and secret objects carry the `supporting` overlay — a dotted outline
documented in the Legend — so they are exempt from `node-connectivity` and
`graph-islands`. Each namespace box is a dashed, borderless Kubernetes-blue
rectangle so the geometry parser nests its workloads as structural members.

## Troubleshooting

If the Linter reports `orphan-landscape`, the `summary_of` cross-link is missing
or does not resolve — keep it pointed at `01-kubernetes-architecture-summary`.
A `node-count` warning above thirty nodes, or an error above fifty, means the
cluster inventory outgrew one canvas; split it per subsystem with an index. A
`geometric-containment` or `structural-integrity` finding means a workload is not
nesting under its namespace — check the namespace style stays dashed with
`fillColor=none` so the detector treats it as a boundary. `graph-islands` is a
tolerated warning here: the control plane is a legitimately separate component,
and its supporting nodes are exempt. `sibling-size-uniformity` is advisory because
the four namespaces are deliberately different sizes, not mirror peers.
`canvas-quality` can warn on aspect ratio since four side-by-side bands make a wide
canvas. `overlay-legend-coverage` must stay clear — the generator appends the
`supporting` line to the Legend.

## See Also

This as-built pairs with `01-kubernetes-architecture-summary.drawio` — the
`flow`-class summary of the same cluster — through the `summary_of` /
`detailed_view` cross-link the Linter validates as one publishable unit. See
`.kiro/steering/provider-profiles.md` for the kubernetes profile (Cluster as the
boundary, Namespace as the network boundary / leaf, the Kubernetes-blue brand
anchor) and `.kiro/steering/asset-packs.md` for the official Kubernetes Icons Set
pack (Apache-2.0 / CC-BY-4.0, fetched from kubernetes/community at a pinned
commit). The namespace leaf boundary reuses the disjoint-sibling placement and
bottom-up sizing, now generalised to four peer bands, so this landscape is
directly comparable to the cross-cloud as-built. The `diagram_type: deployment`
key marks this a deployment view for the taxonomy. For the icon styles, see
`mappings/kubernetes-icons.yaml`; for the frontmatter contract, see
`.kiro/steering/kb-frontmatter.md`. This is the v2 re-baseline.
