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

### Presentation roles (diagram-only, beyond the nine types)

The nine concepts above are the **inventory/schema** contract. Diagrams additionally use
**presentation roles** — how a node is *drawn* — for distinct services that are not
first-class inventory types, for example `cdn`, `dns`, `waf`, `lb`, and `cache`. These are
declared in `mappings/roles.yaml` and resolved, per provider, into the committed
`mappings/icon-index.json` by the init-time icon-set builder (`rule-engine-build-icon-sets`;
see `asset-packs.md`). The rule is **one role per distinct service** — a CDN is not an
object store, a DNS is not a load balancer — so each gets its own correct per-provider icon
(AWS CloudFront/Route 53/WAF; Azure CDN Profiles/DNS/WAF; GCP Networking/Security-Identity
category icons per Google's product-first, category-fallback convention; OCI `cdn`/`dns`/`waf`
embedded stencils). Adding the schema does not change; only the diagram role table grows.

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
| oci | Compartment/Tenancy boundary — dashed rectangle, terracotta `#AE562C` stroke, `#312D2A` caption | VCN boundary — dashed rectangle, terracotta `#AE562C` | OCI Style Guide for draw.io v24.2 (custom, unpacked) |
| generic | Environment boundary — dashed grayscale rectangle (`#333333`) | Network boundary — dashed grayscale rectangle (`#666666`) | grayscale, no vendor icons |

Diagram convention (see `diagram-standards.md`): every provider draws its stack Boundary
and its Network Boundary with the container style its own profile declares — there is no
cross-provider "green outer / blue inner" colour code. The two boundaries are told apart
by **nesting** (the Network Boundary sits inside the Boundary) and by their **captions**,
which the Legend names in words. The container styles above are the provider-specific
shapes that carry those boundaries in the `.drawio` source; the exact style string is
authoritative in `containers.*.style` of `mappings/<provider>-icons.yaml` and is enforced
by the `container-style` lint rule (ERROR).

Only **AWS** ships a dedicated vendor **group shape** (`mxgraph.aws4.group` with `grIcon=group_account` / `group_vpc2`). Azure, GCP, and OCI have no built-in group stencil, so their Boundary / Network Boundary render as **dashed rectangles** in the profile brand color (the exact `containers.*.style` is authoritative in `mappings/<provider>-icons.yaml`); `generic` uses a grayscale dashed rectangle. All are valid container styles — the requirement is that each profile declares exactly one Boundary and one Network Boundary style, not that it be a vendor group shape.

### OCI canonical nested palette (Style Guide v24.2)

The OCI profile follows the official **OCI Architecture Diagram Toolkit v24.2**
(shipped inside `OCI-Style-Guide-for-Drawio.zip` as reference `.drawio` files),
which is a **nested neutral-grey nesting system**, not an all-red palette. OCI
therefore declares — beyond the mandatory `boundary` / `network_boundary` pair —
the **optional** per-level container kinds `region`, `availability_domain`,
`fault_domain`, and `subnet` in `mappings/oci-icons.yaml`. Each level's stroke,
fill, and caption are extracted verbatim from the reference Physical templates:

| Level (container kind) | Stroke | Fill | Caption / shape |
| --- | --- | --- | --- |
| Compartment / Tenancy (`boundary`) | terracotta `#AE562C` | none | dashed, `#312D2A`, left |
| VCN / OSN (`network_boundary`) | terracotta `#AE562C` | none | dashed, terracotta caption, left |
| OCI Region (`region`) | neutral `#9E9892` | `#F5F4F2` | rounded, `#312D2A`, center |
| Availability Domain (`availability_domain`) | neutral `#9E9892` | `#DFDCD8` | rounded, `#312D2A`, center |
| Fault Domain (`fault_domain`) | neutral `#9E9892` | `#FCFBFA` | rounded, `#312D2A`, **italic** |
| Subnet (`subnet`) | terracotta `#AE562C` | none | dashed, terracotta caption, left |

Every level uses `fontFamily=Oracle Sans,Helvetica,Arial,sans-serif` (Oracle Sans
first; the fallback list keeps captions sans-serif where Oracle Sans is not
installed) and a `#312D2A` (Oracle near-black) caption — **never red text**,
including the node captions drawn by `OciStencilIcon`; the service **icon** keeps
its OCI-red brand fill. Every OCI container caption is bold (`fontStyle=1`;
Fault Domain bold italic), and rounded levels use an absolute corner radius
(`absoluteArcSize=1`) so a large Region box does not get oversized corners.
The palette is source-guarded by `tests/test_mappings.py` (no legacy `#F80000` /
`#C74634`; canonical stroke/fill per level; Oracle Sans captions) and recorded
in `docs/REVIEW.md` D17.

### Optional nested levels on the other profiles (1.10.3)

The optional `region` and `availability_domain` (the zone level, whatever the
provider calls it) kinds are declared by all four vendor profiles, so the HA
landscape draws `boundary ⊃ region ⊃ network boundary ⊃ zone` on every provider.
The styles follow each vendor's own published diagrams (`docs/REVIEW.md` D18):

| Provider | Region | Network Boundary | Zone |
| --- | --- | --- | --- |
| aws | `group_region` group, dashed `#00A4A6` | `group_vpc2` group, `#8C4FFF` | dashed `#147EBA` box (AWS ships no AZ icon) |
| azure | dashed neutral `#737373` | dotted `#0078D4` + Virtual Networks corner icon | borderless `#F2F2F2` block |
| gcp | dashed neutral `#5F6368` | dashed `#34A853` | borderless `#F1F3F4` block |
| oci | filled `#F5F4F2`, rounded | dashed terracotta `#AE562C` | filled `#DFDCD8`, rounded |

AWS container styles are copied from draw.io's own *AWS / Groups* palette:
Account `group_account` `#CD2264`, private subnet / public subnet
`group_security_group` on `#E6F6F7` / `#F2F6E8` (kinds `subnet` / `public_subnet`),
on-premises `group_corporate_data_center` (kind `on_premises`). Azure network boxes
carry their corner icon via `shape=label;image=img/lib/azure2/networking/…;imageAlign=left;imageVerticalAlign=top`
(VNet: Virtual Networks, `subnet`: Subnet). No builder hardcodes a container style.
Captions must meet 4.5:1 on white. Where a brand stroke colour is lighter than
that (AWS `#8C4FFF` / `#147EBA`, GCP `#4285F4` / `#34A853`), the stroke keeps the
brand colour and only the caption text is darkened. Azure captions are black.
Container captions use the provider's own words from `profiles/terminology.yaml`
(`vnet-…` on Azure, `vcn-…` / `ad-…` on OCI, `zone-…` on GCP). `generic` still
declares only the mandatory pair; `draw_cli._container_style` maps `az` →
`availability_domain` and `region` → `region` when declared, else falls back to
`network_boundary`.

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
per-provider brand anchors.

**The brand anchor is not the container colour.** The hex above is the node /
General-icon anchor — the `brand_hex` that `icon_resolver.resolve_icon` returns. It is
**never** a Boundary or Network Boundary colour. Container colours come from the
`containers.*.style` string in `mappings/<provider>-icons.yaml` (its `strokeColor` and
`fontColor`): for AWS the Account group is pink `#CD2264`, the VPC group purple
`#8C4FFF`, the Region group teal `#00A4A6` — not Squid Ink `#232F3E`. Painting an AWS
Account box in `#232F3E` (the 1.10.0 defect: a black account border) is caught by the
`container-style` lint rule, an ERROR on both classes. The `generic` profile never emits a vendor color: nodes use a
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

## Service Scope Classification (Diagram Placement)

Cloud services operate at different **scopes** — some require a VPC/VNet/VCN subnet to
deploy, others are **regional managed services** accessed via endpoints, and some are
**global**. Diagrams MUST reflect this: a service that does not run inside a network
boundary MUST NOT be drawn inside the Network Boundary container. Placing a regional
service inside a VPC misrepresents the architecture and implies the service has
network-level isolation it does not have.

### Scope Definitions

| Scope | Meaning | Diagram Placement |
| --- | --- | --- |
| **VPC-scoped** | Requires a subnet; instances/endpoints run inside the network | Inside the Network Boundary container |
| **Regional** | Managed service; accessed via regional endpoints or private endpoints | Inside the Boundary (Account/Subscription/Project) but OUTSIDE the Network Boundary |
| **Global** | Service spans regions or is region-agnostic | Inside the Boundary or at the edge (outside all boundaries for CDN/DNS) |
| **Organization / Tenant / Subscription** | Lives above (or across) the workload Boundary: org management account, identity tenant, deployment scope | In a separate organization / management-account boundary, or in the Boundary with a marker/`callout` naming the scope — never silently outside every boundary |

Rows whose `resource_type` is `—` (EventBridge, Glue, CloudWatch, IAM, …) are not inventory types in `schemas/inventory.schema.json`; the scope column still governs where they are drawn. Deployment mechanisms (CloudFormation, ARM/Bicep, Resource Manager) and identity roles are not data-flow nodes — show them as an attribute, a `callout`, or an identity view (`diagram-standards.md` → *Lane Order*).

### Service Scope by Provider

#### AWS Service Scope

| Service | `resource_type` | Scope | Notes |
| --- | --- | --- | --- |
| EC2 | `compute_instance` | **VPC** | Requires subnet |
| EKS (workers) | `managed_k8s` | **VPC** | Worker nodes in subnet; control plane is regional |
| RDS | `managed_sql` | **VPC** | Requires DB subnet group |
| ElastiCache | `cache` | **VPC** | Requires subnet group |
| Lambda | `serverless_fn` | **Regional** | VPC-attached optional; service itself is regional |
| S3 | `object_store` | **Regional** | Accessed via endpoints; not in VPC |
| SQS | `message_queue` | **Regional** | Accessed via endpoints |
| SNS | — | **Regional** | Accessed via endpoints |
| Secrets Manager | `secrets_store` | **Regional** | Accessed via endpoints |
| Bedrock | `llm_platform` | **Regional** | Managed AI service |
| DynamoDB | — | **Regional** | Accessed via endpoints |
| CloudFront | `cdn` | **Global** | Edge service |
| Route 53 | `dns` | **Global** | Global DNS |
| WAF | `waf` | **Global/Regional** | Attached to CloudFront or ALB |
| ALB/NLB | `lb` | **VPC** | Requires subnets |
| EventBridge | — | **Regional** | Event bus; accessed via endpoints |
| Glue | — | **Regional** | Catalog/ETL; VPC connection optional |
| Athena | — | **Regional** | Serverless query; accessed via endpoints |
| QuickSight | — | **Regional** | BI service; VPC connection optional |
| CloudWatch | — | **Regional** | Metrics, logs, alarms |
| CloudFormation | — | **Regional** | Deployment mechanism; a stack is not a data-flow node |
| IAM | — | **Global** | Identity; roles are attributes, not data-flow nodes |
| IAM Identity Center / Organizations | — | **Organization** | Management account; draw in an organization boundary or mark it |

#### Azure Service Scope

| Service | `resource_type` | Scope | Notes |
| --- | --- | --- | --- |
| Virtual Machines | `compute_instance` | **VNet** | Requires subnet |
| AKS (nodes) | `managed_k8s` | **VNet** | Nodes in subnet |
| Azure SQL DB | `managed_sql` | **Regional** | VNet service endpoint optional |
| Application Gateway | `lb` | **VNet** | Requires subnet |
| Functions | `serverless_fn` | **Regional** | VNet integration optional |
| Blob Storage | `object_store` | **Regional** | Private endpoint optional |
| Service Bus | `message_queue` | **Regional** | Private endpoint optional |
| Key Vault | `secrets_store` | **Regional** | Private endpoint optional |
| Azure OpenAI | `llm_platform` | **Regional** | Managed AI service |
| Azure Front Door | `cdn` | **Global** | Edge service |
| Azure DNS | `dns` | **Global** | Global DNS |
| Event Grid | — | **Regional** | Event routing; private endpoint optional |
| Azure Monitor | — | **Regional** | Metrics, logs, alerts |
| ARM / Bicep deployments | — | **Subscription** | Deployment mechanism; not a data-flow node |
| Entra ID | — | **Tenant (Global)** | Identity; draw in a tenant boundary or mark it |

#### GCP Service Scope

| Service | `resource_type` | Scope | Notes |
| --- | --- | --- | --- |
| Compute Engine | `compute_instance` | **VPC** | Requires subnet |
| GKE (nodes) | `managed_k8s` | **VPC** | Nodes in subnet |
| Cloud SQL | `managed_sql` | **VPC** | Private IP in VPC |
| Cloud Functions | `serverless_fn` | **Regional** | VPC connector optional |
| Cloud Storage | `object_store` | **Global** | Multi-regional or regional buckets |
| Pub/Sub | `message_queue` | **Global** | Global service |
| Secret Manager | `secrets_store` | **Global** | Global service |
| Vertex AI | `llm_platform` | **Regional** | Managed AI service |
| Cloud CDN | `cdn` | **Global** | Edge service |
| Cloud DNS | `dns` | **Global** | Global DNS |
| Cloud Load Balancing | `lb` | **Global/Regional** | Global or regional |
| Eventarc | — | **Regional** | Event routing |
| Cloud Monitoring | — | **Global** | Metrics, logs, alerting |
| BigQuery | — | **Regional/Multi-region** | Dataset location chosen per dataset |
| IAM | — | **Global** | Identity; roles are attributes, not data-flow nodes |

#### OCI Service Scope

| Service | `resource_type` | Scope | Notes |
| --- | --- | --- | --- |
| Compute | `compute_instance` | **VCN** | Requires subnet |
| OKE (nodes) | `managed_k8s` | **VCN** | Nodes in subnet |
| Autonomous DB | `managed_sql` | **VCN** | Private endpoint in VCN |
| Functions | `serverless_fn` | **Regional** | VCN attachment optional |
| Object Storage | `object_store` | **Regional** | Accessed via endpoints |
| Streaming | `message_queue` | **Regional** | Accessed via endpoints |
| Vault | `secrets_store` | **Regional** | Accessed via endpoints |
| OCI Generative AI | `llm_platform` | **Regional** | Managed AI service |
| Load Balancer | `lb` | **VCN** | Requires subnets |
| Events | — | **Regional** | Event rules; accessed via endpoints |
| Monitoring | — | **Regional** | Metrics and alarms |
| Resource Manager | — | **Regional** | Terraform stacks; not a data-flow node |
| IAM Identity Domains | — | **Tenancy** | Identity; draw at tenancy level or mark it |

### Diagram Layout Rules for Scope

1. **VPC-scoped services** are drawn INSIDE the Network Boundary container.
2. **Regional services** are drawn INSIDE the Boundary (Account/Subscription/Project/
   Compartment) but OUTSIDE the Network Boundary. They sit in the gap between the two
   boundaries or in a dedicated "Regional Services" column.
3. **Global/Edge services** (CDN, DNS, WAF) are drawn at the TOP of the diagram, above
   or outside the Boundary, in the edge lane per the lane order.
4. **Private Endpoints**: When a regional service is accessed via a Private Endpoint
   (AWS PrivateLink, Azure Private Endpoint, GCP Private Service Connect), the
   **endpoint** is drawn inside the VPC and the **service** remains outside, connected
   by an edge labeled "private endpoint" or similar.

### Visual Guidance

```
┌─────────────────────────────────────────────────────────┐
│  [CDN]  [DNS]  [WAF]           ← Global/Edge (top)      │
├─────────────────────────────────────────────────────────┤
│ Account/Subscription/Project                            │
│  ┌──────────────────────┐  ┌──────────────────────────┐ │
│  │ VPC/VNet/VCN         │  │ Regional Services        │ │
│  │  [EKS]  [RDS]  [ALB] │  │  [S3]  [SQS]  [Bedrock] │ │
│  │  [EC2]  [Cache]      │  │  [Secrets]  [Lambda]    │ │
│  └──────────────────────┘  └──────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

This separation makes the architecture accurate: a reader can immediately see which
services are network-isolated and which are accessed via endpoints over the AWS/Azure/
GCP backbone.

## Adding a New Provider

To extend the engine with a new provider, add — in order — a terminology normalization
row (all nine concepts), the two container conventions, a brand palette entry, the
read-only verb list, an icon mapping (`mappings/<provider>-icons.yaml`), and a golden
example, then run the Linter until it reports zero violations. See the "add a new
provider" runbook for the full ordered steps.
