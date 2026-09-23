---
id: azure-openai-rag-diagram-v1
title: Azure OpenAI RAG Reference Architecture
kb_namespace: cloud-architecture
section: golden-examples
category: azure
status: draft
updated: 2026-09-22
owner: platform-architecture-team
author: rule-engine-diagram-generator
next_review_date: 2027-03-22
tags:
  - azure
  - openai
  - rag
  - reference-architecture
  - golden-example
related_docs:
  - examples/azure/00-MANIFEST.md
---

# Azure OpenAI RAG Reference Architecture

## Overview

This companion document describes the `azure-openai-rag` golden example, a
retrieval-augmented generation workload deployed inside a single Azure
Subscription (`sub-9f3c1a`) in the `eastus` region. The diagram is the
provider-neutral reference for the `azure` profile: it demonstrates how the nine
neutral resource concepts map onto native Azure services and how the two
structural boundaries render as dashed containers. A User reaches the workload
through an Application Gateway at the edge, which routes to an API Function. The
API Function calls Azure OpenAI for embeddings and completions, reads its key
material from Key Vault, and queries a vector store backed by Azure SQL Database.
Document ingestion runs asynchronously through Service Bus and an Ingest
Function. The diagram stays within the twelve-node limit and orders lanes from
actors on the left to data on the right, matching the workspace diagram
standards so the artifact passes every blocking lint rule cleanly.

## Main Content

The architecture follows the fixed left-to-right lane order: actors, edge,
router, asynchronous messaging, workers, platform core, and data. The User actor
sends an HTTPS request to the Application Gateway, which routes `/chat` traffic
to the API Function. Synchronous requests flow to Azure OpenAI for embedding and
completion, while the API Function reads its API key from Key Vault and queries
vectors from Azure SQL Database. Ingestion is asynchronous: the API Function
publishes a job to Service Bus, which delivers the message to the Ingest
Function. That worker loads source documents from Blob Storage and upserts the
resulting vectors into Azure SQL Database. Every node uses a resolved Azure icon
style drawn from the authoritative mapping, and each edge carries a descriptive
label. The Subscription renders as a dashed green boundary and the VNet renders
as a dashed blue boundary, exactly as the shared Legend defines for all
providers regardless of cloud.

## Troubleshooting

If the linter reports a `node-count` error, the diagram exceeds twelve nodes and
must be split into multiple diagrams with an index document. A `node-quote`
error means a node value contains a space or other special character and is not
double-quoted; rename the node to the allowed character set or wrap it in
quotes. A missing `legend-present` finding indicates the Legend cell was removed
or its value no longer begins with `Legend`. An `icon-resolved` error signals a
placeholder icon; confirm each node style references a real azure2 image shape
(`image=img/lib/azure2/<category>/<Name>.svg`) from the icon mapping. A `companion-doc` error appears when this file is
renamed away from the diagram stem. Frontmatter problems are CRITICAL: verify
all twelve keys are present and non-empty, and that `related_docs` holds at least
one entry. Re-run the CLI linter after each change until it reports OK.

## See Also

The inventory snapshot manifest at `examples/azure/00-MANIFEST.md` records the
read-only collection that produced the resource set shown here, including the
provider, boundary identifier, region set, caller identity, tool versions, file
count, and delta instructions for the next session. The provider profile rules
define the Azure terminology normalization row, container conventions, brand
palette, and read-only enumeration verbs used to build this example. The diagram
standards document specifies the lane order, node limit, title cell format, and
mandatory Legend block. The lint ruleset defines each rule name and severity,
and the knowledge-base frontmatter rules define the twelve required keys and the
section length bounds. Consult those steering documents when adapting this
golden example to a new Azure workload or when adding a different provider
profile to the engine.

## Anti-patterns

Avoid embedding secret values, connection strings, or Key Vault contents in the
diagram or this document; snapshots and companions record metadata only. Do not
add preprocessor directives or multiple diagram roots. The following title cell
format is the required shape and must not be abbreviated:

```text
azure azure-openai-rag — sub-9f3c1a / eastus | 2026-09-22 | v1
```

Do not exceed two levels of list nesting, do not use tables wider than five
columns, and never leave an edge without a descriptive label. Keep the node
count at or below twelve; when a workload grows larger, split it rather than
crowding a single canvas.
