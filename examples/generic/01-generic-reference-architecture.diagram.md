---
id: generic-reference-architecture-companion
title: Generic Reference Architecture — Companion Document
kb_namespace: architecture
section: golden-examples
category: diagram
status: draft
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
  - diagram
related_docs:
  - inventory-generic-env-prod-region-1-2026-09-22_1430/00-MANIFEST.md
---

# Generic Reference Architecture Golden Example

## Overview

This companion document describes `01-generic-reference-architecture.drawio`, the
golden example for the vendor-neutral `generic` Provider Profile. Per decision D1
the source is now authored in draw.io — the only publishable diagram source —
replacing the retired PlantUML sketch. The diagram uses grayscale shapes only:
white fill with black or gray stroke, and no vendor icons, exactly as
`mappings/generic-icons.yaml` prescribes. The workload runs inside the `env-prod`
Environment (the stack Boundary, drawn as a dashed `#333333` rectangle) with every
runtime resource placed inside the `region-1` Network Boundary (dashed `#666666`). An
external end user reaches a managed Kubernetes cluster that fronts the API, which
enqueues work on a message queue; a serverless function then consumes queued
messages and calls the LLM platform and data stores. The diagram exercises seven
neutral resource types plus one external actor, keeps a versioned title cell, a
Legend block, and labeled edges, so it clears every CRITICAL and ERROR lint rule.

## Main Content

The diagram arranges nodes in lane order from actor to data, reading left to
right. The end user (`End_User`) sits outside both boundaries, since only cloud
resources belong inside the Environment and Network. It sends a request to the
managed Kubernetes cluster (`api-cluster`) over a primary-flow edge, and the
cluster enqueues each task onto the message queue (`task-queue`). The queue
delivers messages asynchronously — drawn as a dashed edge — to the serverless
function (`tool-invoker`). The function then fans out to four backends: it
invokes the LLM platform (`inference`), persists state to the managed SQL
database (`state-db`), writes generated output to the object store
(`artifact-store`), and reads credentials from the secrets store (`app-secrets`).
Three branches leave the function's right face and the fourth spills onto the
bottom face, so no single side carries more than three exits. Seven cloud nodes
plus one actor stay well within the twelve-node cap.

## Troubleshooting

If a lint gate blocks this example, inspect the findings by rule name. A
`source-format` error means a `.puml` or `.mmd` file is still present; the
draw.io triple must replace it. A `node-count` error means the twelve-node
ceiling was exceeded; split the diagram and add an index document. A `node-quote`
error means a node value contains a space or a character outside `[A-Za-z0-9_-]`
and was not double-quoted. A missing Legend triggers `legend-present`, so retain
the Legend cell defining line styles, colors, and change markers. A
`title-versioned` warning means the title cell lost its `vN` token or its ISO
date; keep the form `generic reference-architecture — env-prod / region-1 |
2026-09-22 | v1`. Because this is the vendor-neutral profile, never introduce a
brand color: nodes stay grayscale with white fill and black or gray stroke, and
an `icon-resolved` error means a node picked up a vendor `resIcon` style.

## Anti-patterns

Avoid these mistakes when adapting the generic golden example. Do not import
vendor icon packs or emit a brand color: the `generic` profile is grayscale only,
so a `fillColor` outside white-to-black or any `resIcon`/vendor `grIcon` style is
wrong. Do not draw the external actor inside the cloud boundaries — only cloud
resources live inside the Environment and Network. Do not leave an edge
unlabeled; every edge must carry a non-empty descriptive label or the Linter
raises `edge-label`. Do not re-author this as PlantUML — the following intent is
now a `source-format` ERROR that blocks publication:

```text
@startuml
title generic reference-architecture
@enduml
```

Do not exceed twelve nodes in a single diagram; split instead. Finally, never let
a `.drawio` source ship without its matching companion document, since a missing
companion is a `companion-doc` ERROR.

## See Also

The authoritative rules that govern this example live in the always-on steering
set. `diagram-standards.md` defines the lane order, the twelve-node cap, the
container padding, the versioned title-cell format, the mandatory Legend block,
decision D1 (draw.io is the only publishable source), and the edge-routing rules
this diagram follows. `diagram-lint.md` supplies the rule names and severities
referenced in the Troubleshooting section, including `source-format`.
`provider-profiles.md` supplies the `generic` profile: the terminology
normalization for the nine neutral types, the container conventions (dashed `#333333`
Environment, dashed `#666666` Network), the grayscale palette, and the manual-entry
verbs. `mappings/generic-icons.yaml` supplies the concrete grayscale style
strings this diagram resolves for each node, and `kb-frontmatter.md` defines the
twelve required frontmatter keys and section-length bounds this document conforms
to. For the inventory side of the same vendor-neutral workload, see the Snapshot
Manifest `00-MANIFEST.md`, which records the read-only collection metadata.
