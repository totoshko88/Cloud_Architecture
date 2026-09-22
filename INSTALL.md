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

4. **Verify the console scripts are on your `PATH`.** Both should resolve and print
   usage:

   ```bash
   rule-engine-lint --help
   rule-engine-validate-schema --help
   ```

5. **Run a baseline lint and schema check.** This confirms the engine can read the
   steering ruleset, mappings, schema, and examples:

   ```bash
   rule-engine-lint --all --fail-on error,critical
   rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'
   ```

   A clean run reports every golden example as eligible for publication.

6. **Confirm the always-on steering documents are picked up.** Open the project in Kiro
   and verify the five documents under `.kiro/steering/` (`diagram-standards.md`,
   `inventory-standards.md`, `provider-profiles.md`, `kb-frontmatter.md`, and
   `diagram-lint.md`) are active. Because they are always-on, every agent turn in the
   workspace inherits the diagram, inventory, profile, frontmatter, and lint rules with no
   further configuration.

7. **Enable the Kiro hooks.** Confirm the hooks under `.kiro/hooks/` are active so quality
   gates run automatically:
   - `lint-on-save.kiro.hook` — runs `rule-engine-lint --file "$KIRO_FILE_PATH"` on saving
     any `.drawio` or `.md` file and surfaces a blocking failure reason to the session.
   - `validate-on-task.kiro.hook` — runs the linter (`--all`) and schema validation after
     a task executes, and surfaces a blocking failure reason to the session.

Once these steps complete, the Rule Engine is installed and active: the steering rules
govern generation, the hooks gate saves and task completion, and the CLIs are available
for manual and CI use. See the [README](README.md) for a quick-start overview and links
to each steering document.
