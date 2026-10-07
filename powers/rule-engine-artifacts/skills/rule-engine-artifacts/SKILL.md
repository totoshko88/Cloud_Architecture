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
skill and the MCP server, **not** the steering or mappings, and installing a
power does **not** run pip, so the `rule-engine-*` CLIs are not on PATH either.
So in a fresh / empty workspace those rules are absent and the CLI is missing:
the linter cannot run, and any diagram you produce will guess icon colors and
boundary placement (the exact defects that ship when the rules are missing —
orange EFS, actors drawn inside the VPC).

Before generating or editing ANY artifact, **always** run the bundled bootstrap
helper first — even when `rule-engine-init` is already on PATH. It does
everything in one idempotent step: it compares the installed engine with the
release this power pins, installs it when missing and **upgrades a stale one**,
then copies the rules, agents, mappings, schema, and hooks into the current
workspace and verifies the result:

```bash
# from this skill's directory (scripts/ ships with the power):
bash scripts/bootstrap.sh               # install/upgrade the CLI + bootstrap CWD
bash scripts/bootstrap.sh --with-assets # ALSO download the GCP/OCI icon packs
```

Do not shortcut this by calling a `rule-engine-init` that is already on PATH:
an older install keeps serving the rules and mappings it shipped with, which is
exactly how a workspace ends up generating with a stale engine.
`rule-engine-init --version` prints the installed engine version, and
`rule-engine-init --check` reports missing / stale rule files and prints a
`WARNING:` when the workspace lock was written by an older engine than the one
installed (or the engine is older than the power pin) — re-run the bootstrap
when you see one.

`rule-engine-init` copies `.kiro/steering/`, `.kiro/agents/`, `.kiro/hooks/`,
`mappings/`, `schemas/`, and `profiles/` into the target workspace, idempotently.
The source is resolved in order: an explicit `--source`; the **payload bundled
inside the installed package** (so it works with no repo checkout — this is the
normal power/pip case); the installed engine repo root; then the cloned power
repo. Do not skip this step and do not hand-copy a subset — the whole `mappings/`
tree (including `icon-index.json`, `aws-icons.yaml`, `roles.yaml`) is required for
correct icon resolution. Only after the workspace is bootstrapped do the always-on
steering rules apply and the gate commands below work.

**Icons: AWS/Azure are built in; GCP/OCI need the packs fetched.** AWS
(`mxgraph.aws4.*`) and Azure (`img/lib/azure2/*`) icons ship inside the draw.io
app, so they render with no download. **GCP** (official file-path SVGs) and
**OCI** (embedded stencils) resolve to files under `assets/vendor/` that are
**not committed** — `icon-index.json` only carries their *paths*. In a fresh
workspace those files are absent, so a GCP or OCI diagram renders empty boxes.
Run `rule-engine-init --with-assets` (once, needs network) to download the
official packs into `assets/vendor/` and rebuild the workspace `icon-index.json`
against them. If you are only producing AWS/Azure diagrams you can skip
`--with-assets`; for GCP/OCI it is required.

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
5. Export the raster with `rule-engine-export-raster <file>.drawio` (the
   packaged console script; `scripts/export_raster.py` is a thin shim onto it
   for a repo checkout) — it inlines local `assets/vendor` icons as base64 in a
   temp copy (the headless draw.io CLI cannot load local files), keeping the
   committed source lint-clean, and stays within the class-aware D7 budget
   enforced by `rule-engine-check-rasters` (`flow` ≤ 1600px wide / < 500KB;
   `landscape` ≤ 3600px / < 2MB). To re-align a hand-authored/hand-dragged
   `.drawio`, run `rule-engine-orthogonalise <file>.drawio`.
6. **Run every gate last, and publish only with zero BLOCKING findings:**
   `rule-engine-lint --all --fail-on error,critical`,
   `rule-engine-verify-icon --strict`, `rule-engine-check-rasters`,
   `rule-engine-check-snapshot` and `rule-engine-reconcile`. A red raster gate
   is blocking, exactly like a lint ERROR — never hand the user a diagram a
   gate has not cleared.

### Agent discipline (1.10.7)

Lessons from the 1.10.0 quick run (`diagram-standards.md` → *Lane Order* and
*Live Agent Generation → Agent discipline* carry the binding text):

- **Never mutate geometry after `layout()`.** Do not resize a container frame,
  move nodes, or recompute `legend_x` on the placed diagram. If the frame is
  wrong, fix the spec (lanes, slots, containers) or report an engine defect.
  Check `placed.layout_warnings`: a non-empty tuple means the layout carries
  residual findings the linter will report.
- **Pass `node_labels` whenever you build a `DiagramSpec` yourself** (by hand,
  or through private builder APIs such as `_boundaries_from` / `_edges_from`).
  `layout()` places the right-margin Flow/Legend past every node's caption, and
  it sizes each caption from `DiagramSpec.node_labels`; without them every
  caption counts as icon-wide, so a wide caption on a node right of the account
  can end up under the Flow box (`legend-placement` `overlaps-node-<id>`,
  ERROR). `rule-engine-draw` sets it for you. Pass the same text you give
  `Node(label=…)`:

  ```python
  labels = {"quick": "Amazon Quick", "users": "Quick users"}
  spec = DiagramSpec(..., nodes=nodes, edges=edges, containers=containers,
                     flow_lines=flow, title=title,
                     node_labels=tuple(labels.items()))
  placed = layout(spec)   # placed.legend_x now clears the widest caption
  ```
- **Lane semantics.** External sources and AWS-/SaaS-operated APIs go in
  `actors`. A consumer or notification recipient should sit on the external
  edge adjacent to the node that serves it. When that node is in the last
  occupied cloud lane, that is the far external column, declared in the
  `on-premises` lane (the engine draws it as that column), so the delivery edge
  is a short forward run, not a back-edge across the whole account. A lone
  external lane is ranked to the first row, so set the consumer's `sub` (half
  a row per step) to put it on its producer's row. Otherwise the consumer
  shares the `actors` edge with the sources. A source API is never
  put in `on-premises`; apart from this consumer case the lane is only for real
  data centres.
- **Slots are contiguous** — 0..k-1 per lane with no gaps. Never give each node
  a unique slot across lanes; that builds a staircase that stretches the canvas.
- **IAM roles and CloudFormation stacks are not data-flow nodes.** Show them as
  an attribute in the caption or companion, a `callout`, or a separate
  identity view.

## Companion / KB document workflow

- Start every generated Markdown with the 12-key YAML frontmatter from
  `kb-frontmatter.md`; keep the four required sections within their word bounds.
- Include an `Anti-patterns` section whenever the document has a fenced code
  block.

## Inventory workflow

**Before collecting, ask the user for scope — do not guess.** A cloud account
is huge (AWS alone is 30+ regions and 300+ services), so a collection that is
not scoped by the user silently misses whole domains — the *omitted EFS /
omitted AWS Batch* class of defect. Ask for, at minimum: (1) the **region(s)**
to enumerate (never assume one — check where resources actually live); (2) a
short **description of the system** and what it is built from (so you know
which domains matter — e.g. lifecycle mechanics like aws-nuke / Terraform /
STS, not just org/governance); and (3) **what specifically to look for**.
Warn the user explicitly that anything outside the stated scope may be missed,
and enumerate the full §6 domain set regardless so nothing is dropped by
assumption.

- Execute only the read-only verbs declared in the provider profile; the count
  of state-mutating verbs per run is zero.
- **Enumerate the full set of service domains** in `inventory-standards.md` §6 —
  identity, network, edge (CDN/DNS/WAF), load balancing, compute, containers,
  serverless, messaging, storage (**object stores AND file systems — EFS / Azure
  Files / Filestore / OCI File Storage**), database (SQL + cache), secrets, AI.
  A diagram is formed for the *whole* inventory, so a narrow collection silently
  drops resources (the omitted EFS defect). A domain with no resources is an
  empty file, never a silent skip.
- Write the Snapshot to `inventory-<provider>-<boundary-id>-<region>-<UTC>` with
  one JSON per service domain and a per-resource subfolder under `resources/`.
- Record metadata only — never secret values, key material, or SecureString
  contents.
- **Even a control-plane inventory needs `resources/<...>` subfolders.** The
  snapshot gate (§5) requires one per-resource subfolder for **each enumerated
  item**, and for a control-plane collection a "resource" is an OU / account /
  policy — so create a subfolder per OU/account too, not just for data-plane
  resources, or `resources-empty` blocks the snapshot.
- **Raster provenance is automatic.** `rule-engine-export-raster` stamps the
  source `.drawio` sha256 into the PNG (the `rule-engine:source-sha256` chunk)
  so `rule-engine-check-rasters` accepts it. Do not hand-stamp it — that manual
  step was only ever needed on a stale install lacking the exporter (fixed in
  1.9.1; a stale CLI is now upgraded by the bootstrap in 1.9.3).

## After inventory: offer the diagram type (simple / summary / landscape)

Once the snapshot is written, **ask the user which diagram type to produce** —
do not silently pick one (`diagram-standards.md` → *Choosing the diagram type
after inventory*):

- **simple** (`diagram_class: flow`, ≤ 12 nodes) — one focused view / request
  path. The everyday default for a small account or a single-flow question.
- **summary** (`flow`, ≤ 12 nodes) — the *shape* of a large system, paired with a
  landscape (`detailed_view:` ⇄ `summary_of:`).
- **landscape** (`diagram_class: landscape`) — the full as-built, everything
  enumerated on one canvas; cross-links a `flow` summary via `summary_of`.

Recommend **simple** for a small account; the **summary + landscape pair** for a
large one. When drawing **from the snapshot**, every enumerated resource that
resolves to a role (`roles.yaml`, incl. `file_system`, `compute_instance`,
`cdn`, `dns`, `waf`, `lb`, `cache`) MUST appear on the landscape; a
simple/summary shows the in-scope flow but never silently drops a resource that
is part of it. If a resource has no role, add one and re-run
`rule-engine-build-icon-sets` — never omit it or use a look-alike.

## Validate before publishing (run these gates)

```bash
rule-engine-lint --all --fail-on error,critical      # zero CRITICAL/ERROR to publish
rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'
rule-engine-check-asset-paths                         # mapping icon paths + OCI slugs exist
rule-engine-check-rasters --examples .                # exported PNGs within the D7 budget (use --examples . when diagrams sit at the workspace root, not under examples/)
rule-engine-check-snapshot --strict                   # Snapshot folder shape (§3-§5)
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
