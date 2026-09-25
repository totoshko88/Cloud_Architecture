---
name: rule-engine-artifacts
description: >-
  Generate and validate Diagram & Inventory Rule Engine artifacts — draw.io
  diagrams (with the mandatory triple), companion documents, inventory
  snapshots, and versioned KB Markdown — for the five provider profiles (aws,
  azure, gcp, oci, generic). Activate when a task involves producing or checking
  a .drawio diagram, a companion .diagram.md, an inventory snapshot/manifest, a
  provider icon mapping, or running the linter / asset-path guard / raster gate.
---

# Rule Engine Artifacts Skill

This skill packages the repeatable workflow for producing and validating Rule
Engine artifacts so output always clears the quality gates. It complements the
always-on steering documents under `.kiro/steering/` (which carry the
authoritative rules); this file is the *how-to* an agent follows when it is
actually generating or fixing an artifact.

## STEP 0 — Bootstrap the workspace (MANDATORY, do this FIRST)

The authoritative rules live in `.kiro/steering/*.md` and the icon/role tables
in `mappings/` — these are **workspace** files. A Kiro Power carries only this
skill and the MCP server, **not** the steering or mappings. So in a fresh /
empty workspace those rules are absent: the linter cannot run, and any diagram
you produce will guess icon colors and boundary placement (the exact defects
that ship when the rules are missing — orange EFS, actors drawn inside the VPC).

Before generating or editing ANY artifact, ensure the current workspace has the
rules. Run:

```bash
rule-engine-init --check            # reports missing rule files (exit 1 if any)
rule-engine-init                    # copies steering + mappings + schema in
```

`rule-engine-init` copies `.kiro/steering/`, `mappings/`, and `schemas/` from the
installed engine (or the cloned power repo at
`~/.kiro/powers/repos/rule-engine-artifacts`) into the target workspace,
idempotently. Do not skip this step and do not hand-copy a subset — the whole
`mappings/` tree (including `icon-index.json`, `aws-icons.yaml`, `roles.yaml`) is
required for correct icon resolution. Only after the workspace is bootstrapped do
the always-on steering rules apply and the gate commands below work.

## When to use

Activate this skill for any of:

- Authoring or editing a `NN-topic.drawio` diagram and its artifact triple.
- Writing or fixing a companion `NN-topic.diagram.md` document.
- Producing an inventory Snapshot folder (`00-MANIFEST.md` + per-service JSON).
- Editing a `mappings/<provider>-icons.yaml` icon mapping.
- Running the Linter, asset-path guard, or raster gate before publication.

## Authoritative rules live in steering

Do not restate rule values from memory. The binding sources are always-on:

- `diagram-standards.md` — layout, lanes, node cap (12), legend, title cell,
  edge routing, accessibility, raster export budget.
- `diagram-lint.md` — the authoritative lint ruleset and severities
  (CRITICAL / ERROR / WARNING) and publication eligibility.
- `provider-profiles.md` — terminology, container conventions, brand palette,
  read-only verbs per provider.
- `inventory-standards.md` — read-only collection contract, snapshot layout,
  secret-safety.
- `kb-frontmatter.md` — the 12 required frontmatter keys and section bounds.
- `asset-packs.md` — icon resolution order and per-provider icon sources.

## Diagram workflow

1. Pick the source format from the `diagram-standards.md` decision matrix
   (PlantUML for C4/architecture/component/deployment; Mermaid only for
   sequence/flow/state on GitLab/Backstage targets).
2. Resolve every node icon through `mappings/<provider>-icons.yaml` — take the
   whole `style:` string (which carries the correct `resIcon` id AND the correct
   service-family `fillColor`) from the mapping. The nine neutral types live
   under `resources:`; presentation-only services (EC2/compute, EFS/file system,
   load balancer, CDN, DNS, …) live under `presentation:` and in `roles.yaml`.
   **Never hand-write a `fillColor` hex** and never guess an id — a guessed color
   is an icon-fidelity defect (e.g. EFS is Storage GREEN `#7AA116`, not Compute
   orange `#ED7100`; a load balancer is networking purple `#8C4FFF`). Never use a
   `shape=mxgraph.*` id you have not verified or an `image=data:` URI (a `data:`
   URI trips the `icon-resolved` rule; use a file path). If a service has no role
   yet, ADD one to `roles.yaml` + `<provider>-icons.yaml` and re-run
   `rule-engine-build-icon-sets` — do not invent a look-alike. For GCP, respect
   the product → category → gcp2 source priority in `gcp-icons.yaml`.
3. Keep ≤ 12 nodes (flow class), ordered by the fixed lane order; add the Legend,
   a versioned title cell, numbered flow markers with a right-side `Flow` legend,
   and labeled orthogonal edges. **External actors (users) and on-premises nodes
   sit OUTSIDE the cloud boundaries** — never inside the Account/VPC/subnet
   containers. Only regional cloud resources belong in the VPC; a regional
   service like S3 sits in the Account boundary but outside the VPC.
4. Produce the mandatory triple: `NN-topic.drawio`, `NN-topic.drawio.png`,
   `NN-topic.diagram.md`.
5. Export the raster with `scripts/export_raster.py <file>.drawio` — it inlines
   local `assets/vendor` icons as base64 in a temp copy (the headless draw.io
   CLI cannot load local files), keeping the committed source lint-clean, and
   stays within the D7 budget (≤ 1200px wide, < 500KB).

## Companion / KB document workflow

- Start every generated Markdown with the 12-key YAML frontmatter from
  `kb-frontmatter.md`; keep the four required sections within their word bounds.
- Include an `Anti-patterns` section whenever the document has a fenced code
  block.

## Inventory workflow

- Execute only the read-only verbs declared in the provider profile; the count
  of state-mutating verbs per run is zero.
- Write the Snapshot to `inventory-<provider>-<boundary-id>-<region>-<UTC>` with
  one JSON per service domain and a per-resource subfolder under `resources/`.
- Record metadata only — never secret values, key material, or SecureString
  contents.

## Validate before publishing (run these gates)

```bash
rule-engine-lint --all --fail-on error,critical      # zero CRITICAL/ERROR to publish
rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'
rule-engine-check-asset-paths                         # mapping icon paths + OCI slugs exist
rule-engine-check-rasters                             # exported PNGs within the D7 budget
pytest -q                                             # unit + property-based tests
```

An artifact is eligible for publication only with zero CRITICAL and zero ERROR
findings; WARNING findings do not block. If any gate fails, fix the named
finding and re-run — never publish a partially conforming artifact.

## Optional research aid: AWS documentation MCP

When a task needs current AWS service facts (limits, service names, doc links)
to author an accurate AWS diagram or inventory note, the `aws-docs` MCP server
(`awslabs.aws-documentation-mcp-server`) is available. Use its read-only
`search_documentation` / `read_documentation` / `recommend` tools; do not rely
on memory for AWS specifics. See `docs/ARCHITECTURE.md` → "MCP support" for the
registration block.
