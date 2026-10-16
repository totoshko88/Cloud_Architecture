---
id: kubernetes-architecture-landscape-v1
title: Kubernetes Architecture — Landscape
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-10-14
owner: platform-engineering
author: rule-engine
next_review_date: 2027-04-14
diagram_class: landscape
summary_of: 01-kubernetes-architecture-summary
diagram_type: deployment
tags:
  - kubernetes
  - k8s
  - namespace
  - workloads
  - golden-example
  - landscape
related_docs:
  - 01-kubernetes-architecture-summary.diagram.md
---

# Kubernetes Architecture — Landscape

## Overview

This is the `landscape`-class as-built of the `kubernetes` Provider Profile
golden — the full inventory of a cluster on one canvas, the companion to the
flow summary it cross-links via `summary_of`. It answers what is actually
deployed and how it relates at once. The Cluster envelope holds two disjoint
Namespace peer bands: `app` (region a) with its Service, Deployment, two Pods,
a HorizontalPodAutoscaler and a ConfigMap; and `data` (region b) with its
Service, StatefulSet, PersistentVolumeClaim and a Secret. External traffic
enters at the Ingress in the actors lane above the cluster. Every workload,
config and storage object that the cluster runs appears as its own node, so the
diagram is a complete picture rather than a shape — which is exactly the division
of labour between a landscape and its summary.

## Main Content

The layout is North–South by tier, East–West by namespace: `app` on the left,
`data` on the right, each a captioned Kubernetes-blue leaf boundary nested in the
Cluster envelope. Ten numbered flow markers trace the deployment's relationships:
Ingress to Service, Service to Deployment, the Deployment managing its two Pods,
the HPA scaling the Deployment and the ConfigMap configuring it, then the app
reaching the data namespace's Service, its StatefulSet, the PersistentVolumeClaim
and the mounted Secret. Each node resolves to an official Kubernetes Icons Set
glyph through `mappings/kubernetes-icons.yaml`; the namespace boxes are dashed,
borderless Kubernetes-blue rectangles so the geometry parser recognises them as
boundary containers and each workload nests as a structural member. The Ingress
edge crosses the cluster boundary from the external lane, which is correct.

## Troubleshooting

If the Linter reports `orphan-landscape`, the `summary_of` cross-link is missing
or does not resolve — keep it pointed at `01-kubernetes-architecture-summary`.
A `node-count` warning above thirty nodes, or an error above fifty, means the
cluster inventory outgrew one canvas; split it per subsystem with an index rather
than dropping nodes. A `geometric-containment` or `structural-integrity` finding
means a workload is not nesting under its namespace — check that the namespace
style stays dashed with `fillColor=none` so the detector treats it as a boundary
(a solid fill silently demotes it to a plain rectangle and its children lose
membership). `container-dead-space` on a namespace is advisory: it flags a box
much larger than its children, which a sparse namespace can trip without being
wrong. `edge-crossing-excess` is a non-blocking warning for a landscape; the
numbered flow legend documents every marker.

## See Also

This as-built pairs with `01-kubernetes-architecture-summary.drawio` — the
`flow`-class summary of the same cluster — through the `summary_of` /
`detailed_view` cross-link the Linter validates as one publishable unit. See
`.kiro/steering/provider-profiles.md` for the kubernetes profile (Cluster as the
boundary, Namespace as the network boundary / leaf, the Kubernetes-blue brand
anchor) and `.kiro/steering/asset-packs.md` for the official Kubernetes Icons Set
pack (Apache-2.0 / CC-BY-4.0, fetched from kubernetes/community at a pinned
commit). The namespace leaf boundary reuses the disjoint-sibling placement and
bottom-up sizing added for peer-account containers, so this landscape is directly
comparable to the cross-cloud as-built. The `diagram_type: deployment` key marks
this a deployment view for the taxonomy. For the icon styles, see
`mappings/kubernetes-icons.yaml`; for the frontmatter contract, see
`.kiro/steering/kb-frontmatter.md`.
