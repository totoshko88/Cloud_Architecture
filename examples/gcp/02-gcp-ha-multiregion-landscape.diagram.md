---
id: gcp-ha-multiregion-landscape-v1
title: GCP HA Multi-Region — Landscape (as-built)
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-09-23
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-23
diagram_class: landscape
summary_of: 02-gcp-ha-multiregion-summary
tags:
  - gcp
  - ha
  - multi-region
  - active-passive
  - golden-example
  - landscape-asbuilt
related_docs:
  - 02-gcp-ha-multiregion-summary.diagram.md
---

# GCP HA Multi-Region — Landscape (as-built)

## Overview

This is the `landscape`-class as-built of the GCP active-passive multi-region
workload in Project acme-prod. Where the paired summary shows the shape, this diagram shows
what is actually deployed: two regions (us-central1 primary, us-west1 passive), each with
two availability zones, full application, cache, database, object-store, queue,
worker, secrets, and observability tiers, wrapped in a nested container hierarchy
(account → region VPC → availability zone). Its value is completeness on one
canvas, so it deliberately exceeds the twelve-node flow cap — the `landscape`
class relaxes `node-count` to a warning while making container padding an error,
because the nested boundaries are what keep thirty-plus nodes legible. It
cross-links back to its summary via `summary_of`.

## Main Content

The diagram carries about thirty-four nodes across the two regions. Each region
frame nests two availability-zone boundaries; every node sits inside its zone or
region with at least one grid step of padding, so the raised
`container-padding` error stays clean. Numbered markers trace DNS failover to
both regions, the load-balancer fan-out to per-AZ application tiers, in-region
standby database replication, cross-region database and object-store
replication, and the async queue-to-worker path. Dashed edges mark standby,
asynchronous, and replication flows. Parallel runs use explicit waypoint
corridors so no two edges share a lane and none crosses an unrelated icon,
satisfying `edge-routing`. Every node uses a resolved GCP icon.

## Troubleshooting

A `node-count` finding here is a WARNING, not an error, up to fifty nodes — that
is expected for an as-built and does not block publication. An
`orphan-landscape` ERROR means the `summary_of` cross-link is missing or does not
name the sibling flow summary — restore it so the pair resolves. A
`container-padding` finding is an ERROR for this class: a node has drifted within
one grid step of a boundary, or straddles one; nudge it back onto the padded
grid. `node-overlap` or `grid-alignment` warnings indicate a node moved off the
ten-unit grid rhythm. Keep the `diagram_class: landscape` frontmatter key present
or the file silently reverts to the stricter flow rules and the twelve-node cap
will then block it.

## See Also

This as-built pairs with `02-gcp-ha-multiregion-summary.drawio` — the twelve-node-or-fewer `flow` summary of
the same system — via the `summary_of` cross-link the Linter validates as a
single publishable unit, so reviewers read the shape first and drill in here for
detail. The overlay vocabulary for findings and state
(spec-required-not-deployed, observability overlay, and the change markers) is
documented in `.kiro/steering/diagram-standards.md` under Overlay Vocabulary;
this example keeps a clean as-built without overlay markers so it stays a
reference. See `.kiro/steering/diagram-lint.md` (Diagram Class) for the
class-aware severities, `.kiro/steering/kb-frontmatter.md` for the frontmatter
contract, and the sibling AWS, Azure, GCP, and OCI landscape examples for a
cross-provider comparison of the identical HA multi-region pattern.
