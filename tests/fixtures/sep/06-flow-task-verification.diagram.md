---
id: 06-flow-task-verification-v3
title: SEP task solution verification — runtime data flow
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
---

# SEP task verification flow

## Overview

This diagram traces one SEP runtime path end to end: what happens when a student presses verify on a task. It is a data-flow view of the production AWS account `870325637521` in `eu-central-1`, drawn left to right as a numbered sequence rather than an as-built inventory. The facts come from a read-only inventory of the live account and the architecture guide, not from application source: a short-lived AWS Batch worker fetches the submitted solution, deploys or checks it in a sandbox, and reports the grade back. The scope is deliberately one flow, so families are collapsed to representative nodes to stay under the twelve-node flow cap. The three per-topic Batch verifiers — STM for serverless cloud tasks, SRE for Syndicate Rule Engine tasks, and KTM for Kubernetes tasks — are drawn as a single Batch node, and the external verification targets are folded into one neutral box. Nothing on the canvas is invented; services and relationships are the deployed reality at collection time.

## Main Content

The flow reads along the numbered markers. A student action enters over the WebSocket API and is handled by the lti-adapter Lambda, the SEP API core. The lti-adapter submits a Batch job to the topic queue, selecting the STM, SRE, or KTM compute environment. The job pulls its container image from ECR and reads task content and verification scripts from S3. SRE jobs call the Syndicate Rule Engine EC2 host in the EPM-CMTR account, and KTM jobs call the student EKS cluster in another account, both over VPC peering; these externals are the single neutral box outside the account boundary. The job then posts progress and the result through a signed callback back to lti-adapter. The lti-adapter records the grade in MongoDB Atlas, writes output logs to S3, asks Bedrock to summarise failures, and pushes the news to the WebSocket API, which delivers it to the student. Every AWS service sits inside the account boundary; Atlas, the Rule Engine, and the cluster do not.

## Troubleshooting

If a node looks collapsed, remember this is a flow, not an as-built: the single Batch node stands for the STM, SRE, and KTM verifiers, and the single external box stands for both the Syndicate Rule Engine EC2 host and the student EKS cluster, which live in other AWS accounts. For the full per-resource picture open the paired landscape `03-sep-account-landscape`. Two drawing choices are intentional, not defects. MongoDB Atlas, the Rule Engine host, and the EKS cluster are not resources of this account, so they are drawn outside the boundary with no AWS glyph — Atlas carries MongoDB's brand-green leaf and the external targets stay a neutral box; those edges correctly cross the line. The Atlas write (marker 8) now routes in a lower corridor clear of the S3 caption it previously overprinted. Two return steps — the signed callback (step 7) and the result push (step 11) — are named in the Flow legend but not drawn: as leftward back-edges they were the most crossing-toxic, so the legend keeps every step named while cutting crossings.

## See Also

This artifact is one of the mandatory triple: the drawing source `06-flow-task-verification.drawio`, its exported raster `06-flow-task-verification.drawio.png`, and this companion. It is a focused companion to the request-shape summary `02-sep-summary` and the full as-built landscape `03-sep-account-landscape`, which together give the container-level shape and the per-resource detail that this single flow deliberately omits. The authoritative facts come from the read-only production inventory of account `870325637521` in `eu-central-1`, collected under the inventory standards, together with the SEP architecture guide section on task verification; the review of that guide against the inventory is captured in `DOC-REVIEW-for-author.md`, and the recommended additions in `DOC-ADDITIONS-recommended.md`. The lane order, service-scope placement, external-actor placement, and numbered-flow-legend conventions this diagram follows are defined in the diagram standards steering document, and the class-aware severities that gate it are defined in the diagram lint ruleset shipped with the rule engine.
