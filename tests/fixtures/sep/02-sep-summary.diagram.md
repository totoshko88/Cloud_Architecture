---
id: 02-sep-summary-v7
title: SEP summary — request shape (container-level)
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-28
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
diagram_class: flow
diagram_type: container
detailed_view: 03-sep-account-landscape
change_log:
  - date: 2026-10-21
    note: v3 — regenerated on rule-engine 1.10.12 (title v3→v4). No content change; the upgraded engine re-laid-out the geometry (new layout modules, 1.5 raster scale). Icons and edges unchanged.
  - date: 2026-10-22
    note: v5 — regenerated on rule-engine 1.11.0 pre-release with the native skin (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3, dark #1A1A1A circle badge markers). WS2 flow_groups are LIVE (Edge=[rest-apis,socket-api], Workers=[lambda-core,batch]): two decorative grey context boxes are drawn behind the member nodes with no node shift. The pre-release engine now classifies flowgroup-* cells as furniture (not nodes), so intra-group edges no longer trip the edge-routing defect noted in DIAGRAM-ENGINE-FEEDBACK-1.11.0.md. Node geometry otherwise unchanged.
  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (1.11.0): rebuilt BYTE-IDENTICAL. Owner 02 'markers
      8/9 swap exits (9 lower/left)' verified RESOLVED: SYS-B
      direction-ordering already places m8 (→S3) and m9 (→Atlas, farther
      right) on distinct bottom bands heading to their respective targets, no
      overlap and no crossing finding. Version held.
  - date: 2026-10-23
    note: >-
      v6 — tenth-wave B4 (owner re-flagged the 8/9 crossing on the rendered
      PNG). e8 (Lambda->S3) and e9 (Lambda->Atlas) fanned out of Lambda and
      crossed near the data column. The Atlas node is nudged down half a row
      (sub=1) so e9 runs in a LOWER band than e8 and the two fan-out edges nest
      instead of crossing (S3 turns up on the inner/upper band, Atlas runs lower
      and continues right). A placement nudge, not an edge reorder — reordering
      the two fan-out edges made the scored solver search pathologically slow on
      this spec (recorded in DIAGRAM-ENGINE-FEEDBACK). Gates 0 ERROR/CRITICAL,
      11 icons 0 unresolved. Title v5->v6.
  - date: 2026-10-28
    note: >-
      v7 — Wave 12. Added two nodes from the read-only inventory of account
      870325637521 (eu-central-1): WAF (syndicate_education_cloudfront_waf,
      wafv2 GLOBAL, attached to CloudFront) in the EDGE lane in front of the
      REST front door, and RDS sep-strapi-pg (Postgres, Multi-AZ) in the data
      area next to Atlas so the Atlas-vs-RDS datastore split is now visible.
      WAF is global/edge — it is drawn in the edge lane and is NOT inside any
      VPC/region boundary (02 draws only the account boundary). New edges: e3
      waf->rest-apis (WAF protects the REST edge) and e10 lambda-core->rds
      (managed-SQL write path); markers renumbered 1..11 contiguously and Flow
      list extended to 11 steps. Atlas sub nudge raised 1->2 so the long
      Lambda->Atlas edge (e11) routes below the top icon row and clears Bedrock
      (the e11 knee-through-bedrock edge-routing ERROR at sub=1). Gates: lint
      02.drawio/02.diagram.md 0 ERROR/CRITICAL, verify-icon 13 resolved /
      0 unresolved (WAF + RDS real AWS icons), check-rasters within flow budget
      (1565px / 209KB white). Title v6->v7, updated 2026-10-28.
tags:
  - sep
  - aws
  - summary
  - container
  - flow
  - eu-central-1
related_docs:
  - 03-sep-account-landscape.diagram.md
---

# SEP summary — request shape

## Overview

This diagram is the container-level C4 view of the Syndicate Education Platform (SEP) running in the production AWS account `870325637521` in `eu-central-1`. It is the summary half of a summary-plus-landscape pair: it answers a single question — how does a request move end-to-end through SEP? — and deliberately collapses families of resources into representative nodes so the whole shape fits in eleven nodes, under the twelve-node flow cap. The detailed as-built that enumerates every resource is the paired landscape `03-sep-account-landscape`, cross-linked from this companion's `detailed_view`. The facts drawn here come from a strictly read-only inventory of the live production account, not from the application code: thirteen Lambda functions, fourteen SQS queues, five AWS Batch compute environments, twenty-five S3 buckets, three API Gateways, a global CloudFront WAF, a managed RDS sep-strapi-pg Postgres database, and a MongoDB Atlas cluster in Frankfurt reached over VPC peering. Nothing on the canvas is invented; counts and services are the deployed reality at collection time.

## Main Content

The request shape reads left to right along the fixed lane order. A client (web or mobile) enters through the edge lane, which carries the CloudFront WAF and two front doors: the REST APIs node collapses the management-api and ui-api gateways, and socket-api is the WebSocket gateway drawn separately because it is a distinct protocol. The WAF (syndicate_education_cloudfront_waf) is global and attached to CloudFront, so it sits in the edge lane in front of the REST door and never inside a VPC. Both front doors invoke the Lambda core, a single node standing for all thirteen functions. From the Lambda core the asynchronous and data paths fan out: it enqueues the fourteen SQS queues, submits jobs to AWS Batch, and calls Bedrock for the Angry EdA model. For persistence it writes the twenty-five S3 buckets, the managed RDS sep-strapi-pg Postgres database, and the external MongoDB Atlas cluster, so the Atlas-versus-RDS datastore split is explicit. Every regional AWS service sits inside the account boundary; Atlas sits outside because it is not an AWS resource.

## Troubleshooting

If a node looks wrong, remember this is a summary: representative nodes stand for families, so "Lambda core" is one icon for thirteen functions and "SQS" is one icon for fourteen queues. For per-resource detail, open the paired landscape `03-sep-account-landscape` rather than expecting it here. Two icons are known Rule Engine gaps and are intentional, not defects. AWS Batch has no bundled role in the shipped `roles.yaml`, so a workspace-local `batch` role was added to render the official Batch icon; this is noted in the build report as an improvement to upstream. MongoDB Atlas is not an AWS service, so it is drawn with MongoDB's own brand-green leaf mark (not an AWS glyph) in the external on-premises lane outside the account boundary. If the raster looks oversized, confirm the export used the flow budget: at most 1600 pixels wide and under 500 kilobytes on a white background. The 1.11.0 native skin is cosmetic only: grey edges, light-grey Flow/Legend boxes, and dark badge-disc flow markers, with no node moved.

## See Also

This artifact is one of the mandatory triple: the drawing source `02-sep-summary.drawio`, its exported raster `02-sep-summary.drawio.png`, and this companion. Its detailed counterpart is the landscape `03-sep-account-landscape`, which draws every enumerated resource on one canvas and links back here through its `summary_of`. The authoritative facts come from the read-only production inventory of account `870325637521` in `eu-central-1`, collected and recorded under the inventory standards; the review of the architecture guide against that inventory is captured in `DOC-REVIEW-for-author.md`, and the recommended additions in `DOC-ADDITIONS-recommended.md`. The lane order, container padding, service-scope placement, and numbered-flow-legend conventions this diagram follows are defined in the diagram standards steering document, and the class-aware severities that gate it are defined in the diagram lint ruleset maintained alongside the other packaged rule-engine gates.
