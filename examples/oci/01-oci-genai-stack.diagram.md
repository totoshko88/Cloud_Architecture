---
id: oci-genai-stack-companion
title: OCI Generative AI Stack — Companion Document
kb_namespace: architecture
section: golden-examples
category: diagram
status: draft
updated: 2026-09-22
owner: platform-architecture-team
author: rule-engine
next_review_date: 2027-03-22
tags:
  - oci
  - generative-ai
  - golden-example
  - diagram
related_docs:
  - oci-genai-stack-manifest
---

# OCI Generative AI Stack Golden Example

## Overview

This companion document describes the `01-oci-genai-stack` golden example, a
reference architecture for a generative-AI inference and training stack built on
Oracle Cloud Infrastructure. The diagram lives inside a Compartment boundary
(`compartment-acme-prod`) and a Virtual Cloud Network boundary (`vcn-prod`),
rendered with the dashed green stack boundary and the dashed blue network boundary
defined in the shared diagram standards. The workload accepts HTTPS requests at a
Functions entry point, routes inference traffic to OCI Generative AI, and processes
asynchronous ingestion events through OCI Streaming. It demonstrates the mandatory
artifact triple, the versioned title cell, the full Legend block, resolved OCI
provider icons, and labeled edges. Every node value uses the allowed unquoted
character set so the diagram passes the node-quote rule. The example is intended as
a copy-and-adapt starting point for new OCI architecture specs authored against this
Rule Engine, mirroring its AWS, Azure, and GCP siblings exactly.

## Main Content

The stack arranges nodes left to right following the standard lane order. The
`api-function` node sits in the edge lane and forwards HTTPS traffic to the
`load-balancer` router. Primary inference flow reaches `generative-ai`, the platform
core node backed by the OCI Generative AI managed LLM platform. Asynchronous
ingestion runs through `streaming-events`, which delivers messages to the
`ingest-function` Functions worker. That worker submits training work to
`training-oke`, an Oracle Container Engine for Kubernetes cluster, which registers
trained models back into Generative AI. The data lane holds three managed stores:
`autonomous-db` for pipeline metadata, `model-storage` on Object Storage for model
artifacts, and `vault-secrets` for credentials fetched at ingestion time. Eleven
nodes keep the diagram under the twelve-node cap, so no split or index document is
required for this example, matching the sibling profiles.

## Troubleshooting

If the Linter blocks this diagram, check the findings by rule name. A `node-count`
error means more than twelve nodes are present; split the diagram and add an index
document. A `node-quote` error means a node value contains a space or a character
outside `[A-Za-z0-9_-]`; either rename it or wrap the value in double quotes. A
`legend-present` error means the Legend cell was removed or its value no longer
begins with the word Legend. A `title-versioned` warning means the title cell lost
its `vN` version token or its `YYYY-MM-DD` date. An `icon-resolved` error means a
node style points at a placeholder rather than a resolved `mxgraph.oci` shape from
the OCI icon mapping. A `companion-doc` error means this `.diagram.md` file is
missing or misnamed relative to the `.drawio` source. Fix each finding and re-run
the CLI until it reports the artifact as eligible for publication.

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
    { "identity": "generative-ai",           "change": "changed", "marker": "changed" },
    { "identity": "legacy-model-endpoint",   "change": "removed", "marker": "red" }
  ]
}
```

Do not invent icon ids; every style must trace to `mappings/oci-icons.yaml`. Do not
use relative dates in the title cell or change markers; always use ISO 8601 dates.

## See Also

The matching inventory snippet for this example lives in `00-MANIFEST.md` within the
same directory and records the seven required manifest fields for a read-only OCI
snapshot. The authoritative rules that govern this document are defined in the
always-on steering set: `diagram-standards.md` for lane order, node limits, the
title-cell format, and the Legend block; `diagram-lint.md` for the lint rule names
and severities used in Troubleshooting; `kb-frontmatter.md` for the twelve required
frontmatter keys and the section-length bounds applied here; and
`provider-profiles.md` for the OCI terminology normalization row and container
conventions. The OCI icon style strings referenced by every node come from
`mappings/oci-icons.yaml`. For sibling golden examples across the other provider
profiles, see the `aws`, `azure`, `gcp`, and `generic` example directories, which
follow the identical artifact-triple and delta-example structure described here.
