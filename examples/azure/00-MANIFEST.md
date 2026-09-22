---
id: azure-openai-rag-manifest-v1
title: Azure OpenAI RAG Inventory Snapshot Manifest
kb_namespace: cloud-architecture
section: golden-examples
category: azure
status: draft
updated: 2026-09-22
owner: platform-architecture-team
author: rule-engine-inventory-collector
next_review_date: 2027-03-22
tags:
  - azure
  - inventory
  - snapshot
  - manifest
  - golden-example
related_docs:
  - examples/azure/01-azure-openai-rag.diagram.md
---

# Azure OpenAI RAG Inventory Snapshot Manifest

## Overview

This manifest is the golden-example `00-MANIFEST.md` for the `azure-openai-rag`
inventory snapshot. It documents a strictly read-only enumeration of the Azure
Subscription `sub-9f3c1a` in the `eastus` region, collected with only the
declared read-only verbs (`az … list`, `az … show`). No provider state was
created, updated, or deleted during collection, so the count of state-mutating
verbs for this run is zero. The snapshot folder that this manifest heads would be
named `inventory-azure-sub-9f3c1a-eastus-2026-09-22_1430`, using the UTC
collection start timestamp. Every field below is recorded as a non-empty value,
as the inventory standards require. Only non-secret metadata is retained; Key
Vault contents, connection strings, and any SecureString values are dropped
before any snapshot file is written. The delta example at the end shows how the
next collection session reports resources that were added, changed, or removed
relative to this baseline snapshot.

## Main Content

The manifest records the seven required fields exactly as the inventory
standards define them. Each field is populated with a concrete, non-empty value
for this example subscription. The `region_set` covers the single region used by
the workload, and the `caller_identity` names the read-only service principal
that performed the enumeration. The `tool_versions` field pins the CLI versions
so a later session can reproduce the collection, and `file_count` reflects the
total number of files written into the snapshot folder. The `delta_instructions`
field tells the next session how to compute the difference against this
baseline. The per-service enumeration wrote one JSON file per service domain and
one subfolder per resource, but this manifest snippet focuses on the required
header fields and the delta example rather than the full folder contents.

| Field | Value |
| --- | --- |
| `provider` | `azure` |
| `boundary_id` | `sub-9f3c1a` |
| `region_set` | `eastus` |
| `caller_identity` | `sp-inventory-readonly@contoso.onmicrosoft.com` |
| `tool_versions` | `azure-cli 2.58.0; az-account 2.58.0` |
| `file_count` | `9` |
| `delta_instructions` | Compare next run to `inventory-azure-sub-9f3c1a-eastus-2026-09-22_1430` by `resource_id`. |

## Delta Example

The delta compares the next collection against this baseline snapshot. Change
markers follow the shared diagram Legend: 🆕 marks a resource new in this
version, 🔄 marks a changed resource, and a red entry marks a removed, blocked,
or disabled resource. This example records one of each:

- 🆕 `azure/managed_k8s/aks-rag-workers` — added an AKS cluster to host batch
  ingestion workers alongside the Ingest Function.
- 🔄 `azure/managed_sql/azuresqldb-vectors` — changed: scaled the vector store
  from 2 to 4 vCores and enabled zone redundancy.
- 🔴 `azure/message_queue/servicebus-legacy` — removed: the legacy Service Bus
  namespace was decommissioned and no longer appears in the enumeration.

## Troubleshooting

If a snapshot is missing this manifest, the collection run is incomplete: every
snapshot folder must carry a `00-MANIFEST.md` at its root. If any of the seven
fields is empty, the manifest fails the inventory standards and must be
regenerated with a concrete value. If a snapshot file appears to contain a
secret, key material, or a SecureString value, that is a CRITICAL secret-safety
failure; drop the value and retain only metadata before rewriting the file. If a
single service failed to enumerate, the run records the failed service and the
failure reason and continues with the remaining services rather than aborting.
If cost data is present, confirm it came only from the profile's declared cost
endpoint. When the delta looks wrong, verify the `delta_instructions` reference
the correct baseline snapshot folder name and that resource identifiers are
stable across runs so additions and removals compute correctly every session.

## See Also

The companion diagram document at `examples/azure/01-azure-openai-rag.diagram.md`
describes the architecture that this snapshot enumerates and pairs with the
`01-azure-openai-rag.drawio` source. The inventory standards define the
read-only collection contract, the snapshot folder naming convention, the
manifest field set, the snapshot content layout, secret-safety, non-fatal
per-service failure handling, and the declared cost endpoint rule. The provider
profile rules list the Azure read-only enumeration verbs and the cost endpoint
that this collection is permitted to call. The diagram standards and lint
ruleset define the change markers used in the delta example and the severities
that gate publication. Consult those steering documents when reproducing this
snapshot for another subscription or when extending the collector to a new
provider profile.

## Anti-patterns

Never execute a state-mutating verb during collection: no `create`, `update`,
`delete`, or `set` operations belong in a read-only snapshot. Never record a raw
secret. The folder name must follow the exact pattern and use the UTC start
timestamp:

```text
inventory-azure-sub-9f3c1a-eastus-2026-09-22_1430/
```

Do not merge multiple service domains into one JSON file, and do not omit the
`resources/` subfolders. Keep every manifest field non-empty and express all
change-marker dates in ISO 8601 form. Avoid relative time expressions such as
"yesterday" or "last week" anywhere in the manifest; every date must be an
explicit calendar date. Do not reuse a previous snapshot folder name for a new
collection run, because a stale timestamp breaks delta computation for the next
session. Never let a single failed service abort the run; record the failure
reason and continue enumerating the remaining services. Finally, do not call any
cost or billing endpoint other than the one the provider profile declares, and
never widen a table beyond five columns or nest lists more than two levels deep
in this document.
