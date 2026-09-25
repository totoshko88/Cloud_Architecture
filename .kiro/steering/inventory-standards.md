---
inclusion: always
---

# Inventory Standards

These standards govern the Inventory Collector across all five provider profiles
(`aws`, `azure`, `gcp`, `oci`, `generic`). They are binding in every agent turn
within this workspace. Inventory collection is strictly **read-only**: no
provider state is ever created, updated, or deleted.

## 1. Read-Only Collection Contract

The Inventory Collector executes **only** read-only enumeration verbs that are
explicitly listed in the corresponding Provider Profile. Any verb not present in
the profile's read-only enumeration list MUST NOT be executed (Requirement 3.1,
3.2).

| Provider | Read-only verbs |
| --- | --- |
| `aws` | `list*`, `describe*`, `get*` |
| `azure` | `az … list`, `az … show` |
| `gcp` | `gcloud … list`, `gcloud … describe` |
| `oci` | `oci … list`, `oci … get` |
| `generic` | manual entry / Terraform-state import |

## 2. Zero State-Mutation Rule

Every verb that creates, updates, or deletes provider state is excluded. The
count of executed state-mutating verbs per collection run MUST equal zero
(Requirement 3.3). If a needed capability is not expressible as a declared
read-only verb, the collection records the gap rather than mutating state.

## 3. Snapshot Folder Naming

When the Inventory Collector produces a Snapshot, it writes the Snapshot to a
folder named (Requirement 3.4):

```
inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>
```

where `<YYYY-MM-DD_HHMM>` is the **UTC collection start** timestamp.

Example:

```
inventory-aws-123456789012-us-east-1-2025-01-15_1430/
├── 00-MANIFEST.md
├── compute.json            # one JSON file per service domain
├── storage.json
├── network.json
└── resources/
    ├── s3-my-bucket/       # one subfolder per enumerated resource
    └── lambda-my-fn/
```

## 4. Manifest (`00-MANIFEST.md`)

When the Inventory Collector creates a Snapshot folder, it writes a Manifest
named `00-MANIFEST.md` at the root of that Snapshot folder (Requirement 3.5).
The Manifest MUST record all of the following fields as **non-empty** values
(Requirement 3.6):

| Field | Description |
| --- | --- |
| `provider` | Provider enum value (`aws` / `azure` / `gcp` / `oci` / `generic`) |
| `boundary_id` | Boundary identifier enumerated |
| `region_set` | Regions covered by the snapshot |
| `caller_identity` | Read-only identity that performed collection |
| `tool_versions` | CLI/SDK versions used |
| `file_count` | Total file count of the snapshot folder |
| `delta_instructions` | Instructions for the next session to compute the delta |

## 5. Snapshot Content Layout

When the Inventory Collector writes Snapshot content, it MUST write
(Requirement 3.7):

- **Exactly one JSON file per service domain** (for example `compute.json`,
  `storage.json`, `network.json`) at the root of the Snapshot folder.
- **One per-resource subfolder** for each enumerated resource, placed under a
  `resources/` folder within the Snapshot folder.

## 6. Service Domains to Enumerate (diagram-complete coverage)

A diagram is formed for the **whole** inventory, so the collection must be broad
enough that every resource the diagram will draw has already been enumerated. A
narrow collection (for example only compute + storage + network) silently drops
resources that then never appear on the diagram — the EFS filesystem that was
omitted from an `eu-central-1` diagram even though it existed in the account.

The Inventory Collector SHOULD enumerate **at least** the following service
domains, each written as its own JSON file per §5. The domains are the union of
the nine neutral resource types and the diagram **presentation roles**
(`mappings/roles.yaml`), so anything the diagram can render has a home in the
snapshot. Use the profile's read-only verbs (§1) for each.

| Domain (JSON file) | Covers (neutral type / presentation role) | AWS example verbs |
| --- | --- | --- |
| `identity.json` | Boundary (account/subscription/project/tenancy) | `sts get-caller-identity`, `organizations describe-account` |
| `network.json` | Network Boundary, subnets, route tables, gateways | `ec2 describe-vpcs`, `describe-subnets`, `describe-route-tables` |
| `edge.json` | `cdn`, `dns`, `waf` | `cloudfront list-distributions`, `route53 list-hosted-zones`, `wafv2 list-web-acls` |
| `loadbalancing.json` | `lb` | `elbv2 describe-load-balancers`, `elb describe-load-balancers` |
| `compute.json` | `compute_instance`, autoscaling | `ec2 describe-instances`, `autoscaling describe-auto-scaling-groups` |
| `containers.json` | `managed_k8s`, container registries/clusters | `eks list-clusters`, `ecs list-clusters` |
| `serverless.json` | `serverless_fn` | `lambda list-functions` |
| `messaging.json` | `message_queue` (queues, topics, streams) | `sqs list-queues`, `sns list-topics` |
| `storage.json` | `object_store`, **`file_system`** (EFS/Files/NFS) | `s3api list-buckets`, **`efs describe-file-systems`**, `fsx describe-file-systems` |
| `database.json` | `managed_sql`, `cache` (in-memory) | `rds describe-db-instances`, `elasticache describe-cache-clusters` |
| `secrets.json` | `secrets_store` | `secretsmanager list-secrets`, `kms list-keys` |
| `ai.json` | `llm_platform` | `bedrock list-foundation-models` |

This table is a **floor, not a ceiling**: enumerate additional domains the target
uses. A domain with no resources is recorded as an empty file (or omitted with a
note), never skipped silently. The equivalent Azure / GCP / OCI verbs follow each
profile's read-only pattern (§1); the AWS column is illustrative. **Storage MUST
include managed file systems (EFS / Azure Files / Filestore / OCI File Storage),
not only object stores** — the omission above is precisely the gap this section
closes: `file_system` is a distinct storage service with its own icon and MUST be
collected whenever present.

## 7. Secret-Safety

The Inventory Collector records resource **metadata only**. It MUST exclude
secret values, key material, and SecureString values from every Snapshot file,
such that no Snapshot file contains any such value (Requirement 3.8). If a
provider response includes a secret, key material, or a SecureString value, that
value is dropped before the Snapshot file is written; only non-secret metadata is
retained.

## 8. Non-Fatal Per-Service Failure Handling

If enumeration of a single service fails, the Inventory Collector MUST record the
failure with an entry indicating **the failed service and the failure reason**,
and MUST continue enumeration of the remaining services without terminating the
collection run (Requirement 3.9). A single service failure never aborts the run.

## 9. Declared Cost Endpoint Rule

Where cost or billing data is collected, the Inventory Collector MUST use **only**
the provider-specific cost endpoint declared in the corresponding Provider Profile
(Requirement 3.10). No cost or billing endpoint outside the profile declaration is
called.
