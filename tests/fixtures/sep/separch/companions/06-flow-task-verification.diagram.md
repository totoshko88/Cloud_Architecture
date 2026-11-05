---
id: 06-flow-task-verification-v12
title: SEP task solution verification — runtime data flow
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-31
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
diagram_class: flow
diagram_type: data-flow
tags:
  - sep
  - aws
  - batch
  - verification
  - data-flow
  - eu-central-1
related_docs:
  - 02-sep-summary.diagram.md
  - 03-sep-account-landscape.diagram.md
change_log:
  - date: 2026-10-15
    note: >-
      regen5 — companion-only edit: trimmed the Troubleshooting section to the
      kb-frontmatter 100-200 word bound (was 269, a pre-existing CRITICAL
      section-length finding). Diagram geometry unchanged; title not bumped.
  - date: 2026-10-17
    note: >-
      v4 — marker-8 fix. Marker 8 (lti-adapter to MongoDB Atlas) overprinted the
      S3 tasks caption; dropped MongoDB Atlas two sub-rows in the spec so the e8
      corridor routes below S3 and marker 8 is clear. Coordinate-free; no hand
      coordinates. No icon-fidelity change was needed (the external Syndicate
      Rule Engine / EKS box stays a folded multi-target neutral box).
  - date: 2026-10-21
    note: >-
      v5 — regenerated on rule-engine 1.10.12 (title v4→v5). No content change;
      the upgraded engine re-laid-out the geometry. Icons and edges unchanged.
  - date: 2026-10-22
    note: >-
      v6 — regenerated on rule-engine 1.11.0 pre-release. Native skin applied
      (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3, dark
      #1A1A1A circle badge markers). WS2 flow_steps="document" is LIVE: the
      on-canvas Flow box is dropped and the Legend takes the top slot, so every
      numbered step is named in the companion rather than on the canvas. The
      WS2 flow_groups (On-Premises=[ext,atlas]) is LIVE: one decorative grey
      context box is drawn behind the member nodes with no node shift, now that
      the pre-release engine classifies flowgroup-* cells as furniture (not
      nodes) and intra-group edges no longer trip the edge-routing defect noted
      in DIAGRAM-ENGINE-FEEDBACK-1.11.0.md.
      Added a ## Assumptions section from the WS5 clarify scan. Geometry
      otherwise unchanged.
  - date: 2026-10-23
    note: >-
      v7 — Task-4 (owner): dropped the deprecated EPM-CMTR dev/cicd framing. The
      external verification box no longer names an external "Syndicate Rule
      Engine EC2 in EPM-CMTR"; the Syndicate Rule Engine (SRE) verifier is a SEP
      in-account Batch job (ECR image syndicate/sep/task-manager/sre:latest) and
      the Rule Engine control plane is the SEP-internal Syndicate Server. The
      only external verification target is now the ED-KRSB student EKS cluster
      development-dev (account 183631338639), reached by the se-ktm-job-definition
      Batch job via the cluster public API endpoint; it is retained. Flow line 6
      and the Legend account lines updated accordingly. Coordinate-free spec
      change only; no hand-edited coordinates. Title v6→v7.
  - date: 2026-10-23
    note: >-
      v8 — wave-2 owner review ("хтось явно повинен звертатись до Angry EdA").
      Restored the drawn edge lti-adapter → Bedrock (marker 10, e10): it had
      been folded into the Flow legend, leaving Bedrock with no incident edge
      (a floating glyph / node-connectivity WARNING). Bedrock drops to its own
      lower sub-row so the restored edge routes clear of the other lti fan-out
      drops, introducing no new crossing / marker / corridor-sharing finding.
      Coordinate-free spec change only. Title v7→v8.
  - date: 2026-10-23
    note: >-
      v9 — FEAT-002 (owner: "Flow можна повернути на діаграму ... варто
      реалізувати багато стовпчиків"). The numbered Flow legend is back ON the
      canvas: flow_steps returns to the default on-canvas "box" and the 12-step
      list is reflowed into TWO side-by-side columns via the new flow_columns=2
      capability (rule-engine 1.11.0 FEAT-001 B / backlog G22). The split keeps
      the diagram wide-and-short so it stays inside the 1600px / 500KB flow
      raster budget (exported 1507px, 178KB). Bedrock stays drawn-connected
      (edge 10). Coordinate-free spec change only; no hand coordinates.
      Title v8→v9.
  - date: 2026-10-23
    note: >-
      v10 — wave-4 ITEM 1 (owner: "для горизонтальних блоків Flow та Legend
      варто їх показувати однаковою висоти"). Engine fix in rule-engine 1.11.0:
      when Flow/Legend boxes are laid out horizontally (the row-below Mode B,
      including the multi-column Flow case), every box in the row now renders at
      a common height = the tallest natural box, so the row shares one flat
      bottom edge. The two Flow columns and the Legend on this diagram are now
      all height 212 (previously 132 / 132 / 212, a ragged 80px overhang).
      Engine change only; the 06 spec is unchanged. Title v9→v10.

  - date: 2026-10-23
    note: >-
      v11 — seventh-wave edge-routing sweep on rule-engine 1.11.0 (SYS-B /
      SYS-A / ENG-1). Rebuilt + re-exported; routing geometry updated under
      the new engine. All gates 0 ERROR/CRITICAL, icons 0 unresolved. Title
      v10→v11.
  - date: 2026-10-31
    note: >-
      v12 — review 05-08 (06 was misleading). Drew step 7 (signed callback,
      Batch to lti-adapter) and step 11 (lti-adapter pushes to the WebSocket)
      as dashed return-bus edges, so the grade no longer appears on the
      WebSocket from nowhere. The ED-KRSB cluster now uses the EKS icon (role
      managed_k8s). The single On-Premises box is split into a peer-account
      box (183631338639) and a SaaS box for Atlas. Edge 6 enters the EKS left
      face clear of the caption. Lambda and Batch are marked VPC-attached in
      the Legend. EPM-CMTR (legacy Jenkins) is deprecated and not drawn; none
      was present on this diagram. Built on rule-engine 1.13.0.
---

# SEP task verification flow

## Overview

This diagram traces one SEP runtime path end to end, request and response: what happens when a student presses verify on a task, through to the grade coming back. It is a data-flow view of the production AWS account `870325637521` in `eu-central-1`, drawn left to right as a numbered sequence rather than an as-built inventory. The facts come from a read-only inventory of the live account and the architecture guide: a short-lived AWS Batch worker fetches the submitted solution, checks it in a sandbox, and reports the grade back over a signed callback. Families are collapsed to representative nodes to stay under the twelve-node flow cap. The three per-topic Batch verifiers — STM for serverless cloud tasks, SRE for Syndicate Rule Engine tasks, and KTM for Kubernetes tasks — are drawn as a single Batch node; all three are SEP in-account Batch job definitions. The only external verification target is the ED-KRSB student EKS cluster, drawn with the real EKS icon in its own peer-account box outside the account; MongoDB Atlas sits in a separate SaaS box next to it. Nothing on the canvas is invented; services and relationships are the deployed reality at collection time.

## Main Content

The flow reads along the numbered markers. A student action enters over the WebSocket API and is handled by the lti-adapter Lambda, the SEP API core. The lti-adapter submits a Batch job to the topic queue, selecting the STM, SRE, or KTM compute environment. The job pulls its container image from ECR and reads task content and verification scripts from S3. SRE verification runs entirely in the SEP account as a Batch job against the Syndicate Rule Engine, the control-plane logic hosted on the SEP-internal Syndicate Server — there is no external Rule Engine box. KTM jobs call the ED-KRSB student EKS cluster development-dev in account 183631338639, reached over the cluster public API endpoint; that cluster is the single box outside the account boundary, in its own peer-account group. The job then posts the result through the signed callback back to lti-adapter (step 7, drawn). The lti-adapter records the grade in MongoDB Atlas, writes output logs to S3, asks Bedrock to summarise failures, and pushes the result to the WebSocket API (step 11, drawn), which delivers it to the student (step 12). Every AWS service of SEP sits inside the account boundary; Atlas and the EKS cluster do not.

## Troubleshooting

If a node looks collapsed, remember this is a flow, not an as-built: the single Batch node stands for the STM, SRE, and KTM verifiers, all SEP in-account jobs. The external box is the ED-KRSB student EKS cluster development-dev in peer AWS account 183631338639, drawn with the EKS icon; MongoDB Atlas is a SaaS product in its own box. The legacy EPM-CMTR Jenkins account is deprecated and deliberately absent, and there is no external Syndicate Rule Engine because the control plane is the SEP-internal Syndicate Server. Both return steps are drawn: the signed callback (step 7) and the WebSocket push (step 11) run as dashed edges over the top of the row. Lambda and Batch are VPC-attached in the live account; the flow draws them in the account body for readability. Known residual warnings: edge 8 leaves lti-adapter downward across its own caption, and the account has some dead space. Open the paired landscape `03-sep-account-landscape` for per-resource detail.

## Assumptions

- **unresolved_role** on `atlas`: applied default *boundary icon fallback* — the contract falls back to the enclosing boundary icon when a role does not resolve.
- **ambiguous_edge_kind** on `e1`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e10`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e11`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e2`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e3`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e4`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e5`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e6`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e7`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e8`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e9`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.

## See Also

This artifact is one of the mandatory triple: the drawing source `06-flow-task-verification.drawio`, its exported raster `06-flow-task-verification.drawio.png`, and this companion. It is a focused companion to the request-shape summary `02-sep-summary` and the full as-built landscape `03-sep-account-landscape`, which together give the container-level shape and the per-resource detail that this single flow deliberately omits. The authoritative facts come from the read-only production inventory of account `870325637521` in `eu-central-1`, collected under the inventory standards, together with the SEP architecture guide section on task verification; the review of that guide against the inventory is captured in `DOC-REVIEW-for-author.md`, and the recommended additions in `DOC-ADDITIONS-recommended.md`. The lane order, service-scope placement, external-actor placement, and numbered-flow-legend conventions this diagram follows are defined in the diagram standards steering document, and the class-aware severities that gate it are defined in the diagram lint ruleset shipped with the rule engine.
