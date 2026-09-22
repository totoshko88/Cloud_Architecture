---
id: generic-reference-architecture-manifest-2026-09-22_1430
title: Generic Reference Architecture Inventory Manifest
kb_namespace: cloud-architecture
section: inventory-snapshots
category: manifest
status: published
updated: 2026-09-22
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-22
tags:
  - generic
  - inventory
  - snapshot
  - manifest
related_docs:
  - ../generic-reference-architecture.diagram.md
  - 10-delta-example.md
---

# Generic Reference Architecture Inventory Manifest

## Overview

This Manifest is the root record of the read-only inventory Snapshot for the
vendor-neutral `generic` reference workload in the `env-prod` Environment,
region `region-1`. It was produced by the Inventory Collector using only the
`generic` Provider Profile enumeration path — manual entry and Terraform-state
import — so the count of state-mutating verbs executed during the run is zero.
The Snapshot folder is named per the inventory standard
`inventory-generic-env-prod-region-1-2026-09-22_1430`, where the timestamp is the
UTC collection start. The Manifest records the seven mandatory fields below as
non-empty values, and records metadata only — no secret values, key material, or
SecureString contents are ever written to any Snapshot file. Because the profile
is vendor-neutral, the recorded tooling reflects a Terraform-state import rather
than a cloud CLI, and identities are the neutral names carried in the state file.

## Main Content

The seven mandatory Manifest fields for this Snapshot are recorded here. Each
service domain is written to exactly one JSON file at the Snapshot root
(`compute.json`, `storage.json`, `network.json`), and each enumerated resource
gets one subfolder under `resources/`.

| Field | Value |
| --- | --- |
| provider | generic |
| boundary_id | env-prod |
| region_set | region-1 |
| caller_identity | terraform-state-import (read-only) |
| tool_versions | terraform 1.7.0 / manual-entry 1.0 |
| file_count | 11 |
| delta_instructions | Compare next run against this folder by identity tuple |

The `delta_instructions` field tells the next session to match resources on
`(provider, resource_type, identity)` and classify each as added, changed,
removed, or unchanged.

## Troubleshooting

If a single service enumeration fails, the Collector records the failed service
and its failure reason and continues the run; one service failure never aborts
collection. If the Linter reports a `secret-safety` CRITICAL finding, a Snapshot
file contains a secret, key material, or SecureString value — drop the offending
value and re-emit metadata only. A `frontmatter` finding names the offending
key; ensure all twelve keys are non-empty and `related_docs` holds at least one
entry. If the folder name is rejected, confirm it matches
`inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>` using the UTC
collection start timestamp. For the generic profile there is no cloud cost
endpoint; any cost data must come from the profile's declared source only.

## See Also

This Manifest pairs with the service-domain JSON files at the Snapshot root and
the per-resource subfolders under `resources/`. For the diagram view of the same
vendor-neutral workload, see `../generic-reference-architecture.diagram.md` and
its PlantUML source. The delta example `10-delta-example.md` in this folder shows
one added, one changed, and one removed resource relative to the previous
Snapshot. The inventory-standards steering document defines the read-only
collection contract, the zero state-mutation rule, the Snapshot folder naming,
and the secret-safety rule that this Snapshot conforms to, and the
provider-profiles document lists the `generic` manual-entry and Terraform-state
import path used to produce it, which is the fallback used when adding a new
provider.
