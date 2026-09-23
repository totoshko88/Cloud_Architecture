---
inclusion: always
---

# Provider Profiles

The Rule Engine separates a **provider-neutral core** from **per-provider profiles**.
The core never hard-codes provider terminology, icons, or verbs; it reads them from the
profile selected at invocation. A new provider is added by data — a profile row, an icon
mapping, read-only verbs, and a golden example — never by changing core code.

Every Provider Profile is a configuration set with four parts:

1. a **terminology normalization** row for each of the nine neutral concepts,
2. **container conventions** for the Boundary and the Network Boundary,
3. a **brand palette** entry, and
4. a **read-only inventory verb** list.

The five profiles are `aws`, `azure`, `gcp`, `oci`, and a vendor-neutral `generic`
profile. The `generic` profile uses grayscale and no vendor icons; it is the fallback and
the reference used when adding a new provider.

## Terminology Normalization Table

Every profile defines a row for each of the nine neutral concepts. This is the
authoritative neutral-concept → per-provider mapping (Requirement 9 AC10).

| # | Neutral concept | `resource_type` | aws | azure | gcp | oci | generic |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Boundary | `boundary` | Account | Subscription | Project | Tenancy/Compartment | Environment |
| 2 | Network Boundary | `network_boundary` | VPC | VNet | VPC | VCN | Network |
| 3 | serverless function | `serverless_fn` | Lambda | Functions | Cloud Functions | Functions | Function |
| 4 | object store | `object_store` | S3 | Blob Storage | Cloud Storage | Object Storage | Object Store |
| 5 | managed SQL | `managed_sql` | RDS | Azure SQL DB | Cloud SQL | Autonomous/DB Systems | Managed SQL |
| 6 | message queue | `message_queue` | SQS | Service Bus/Queue | Pub/Sub | Streaming/Queue | Message Queue |
| 7 | secrets store | `secrets_store` | Secrets Manager | Key Vault | Secret Manager | Vault | Secrets Store |
| 8 | managed Kubernetes | `managed_k8s` | EKS | AKS | GKE | OKE | Managed Kubernetes |
| 9 | LLM platform | `llm_platform` | Bedrock | Azure OpenAI | Vertex AI | OCI Generative AI | LLM Platform |

The `resource_type` column is the enum value used in the Normalized Resource schema
(`schemas/inventory.schema.json`). Provider labels are the native service names surfaced
in diagrams and inventory documents.

## Per-Provider Container Conventions

Each profile declares exactly one Boundary container style and exactly one Network
Boundary container style (Requirement 2 AC6). These map the two structural concepts
(rows 1 and 2 above) to draw.io group/container shapes sourced from the profile's
authoritative asset pack. A profile that declares no container group style for its
Boundary or Network Boundary is a profile-convention error.

| Provider | Boundary container | Network Boundary container | Asset pack / source |
| --- | --- | --- | --- |
| aws | Account group — `mxgraph.aws4.group` / `grIcon=mxgraph.aws4.group_account` | VPC group — `mxgraph.aws4.group` / `grIcon=mxgraph.aws4.group_vpc2` | `mxgraph.aws4` (draw.io built-in, AWS 2019+) |
| azure | Subscription boundary — dashed rectangle (`#0078D4`) | VNet boundary — dashed rectangle (`#0062AD`) | Azure icon library (custom, unpacked) |
| gcp | Project boundary — dashed rectangle (`#4285F4`) | VPC boundary — dashed rectangle (`#34A853`) | GCP icon library (custom/built-in) |
| oci | Tenancy/Compartment boundary — dashed rectangle (`#F80000`) | VCN boundary — dashed rectangle (`#C74634`) | OCI icon library (custom, unpacked) |
| generic | Dashed green boundary rectangle | Dashed blue boundary rectangle | grayscale, no vendor icons |

Diagram convention (see `diagram-standards.md`): the stack Boundary renders as a **dashed
green boundary** and the Network Boundary renders as a **dashed blue boundary** in the
Legend, regardless of provider. The container styles above are the provider-specific
group shapes that carry those boundaries in the `.drawio` source.

Only **AWS** ships a dedicated vendor **group shape** (`mxgraph.aws4.group` with `grIcon=group_account` / `group_vpc2`). Azure, GCP, and OCI have no built-in group stencil, so their Boundary / Network Boundary render as **dashed rectangles** in the profile brand color (the exact `containers.*.style` is authoritative in `mappings/<provider>-icons.yaml`); `generic` uses a grayscale dashed rectangle. All are valid container styles — the requirement is that each profile declares exactly one Boundary and one Network Boundary style, not that it be a vendor group shape.

## Brand Palette

The Icon Resolver returns a `#RRGGBB` brand color for each node, sourced from the
profile. The primary brand color per provider:

| Provider | Primary brand hex | Swatch intent |
| --- | --- | --- |
| aws | `#232F3E` | AWS Squid Ink |
| azure | `#0078D4` | Azure blue |
| gcp | `#4285F4` | Google blue |
| oci | `#F80000` | Oracle red |
| generic | grayscale — `#FFFFFF` fill, `#000000` stroke | no vendor color |

Individual service icons may carry their own service-family hex (for example AWS S3 uses
`#7AA116`) as declared in `mappings/<provider>-icons.yaml`; the values above are the
per-provider brand anchors. The `generic` profile never emits a vendor color: nodes use a
white fill with a black stroke (`fillColor=#FFFFFF;strokeColor=#000000`) only.

## Read-Only Inventory Verb List

The Inventory Collector executes **only** the read-only enumeration verbs explicitly
listed in the profile (Requirement 3 AC1–AC3). Any verb that creates, updates, or deletes
provider state is excluded; the count of state-mutating verbs per collection run is zero.
A verb not present in this list is never executed.

| Provider | Read-only enumeration verbs |
| --- | --- |
| aws | `list*`, `describe*`, `get*` |
| azure | `az … list`, `az … show` |
| gcp | `gcloud … list`, `gcloud … describe` |
| oci | `oci … list`, `oci … get` |
| generic | manual entry / Terraform-state import |

Rules:

- Only verbs matching the patterns above may run for a given provider.
- Exclude every verb that creates, updates, or deletes state (no `create*`, `put*`,
  `update*`, `delete*`, `remove*`, `set*`, or equivalent).
- Cost/billing data uses only the profile's declared cost endpoint.
- Snapshots record metadata only — never secret values, key material, or SecureString
  contents (secret-safety).

## Adding a New Provider

To extend the engine with a new provider, add — in order — a terminology normalization
row (all nine concepts), the two container conventions, a brand palette entry, the
read-only verb list, an icon mapping (`mappings/<provider>-icons.yaml`), and a golden
example, then run the Linter until it reports zero violations. See the "add a new
provider" runbook for the full ordered steps.
