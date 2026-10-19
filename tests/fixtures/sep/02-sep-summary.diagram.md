---
id: 02-sep-summary-v2
title: SEP summary — request shape (container-level)
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-14
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-13
diagram_class: flow
diagram_type: container
detailed_view: 03-sep-account-landscape
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

This diagram is the container-level C4 view of the Syndicate Education Platform (SEP) running in the production AWS account `870325637521` in `eu-central-1`. It is the summary half of a summary-plus-landscape pair: it answers a single question — how does a request move end-to-end through SEP? — and deliberately collapses families of resources into representative nodes so the whole shape fits in nine nodes, under the twelve-node flow cap. The detailed as-built that enumerates every resource is the paired landscape `03-sep-account-landscape`, cross-linked from this companion's `detailed_view`. The facts drawn here come from a strictly read-only inventory of the live production account, not from the application code: thirteen Lambda functions, fourteen SQS queues, five AWS Batch compute environments, twenty-five S3 buckets, three API Gateways, and a MongoDB Atlas cluster in Frankfurt reached over VPC peering. Nothing on the canvas is invented; counts and services are the deployed reality at collection time.

## Main Content

The request shape reads left to right along the fixed lane order. A client (web or mobile) enters through the edge lane, which carries two front doors: the REST APIs node collapses the management-api and ui-api gateways, and socket-api is the WebSocket gateway drawn separately because it is a distinct protocol. Both front doors invoke the Lambda core, a single node standing for all thirteen functions (lti-adapter, management-api-handler, socket-handler, and the rest). From the Lambda core three asynchronous and data paths fan out: it enqueues and consumes the fourteen SQS queues, submits jobs to the AWS Batch fleet, and calls Bedrock for the Angry EdA model. For persistence it reads and writes the twenty-five S3 buckets and the external MongoDB Atlas cluster. Every regional AWS service sits inside the account boundary but outside any VPC; Atlas sits outside the account because it is not an AWS resource.

## Troubleshooting

If a node looks wrong, remember this is a summary: representative nodes stand for families, so "Lambda core" is one icon for thirteen functions and "SQS" is one icon for fourteen queues. For per-resource detail, open the paired landscape `03-sep-account-landscape` rather than expecting it here. Two icons are known Rule Engine gaps and are intentional, not defects. AWS Batch has no bundled role in the shipped `roles.yaml`, so a workspace-local `batch` role was added to render the official Batch icon; this is noted in the build report as an improvement to upstream. MongoDB Atlas is not an AWS service, so it is drawn with MongoDB's own brand-green leaf mark (not an AWS glyph) in the external on-premises lane outside the account boundary. If the raster looks oversized, confirm the export used the flow budget: at most 1600 pixels wide and under 500 kilobytes on a white background.

## See Also

This artifact is one of the mandatory triple: the drawing source `02-sep-summary.drawio`, its exported raster `02-sep-summary.drawio.png`, and this companion. Its detailed counterpart is the landscape `03-sep-account-landscape`, which draws every enumerated resource on one canvas and links back here through its `summary_of`. The authoritative facts come from the read-only production inventory of account `870325637521` in `eu-central-1`, collected and recorded under the inventory standards; the review of the architecture guide against that inventory is captured in `DOC-REVIEW-for-author.md`, and the recommended additions in `DOC-ADDITIONS-recommended.md`. The lane order, container padding, service-scope placement, and numbered-flow-legend conventions this diagram follows are defined in the diagram standards steering document, and the class-aware severities that gate it are defined in the diagram lint ruleset maintained alongside the other packaged rule-engine gates.
