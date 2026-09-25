---
id: generic-reference-architecture-diagram-v1
title: Generic Reference Architecture
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
  - generic
  - vendor-neutral
  - reference-architecture
  - golden-example
related_docs:
  - inventory-generic-env-prod-region-1-2026-09-22_1430/00-MANIFEST.md
  - inventory-generic-env-prod-region-1-2026-09-22_1430/10-delta-example.md
---

# Generic Reference Architecture

## Overview

This diagram is the golden example for the vendor-neutral `generic` Provider
Profile. It authors a PlantUML component diagram in `generic-reference-architecture.puml`
and uses grayscale shapes only — white fill with black or gray stroke — and no
vendor icons, exactly as `mappings/generic-icons.yaml` prescribes. The workload
runs inside the `env-prod` Environment (the stack Boundary) with all runtime
resources placed inside the `region-1` Network. An end user reaches a managed
Kubernetes cluster that fronts the API, which enqueues work on a message queue.
A serverless function consumes queued messages, calls the LLM platform for
inference, and persists state to managed data stores. The diagram exercises
seven neutral resource types, keeps a versioned title cell, a Legend block, and
labeled edges, so it passes every CRITICAL and ERROR lint rule and is eligible
for publication as the reference used when adding a new provider.

## Main Content

The diagram arranges nodes in lane order from actor to data. The end user
(`EndUser`) sends a request to the managed Kubernetes cluster (`api-cluster`)
over a primary-flow edge, and the cluster enqueues each task onto the message
queue (`task-queue`). The queue delivers messages asynchronously — drawn as a
dashed edge — to the function (`tool-invoker`). The function then fans out to
four backends: it invokes the LLM platform (`inference`) for model output,
persists state to the managed SQL database (`state-db`), writes generated output
to the object store (`artifact-store`), and reads credentials from the secrets
store (`app-secrets`). Every edge carries a descriptive label, and each node
name that contains a space is enclosed in double quotes so the `node-quote` rule
is satisfied. Nine workload nodes sit inside the two dashed boundary containers,
so the twelve-node cap holds without a split diagram or an index document.

## Troubleshooting

If the Linter reports `node-quote`, confirm every node label containing a space
is double-quoted in the PlantUML source. A `node-count` error means the diagram
exceeds twelve nodes; split it into multiple diagrams and add an index document
that references each split. A missing Legend triggers `legend-present`, so retain
the `legend right ... endlegend` block that defines the line styles, colors, and
change markers. A `title-versioned` warning means the title cell lost its `vN`
version token or its ISO date; keep the form `generic reference-architecture —
env-prod / region-1 | 2026-09-22 | v1`. Because this is the vendor-neutral
profile, never introduce a brand color: nodes stay grayscale with white fill and
black or gray stroke. A `frontmatter` CRITICAL finding names the offending key —
ensure all twelve keys are non-empty and `related_docs` holds at least one entry.

## See Also

This companion document pairs with the PlantUML source
`generic-reference-architecture.puml` to satisfy the diagram-standards decision
matrix, which requires a component or architecture diagram to be authored in
PlantUML. For the inventory side of the same vendor-neutral workload, see the
Snapshot Manifest `00-MANIFEST.md`, which records the read-only collection
metadata, and the delta example `10-delta-example.md`, which shows one added,
one changed, and one removed resource between snapshots. The `generic` Provider
Profile in the provider-profiles steering document lists the terminology
normalization, container conventions, grayscale palette, and manual-entry verbs
used here. The authoritative lint ruleset in `diagram-lint.md` defines every
rule this golden example is built to satisfy, and `kb-frontmatter.md` defines the
frontmatter contract this document conforms to. The following fenced example
shows the title-cell format used by the source:

```text
generic reference-architecture — env-prod / region-1 | 2026-09-22 | v1
```

## Anti-patterns

Avoid these mistakes when adapting the generic golden example. Do not import
vendor icon packs or emit a brand color: the `generic` profile is grayscale only,
so a `fillColor` outside white-to-black or any `resIcon`/vendor `grIcon` style is
wrong. Do not use PlantUML preprocessor directives — the following is rejected by
the diagram standards:

```plantuml
!include AWSCommon.puml
```

Do not leave an edge unlabeled; every edge must carry a non-empty descriptive
label or the Linter raises `edge-label`. Do not drop the version token or date
from the title cell, and do not use relative time expressions such as
"yesterday" in Change Marker descriptions — always use an ISO 8601 date. Do not
exceed twelve nodes in a single diagram; split instead. Finally, never let a
`.puml` or `.drawio` source ship without its matching companion document, since a
missing companion is a `companion-doc` ERROR that blocks publication.
