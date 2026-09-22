---
id: aws-agent-platform-manifest-2026-09-22_1430
title: AWS Agent Platform Inventory Manifest
kb_namespace: cloud-architecture
section: inventory-snapshots
category: manifest
status: published
updated: 2026-09-22
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-22
tags:
  - aws
  - inventory
  - snapshot
  - manifest
related_docs:
  - ../01-aws-agent-platform.diagram.md
---

# AWS Agent Platform Inventory Manifest

## Overview

This Manifest is the root record of the read-only inventory Snapshot for the
`aws-agent-platform` workload in AWS Account `123456789012`, region
`us-east-1`. It was produced by the Inventory Collector using only the `aws`
Provider Profile read-only enumeration verbs (`list*`, `describe*`, `get*`); the
count of state-mutating verbs executed during the run is zero. The Snapshot
folder is named per the inventory standard
`inventory-aws-123456789012-us-east-1-2026-09-22_1430`, where the timestamp is
the UTC collection start. The Manifest records the seven mandatory fields below
as non-empty values and records metadata only — no secret values, key material,
or SecureString contents are ever written to any Snapshot file.

## Main Content

The seven mandatory Manifest fields for this Snapshot are recorded here. Each
service domain is written to exactly one JSON file at the Snapshot root
(`compute.json`, `storage.json`, `network.json`), and each enumerated resource
gets one subfolder under `resources/`.

| Field | Value |
| --- | --- |
| provider | aws |
| boundary_id | 123456789012 |
| region_set | us-east-1 |
| caller_identity | arn:aws:iam::123456789012:role/inventory-readonly |
| tool_versions | aws-cli 2.15.0 / botocore 1.34.0 |
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
collection start timestamp. Cost data, when collected, uses only the profile's
declared cost endpoint.

## See Also

This Manifest pairs with the service-domain JSON files at the Snapshot root and
the per-resource subfolders under `resources/`. For the diagram view of the same
workload, see `../01-aws-agent-platform.diagram.md` and its `.drawio` source and
exported raster. The delta example `10-delta-example.md` in this folder shows
one added, one changed, and one removed resource relative to the previous
Snapshot. The inventory-standards steering document defines the read-only
collection contract, the zero state-mutation rule, the Snapshot folder naming,
and the secret-safety rule that this Snapshot conforms to, and the
provider-profiles document lists the `aws` read-only verbs used to produce it.
