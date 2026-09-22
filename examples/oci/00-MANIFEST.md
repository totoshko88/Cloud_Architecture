---
id: oci-genai-stack-manifest
title: OCI Generative AI Stack — Inventory Manifest Snippet
kb_namespace: architecture
section: golden-examples
category: inventory
status: draft
updated: 2026-09-22
owner: platform-architecture-team
author: rule-engine
next_review_date: 2027-03-22
tags:
  - oci
  - inventory
  - manifest
  - golden-example
related_docs:
  - oci-genai-stack-companion
---

# OCI Generative AI Stack Inventory Manifest

## Overview

This manifest snippet accompanies the `01-oci-genai-stack` golden example and
illustrates the root `00-MANIFEST.md` that the Inventory Collector writes at the top
of every snapshot folder. It records the seven mandatory manifest fields, each with a
non-empty value, for a read-only OCI enumeration of the `acme-prod` compartment
boundary in the `us-ashburn-1` region. Inventory collection is strictly read-only:
only the profile's declared `oci … list` and `oci … get` verbs run, and the count of
state-mutating verbs is zero. The snippet is a documentation example, so the values
below are representative rather than the output of a live collection run. It mirrors
the folder-naming convention `inventory-oci-acme-prod-us-ashburn-1-2026-09-22_1430`
and the metadata-only, secret-safe recording rules defined by the inventory standards
steering document, matching its AWS, Azure, and GCP manifest siblings exactly.

## Main Content

The seven required manifest fields are recorded in the table below. Every value is
non-empty, matching the manifest contract. The snapshot records resource metadata
only; no secret values, key material, or SecureString contents appear in any file.

| Field | Value |
| --- | --- |
| provider | oci |
| boundary_id | acme-prod |
| region_set | us-ashburn-1 |
| caller_identity | ocid1.user.oc1..ci-readonly |
| tool_versions | oci-cli 3.37.0 |
| file_count | 14 |
| delta_instructions | Compare against the previous snapshot folder by identity tuple to compute added, changed, and removed resources. |

Each service domain is written as one JSON file (`compute.json`, `storage.json`,
`network.json`) at the snapshot root, with one subfolder per enumerated resource
under `resources/`, following the inventory content-layout rule.

## Troubleshooting

If a manifest field is blank, the Linter reports a CRITICAL `frontmatter` finding for
generated documents and the snapshot is treated as incomplete; populate every field
with a non-empty value before publishing. If a single service enumeration fails, the
Collector records the failed service and the failure reason and continues with the
remaining services rather than aborting the run, so a partial snapshot still produces
a valid manifest. If any snapshot file is found to contain a secret value, key
material, or a SecureString, the Linter raises a CRITICAL `secret-safety` finding;
drop the offending value and retain only non-secret metadata. If cost or billing data
is required, use only the cost endpoint declared in the OCI provider profile, never an
undeclared endpoint. Confirm the folder name matches the mandated
`inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>` pattern using the UTC
collection start timestamp before publishing the snapshot.

## See Also

The companion diagram document `01-oci-genai-stack.diagram.md` in this directory
describes the architecture that this inventory snapshot enumerates. The rules that
govern this manifest are defined in the always-on steering set: `inventory-standards.md`
specifies the read-only collection contract, the zero state-mutation rule, the snapshot
folder naming, the seven manifest fields, the one-JSON-per-domain content layout, and
the secret-safety requirement applied here. The `provider-profiles.md` document
defines the OCI read-only enumeration verb list and the declared cost endpoint. The
`diagram-lint.md` ruleset defines the CRITICAL `frontmatter` and `secret-safety`
findings referenced in Troubleshooting. For the normalized resource shape produced from
this snapshot, see `schemas/inventory.schema.json` and the sibling
`examples/oci/sample-resource.json`. Parallel manifest snippets for the other provider
profiles live in the `aws`, `azure`, `gcp`, and `generic` example directories.
