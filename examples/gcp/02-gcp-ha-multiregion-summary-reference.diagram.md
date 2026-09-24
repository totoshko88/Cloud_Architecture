---
id: gcp-ha-multiregion-summary-v1
title: GCP HA Multi-Region — Summary
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-09-23
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-23
diagram_class: flow
detailed_view: 02-gcp-ha-multiregion-landscape
tags:
  - gcp
  - ha
  - multi-region
  - active-passive
  - golden-example
  - flow-summary
related_docs:
  - 02-gcp-ha-multiregion-landscape.diagram.md
---

# GCP HA Multi-Region — Summary

## Overview

This is the `flow`-class summary of the GCP highly available, active-passive
multi-region reference workload in Project acme-prod. It answers one question — how does a
request move end-to-end — and deliberately holds at most twelve nodes so a
reviewer sees the shape of the system at a glance. Traffic enters through global
DNS failover, which routes to the active region (us-central1) and holds the passive
region (us-west1) on standby behind health checks. Each region runs a load
balancer, an application tier, a database, and an object store. The single most
important cross-region relationship — database replication — is shown explicitly.
This summary is cross-linked to its detailed as-built via `detailed_view`, so the
pair reads together: shape first, full inventory second.

## Main Content

Nodes are laid out North–South by tier and East–West by region: the active
region on the left, the passive peer on the right, mirrored. Numbered flow
markers 1–9 trace the primary path (DNS → primary LB → app → database, with the
object-store write) and the standby path (DNS → passive LB → app → regional
stores), then the cross-region database replication edge that keeps the passive
region warm. Dashed edges denote the standby and replication flows; solid edges
denote the live primary flow. Every node uses a resolved GCP provider icon and a
hyphenated identifier, so `node-quote` and `icon-resolved` pass. Because the
diagram is `flow`-class, the twelve-node cap applies and this artifact stays at
nine nodes, comfortably eligible for publication.

## Troubleshooting

If the Linter reports `node-count` on this file, it has drifted above twelve
nodes — move the additional detail into the paired landscape as-built rather than
growing the summary, because the summary's whole job is to stay small and
legible. An `orphan-landscape` finding never applies here, since that rule is
landscape-only. A `frontmatter` CRITICAL names the offending key: keep all twelve
required keys present and non-empty, plus the `diagram_class: flow` marker and
the `detailed_view` cross-link that binds this summary to its as-built. If
`companion-doc` fires, the `.drawio` stem and this file's stem have diverged —
keep them identical so the pairing resolves. A `title-versioned` warning means
the title cell lost its `vN` version token or its ISO 8601 date; both must be
present in the title cell for the artifact to pass cleanly.

## See Also

This summary pairs with `02-gcp-ha-multiregion-landscape.drawio` — the `landscape`-class as-built of the same
system — through the `detailed_view` / `summary_of` cross-link that the Linter
checks as one publishable unit, so the two artifacts are always reviewed
together. See `.kiro/steering/diagram-standards.md` (Diagram Class) for the
flow-versus-landscape contract, the overlay vocabulary, and the named routing
patterns, and `.kiro/steering/diagram-lint.md` for the class-aware rule
severities that make `node-count` an error here but a warning on the as-built.
The four provider profiles each ship this same summary-plus-landscape pair, so
the AWS, Azure, GCP, and OCI examples are directly comparable node for node. For
the exact icon styles used in this diagram, see the per-provider mapping under
`mappings/`, and for the frontmatter contract this document satisfies, see
`.kiro/steering/kb-frontmatter.md`.
