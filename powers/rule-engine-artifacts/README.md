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

## Relationship to the workspace

In this repository the same skill is also available workspace-locally at
`.kiro/skills/rule-engine-artifacts/SKILL.md` and the same MCP server at
`.kiro/settings/mcp.json` (mirrored at the user level). This power packages them
into one installable, shareable unit — the wrapping the project's
`docs/KIRO-UNIVERSITY-COMPLIANCE.md` described as a future step.
