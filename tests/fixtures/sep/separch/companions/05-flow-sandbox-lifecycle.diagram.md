---
id: 05-flow-sandbox-lifecycle-v11
title: SEP sandbox lifecycle — Education Extension SQS dance
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-11-03
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
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
  - date: 2026-10-21
    note: v5 — regenerated on rule-engine 1.10.12 (title v4→v5). No content change; the upgraded engine re-laid-out the geometry. Icons and edges unchanged.
  - date: 2026-10-22
    note: v6 — regenerated on rule-engine 1.11.0 pre-release with the native skin (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3, dark #1A1A1A circle badge markers). WS2 flow_groups are LIVE (On-Premises=[syndicate,atlas]): one decorative grey context box is drawn behind the member nodes with no node shift. The pre-release engine now classifies flowgroup-* cells as furniture (not nodes), so intra-group edges no longer trip the edge-routing defect noted in DIAGRAM-ENGINE-FEEDBACK-1.11.0.md. Node geometry otherwise unchanged.
  - date: 2026-10-23
    note: >-
      v7 — wave-2 owner review. The Syndicate Server is moved INSIDE the SEP
      account boundary (platform lane) as the SEP-internal control plane that
      drives the full sandbox lifecycle, instead of being drawn external in the
      On-Premises group. Its SQS allocation / deletion / activation edges now
      cross the account boundary inside-out. MongoDB Atlas stays external; the
      external-framing legend line for the Syndicate Server is removed.

  - date: 2026-10-23
    note: >-
      v8 — seventh-wave edge-routing sweep on rule-engine 1.11.0 (SYS-B
      spread-by-direction / SYS-A downward-exit / ENG-1 peering-label
      installed). Rebuilt + re-exported; geometry changed under the new
      contact-selection engine. Regression-checked: all gates 0
      ERROR/CRITICAL, icons 0 unresolved. Title v7→v8.
  - date: 2026-10-23
    note: >-
      v9 — FEAT-003 (Syndicate Server two-component model). The server node is
      relabelled "Syndicate Server — Education Extension": the one in-account EC2
      hosts two logical components (Education Extension + Syndi), and this
      diagram is the EE sandbox-lifecycle view. All FIVE EE lifecycle queues are
      now drawn with inventory-verified directions — the previously missing
      resource-limit findings queue (notification-queue, EE→SEP) is added, and
      the teardown-confirmation leg is no longer folded. se-management-api-handler
      is named and shown as the consumer of the three EE→SEP reply queues
      (activation ESM 212fa9f3, deletion-notification ESM a72b7c05, notification
      ESM 02afbaa0); the two SEP→EE request queues (allocation, deletion) have no
      Lambda ESM — EE on the server consumes them. The EC2 stays ONE node inside
      the SEP account. Coordinate-free spec change only. Title v8→v9.
  - date: 2026-10-28
    note: >-
      v10 — Wave 12 text-only refinement. The Flow step 6 and a new Legend line
      make the sandbox-account cleanup explicit: AWS Batch in the sandbox
      accounts performs the cleanup, driven by the Syndicate Server Education
      Extension (EE), with SEP + Batch verifying. No node or edge change — the
      EE lifecycle topology is unchanged. Title v9→v10, updated 2026-10-28.
  - date: 2026-11-03
    note: >-
      v11 — review fixes (05-1..05-12) and regeneration on the final rule-engine
      1.13.0. The request/reply CYCLE is re-laid-out so every EE→reply-queue leg
      reads forward instead of raking the three reply legs back across the whole
      account: lane order is now send-queues → Syndicate Server (EE) → reply
      queues → se-management-api-handler → MongoDB Atlas, which cuts the cycle at
      the two SEP→EE send requests (the only back-edges, ridden on a return bus
      inside the account). This removes e7's five crossings, its own-caption cut,
      e9 escaping the account and the e3/e9 collinear bus. The "On-Premises"
      context group is renamed "External SaaS" and MongoDB Atlas is labelled with
      its real peered account 781849312837 (NOT a corporate data centre, NOT
      088595288622). se-management-api-handler is noted VPC-attached in the Legend
      (it reaches Atlas over peering, so the earlier "regional … outside any VPC"
      Overview claim is corrected). The EC2 caption is shortened to "Syndicate
      Server (EE)" and the duplicate "dashed = asynchronous" Legend line removed.
      EPM-CMTR / CMTM (legacy Jenkins Task Manager, DEPRECATED per
      INVENTORY-STATE.md R9) is not drawn in this view and never was — nothing to
      remove here. Title v10→v11, updated 2026-11-03.
---

# SEP sandbox lifecycle — Education Extension SQS dance

## Overview

This data-flow diagram shows how the Education Extension (EE) component of the Syndicate Server allocates, activates, releases and cleans up a sandbox for a student task in the production account `870325637521` in `eu-central-1`. The Syndicate Server EC2 hosts two logical components on one host — Education Extension (sandbox lifecycle) and Syndi (student support, covered by `07-flow-support-syndi`); this is the EE lifecycle view, so the single server node is captioned "Syndicate Server — Education Extension" and is never split into two. It is drawn inside the SEP account boundary as the in-account control plane, carrying the real EC2 icon. The five lifecycle SQS queues are regional services reached over endpoints, while `se-management-api-handler` (Lambda) is VPC-attached (`VpcId vpc-05cd5663a70d3a65c`) — all live inside the SEP account. This is a flow view, so the VPC is not drawn; the Lambda's VPC attachment is noted in the Legend because it is how the handler reaches the peered MongoDB Atlas cluster. MongoDB Atlas is the only external system, drawn outside the boundary with MongoDB's own brand-green leaf, in the Atlas-managed peered AWS account `781849312837`. Every queue direction was verified against the read-only inventory `event-source-mappings.json`, not inferred from code.

## Main Content

The dance uses five SQS queues, split by direction. On the send side (SEP to EE), `se-management-api-handler` enqueues an allocation request on `allocation-queue`; the Education Extension consumes it — there is no Lambda event-source mapping — and provisions the sandbox. EE returns the activated sandbox details on `activation-queue`, which the handler consumes through ESM 212fa9f3. On release, the handler sends teardown on `deletion-queue`; EE consumes it (again no ESM), and AWS Batch in the sandbox accounts performs the account cleanup driven by the Education Extension, with SEP and Batch verifying, then EE notifies expiration or automatic cleanup on `deletion-notification-queue`, consumed by the handler through ESM a72b7c05. Separately, EE reports resource-limit findings and quota alerts on `notification-queue`, consumed through ESM 02afbaa0 — the fifth queue, previously missing from this view. Finally the handler persists sandbox and application state in the external MongoDB Atlas cluster over VPC peering. The verified asymmetry: `allocation-queue` and `deletion-queue` have no Lambda consumer in SEP because EE on the server drains them; the three EE→SEP reply queues are all consumed by `se-management-api-handler`.

## Troubleshooting

If the layout engine prints a warning, read `placed.layout_warnings` and fix the coordinate-free spec in `scripts/build_flow_sandbox_lifecycle.py`, never the generated `.drawio`. The request-reply pattern is a cycle, laid out so every EE-to-reply-queue leg reads forward: the lane order is send queues, then the Syndicate Server (EE), then the reply queues, then the Lambda. The cycle is cut at the two SEP-to-EE send requests (`se-management-api-handler` to `allocation-queue` and to `deletion-queue`), which are the only back-edges and ride a return bus inside the account. If a reply queue leg rakes back across the account again, re-check that the Syndicate Server stays between the send queues (left, it consumes them) and the three reply queues (right, it produces them), with the Lambda to the right of the reply queues. The Syndicate Server is an in-account EC2 host, so it correctly shows the EC2 icon; Atlas shows the MongoDB brand leaf and stays outside the account boundary. Residual corridor-sharing and crossing findings are flow-class warnings, not errors. If an SQS or Lambda icon is an empty box, the role is missing from `mappings/aws-icons.yaml`. The 1.11.0 native skin is cosmetic only. Re-run the lint, icon-verify and raster gates after any change.

## Anti-patterns

Do not split the Syndicate Server into two nodes for Education Extension and Syndi — it is one EC2 host inside the SEP account; name the component in the caption instead. Do not move the server or MongoDB Atlas across their boundaries: the server is in-account, Atlas is external, and the queue edges are meant to cross as drawn. Do not collapse a two-way queue relationship into a single double-headed arrow; model each direction as its own single-ended edge, because `allocation-queue` and `activation-queue` carry opposite directions and conflating them hides which side depends on which. Do not invent a Lambda consumer for `allocation-queue` or `deletion-queue`: the inventory confirms they have no event-source mapping because EE consumes them on the server. Do not substitute a look-alike AWS icon for Atlas — it keeps MongoDB's own brand leaf. Do not add the student, API Gateway, or Batch workers here; this flow is scoped to the EE sandbox lifecycle, the support loop is in `07-flow-support-syndi`, and the full inventory in `03-sep-account-landscape`.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_flow_sandbox_lifecycle.py
#   rule-engine-export-raster 05-flow-sandbox-lifecycle.drawio
```

## See Also

The broader context of SEP is in `01-sep-context`, which shows the in-account Syndicate Server and the external MongoDB Atlas as neighbouring systems; the Syndi student-support loop on the same host is in `07-flow-support-syndi`; the full production as-built is `03-sep-account-landscape`, and the request-path shape is `02-sep-summary`. The authoritative facts behind every node and edge are in `INVENTORY-STATE.md` and `event-source-mappings.json`: the account holds the five lifecycle queues, and the owner-confirmed component facts record that Education Extension drives the sandbox lifecycle via SQS while the handler consumes the three reply queues. The provider-neutral rules this diagram obeys are in the always-on steering: `diagram-standards.md` for lane order, service-scope placement, numbered-flow-legend and two single-ended edges for a two-way relationship; `diagram-lint.md` for the class-aware severities; `provider-profiles.md` for the AWS regional-versus-VPC scope of SQS and Lambda; `asset-packs.md` for icon resolution; and `kb-frontmatter.md` for this companion's required frontmatter.
