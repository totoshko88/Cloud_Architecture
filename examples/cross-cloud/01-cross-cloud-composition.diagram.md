---
id: cross-cloud-composition-companion
title: Cross-Cloud Composition — Companion Document
kb_namespace: architecture
section: golden-examples
category: diagram
status: draft
updated: 2026-09-22
owner: platform-architecture-team
author: rule-engine
next_review_date: 2027-03-22
diagram_class: flow
tags:
  - cross-cloud
  - multicloud
  - c4-container
  - golden-example
  - diagram
related_docs:
  - aws-agent-platform-companion
  - azure-openai-rag-companion
  - gcp-vertex-pipeline-companion
---

# Cross-Cloud Composition Golden Example

## Overview

This companion document describes `01-cross-cloud-composition.drawio`, the
reference C4 container diagram that spans three provider profiles in one coherent
picture: AWS, Azure, and Google Cloud. The composition models an agent platform
whose edge and authentication tier lives on AWS, whose retrieval-augmented
generation tier lives on Azure, and whose training and artifact-storage tier
lives on Google Cloud. Each provider is named explicitly and rendered with its
brand-color anchor from `provider-profiles.md`: AWS uses `#232F3E`, Azure uses
`#0078D4`, and Google Cloud uses `#4285F4`. Every provider contributes both a
Boundary container and a Network Boundary container, drawn as nested groups that
carry the profile brand color. Per decision D1 the source is now authored in
draw.io — the only publishable diagram source — replacing the retired PlantUML
sketch, while keeping the total service-node count within the twelve-node
ceiling for a flow-class diagram.

## Main Content

The diagram arranges the three provider stacks left to right and connects them
with labeled cross-provider edges. On AWS, the `edge-gateway` node accepts
inbound traffic inside the `vpc-edge` network boundary and forwards requests to
`auth-lambda`, which validates the caller. The authenticated prompt then crosses
into Azure, where `openai-service` performs the retrieval-augmented generation
call and `service-bus` publishes a completion event asynchronously. From Azure
the event streams into Google Cloud, where `vertex-ai` computes embeddings and
`cloud-storage` persists the resulting model artifacts. A final return edge
sends a signed artifact URL from Google Cloud back to the AWS edge gateway,
closing the loop. Six service nodes carry six numbered flow markers, and the
three Boundary plus three Network Boundary containers frame each stack. Icons
resolve through `mappings/<provider>-icons.yaml`, so every node uses its correct
per-provider service icon.

## Troubleshooting

If a lint gate blocks this composition, inspect the findings by rule name. A
`node-count` error means the twelve-node ceiling was exceeded; remove an
incidental node or split the composition into multiple diagrams with an index
document. A `node-quote` error means a node value contains a space or a
character outside `[A-Za-z0-9_-]` and was not wrapped in double quotes. A
`source-format` error means a `.puml` or `.mmd` file is still present; the
draw.io triple must replace it. A missing edge label surfaces the `edge-label`
warning, so confirm every cross-provider arrow still carries its data-flow text.
A `title-versioned` warning means the title line lost its `vN` token or its
`YYYY-MM-DD` date. An `icon-resolved` error means a node references an unknown
stencil id or image path; verify each style against the committed manifests
before publishing the composition.

## Anti-patterns

Avoid these recurring mistakes when adapting the cross-cloud example. Do not
collapse multiple providers into one unlabeled cloud; each provider must be
named and colored with its own brand anchor. Do not leave any cross-provider
edge without a data-flow label, since an unlabeled edge hides the meaning of the
integration and raises a warning. Do not exceed twelve nodes by drawing every
incidental resource; model the significant flow and split when a system is
genuinely larger. Do not embed real secret values or key material anywhere in
the source or this companion. The delta snippet below shows the intended change
marker vocabulary rather than an anti-pattern.

```json
{
  "delta": [
    { "identity": "vertex-ai",       "change": "added",   "marker": "new" },
    { "identity": "openai-service",  "change": "changed", "marker": "changed" },
    { "identity": "legacy-bridge",   "change": "removed", "marker": "red" }
  ]
}
```

Do not use relative dates in the title or markers; always use ISO 8601 dates.

## See Also

The authoritative rules that govern this composition live in the always-on
steering set. `diagram-standards.md` defines the Multi-cloud Composition
section, the twelve-node cap, the C4 container requirement, per-provider icon
and color conventions, the container styles for every Boundary and Network
Boundary, the versioned title-cell format, and the mandatory Legend block. It
also defines decision D1, which makes draw.io the only publishable source.
`diagram-lint.md` supplies the rule names and severities referenced in the
Troubleshooting section, including `source-format`. `kb-frontmatter.md` defines
the twelve required frontmatter keys and the section-length bounds applied to
this document. `provider-profiles.md` supplies the brand palette anchors and the
per-provider container conventions used to color and group each stack. The
single-cloud sibling golden examples for AWS, Azure, and Google Cloud live under
the `aws`, `azure`, and `gcp` example directories and follow the same artifact
triple, while `mappings/<provider>-icons.yaml` supplies the concrete style
strings this composition resolves for each provider node.
