---
id: 05-flow-sandbox-lifecycle-v3
title: SEP sandbox lifecycle — the SQS dance with Syndicate Server
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-17
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-17
diagram_class: flow
diagram_type: data-flow
tags:
  - aws
  - sep
  - flow
  - data-flow
  - sqs
  - sandbox-lifecycle
  - 870325637521
  - eu-central-1
related_docs:
  - 01-sep-context.diagram.md
  - 03-sep-account-landscape.diagram.md
  - INVENTORY-STATE.md
change_log:
  - date: 2026-10-17
    note: v4 — icon fidelity pass. The external Syndicate Server, an EC2 host drawn as its own node, now uses the real EC2 service icon instead of a neutral box. It stays external (outside the account boundary). MongoDB Atlas brand leaf unchanged.
---

# SEP sandbox lifecycle — the SQS dance

## Overview

This data-flow diagram shows how the Syndicate Education Platform (SEP) allocates, activates and tears down a sandbox AWS account for a student task, in the production account `870325637521` in `eu-central-1`. It is a first-draft `flow` view of the asynchronous SQS "dance" between SEP and the external Syndicate Server, drawn left to right along the message path. Only the SEP cloud nodes sit inside the AWS Account boundary: `se-management-api-handler` (Lambda) and the four lifecycle SQS queues, all regional services reached over endpoints, so they live in the Account but outside any VPC. The Syndicate Server (an EC2 host) and MongoDB Atlas are external systems drawn outside the boundary: the Server now carries the real EC2 service icon because it is an EC2 host drawn as its own node, and Atlas carries MongoDB's own brand-green leaf. Neither is a faked look-alike — each wears its true resource glyph. The facts come from the live read-only inventory in `INVENTORY-STATE.md` and the architecture guide section 7.2.2; the queue-to-consumer wiring was verified against the account, not inferred from code.

## Main Content

The dance uses four SQS queues, split by direction. On the send side (SEP to Server), the Lambda enqueues an allocation request on `allocation-queue`; the Syndicate Server consumes it and provisions a sandbox AWS account. The Server returns the provisioned account data on `activation-queue`, which `se-management-api-handler` consumes through a confirmed event-source mapping. On a terminal task state or a student destroy, the Lambda sends cleanup on `deletion-queue`; the Server consumes it, runs AWS Nuke on the sandbox, then confirms teardown on `deletion-notification-queue`, which the handler also consumes through a confirmed event-source mapping. Finally the handler persists the sandbox and application state in the external MongoDB Atlas cluster over VPC peering. The key verified asymmetry: `allocation-queue` and `deletion-queue` have no Lambda consumer in SEP — the Syndicate Server consumes them over the integration — while `activation-queue` and `deletion-notification-queue` are consumed by the handler.

## Troubleshooting

If the layout engine prints a warning, read `placed.layout_warnings` and fix the coordinate-free spec in `scripts/build_flow_sandbox_lifecycle.py`, never the generated `.drawio`. The request-reply pattern is a cycle, so some queue edges are back-edges by nature: the return queues sit left of the Lambda so each queue-to-Lambda edge enters its left face, while the Server-to-return-queue legs loop back — this is the honest shape of a reply queue. The teardown-confirmation step (step 7, Syndicate Server to deletion-notification-queue) was the most crossing-toxic of these back-edges, so it is named in the Flow legend rather than drawn as a line; every step stays named and the residual corridor-sharing findings are flow-class warnings, not errors. If a queue edge pierces a node, re-check that the return queues stay left of the Lambda and the send queues stay right of it. The Syndicate Server is external but an EC2 host, so it correctly shows the EC2 icon; Atlas shows the MongoDB brand leaf. Both stay outside the account boundary. If an SQS or Lambda icon is an empty box, the role is missing from `mappings/aws-icons.yaml`. Re-run the lint, icon-verify and raster gates after any change.

## Anti-patterns

Do not draw the Syndicate Server or MongoDB Atlas inside the AWS Account boundary to avoid the cross-boundary edges — both are external systems, and the queue-to-Server edges are meant to cross the boundary. Do not collapse a two-way queue relationship into a single double-headed arrow; model each direction as its own single-ended edge, because `allocation-queue` and `activation-queue` carry opposite directions and conflating them hides which side depends on which. Do not substitute a look-alike AWS icon for a service that has none: Atlas keeps MongoDB's own brand leaf, never an AWS database glyph. The Syndicate Server is different — it genuinely is an EC2 host, so the EC2 icon names its real resource type and is correct even though the node is external; being external is shown by its position outside the boundary, not by a neutral box. Do not add the student, API Gateway, or Batch workers here — this flow is scoped to the sandbox lifecycle; the broader request path is in `02-sep-summary` and the full inventory in `03-sep-account-landscape`.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_flow_sandbox_lifecycle.py
#   rule-engine-export-raster 05-flow-sandbox-lifecycle.drawio
```

## See Also

The broader context of SEP and its external systems is in `01-sep-context`, which shows the Syndicate Server (EC2) and MongoDB Atlas as neighbouring systems; the full production as-built is `03-sep-account-landscape`, and the request-path shape is `02-sep-summary`. The authoritative facts behind every node and edge are in `INVENTORY-STATE.md`: section 2 covers the SEP account and its 14 SQS queues, and the owner-confirmed component facts record that the Syndicate Server communicates with SEP exclusively via SQS. The provider-neutral rules this diagram obeys are in the always-on steering: `diagram-standards.md` for lane order, service-scope placement, numbered-flow-legend and two single-ended edges for a two-way relationship; `diagram-lint.md` for the class-aware severities; `provider-profiles.md` for the AWS regional-versus-VPC scope of SQS and Lambda; `asset-packs.md` for icon resolution; and `kb-frontmatter.md` for this companion's required frontmatter.
