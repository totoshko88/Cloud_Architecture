---
id: kubernetes-architecture-summary-v2
title: Kubernetes Architecture — Summary
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-10-29
owner: platform-engineering
author: rule-engine
next_review_date: 2027-04-29
diagram_class: flow
detailed_view: 01-kubernetes-architecture-landscape
tags:
  - kubernetes
  - k8s
  - namespace
  - workloads
  - golden-example
  - flow-summary
related_docs:
  - 01-kubernetes-architecture-landscape.diagram.md
---

# Kubernetes Architecture — Summary

## Overview

This is the `flow`-class summary of the `kubernetes` Provider Profile golden —
the orchestrator-platform profile that models a Cluster as the boundary envelope
and a Namespace as a leaf boundary holding workloads directly. It answers one
question: how does a request move end-to-end through a cluster. An external
client enters at the ingress Service in the app namespace, which routes it to the
app Service and its Deployment; the Deployment then calls the data namespace,
whose Service backs a StatefulSet persisted by a PersistentVolumeClaim. A single
control-plane node, the API server, sits in a kube-system namespace band marked
as a supporting service so the reader sees the control plane without it cluttering
the request path. The summary stays at eight nodes, well under the twelve-node
flow cap, and cross-links its full as-built via `detailed_view`. This is the v2
re-baseline, richer than the earlier five-node line.

## Main Content

Three namespaces are drawn as disjoint peer bands inside the Cluster envelope:
app (region a) with the ingress Service, app Service and Deployment; data
(region b) with the Service, StatefulSet and PersistentVolumeClaim; and
kube-system (region c) with the supporting API server. Numbered flow markers one
through six trace the primary path — client to ingress Service, ingress Service
to app Service, app Service to Deployment, Deployment to the data Service, data
Service to the StatefulSet, StatefulSet to its PersistentVolumeClaim — and marker
seven shows the API server admitting the Deployment. The API server carries the
`supporting` overlay, a dotted outline documented in the Legend, so it is exempt
from the connectivity rules and reads as an ops concern rather than a flow step.
Every node uses an official Kubernetes Icons Set glyph resolved through
`mappings/kubernetes-icons.yaml`, and each namespace box uses the profile's
Kubernetes-blue container style.

## Troubleshooting

If the Linter reports `node-count` on this file, it has drifted above twelve
nodes — move the extra detail into the paired landscape as-built rather than
growing the summary. An `orphan-landscape` finding never applies here, since that
rule is landscape-only. A `frontmatter` CRITICAL names the offending key: keep
all twelve required keys present and non-empty, plus the `diagram_class: flow`
marker and the `detailed_view` cross-link. If `overlay-legend-coverage` fires on
`supporting`, the Legend lost its supporting line — the generator appends it to
the auto-derived Legend, so keep that wiring. If `companion-doc` fires, the
`.drawio` stem and this file's stem have diverged — keep them identical. If a
namespace box is drawn with a solid fill it stops being recognised as a boundary
container, so its children lose membership — keep the namespace style
borderless-dashed. Draw the client in the `actors` lane so it sits above the
cluster.

## See Also

This summary pairs with `01-kubernetes-architecture-landscape.drawio` — the
`landscape`-class as-built of the same cluster — through the `detailed_view` /
`summary_of` cross-link the Linter checks as one publishable unit, so the two
artifacts are reviewed together. See `.kiro/steering/provider-profiles.md` for
the kubernetes profile's terminology row (Cluster / Namespace / Deployment / …)
and the Kubernetes-blue brand anchor, and `.kiro/steering/diagram-standards.md`
(Diagram Class) for the flow-versus-landscape contract and the `supporting`
overlay vocabulary. The namespace leaf boundary reuses the disjoint-sibling
placement and bottom-up container sizing as the peer-account containers, so this
golden is directly comparable to the cross-cloud examples. For the icon styles,
see `mappings/kubernetes-icons.yaml`; for the frontmatter contract this document
satisfies, see `.kiro/steering/kb-frontmatter.md`. This is the v2 re-baseline.
