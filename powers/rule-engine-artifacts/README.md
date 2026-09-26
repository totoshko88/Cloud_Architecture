# rule-engine-artifacts (Kiro Power)

A Kiro power that bundles the **Rule Engine artifacts** workflow — generating and
validating multi-cloud architecture diagrams (draw.io + companion documents),
inventory snapshots, and versioned knowledge-base documents for the five
provider profiles (`aws`, `azure`, `gcp`, `oci`, `generic`) — with the built-in
linter, raster gate, and icon verifier as the publication gate.

## What's inside

- **`plugin.json`** — the power manifest (name, version, description, author,
  keywords). Skills and MCP servers are **not** declared here — Kiro discovers
  them by file/directory convention (see below). A power logo is referenced via
  the schema's `extensions."dev.kiro".icon` namespace (→ `icon.png`), the only
  schema-valid place for client-specific manifest data.
- **`icon.png`** — the power logo (640×640 PNG).
- **`dev.kiro/steering/rule-engine-setup.md`** — a Kiro-specific always-on
  steering file (the sanctioned power activation-time instructions) that reminds
  the agent to run `rule-engine-init --check` / `rule-engine-init --with-assets`
  to bootstrap the workspace before generating artifacts, and restates the
  icon-fidelity and boundary rules.
- **`mcp.json`** — the read-only AWS-docs MCP server, declared under
  `mcpServers` per the `mcp.schema.json` schema (Kiro loads MCP servers from
  this sibling file, not from `plugin.json`).
- **`skills/rule-engine-artifacts/SKILL.md`** — the on-demand *how-to* skill: the
  diagram / companion-document / inventory workflow and the exact gate commands
  to run before publication. Rule *values* stay in the project's always-on
  steering documents; the skill carries only the workflow.
- **MCP** — registers the read-only `awslabs.aws-documentation-mcp-server` so an
  agent can look up current AWS facts when authoring AWS diagrams.

## Install

Point Kiro Powers at this directory (a public GitHub repository works without
special approval). The manifest follows the
`https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` schema; a power may
ship Agent Skills, MCP server configuration, and Kiro-specific extensions.

### First run: bootstrap the workspace (one step)

Installing the power wires up the skill, the `dev.kiro/` steering, and the MCP
server — but a power **cannot** run pip or ship the always-on rule files, so on
first use the `rule-engine-*` CLIs are not on `PATH` and the target workspace has
no rules/mappings yet. The skill's `dev.kiro/` steering makes the agent run the
bundled one-step helper before generating anything:

```bash
# from the skill dir: skills/rule-engine-artifacts/
bash scripts/bootstrap.sh               # install the rule-engine CLI (if missing) + bootstrap CWD
bash scripts/bootstrap.sh --with-assets # ALSO download the official GCP/OCI icon packs
```

`scripts/bootstrap.sh`:

1. installs the `rule-engine` package if `rule-engine-init` is not already on
   `PATH` — the **release the Power ships with** (the matching `vX.Y.Z` git tag),
   never the moving default branch. With `uv` available it uses
   `uv tool install` (an isolated environment with a supported Python, fetched if
   needed); otherwise `python3 -m pip install`. Override the release with
   `RULE_ENGINE_VERSION`, the whole target with `RULE_ENGINE_SPEC` (one argument,
   e.g. a local checkout `/path/to/repo`), or force pip with `PIP`;
2. runs `rule-engine-init` to copy `.kiro/steering/`, `.kiro/hooks/`, `mappings/`,
   and `schemas/` into the current workspace — resolved from the payload
   **bundled inside the installed package**, so no repo checkout is required;
3. with `--with-assets`, also fetches the official GCP/OCI icon packs (AWS/Azure
   icons are built into draw.io and need no download).

After this one step the always-on rules apply, the linter runs, and every node
resolves to the correct provider icon. The bootstrap is idempotent — re-running
it is safe.

## Relationship to the workspace

In this repository the same skill is also available workspace-locally at
`.kiro/skills/rule-engine-artifacts/SKILL.md` (kept byte-identical to the Power's
copy by a test). The MCP server is declared in this power's `mcp.json`, pinned to
an exact release of `awslabs.aws-documentation-mcp-server` so a new upstream
release cannot change the power's behaviour unannounced. This power packages them
into one installable, shareable unit — the wrapping the project's
`docs/KIRO-UNIVERSITY-COMPLIANCE.md` described as a future step.
