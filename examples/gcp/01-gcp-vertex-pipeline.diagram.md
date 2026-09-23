---
id: gcp-vertex-pipeline-companion
title: GCP Vertex AI Pipeline — Companion Document
kb_namespace: architecture
section: golden-examples
category: diagram
status: draft
updated: 2026-09-22
owner: platform-architecture-team
author: rule-engine
next_review_date: 2027-03-22
tags:
  - gcp
  - vertex-ai
  - golden-example
  - diagram
related_docs:
  - gcp-vertex-pipeline-manifest
---

# GCP Vertex AI Pipeline Golden Example

## Overview

This companion document describes the `01-gcp-vertex-pipeline` golden example, a
reference architecture for a machine-learning inference and training pipeline built
on Google Cloud. The diagram lives inside a Project boundary (`project-acme-prod`)
and a VPC network boundary (`vpc-prod`), rendered with the dashed green stack
boundary and the dashed blue network boundary defined in the shared diagram
standards. The workload accepts HTTPS requests at an API entry point, routes
inference traffic to Vertex AI, and processes asynchronous ingestion events through
Pub/Sub. It demonstrates the mandatory artifact triple, the versioned title cell,
the full Legend block, resolved GCP provider icons, and labeled edges. Every node
value uses the allowed unquoted character set so the diagram passes the node-quote
rule. The example is intended as a copy-and-adapt starting point for new GCP
architecture specs authored against this Rule Engine.

## Main Content

The pipeline arranges nodes left to right following the standard lane order. The
`api-gateway` node sits in the edge lane and forwards HTTPS traffic to the
`load-balancer` router. Primary inference flow reaches `vertex-ai`, the platform
core node backed by the Vertex AI managed LLM platform. Asynchronous ingestion runs
through `pubsub-events`, which delivers messages to the `ingest-function` Cloud
Function worker. That worker submits training work to `training-gke`, a Google
Kubernetes Engine cluster, which registers trained models back into Vertex AI. The
data lane holds three managed stores: `cloud-sql` for pipeline metadata,
`model-storage` on Cloud Storage for model artifacts, and `secret-manager` for
credentials fetched at ingestion time. Eleven nodes keep the diagram under the
twelve-node cap, so no split or index document is required for this example.

## Troubleshooting

If the Linter blocks this diagram, check the findings by rule name. A `node-count`
error means more than twelve nodes are present; split the diagram and add an index
document. A `node-quote` error means a node value contains a space or a character
outside `[A-Za-z0-9_-]`; either rename it or wrap the value in double quotes. A
`legend-present` error means the Legend cell was removed or its value no longer
begins with the word Legend. A `title-versioned` warning means the title cell lost
its `vN` version token or its `YYYY-MM-DD` date. An `icon-resolved` error means a
node style points at a placeholder rather than a resolved official Google Cloud
icon file path from the GCP icon mapping. A `companion-doc` error means this `.diagram.md` file is
missing or misnamed relative to the `.drawio` source. Fix each finding and re-run
the CLI until it reports the artifact as eligible.

## Anti-patterns

Avoid these recurring mistakes when adapting the example. Do not embed real secret
values, key material, or SecureString contents anywhere in the diagram or its
companion; snapshots record metadata only, and any leaked value triggers a CRITICAL
secret-safety finding. Do not exceed the twelve-node limit by adding every incidental
resource; model the significant flow instead and split into multiple diagrams with an
index document when a system is genuinely larger. Do not leave any edge unlabeled,
since a missing label raises an edge-label warning and hides the meaning of the flow.
Do not mix providers into a single-cloud example; use the cross-cloud composition
example for multi-provider work. The delta snippet below shows the intended
change-marker vocabulary rather than an anti-pattern.

```json
{
  "delta": [
    { "identity": "batch-predict-function", "change": "added",   "marker": "new" },
    { "identity": "vertex-ai",               "change": "changed", "marker": "changed" },
    { "identity": "legacy-cloud-endpoints",  "change": "removed", "marker": "red" }
  ]
}
```

Do not invent icon ids; every style must trace to `mappings/gcp-icons.yaml`. Do not
use relative dates in the title cell or change markers; always use ISO 8601 dates.

## See Also

The matching inventory snippet for this example lives in `00-MANIFEST.md` within the
same directory and records the seven required manifest fields for a read-only GCP
snapshot. The authoritative rules that govern this document are defined in the
always-on steering set: `diagram-standards.md` for lane order, node limits, the
title-cell format, and the Legend block; `diagram-lint.md` for the lint rule names
and severities used in Troubleshooting; `kb-frontmatter.md` for the twelve required
frontmatter keys and the section-length bounds applied here; and
`provider-profiles.md` for the GCP terminology normalization row and container
conventions. The GCP icon style strings referenced by every node come from
`mappings/gcp-icons.yaml`. For sibling golden examples across the other provider
profiles, see the `aws`, `azure`, `oci`, and `generic` example directories, which
follow the identical artifact-triple and delta-example structure described in this
document.
