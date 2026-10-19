---
id: 07-flow-support-syndi-v3
title: SEP Syndi support — student help loop (runtime flow)
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-17
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-17
diagram_class: flow
diagram_type: data-flow
tags:
  - sep
  - aws
  - syndi
  - support
  - data-flow
  - eu-central-1
related_docs:
  - 01-sep-context.diagram.md
  - 03-sep-account-landscape.diagram.md
change_log:
  - date: 2026-10-15
    note: >-
      regen5 — engine reinstall (1.10.11) subtly changed the shared routing
      path; the processor->response-queue leg collapsed a redundant waypoint
      and two flow-marker label offsets were dropped. Geometry delta only
      (same nodes, edges, and architecture); title bumped v3 -> v4.
  - date: 2026-10-17
    note: >-
      v5 — icon fidelity pass. The external Syndicate Server (Syndi), an EC2
      host drawn as its own node, now uses the real EC2 service icon instead of
      a neutral box; it stays outside the account boundary. DIAL AI stays a
      neutral box (external non-AWS AI proxy, not Bedrock).
---

# SEP Syndi support — student help loop

## Overview

This diagram traces the runtime data flow of the Syndi student-support loop in the production Syndicate Education Platform (SEP), AWS account `870325637521` in `eu-central-1`. A student asks for help in the Syndicate UI built-in chat; Syndi, the AI first-line support agent running on the external Syndicate Server, answers and can escalate to a human. It is a first-draft `flow` / `data-flow` view at nine nodes, well under the twelve-node cap, and it reads left to right along the request path with the response folding back to the student. Every service name is the deployed reality from a read-only inventory of the live account, not from application code: `se-socket-api`, `se-socket-handler`, `se-support-request-queue`, `se-support-response-queue`, `se-syndi-request-processor`, and the `se-support-request-attachments` bucket. The two externals — Syndicate Server (Syndi) and DIAL AI — sit outside the account boundary because they are not AWS resources in this account; the Syndicate Server is drawn with the real EC2 icon because it is an EC2 host, while DIAL AI stays a neutral box.

## Main Content

The request enters over the WebSocket API (`se-socket-api`), which invokes the `se-socket-handler` Lambda. The handler puts the support message on `se-support-request-queue` (SQS, direction SEP to Syndicate Server) and stores any student attachments in the `se-support-request-attachments` S3 bucket. The request queue has no Lambda event-source mapping in SEP — it is consumed by the external Syndicate Server EC2 host, which runs Syndi. Syndi may call DIAL AI (`ai-proxy.lab.epam.com`) for the model and can escalate to a human operator. Syndi's resolved response returns on `se-support-response-queue` (Syndicate Server to SEP), which has a confirmed event-source mapping to `se-syndi-request-processor`. That Lambda pushes the reply back to the student's active WebSocket connection through `se-socket-api`, closing the loop in the UI chat. The two queue-to-Syndi edges correctly cross the account boundary and are drawn as two single-ended arrows, one per direction.

## Troubleshooting

If the request-to-response direction looks like one bidirectional link, remember it is modelled as two single-ended edges: `support-request-queue` out to Syndicate Server, and Syndicate Server back in via `support-response-queue`. That mirrors reality — two distinct SQS queues, not one. If you expect a Lambda consumer on the request queue, there is none in SEP: the queue is drained by the external Syndicate Server, which is why that node is outside the boundary and the edge crosses it. The Syndicate Server shows the real EC2 icon because it is an EC2 host, even though external; DIAL AI stays a neutral box as a non-AWS proxy with no faithful glyph. A look-alike AWS icon for DIAL would be dishonest. The optional Microsoft Teams path is left off this first draft to keep the loop legible; it belongs on the account landscape. The loop-closing step — the processor Lambda pushing the reply back to the student's WebSocket connection (step 9) — is named in the Flow legend rather than drawn: as a leftward return edge across the whole flow it was the most crossing-toxic edge, so folding it into the legend keeps every step named while clearing the crossing warning.

## See Also

This artifact is one of the mandatory triple: the drawing source `07-flow-support-syndi.drawio`, its exported raster `07-flow-support-syndi.drawio.png`, and this companion. For the wider picture, see the system context `01-sep-context`, which places Syndicate Server, DIAL, and the other external systems around the SEP platform, and the full as-built `03-sep-account-landscape`, which enumerates every resource in the account including the Teams proxy path omitted here. The authoritative facts come from the read-only production inventory of account `870325637521` in `eu-central-1`, in particular the messaging and event-source-mapping records that confirm `se-support-request-queue` has no SEP consumer and `se-support-response-queue` maps to `se-syndi-request-processor`. The lane order, service-scope placement, two-single-edges convention, numbered-flow-legend, and class-aware lint severities this diagram follows are defined in the always-on diagram-standards and diagram-lint steering documents.
