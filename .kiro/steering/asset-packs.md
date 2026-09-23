# Provider Asset Packs & Icon Fallback

This steering document defines where each provider's **official icon asset pack** lives, how it is laid out, and the **fallback order** the engine uses when a specific service is not available as a built-in draw.io stencil. It complements `provider-profiles.md` (which maps the nine neutral resource types to built-in stencils) and `diagram-standards.md` (which forbids unresolved placeholder icons via the `icon-resolved` ERROR).

The built-in `mxgraph.*` stencil libraries cover the common services but lag the vendors' newest releases. Newer services — for example **AWS DevOps agent**, **AWS FinOps agent**, and **AWS Security agent** — have no built-in stencil yet. For those, the deterministic answer is to fall back to the vendor's official SVG (preferred) or PNG from the pack, never to an unresolved placeholder.

## Icon Resolution Order

For any specific service the engine resolves an icon in this fixed order:

1. **Built-in stencil** — a known `mxgraph.<lib>.*` id (editable, scalable). This is what `provider-profiles.md` / `mappings/<provider>-icons.yaml` provide for the nine neutral types and a small curated set of common services.
2. **Official asset file** — the vendor SVG (preferred) or PNG from the indexed pack, when no built-in stencil matches. Embed it in the `.drawio`/`.puml` source as an image node with correct alt text.
3. **Unresolved** — nothing matched. This is fail-honest: the generator must obtain an official asset before publishing, because a placeholder icon is an `icon-resolved` ERROR that blocks publication.

The Asset Index (`src/rule_engine/asset_index.py`, CLI `rule-engine-index-assets`) implements steps 1–3 and indexes a local directory of unpacked packs by a normalized service **slug** (lowercase, hyphenated, vendor/size/format decoration stripped), so `"AWS Security Agent"`, `"security-agent"`, and `"Security Agent"` resolve to the same entry.

## Per-Provider Icon Resolution (verified 2026-09-23)

Each provider's icon delivery mechanism was verified against the draw.io sources (`js/diagramly/sidebar/Sidebar-<Provider>.js`) and the official vendor packs. The five profiles resolve differently, and `mappings/<provider>-icons.yaml` reflects this:

| Provider | Mechanism | Style form | Notes |
| --- | --- | --- | --- |
| **aws** | Built-in `mxgraph.aws4.*` stencils | `shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.<svc>` | 7 service resIcons verified (`lambda`, `s3`, `rds`, `eks`, `sqs`, `secrets_manager`, `bedrock`). Containers: `shape=mxgraph.aws4.group` with `grIcon=mxgraph.aws4.group_account` (Account) and `group_vpc2` (VPC — note the `2` suffix; `group_vpc` is wrong). |
| **azure** | Built-in **azure2 image shapes** | `image;...;image=img/lib/azure2/<category>/<Name>.svg` | The legacy `mxgraph.azure.*` stencil library covered only ~3 of the 9 neutral types (the rest rendered as empty boxes), so Azure uses the current azure2 **file-path image shapes** instead. All 9 verified in `Sidebar-Azure2.js`. |
| **gcp** | Official icons (file-path), **product first, category fallback** | `image;...;image=assets/vendor/gcp-core/Unique Icons/<Product>/SVG/<Name>.svg` or `.../gcp-category/Category Icons/<Category>/SVG/<Name>.svg` | GCP resolves by a **source priority**: (1) the official **Core Product** icon (`core-products-icons.zip` → `gcp-core`) when the neutral type maps to a flagship product Google ships a dedicated 2025 icon for; (2) the official **Product Category** icon (`category-icons.zip` → `gcp-category`) otherwise. Both are official 2025 packs, referenced by file path. Currently 4 types resolve to a product icon (object_store, managed_sql, managed_k8s, llm_platform) and 5 to a category icon. **Correction:** the earlier note that `mxgraph.gcp2.*` has "no service stencils, only 9 structural shapes" is **wrong** — gcp2 defines **255 shapes** incl. per-service icons (e.g. `cloud_load_balancing`, `cloud_functions`, `cloud_pubsub`, `container_engine`, `cloud_sql`, `cloud_storage`, `key_management_service`, `cloud_machine_learning`), verified against the draw.io `app.asar` and confirmed by headless export. gcp2 is a **pre-2025** style, so it is the **last-resort fallback** (tier 3), used only where no official 2025 asset exists — never mixed with the 2025 icons by default. |
| **oci** | Custom-imported `mxgraph.oci.*` stencils | `shape=mxgraph.oci.<svc>` (or embedded stencil group) | OCI ships **no** built-in draw.io library; stencils come only from the pack's `OCI Library.xml`, imported into draw.io or embedded into the source. |
| **generic** | Base draw.io shapes | `rounded=...`, `shape=cylinder3`, etc. | Grayscale, no vendor library. |

**Neutral-type → GCP icon** (source per the product-first priority; `authoritative in `mappings/gcp-icons.yaml`). Product icons live under `assets/vendor/gcp-core/Unique Icons/<Product>/SVG/`; category icons under `assets/vendor/gcp-category/Category Icons/<Category>/SVG/`:

| Neutral type | Source | GCP icon |
| --- | --- | --- |
| `boundary` | category | Management Tools |
| `network_boundary` | category | Networking |
| `serverless_fn` | category | Serverless Computing |
| `object_store` | **product** | Cloud Storage |
| `managed_sql` | **product** | Cloud SQL |
| `message_queue` | category | Integration Services |
| `secrets_store` | category | Security Identity |
| `managed_k8s` | **product** | GKE |
| `llm_platform` | **product** | Vertex AI |

The GCP golden example additionally uses the **Apigee** product icon for its `api-gateway` node (the closest official product to API Gateway), which makes it visually distinct from the `load-balancer` node (Networking category) — the source's `image=` path is what carries this per-node choice, independent of the neutral-type table above.

### Image-style caveat (base64 vs file path)

For **image-shape** providers (azure2, gcp) always reference the icon by **file path** (`image=<path under the asset root>`), never as an inline base64 data-URI. The linter intentionally flags `image=data:image/svg+xml,...` as an `icon-resolved` finding (`_UNRESOLVED_STYLE_MARKERS` in `cli.py` — "draw.io fails to render"), so a base64 style would block publication. File-path styles pass the linter and keep the `.drawio` small. Also: every `resources` entry in a mapping **must** keep a non-empty `style` key — `icon_resolver.resolve_icon()` raises an `AssetSourceError` if it is missing.

## Official Pack Sources

Packs are downloaded on demand into a local, **uncommitted** directory (the `.build-tools/` / `assets/` trees are git-ignored). Never commit vendor icon binaries.

| Provider | Pack | Download |
| --- | --- | --- |
| aws | AWS Architecture Icons | `https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/` (current Icon-package ZIP) |
| azure | Azure Public Service Icons | `https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip` |
| gcp | GCP Category Icons | `https://services.google.com/fh/files/misc/category-icons.zip` |
| gcp | GCP Core Product Icons | `https://services.google.com/fh/files/misc/core-products-icons.zip` |
| oci | OCI Style Guide for draw.io | `https://docs.oracle.com/iaas/Content/Resources/Assets/OCI-Style-Guide-for-Drawio.zip` |

Vendor icon assets remain under their owners' trademark/usage terms; they are a build-time input, not redistributed by this repository.

## Pack Layouts

The indexer understands these layouts (files ending `.svg` preferred, `.png` as raster fallback):

| Provider | Layout (under the unpacked root) |
| --- | --- |
| aws | `Architecture-Service-Icons_*/Arch_<Category>/<size>/Arch_<Service>_<size>.svg` and `Resource-Icons_*/Res_<Category>/<size>/Res_<Service>_<size>.svg` |
| azure | `Azure_Public_Service_Icons/Icons/<category>/NNNNN-icon-service-<Name>.svg` |
| gcp | `Category Icons/<Category>/SVG/<Name>-512-color.svg` (used for all 9 neutral types) and `Unique Icons/<Product>/SVG/<Name>-<size>-color.svg` (flagship products only; incomplete coverage) |
| oci | `OCI Style Guide for Drawio/OCI Library.xml` — a draw.io `<mxlibrary>` of `mxgraph.oci.*` shapes (OCI ships shapes, not per-service SVGs) |

### OCI note

OCI has **no built-in draw.io library**; its shapes come only from the custom `OCI Library.xml` in the pack. Import that library into draw.io to render `mxgraph.oci.*` shapes. Where the library is not available, the OCI golden example uses self-contained OCI-red (`#F80000`) labelled boxes so the diagram still renders and reads correctly (see `examples/oci/`).

## Indexing & Resolving

```bash
# Build a manifest of every indexed asset (JSON, sorted, deterministic)
rule-engine-index-assets --root ./assets-src \
  --aws aws-icons --azure azure-icons --gcp gcp-core --oci oci-style \
  --out asset-index.json

# Resolve one specific service to its best icon (exit 1 if unresolved)
rule-engine-index-assets --root ./assets-src --aws aws-icons \
  --resolve aws "AWS Security Agent"

```

### Anti-patterns

- Do **not** hand-write a `shape=mxgraph.<lib>.<guess>` id and hope it resolves; an unknown stencil renders as an empty box (`icon-resolved` ERROR). Verify the id exists, or fall back to an official asset.
- Do **not** commit vendor icon binaries or the unpacked packs; index them from a local build directory instead.
- Do **not** substitute a look-alike icon for a missing service; use the correct official asset or leave it `unresolved` and obtain the right one.

## Adding Coverage For A New Service

1. Try the built-in stencil first (extend the curated table or `mappings/<provider>-icons.yaml` when the neutral type already covers it).
2. If none exists, download/refresh the provider pack, run `rule-engine-index-assets --resolve <provider> "<Service>"`, and embed the returned official SVG/PNG as an image node with alt text.
3. If the service is genuinely absent from the official pack too, record the gap rather than shipping a placeholder.

