---
id: kubernetes-architecture-summary-v1
title: Kubernetes Architecture — Summary
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-10-14
owner: platform-engineering
author: rule-engine
next_review_date: 2027-04-14
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
the orchestrator-platform profile added in 1.10.11, which models a Cluster as the
boundary envelope and a Namespace as a leaf boundary that holds workloads
directly. It answers one question: how does a request move end-to-end through a
cluster. External traffic enters at the Ingress, which sits outside the cluster
in the external actors lane; the app namespace routes it through a Service to a
Deployment; the data namespace runs a StatefulSet backed by a
PersistentVolumeClaim. The two namespaces are drawn as disjoint peer bands inside
the Cluster envelope, each a captioned Kubernetes-blue box. The summary stays at
five nodes, well under the twelve-node flow cap, and cross-links its full
as-built via `detailed_view`.

## Main Content

Nodes are laid out North–South by tier — Ingress at the top (external), then the
app namespace's Service and Deployment, then the data namespace's StatefulSet and
its PersistentVolumeClaim. The app namespace (region a) and the data namespace
(region b) sit side by side as disjoint peer bands, so a node is unambiguously a
member of exactly one namespace. Numbered flow markers 1–4 trace the primary
path: Ingress to Service, Service to Deployment, Deployment to the data
StatefulSet, StatefulSet to its PersistentVolumeClaim. Every node uses an
official Kubernetes Icons Set glyph (Apache-2.0 / CC-BY-4.0) resolved through
`mappings/kubernetes-icons.yaml`, and the cluster/namespace boxes use the
profile's Kubernetes-blue container styles. The Ingress sits in the external
actors lane and its edge correctly crosses the cluster boundary.

## Troubleshooting

If the Linter reports `node-count` on this file, it has drifted above twelve
nodes — move the extra detail into the paired landscape as-built rather than
growing the summary. An `orphan-landscape` finding never applies here, since that
rule is landscape-only. A `frontmatter` CRITICAL names the offending key: keep
all twelve required keys present and non-empty, plus the `diagram_class: flow`
marker and the `detailed_view` cross-link. If `companion-doc` fires, the `.drawio`
stem and this file's stem have diverged — keep them identical. If a namespace box
is drawn with a solid fill it stops being recognised as a boundary container (the
detector wants a dashed, `fillColor=none` rectangle), so its child workloads lose
their membership — keep the namespace style borderless-dashed. Draw the Ingress in
the `actors` lane, not `edge`, so it sits above the cluster.

## See Also

This summary pairs with `01-kubernetes-architecture-landscape.drawio` — the
`landscape`-class as-built of the same cluster — through the `detailed_view` /
`summary_of` cross-link the Linter checks as one publishable unit, so the two
artifacts are reviewed together. See `.kiro/steering/provider-profiles.md` for
the kubernetes profile's terminology row (Cluster / Namespace / Deployment / …)
and the Kubernetes-blue brand anchor, and `.kiro/steering/diagram-standards.md`
(Diagram Class) for the flow-versus-landscape contract. The namespace leaf
boundary reuses the same disjoint-sibling placement and bottom-up container
sizing as the peer-account containers, so this golden is directly comparable to
the cross-cloud examples. For the icon styles, see
`mappings/kubernetes-icons.yaml`; for the frontmatter contract this document
satisfies, see `.kiro/steering/kb-frontmatter.md`.
