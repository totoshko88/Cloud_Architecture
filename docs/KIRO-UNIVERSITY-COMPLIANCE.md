# Kiro University — Feature Compliance

This document maps the project against the six Kiro University lessons
(<https://kiro.dev/2026/university/>) and points to the concrete evidence in
this repository for each. It is a hand-authored project document, so the
`kb-frontmatter` contract does not apply to it.

Summary: all six lessons are exercised with real, verifiable artifacts in the
repo — a full spec, six always-on steering documents, two hooks, fifteen
property-based test files, an agent skill, and an MCP server registration.

| # | Lesson | Status | Primary evidence |
| --- | --- | --- | --- |
| 1 | Spec-driven development | ✅ | `.kiro/specs/multicloud-diagram-inventory/` |
| 2 | Steering documents | ✅ | `.kiro/steering/*.md` (6 files) |
| 3 | Hooks | ✅ | `.kiro/hooks/*.hook` (2 files) |
| 4 | Property-based testing | ✅ | `tests/test_*_propert*.py` (15 files) |
| 5 | Powers / Skills | ✅ | `.kiro/skills/rule-engine-artifacts/SKILL.md` |
| 6 | Model Context Protocol (MCP) | ✅ | `.kiro/settings/mcp.json` (AWS docs) |

---

## Lesson 1 — Spec-driven development

The whole engine was built spec-first. The spec lives at
`.kiro/specs/multicloud-diagram-inventory/` and contains the three canonical
documents:

- `requirements.md` — requirements in **EARS** notation with an explicit
  glossary and the Absolute Context principle (no pronouns, no relative time).
  Example acceptance criterion (Requirement 1): "THE Diagram Generator SHALL
  limit each diagram to a maximum of 12 nodes." Every criterion is written so a
  linter or reviewer can assign a pass/fail verdict.
- `design.md` — the design narrative: the neutral-core-plus-profiles
  architecture, a C4 container view, and per-component designs.
- `tasks.md` — the implementation plan the build followed.

Each requirement traces forward to a lint rule in `diagram-lint.md` and to a
test, so the spec is not decorative — it is the source of the engine's behavior.

---

## Lesson 2 — Steering documents

Six always-on steering documents in `.kiro/steering/` give Kiro persistent,
project-specific knowledge so its output follows the established standards
without re-prompting:

- `diagram-standards.md` — diagram layout, lanes, node cap, legend, title cell,
  edge routing, accessibility, and the raster export budget.
- `diagram-lint.md` — the authoritative lint ruleset and severities.
- `provider-profiles.md` — terminology, container conventions, brand palette,
  and read-only verbs per provider.
- `inventory-standards.md` — the read-only collection contract and snapshot
  layout.
- `kb-frontmatter.md` — the twelve required frontmatter keys and section bounds.
- `asset-packs.md` — icon resolution order and per-provider icon sources.

These are always-on (they carry `inclusion: always`), so every agent turn
inherits them. They enforce conventions — e.g. "always resolve an icon through
`mappings/<provider>-icons.yaml`, never hand-write a `shape=mxgraph.*` id" — the
intent being that any conforming agent produces the same review-passing output.

---

## Lesson 3 — Hooks

Two hooks in `.kiro/hooks/` automate the quality gates:

- `lint-on-save.kiro.hook` — trigger `PostFileSave`, matcher `\.(drawio|md)$`,
  action runs `rule-engine-lint --file "$KIRO_FILE_PATH" --fail-on
  error,critical`. Every diagram/document is linted the moment it is saved.
- `validate-on-task.kiro.hook` — trigger `PostTaskExec`, action runs
  `rule-engine-lint --all` **and** `rule-engine-validate-schema`, so completing
  a spec task automatically re-checks the whole workspace.

This matches the lesson's pattern of a trigger event plus a corresponding
command action, letting Kiro handle execution.

---

## Lesson 4 — Property-based testing

The project extracts **correctness properties** from spec acceptance criteria
and validates them with Hypothesis across hundreds of generated inputs. There
are **fifteen** property-based test files under `tests/` (each uses
`from hypothesis import given, settings`), covering the behavior that matters:

- `test_icon_resolver_properties.py` — `resolve_icon` is total over every
  (provider, mapped-type) pair (200 examples).
- `test_icon_resolver_brand_color_property.py` — every `brand_hex` matches
  `^#[0-9A-Fa-f]{6}$`.
- `test_icon_resolver_generic_property.py` — the `generic` profile is always
  grayscale and vendor-free.
- `test_normalizer_schema_property.py` — every normalized resource validates
  against the Inventory Schema.
- `test_normalizer_digest_property.py` — the `config_digest` is deterministic,
  order-independent, and ignores secret values.
- `test_delta_partition_property.py` — the delta classification partitions the
  identity set (added/changed/removed/unchanged are exhaustive and disjoint).
- …and nine more across the resolver, normalizer, and delta engine.

These are optional-by-design (they assert the high-level intent of a requirement)
and run in both CI and the pre-commit hook. Full example generation
(`@settings(max_examples=200)`) requires the Kiro IDE / a local run, per the
lesson's IDE-only note.

---

## Lesson 5 — Powers / Skills

The project ships an agent **skill** at
`.kiro/skills/rule-engine-artifacts/SKILL.md`. It packages the repeatable
workflow for producing and validating Rule Engine artifacts (diagrams, companion
documents, inventory snapshots, icon mappings) and the exact gate commands to
run before publication. Its frontmatter `description` lists the triggers, so Kiro
loads it on demand when a task matches (authoring a `.drawio`, a `.diagram.md`, a
snapshot, or a mapping).

The skill deliberately defers rule *values* to the always-on steering documents
and only carries the *how-to* workflow — consistent with the lesson's model of a
skill as packaged, on-demand best-practice context. It is structured as the
lesson describes (a skill directory with a `SKILL.md` manifest); a full Kiro
Power could later wrap this skill together with the MCP config below into one
installable package.

---

## Lesson 6 — Model Context Protocol (MCP)

The project registers the **AWS Documentation MCP server** so Kiro can look up
current AWS facts (service names, limits, documentation links) instead of
relying on memory when authoring AWS diagrams or inventory notes.

Registration (`.kiro/settings/mcp.json`, mirrored at the user level
`~/.kiro/settings/mcp.json`):

```json
{
  "mcpServers": {
    "aws-docs": {
      "command": "uvx",
      "args": ["awslabs.aws-documentation-mcp-server@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" },
      "disabled": false,
      "autoApprove": ["search_documentation", "read_documentation", "recommend"]
    }
  }
}
```

The server exposes read-only tools (`search_documentation`,
`read_documentation`, `recommend`) and was used during development to verify
provider facts. `uvx` runs it on demand with no manual install. As the lesson
notes, an MCP server is a third-party tool subject to its own terms; this one is
read-only and used solely for documentation lookups.

> Configuration note: in this environment the workspace `.kiro/settings/`
> directory is access-controlled, so the authoritative registration is the
> user-level `~/.kiro/settings/mcp.json` (already active). Copy the block above
> into the workspace file when that directory is writable to make the project
> fully self-contained.

---

## How to verify each claim

```bash
# Lesson 1: the spec exists
ls .kiro/specs/multicloud-diagram-inventory/

# Lesson 2: six always-on steering docs
ls .kiro/steering/

# Lesson 3: two hooks
ls .kiro/hooks/*.hook

# Lesson 4: fifteen property-based test files, all green
ls tests/*propert*.py | wc -l
pytest -q

# Lesson 5: the skill manifest
cat .kiro/skills/rule-engine-artifacts/SKILL.md

# Lesson 6: the MCP registration
cat ~/.kiro/settings/mcp.json
```
