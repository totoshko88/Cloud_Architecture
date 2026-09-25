---
id: aws-agent-platform-diagram-v1
title: AWS Agent Platform Architecture
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-09-22
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-22
diagram_class: flow
tags:
  - aws
  - bedrock
  - agent-platform
  - golden-example
related_docs:
  - 00-MANIFEST.md
---

# AWS Agent Platform Architecture

## Overview

The AWS agent platform is the reference workload for the `aws` Provider Profile.
It runs inside AWS Account `123456789012` in `us-east-1`, with all workload
resources placed inside the `VPC-agent-net` Network Boundary. Requests enter
through an Amazon EKS cluster that fronts the agent API, which enqueues work on
an SQS task queue. A Lambda tool-invoker consumes queued messages, calls Amazon
Bedrock for model inference, and persists state to managed data stores. This
diagram is the aws golden example: it exercises seven of the nine neutral
resource types with resolved `mxgraph.aws4` icons, a versioned title cell, a
Legend block, labeled edges, and the mandatory companion document, so it passes
every CRITICAL and ERROR lint rule and is eligible for publication.

## Main Content

The diagram places nodes in lane order from edge to data. The EKS cluster
(`agent-eks-cluster`) receives inbound traffic and enqueues each request onto
the SQS queue (`agent-task-queue`) over a primary flow edge. The queue delivers
messages asynchronously — shown as a dashed edge — to the Lambda tool-invoker
(`agent-tool-invoker`). Lambda then fans out to four backends: it invokes the
Bedrock LLM platform (`agent-bedrock-llm`) for inference, persists dialogue to
the RDS conversation store (`agent-conversation-db`), writes generated output to
the S3 artifact store (`agent-artifact-store`), and reads API credentials from
Secrets Manager (`agent-api-secrets`). Every edge carries a descriptive label,
and node names use only hyphenated identifiers so the `node-quote` rule is
satisfied without double quoting. The full artifact triple accompanies this
source.

## Troubleshooting

If the Linter reports `icon-resolved`, confirm each node style references a
concrete `resIcon=mxgraph.aws4.<service>` value from `mappings/aws-icons.yaml`
rather than a placeholder. A `node-count` error means the diagram exceeds twelve
nodes; split it and add an index document. A `companion-doc` error indicates
this `.diagram.md` file was renamed away from the `01-aws-agent-platform` stem
that the `.drawio` source expects — keep the stems identical. A `frontmatter`
CRITICAL finding names the offending key: ensure all twelve keys are present and
non-empty, and that `related_docs` holds at least one entry, since the Linter
treats an empty list as missing. A missing Legend triggers `legend-present`, so
retain the Legend cell whose value begins with the word Legend.

## See Also

This companion document pairs with `01-aws-agent-platform.drawio` and its
exported raster `01-aws-agent-platform.drawio.png` to complete the mandatory
artifact triple defined in the diagram standards. For the inventory side of the
same workload, see the snapshot Manifest `00-MANIFEST.md`, which records the
read-only collection metadata, and the delta example that shows one added, one
changed, and one removed resource between snapshots. The `aws` Provider Profile
in the provider-profiles steering document lists the terminology normalization,
container conventions, brand palette, and read-only verbs used here. The
authoritative lint ruleset in `diagram-lint.md` defines every rule this golden
example is built to satisfy, and `kb-frontmatter.md` defines the frontmatter
contract this document conforms to.
