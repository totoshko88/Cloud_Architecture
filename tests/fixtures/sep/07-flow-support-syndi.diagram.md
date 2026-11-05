---
id: 07-flow-support-syndi-v13
title: SEP Syndi support — student help loop (runtime flow)
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-28
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
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
  - date: 2026-10-28
    note: >-
      v13 — reordered e3/e4 so edge 4 routes above edge 3; removed e3's extra
      jog. LAYOUT/ROUTING-ONLY spec-lever cleanup (coordinate-free, no pinned
      coordinates): attachments raised to sub=0 (top of the data lane) so its
      fan-out leg e4 (socket-handler -> attachments) exits the upper band and
      routes over the account top band ABOVE e3 (the owner's "4 вийшло згори");
      req-queue restored to sub=0 (top async row, same row as socket-handler)
      so e3 (socket-handler -> req-queue) is a single straight horizontal with
      no waypoints, removing the extra jog ("3 зайва сходинка"). No node, edge,
      caption or queue-direction change. Lint [OK] (only the pre-existing
      non-blocking container-dead-space WARNING; the prior collinear [e8,e9]
      WARNING is also gone). Title v12->v13; updated 2026-10-28.
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
  - date: 2026-10-21
    note: >-
      v6 — regenerated on rule-engine 1.10.12 (title v5→v6). No content change;
      the upgraded engine re-laid-out the geometry and the flow raster is
      exported with --max-width 1500 to stay under the 1600px flow budget
      (1.10.12's 1.5 scale otherwise lands it at 1622px). Icons/edges unchanged.
  - date: 2026-10-21
    note: >-
      v7 — DIAL AI now renders the owner-supplied EPAM DIAL brand mark (dial
      role, mappings/local overlay) instead of the neutral box; it keeps its
      on-premises-lane placement outside the account boundary (only the glyph
      changed). Brings 07 in line with 09, where DIAL already carries its brand
      mark. Node set, edges, and routing otherwise unchanged.
  - date: 2026-10-22
    note: >-
      v8 — regenerated on rule-engine 1.11.0 pre-release with the native skin
      applied (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3,
      dark #1A1A1A circle badge markers). WS2 flow_groups are LIVE
      (On-Premises=[syndi,dial], Async=[req-queue,resp-queue]): two decorative
      grey context boxes are drawn behind the member nodes with no node shift.
      The pre-release engine now classifies flowgroup-* cells as furniture (not
      nodes), so intra-group edges no longer trip the edge-routing defect noted
      in DIAGRAM-ENGINE-FEEDBACK-1.11.0.md.
      Geometry and icons otherwise unchanged, presentation-only. Raster exported
      with --max-width 1500 to stay under the 1600px flow budget (the default
      1.5 scale otherwise lands it at 1622px).
  - date: 2026-10-23
    note: >-
      v9 — Task-4 (owner): the Syndicate Server (Syndi) is the EC2 control-plane
      host INSIDE the SEP account (verified in compute.json: instance-profile
      syndicate-server, vpc-05cd5663a70d3a65c), so it is now drawn as an account
      member in the platform-core lane with the real EC2 icon instead of in the
      on-premises lane. Its SQS request/response edges now cross the account
      boundary from the inside out, which is correct; they stay two single-ended
      edges (no double head). Syndi leaves the On-Premises flow_group (only DIAL
      AI remains external). The deprecated external "Syndicate task manager"
      (the MVP-era Jenkins in another account) is removed and no longer mentioned.
      Coordinate-free spec change only; no hand-edited coordinates. Title v8→v9.
  - date: 2026-10-23
    note: >-
      v10 — FEAT-002 ITEM D (owner: "Syndi-request-processor точно повинна із
      кимось бути повязана. зараз загублений ресурс"). The two folded reply
      edges are restored and drawn: se-support-response-queue →
      se-syndi-request-processor (confirmed event-source mapping) and
      se-syndi-request-processor → se-socket-api (WebSocket push). The processor
      is no longer an orphaned glyph — it now carries exactly two incident
      edges. The 1.11.0 auto-ordering/routing places the reply trio cleanly with
      no crossing-excess or marker overprint, so no edge-folding is needed any
      more. All nine Flow steps are drawn (no flow-step-undrawn). Coordinate-free
      spec change only; no hand coordinates. Title v9→v10.
  - date: 2026-10-23
    note: >-
      v11 — wave-4 ITEM 2 (owner: "4 наклалась на блок Async варто трошки више
      пустити"). Edge 4 (socket-handler → attachments S3) ran its horizontal leg
      in the account top band ~2px above the decorative "Async" flow-group box
      top, so the line grazed the box caption. Dropping req-queue one sub-row
      (sub=1) lowers the Async box top by ~80px so the edge-4 run clears it with
      comfortable margin; resp-queue and syndi-request-processor each drop one
      sub-row to stay separated and keep edge 5 from kneeing through the
      processor glyph. Coordinate-free spec levers only; lint stays [OK]
      (dead-space / collinear WARNings, non-blocking). Title v10→v11.

  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (1.11.0): rebuilt BYTE-IDENTICAL (exported
      --max-width 1500). Owner 07 'markers 3/4 swap exits (3 lower, 4 higher)'
      verified RESOLVED: m3 exits mid-right (0.51) straight to the queue, m4
      exits lower-right (0.77) and rises over the top — distinct bands, no
      overlap, no crossing finding. Version held.
  - date: 2026-10-23
    note: >-
      v12 — FEAT-003 (Syndicate Server two-component model). The server node is
      relabelled "Syndicate Server — Syndi" to read as the Syndi support
      component of the one in-account EC2 that also hosts Education Extension
      (the EE sandbox lifecycle is diagram 05). Two Legend lines name the server
      as a two-component host and name the two developer-stated Syndicate Server
      APIs as attributes: the SS/EE Sandbox Access Management API and the
      Syndicate Server Reporting API (emails + FreeMarker .ftl templates). The
      support-loop queue directions are unchanged and were re-verified against
      event-source-mappings.json: se-support-request-queue has no Lambda ESM
      (Syndi-consumed) and se-support-response-queue maps to
      se-syndi-request-processor (ESM 8a2f04ee). Wording/legend change only; no
      geometry or queue-direction change. Title v11→v12.
---

# SEP Syndi support — student help loop

## Overview

This diagram traces the runtime data flow of the Syndi student-support loop in the production Syndicate Education Platform (SEP), AWS account `870325637521` in `eu-central-1`. A student asks for help in the Syndicate UI built-in chat; Syndi, the AI first-line support agent running on the Syndicate Server, answers and can escalate to a human. Syndi is one of two logical components hosted on that single in-account EC2 — the other is Education Extension, the sandbox-lifecycle component shown in `05-flow-sandbox-lifecycle`; the server node here is captioned "Syndicate Server — Syndi" and the two developer-stated Syndicate Server APIs (SS/EE Sandbox Access Management; Syndicate Server Reporting, for emails and FreeMarker `.ftl` templates) are named as Legend attributes. It is a `flow` / `data-flow` view at nine nodes, well under the twelve-node cap, reading left to right with the response folding back to the student. Every service name is the deployed reality from a read-only inventory: `se-socket-api`, `se-socket-handler`, `se-support-request-queue`, `se-support-response-queue`, `se-syndi-request-processor`, and the `se-support-request-attachments` bucket. The Syndicate Server is the EC2 control-plane host inside the SEP account, drawn as an account member with the real EC2 icon. Only DIAL AI remains outside the account boundary, as a non-AWS proxy.

## Main Content

The request enters over the WebSocket API (`se-socket-api`), which invokes the `se-socket-handler` Lambda. The handler puts the support message on `se-support-request-queue` (SQS) and stores any student attachments in the `se-support-request-attachments` S3 bucket. The request queue has no Lambda event-source mapping in SEP — it is consumed by the Syndicate Server EC2 host, which runs Syndi and is also the control plane for the sandbox organisations. Syndi may call DIAL AI (`ai-proxy.lab.epam.com`) for the model and can escalate to a human operator. Syndi's resolved response returns on `se-support-response-queue`, which has a confirmed event-source mapping to `se-syndi-request-processor`. That Lambda pushes the reply back to the student's active WebSocket connection through `se-socket-api`, closing the loop in the UI chat. The two queue-to-Syndi edges run between the SQS queues and the Syndicate Server inside the account, and the DIAL call crosses the boundary outward; each is a single-ended arrow, one per direction, never a double head.

## Troubleshooting

If the request-to-response direction looks like one bidirectional link, remember it is modelled as two single-ended edges: `support-request-queue` to Syndicate Server, and Syndicate Server back via `support-response-queue`. That mirrors reality — two distinct SQS queues, not one. If you expect a Lambda consumer on the request queue, there is none in SEP: the queue is drained by the Syndicate Server, the EC2 control-plane host now drawn inside the account boundary. If you look for the old external "Syndicate task manager", it is gone: that was the MVP-era Jenkins in another account, deprecated and removed per the Task-4 review. The Syndicate Server shows the real EC2 icon because it is an EC2 host; DIAL AI stays a brand box as a non-AWS proxy. The loop-closing steps — the processor consuming the response (step 8, a confirmed event-source mapping) and pushing the reply back to the student's WebSocket connection (step 9) — are now drawn, so `se-syndi-request-processor` carries two incident edges and is no longer an orphaned glyph. The 1.11.0 engine routes the reply trio cleanly, so no edge-folding is needed. Edge 4 (attachments store) now runs clear above the decorative Async group box.

## See Also

This artifact is one of the mandatory triple: the drawing source `07-flow-support-syndi.drawio`, its exported raster `07-flow-support-syndi.drawio.png`, and this companion. For the wider picture, see the system context `01-sep-context`, which places Syndicate Server, DIAL, and the other external systems around the SEP platform, and the full as-built `03-sep-account-landscape`, which enumerates every resource in the account including the Teams proxy path omitted here. The authoritative facts come from the read-only production inventory of account `870325637521` in `eu-central-1`, in particular the messaging and event-source-mapping records that confirm `se-support-request-queue` has no SEP consumer and `se-support-response-queue` maps to `se-syndi-request-processor`. The lane order, service-scope placement, two-single-edges convention, numbered-flow-legend, and class-aware lint severities this diagram follows are defined in the always-on diagram-standards and diagram-lint steering documents.
