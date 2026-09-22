---
id: runbook-add-a-provider
title: Add a New Provider Runbook
kb_namespace: cloud-architecture
section: runbooks
category: runbook
status: published
updated: 2026-09-22
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-22
tags:
  - runbook
  - provider-profile
  - extensibility
  - icon-mapping
  - inventory-verbs
related_docs:
  - ../README.md
  - ../.kiro/steering/provider-profiles.md
  - ../.kiro/steering/diagram-lint.md
---

# Add a New Provider Runbook

## Overview

This runbook enumerates the discrete, ordered steps to extend the Diagram &
Inventory Rule Engine with a new provider. The engine separates a
provider-neutral core from per-provider profiles, so a new provider is added by
**data**, never by changing core code. You add a terminology row, an icon
mapping, read-only inventory verbs, a golden example, and then confirm a clean
lint run. Follow the steps in order: each later step depends on the artifacts
created earlier, and the final lint run is the completion gate defined by
Requirement 9 AC9. When the Linter reports zero violations across every diagram
and Markdown document, the new provider is considered fully integrated and ready
for release bundling. Perform every step exactly once for the new provider, and
keep the provider identifier consistent across the profile row, the mapping
file name, the verb list, and the golden example folder so the core resolves
them without ambiguity.

## Main Content

The workflow has five ordered steps, summarized in the table below and detailed
in the sections that follow. Execute them top to bottom.

| # | Step | Primary artifact |
| --- | --- | --- |
| 1 | Add a Provider Profile row | `.kiro/steering/provider-profiles.md` |
| 2 | Add an icon mapping | `mappings/<provider>-icons.yaml` |
| 3 | Add inventory verbs | `.kiro/steering/provider-profiles.md` |
| 4 | Add a Golden Example | `examples/<provider>/` |
| 5 | Complete a lint run | `rule-engine-lint --all` |

Step 1 registers the nine neutral concepts. Step 2 binds each concept to a
concrete icon, brand hex, and draw.io style plus the two container styles. Step
3 declares the read-only enumeration verbs and the cost endpoint. Step 4 proves
the profile end to end with a reference artifact triple, a manifest, and a delta.
Step 5 gates the work: the Linter must report zero CRITICAL and zero ERROR
findings before the provider ships. Each step names concrete files so the change
stays reviewable and traceable.

## Step 1 — Add a Provider Profile terminology row

Add one terminology normalization row for the new provider in
`.kiro/steering/provider-profiles.md`, covering all nine neutral concepts. Every
concept must map to a native service label; a profile that omits any concept is
a profile-convention error.

The nine neutral concepts and their `resource_type` enum values are:

1. Boundary (`boundary`)
2. Network Boundary (`network_boundary`)
3. serverless function (`serverless_fn`)
4. object store (`object_store`)
5. managed SQL (`managed_sql`)
6. message queue (`message_queue`)
7. secrets store (`secrets_store`)
8. managed Kubernetes (`managed_k8s`)
9. LLM platform (`llm_platform`)

In the same step, declare the provider's two **container conventions** (exactly
one Boundary container style and exactly one Network Boundary container style)
and its **brand palette** primary `#RRGGBB` anchor.

## Step 2 — Add an icon mapping

Create `mappings/<provider>-icons.yaml`. Map each of the nine neutral
`resource_type` values to an icon id/file, a `#RRGGBB` brand hex, and a complete
draw.io style string. Declare exactly one `boundary` and one `network_boundary`
container group style, and declare `asset_pack` plus `icon_source` (exactly one
of `custom` or `builtin`). Source every icon id and color from the provider's
authoritative asset pack.

```yaml
provider: <provider>
asset_pack: <authoritative-asset-pack-id>
icon_source: custom        # custom | builtin
brand_hex: "#RRGGBB"
resources:
  serverless_fn:
    icon: <icon-id>
    brand_hex: "#RRGGBB"
    style: "<drawio-style-string>"
  # ... all nine resource_type entries ...
containers:
  boundary:
    style: "<boundary-group-style>"
  network_boundary:
    style: "<network-boundary-group-style>"
```

## Step 3 — Add inventory read-only verbs

Declare the provider's read-only enumeration verbs and its cost endpoint in the
profile. Include **only** read-only verbs; every create, update, or delete verb
is excluded so the count of state-mutating verbs per run is zero.

```text
Read-only verbs: <provider list-style verbs, e.g. `xyz … list`, `xyz … get`>
Cost endpoint:   <provider-specific cost/billing endpoint>
```

## Step 4 — Add a Golden Example

Add one reference artifact under `examples/<provider>/` that passes every
CRITICAL and ERROR lint rule. Produce the full artifact triple plus the inventory
side and a delta example:

```text
examples/<provider>/
├── 01-<workload>.drawio
├── 01-<workload>.drawio.png
├── 01-<workload>.diagram.md          # kb-frontmatter compliant companion
├── sample-resource.json              # validates against the Inventory Schema
└── inventory-<provider>-<boundary>-<region>-<YYYY-MM-DD_HHMM>/
    └── 00-MANIFEST.md                # all fields non-empty + delta instructions
```

## Step 5 — Complete a lint run

Run the Linter and confirm zero violations. This is the completion gate.

```bash
pip install -e .
.venv/bin/rule-engine-lint --all --fail-on error,critical
rule-engine-validate-schema --schema schemas/inventory.schema.json \
  --targets 'examples/**/*.json'
```

A clean run exits `0` with no CRITICAL and no ERROR findings. Only then is the
new provider ready for the CI Release Bundle.

## Anti-patterns

Avoid these mistakes when adding a provider. Do not add a partial terminology
row: omitting any of the nine concepts is a profile-convention error and the
core cannot resolve the missing concept. Do not emit placeholder icons in the
mapping; an unresolved placeholder is an `icon-resolved` ERROR. Do not include
any state-mutating verb (`create*`, `put*`, `update*`, `delete*`, `remove*`,
`set*`) in the read-only verb list. Do not record secret values, key material,
or SecureString contents in any snapshot file — that is a `secret-safety`
CRITICAL finding. Do not ship a `.drawio` without its matching `.diagram.md`
companion, and do not omit the twelve required frontmatter keys from any
generated Markdown document. Never treat a lint run with WARNING-only findings
as failed, but never ship one with any ERROR or CRITICAL finding.

## Troubleshooting

If the Linter reports `frontmatter` (CRITICAL) on your golden companion doc,
confirm all twelve frontmatter keys are present and non-empty, that `status` is
one of `draft`, `review`, or `published`, and that `tags` holds one to twenty
entries. An `icon-resolved` ERROR means a node style still references a
placeholder rather than a concrete icon from `mappings/<provider>-icons.yaml`. A
`companion-doc` ERROR means a `.drawio` file has no matching `.diagram.md` with
the same stem. A `legend-present` or `node-count` ERROR points at the diagram
itself: add the Legend block or split diagrams above twelve nodes. If
`rule-engine-lint --all` unexpectedly lints this runbook, verify it stays
kb-frontmatter compliant or that its basename sits in the CLI exclusion set. A
`secret-safety` CRITICAL means a snapshot file leaked a secret value; strip it
and record metadata only.

## See Also

The authoritative source for the ordered steps is Requirement 9 AC9 in
`.kiro/specs/multicloud-diagram-inventory/requirements.md`, and the design
narrative lives in the Extensibility / Add-a-Provider Runbook section of
`.kiro/specs/multicloud-diagram-inventory/design.md`. The provider profile
structure — the nine-concept terminology table, container conventions, brand
palette, and read-only verb lists — is defined in
`.kiro/steering/provider-profiles.md`, whose "Adding a New Provider" section
mirrors these steps. The lint rules and severities that the final gate enforces
are defined in `.kiro/steering/diagram-lint.md`, and the frontmatter contract
for the golden example companion document is in
`.kiro/steering/kb-frontmatter.md`. For a concrete reference to copy, study the
`aws` golden example under `examples/aws/` and its companion document. The
project `README.md` links every steering document and the installation guide.
