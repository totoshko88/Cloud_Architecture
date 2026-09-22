# Provider Asset Packs & Icon Fallback

This steering document defines where each provider's **official icon asset pack**
lives, how it is laid out, and the **fallback order** the engine uses when a
specific service is not available as a built-in draw.io stencil. It complements
`provider-profiles.md` (which maps the nine neutral resource types to built-in
stencils) and `diagram-standards.md` (which forbids unresolved placeholder icons
via the `icon-resolved` ERROR).

The built-in `mxgraph.*` stencil libraries cover the common services but lag the
vendors' newest releases. Newer services — for example **AWS DevOps agent**,
**AWS FinOps agent**, and **AWS Security agent** — have no built-in stencil yet.
For those, the deterministic answer is to fall back to the vendor's official
SVG (preferred) or PNG from the pack, never to an unresolved placeholder.

## Icon Resolution Order

For any specific service the engine resolves an icon in this fixed order:

1. **Built-in stencil** — a known `mxgraph.<lib>.*` id (editable, scalable). This
   is what `provider-profiles.md` / `mappings/<provider>-icons.yaml` provide for
   the nine neutral types and a small curated set of common services.
2. **Official asset file** — the vendor SVG (preferred) or PNG from the indexed
   pack, when no built-in stencil matches. Embed it in the `.drawio`/`.puml`
   source as an image node with correct alt text.
3. **Unresolved** — nothing matched. This is fail-honest: the generator must
   obtain an official asset before publishing, because a placeholder icon is an
   `icon-resolved` ERROR that blocks publication.

The Asset Index (`src/rule_engine/asset_index.py`, CLI
`rule-engine-index-assets`) implements steps 1–3 and indexes a local directory of
unpacked packs by a normalized service **slug** (lowercase, hyphenated,
vendor/size/format decoration stripped), so `"AWS Security Agent"`,
`"security-agent"`, and `"Security  Agent"` resolve to the same entry.

## Official Pack Sources

Packs are downloaded on demand into a local, **uncommitted** directory (the
`.build-tools/` / `assets/` trees are git-ignored). Never commit vendor icon
binaries.

| Provider | Pack | Download |
|---|---|---|
| aws | AWS Architecture Icons | `https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/` (current Icon-package ZIP) |
| azure | Azure Public Service Icons | `https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip` |
| gcp | GCP Category Icons | `https://services.google.com/fh/files/misc/category-icons.zip` |
| gcp | GCP Core Product Icons | `https://services.google.com/fh/files/misc/core-products-icons.zip` |
| oci | OCI Style Guide for draw.io | `https://docs.oracle.com/iaas/Content/Resources/Assets/OCI-Style-Guide-for-Drawio.zip` |

Vendor icon assets remain under their owners' trademark/usage terms; they are a
build-time input, not redistributed by this repository.

## Pack Layouts

The indexer understands these layouts (files ending `.svg` preferred, `.png` as
raster fallback):

| Provider | Layout (under the unpacked root) |
|---|---|
| aws | `Architecture-Service-Icons_*/Arch_<Category>/<size>/Arch_<Service>_<size>.svg` and `Resource-Icons_*/Res_<Category>/<size>/Res_<Service>_<size>.svg` |
| azure | `Azure_Public_Service_Icons/Icons/<category>/NNNNN-icon-service-<Name>.svg` |
| gcp | `Unique Icons/<Product>/SVG/<Name>-<size>-color.svg` and `Category Icons/<Category>/... .svg` |
| oci | `OCI Style Guide for Drawio/OCI Library.xml` — a draw.io `<mxlibrary>` of `mxgraph.oci.*` shapes (OCI ships shapes, not per-service SVGs) |

### OCI note

OCI has **no built-in draw.io library**; its shapes come only from the custom
`OCI Library.xml` in the pack. Import that library into draw.io to render
`mxgraph.oci.*` shapes. Where the library is not available, the OCI golden
example uses self-contained OCI-red (`#F80000`) labelled boxes so the diagram
still renders and reads correctly (see `examples/oci/`).

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

- Do **not** hand-write a `shape=mxgraph.<lib>.<guess>` id and hope it resolves;
  an unknown stencil renders as an empty box (`icon-resolved` ERROR). Verify the
  id exists, or fall back to an official asset.
- Do **not** commit vendor icon binaries or the unpacked packs; index them from a
  local build directory instead.
- Do **not** substitute a look-alike icon for a missing service; use the correct
  official asset or leave it `unresolved` and obtain the right one.

## Adding Coverage For A New Service

1. Try the built-in stencil first (extend the curated table or
   `mappings/<provider>-icons.yaml` when the neutral type already covers it).
2. If none exists, download/refresh the provider pack, run
   `rule-engine-index-assets --resolve <provider> "<Service>"`, and embed the
   returned official SVG/PNG as an image node with alt text.
3. If the service is genuinely absent from the official pack too, record the gap
   rather than shipping a placeholder.
