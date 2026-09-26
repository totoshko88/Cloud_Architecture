# Installation Guide

This guide lists the prerequisites and the ordered steps to install and activate the
Diagram & Inventory Rule Engine in a Kiro workspace.

## Prerequisites

- **Python 3.14 or newer** — the core components and CLIs target `python_requires >= 3.14`.
  (Python 3.10 reaches end-of-life in October 2026; the engine targets a supported runtime.)
- **pip** — used to install the project and its dependencies (a virtual environment such
  as `venv` is recommended so the console scripts land on your `PATH` cleanly).
- **Kiro** — the workspace host that reads the always-on steering documents and runs the
  hooks under `.kiro/`.
- **Runtime dependencies** (installed automatically by `pip install -e .`, declared in
  `pyproject.toml`):
  - `jsonschema` — validates normalized resources against `schemas/inventory.schema.json`
  - `PyYAML` — reads the per-provider `mappings/<provider>-icons.yaml` files
  - `hypothesis` — drives the property-based tests
  - `pytest` — runs the unit, integration, and property test suites

## Install and activate

Follow these steps in order.

1. **Obtain the project.** Clone or copy the Rule Engine into the workspace you want to
   use it from:

   ```bash
   git clone <repository-url> Cloud_Architecture
   cd Cloud_Architecture
   ```

2. **(Recommended) Create and activate a virtual environment.**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate      # Windows: .venv\Scripts\activate
   ```

3. **Install the engine and its dependencies.** The editable install also registers the
   console scripts:

   ```bash
   pip install -e .
   ```

4. **Verify the console scripts are on your `PATH`.** These should resolve and print
   usage (the full set the hooks, gate, and CI use):

   ```bash
   rule-engine-lint --help
   rule-engine-validate-schema --help
   rule-engine-check-rasters --help        # class-aware exported-PNG budget
   rule-engine-check-snapshot --help       # inventory Snapshot folder shape
   rule-engine-verify-icon --help          # every icon reference resolves
   rule-engine-check-asset-paths --help    # mapping icon paths / OCI slugs exist
   ```

5. **Run a baseline lint and schema check.** This confirms the engine can read the
   steering ruleset, mappings, schema, and examples:

   ```bash
   rule-engine-lint --all --fail-on error,critical
   rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'
   ```

   A clean run reports every golden example as eligible for publication.

6. **(Optional, for diagram generation) Build the official icon sets.** Diagram
   generation and raster export resolve each node's icon from the official provider
   packs. To fetch those packs and (re)build the committed icon index, run the
   init-time builder:

   ```bash
   rule-engine-build-icon-sets            # download packs + build mappings/icon-index.json
   rule-engine-build-icon-sets --check    # verify the committed index is current (CI)
   ```

   This downloads each pack declared in `mappings/asset-sources.yaml` into the
   git-ignored `assets/vendor/` root, parses every pack's filename/library structure,
   and writes `mappings/icon-index.json` (each diagram role → its resolved official icon
   per provider). The vendor binaries stay uncommitted; only the index is committed, so
   the linter and generators resolve and verify role→icon wiring without the packs
   present. Re-run it whenever a provider refreshes its icon pack — a new or renamed icon
   is a re-index, not a code change. Linting and schema checks (steps 4–5) do **not**
   require this step.

7. **Confirm the always-on steering documents are picked up.** Open the project in Kiro
   and verify the six documents under `.kiro/steering/` (`diagram-standards.md`,
   `inventory-standards.md`, `provider-profiles.md`, `kb-frontmatter.md`,
   `diagram-lint.md`, and `asset-packs.md`) are active. Because they are always-on, every
   agent turn in the workspace inherits the diagram, inventory, profile, frontmatter, lint,
   and asset-pack rules with no further configuration.

8. **Enable the Kiro hooks.** Confirm the hooks under `.kiro/hooks/` are active so quality
   gates run automatically:
   - `lint-on-save.json` — lints the saved `.drawio`/`.md` file and surfaces a
     blocking failure reason. It resolves the saved path from the hook's stdin JSON
     (falling back to `$KIRO_FILE_PATH`), and **skips silently** when the
     `rule-engine-lint` CLI is not installed (a Power-only install without pip) —
     so a fresh workspace never errors on save.
   - `validate-on-task.json` — runs the linter (`--all`) and schema validation
     after a task executes. It also **skips silently** when the CLI is absent.

   > **Hook file format.** Hooks are `.kiro/hooks/<name>.json` files carrying the
   > `{"version":"v1","hooks":[…]}` schema. Do **not** rename them to `.kiro.hook`:
   > that extension is the legacy IDE `when`/`then` format, and pairing it with the
   > current `version`/`hooks` body makes Kiro report **"Hook has invalid data
   > structure"** on install.

9. **(Optional) Use the custom agents.** Three purpose-built agents live under
   `.kiro/agents/` and are picked up automatically when the project is open in Kiro
   (switch to one with the agent selector):
   - `diagram-author` — authors/regenerates the provider diagrams through the layout
     engine and runs the full gate; `write`/`shell` are scoped to the build/gate commands.
   - `inventory-collector` — strictly read-only inventory collection (no write tool; only
     the profile-declared read-only verbs are permitted, every mutating verb is denied).
   - `rule-engine-reviewer` — a read-only verification gate that judges publication
     eligibility (lint / raster / icon / schema / tests) but never edits anything.

   These are workspace-local (`.kiro/agents/`), so they ship with the repo and need no
   extra setup. To make one available in any directory, copy it to `~/.kiro/agents/`.

10. **(Optional) Install the Kiro power.** `powers/rule-engine-artifacts/` packages the
    artifact-generation skill together with the read-only AWS-docs MCP server into one
    shareable unit (`plugin.json`, following the
    `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` schema). Point Kiro
    Powers at that directory (or its public GitHub repository) to install the skill and MCP
    server as a single power instead of the workspace-local copies. See
    [`powers/rule-engine-artifacts/README.md`](powers/rule-engine-artifacts/README.md).

    **Power-only install (a new user who did not do steps 1–5).** Installing a power
    does *not* run pip and does *not* copy the workspace rule files, so the power ships a
    one-step bootstrap that closes both gaps. On first use, run the helper from the skill
    directory:

    ```bash
    # from skills/rule-engine-artifacts/ inside the installed power:
    bash scripts/bootstrap.sh               # pip-install the rule-engine CLI (if missing) + bootstrap the workspace
    bash scripts/bootstrap.sh --with-assets # ALSO fetch the official GCP/OCI icon packs
    ```

    It installs the `rule-engine` package when `rule-engine-init` is absent, then copies
    `.kiro/steering/`, `.kiro/agents/`, `.kiro/hooks/`, `mappings/`, `schemas/`, and
    `profiles/` into the current workspace from the payload **bundled inside the installed
    package** (no repo checkout needed). The three agents — diagram-author,
    inventory-collector, rule-engine-reviewer — ship from v1.6.0; before that a fresh
    workspace got the always-on rules but none of the roles that apply them. The skill's always-on `dev.kiro/` steering instructs the agent to run this
    before generating any artifact. Steps 1–5 above remain the path for a full repo/CI
    checkout; the bootstrap helper is the equivalent for a power-only install.

Once these steps complete, the Rule Engine is installed and active: the steering rules
govern generation, the hooks gate saves and task completion, the custom agents provide
least-privilege per-workflow configurations, and the CLIs are available for manual and CI
use. See the [README](README.md) for a quick-start overview and links to each steering
document, and [docs/KIRO-UNIVERSITY-COMPLIANCE.md](docs/KIRO-UNIVERSITY-COMPLIANCE.md) for
how the spec, steering, hooks, tests, skill, MCP, agents, and power map to the Kiro
University lessons.
