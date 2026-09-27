---
id: aws-agent-platform-delta-2026-09-22_1430
title: AWS Agent Platform Delta Example
kb_namespace: cloud-architecture
section: inventory-snapshots
category: delta
status: published
updated: 2026-09-22
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-22
tags:
  - aws
  - inventory
  - delta
  - change-markers
related_docs:
  - 00-MANIFEST.md
---

# AWS Agent Platform Delta Example

## Overview

This delta example compares the current Snapshot
`inventory-aws-123456789012-us-east-1-2026-09-22_1430` against the previous
Snapshot for the same boundary and region. The Delta Engine matches every
Normalized Resource on the identity tuple
`(provider, resource_type, boundary, region, identity)`, where identity is the
resource `id` when present and non-empty, otherwise its `name`. Including
`boundary` and `region` keeps two resources that share a name in different
accounts or regions from colliding. Each matched identity is classified as
added, changed, removed, unchanged, or duplicate, and every classification
carries a Change Marker: 🆕 for added, 🔄 for changed, and red styling for
removed. Unchanged and duplicate resources carry no marker. This example
deliberately shows exactly one added, one changed, and one removed resource so
the golden example demonstrates all three visible Change Markers.

## Main Content

The three highlighted transitions between the previous and current Snapshot are
listed below. The `agent-artifact-store` bucket is new this run (🆕). The
`agent-tool-invoker` function changed because its `config_digest` differs
between snapshots (🔄). The retired `agent-legacy-cache` store is present only in
the previous Snapshot and is therefore removed (red).

| Marker | Resource | resource_type | Classification |
| --- | --- | --- | --- |
| 🆕 | agent-artifact-store | object_store | added |
| 🔄 | agent-tool-invoker | serverless_fn | changed |
| red | agent-legacy-cache | object_store | removed |

The added row has no previous digest; the changed row has differing previous and
current digests; the removed row has no current digest. All other resources in
the Snapshot are unchanged and carry no marker.

## Troubleshooting

If a resource that clearly moved shows as both added and removed instead of
changed, its identity key changed between snapshots — confirm the `id` (or
`name` fallback) is stable across runs. If the Delta Engine raises a
`snapshot-input` error, one of the two snapshots is missing or malformed and no
classification is produced; validate that every entry is a mapping carrying
`provider`, `resource_type`, `boundary`, `region`, and a non-empty `id` or
`name`. If an identity is reported `duplicate` (with a detail such as
`current: 2 entries`), that identity occurs more than once in one snapshot; the
Engine reports it explicitly rather than silently keeping the last writer, so
de-duplicate the source enumeration. A resource expected to be changed but
reported unchanged means its `config_digest` did not change. Removed resources
must never trigger any state-mutating call — the delta is a read-only
comparison.

## See Also

This delta example is driven by the same Snapshot recorded in `00-MANIFEST.md`
in this folder, and it feeds the diagram Change Markers documented in
`../01-aws-agent-platform.diagram.md`. The classification rules and Change
Marker mapping come from the Delta Engine: added maps to 🆕, changed to 🔄,
removed to red, and both unchanged and duplicate to no marker, giving one source
of truth for both the versioned document and the diagram. A duplicate is
reported in this document but never drawn, because either drawn answer would be
a guess. The diagram-standards steering document defines the Legend entries for
these markers, and the diagram-lint ruleset defines the publication gate every
artifact in this golden example is built to pass, including the KB frontmatter
and section-length checks this document itself satisfies.
