---
inclusion: always
---

# Rule Engine — workspace setup check (read this first)

This steering ships with the **rule-engine-artifacts** Kiro Power. When the power
is active in a workspace, apply this before producing any diagram, inventory
snapshot, or knowledge-base document.

## Bootstrap the workspace before generating anything

The Rule Engine's authoritative rules (`.kiro/steering/*.md`), the icon/role
mappings (`mappings/`), the hooks (`.kiro/hooks/`), and the JSON schema
(`schemas/`) are **workspace files**. The Power itself carries only this skill +
MCP — it does **not** carry those rule files or the icon binaries. So in a fresh
workspace the linter cannot run and icons do not resolve.

At the start of working in a workspace, run the check and act on it:

```bash
rule-engine-init --check          # exit 1 if the rules/mappings are missing
rule-engine-init                  # copy steering + hooks + mappings + schema in
rule-engine-init --with-assets    # AND download the official GCP/OCI icon packs
```

- If `rule-engine-init --check` reports missing files, run `rule-engine-init`
  (or `rule-engine-init --with-assets`) before anything else.
- **AWS and Azure** icons are built into the draw.io app and need no download.
- **GCP and OCI** icons are official file/stencil assets that are **not
  committed** (`icon-index.json` records only their paths); a GCP or OCI diagram
  renders empty boxes until you run `rule-engine-init --with-assets` once (needs
  network). For AWS/Azure-only work, plain `rule-engine-init` is enough.

## Icon fidelity (do not guess)

Take each node's whole `style:` string — the correct `resIcon`/image id **and**
the correct service-family `fillColor` — from `mappings/<provider>-icons.yaml`
(`resources:` for the nine neutral types, `presentation:` for EC2/EFS/LB/CDN/DNS).
Never hand-write a `fillColor` hex or guess an id. If a service has no role, add
one to `mappings/roles.yaml` + `<provider>-icons.yaml` and re-run
`rule-engine-build-icon-sets` — never substitute a look-alike.

## Boundaries

External actors (users) and on-premises nodes sit **outside** the cloud
boundaries. A regional service (e.g. S3) sits inside the Account boundary but
outside the VPC. Only in-VPC resources go inside the Network Boundary.
