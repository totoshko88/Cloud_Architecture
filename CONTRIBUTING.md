# Contributing

Thanks for improving the Diagram & Inventory Rule Engine. This guide covers the
local dev setup, the checks that gate every change, and where to look when adding
a provider.

## Prerequisites

- **Python 3.14+** — the core and CLIs target `python_requires >= 3.14` (Python
  3.10 reaches end-of-life in October 2026; see [INSTALL.md](INSTALL.md)).
- A virtual environment is recommended so the console scripts land on your PATH.

## Dev setup

Install the engine editable, with the test/dev extras:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Runtime dependencies are just `jsonschema` and `PyYAML`; `pytest` and
`hypothesis` come from the `dev` extra and are not installed for downstream
consumers.

## Running the checks

These are exactly what CI runs (GitHub Actions `.github/workflows/ci.yml` and the
GitLab `.gitlab-ci.yml` lint/validate stages).

```bash
# Unit + property-based tests
pytest -q

# Lint every diagram and Markdown document (fail on CRITICAL/ERROR)
rule-engine-lint --all --fail-on error,critical

# Validate the golden examples against the Inventory Schema
rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'
```

### Property-based tests

The suite includes property-based tests (`hypothesis`) that assert general rules
rather than examples — the order-independent `config_digest`, schema conformance,
icon-resolution invariants, and delta classification. They live in
`tests/test_*_property.py` and run as part of `pytest`.

### Pre-commit hooks (optional but recommended)

Run the same gates automatically before each commit:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files   # one-off run over the whole tree
```

## Regenerating examples and rasters

Every generated example has a builder in `scripts/build_*_example.py`, listed in
the one table `scripts/regen_examples.GENERATORS` (the freshness test imports the
same table). Regenerate everything, and re-export only the rasters whose source
changed, with:

```bash
make examples          # or: python scripts/regen_examples.py
make examples-check    # write nothing; fail if an example or raster is stale
```

The raster export needs the draw.io desktop CLI on `PATH`, and the OCI examples
need the stencil pack (`python scripts/fetch_assets.py --only oci`). A new
`build_*_example.py` must be added to `GENERATORS`, or
`tests/test_generators_fresh.py` fails.

## Adding a provider

A new provider is a **data** change, not a core-code change. Follow the ordered
runbook in [docs/add-a-provider.md](docs/add-a-provider.md): add a terminology row
to `profiles/terminology.yaml`, the container conventions and brand entry, the
read-only verb list, an icon mapping (`mappings/<provider>-icons.yaml`), and a
golden example — then run the Linter until it reports zero violations. The
`tests/test_terminology_source.py` guardrail asserts the steering table, the
terminology YAML, and the core modules stay in agreement.

## Releasing

The release is scripted in `scripts/release.py`; the `Makefile` wraps it.

1. Record changes under `## [Unreleased]` in `CHANGELOG.md` as you go.
2. Create the release branch, named exactly after the version:
   `git checkout -b 1.10.2`.
3. `make bump VERSION=1.10.2` rewrites every version pin
   (`rule_engine.version_pins.PINS`) and turns `[Unreleased]` into
   `## [1.10.2] - <today>`. Use `make bump-dry VERSION=1.10.2` to see the diff
   first. If there was no `[Unreleased]` section, fill in the placeholder the
   bump inserts; `publish` refuses to run while it is still there.
4. `make preflight` runs every CI gate and the test suite locally.
5. Commit the release on the branch.
6. `make publish` pushes the branch, opens the PR, waits for its checks, merges,
   then tags `v1.10.2` **on the merge commit** and pushes the tag. The tag push
   triggers `.github/workflows/release.yml`, which refuses a tag that is not on
   `main`. Run `make publish-dry` to print the commands without running them.

If `git push` over SSH fails because no key is loaded, `publish` retries over
HTTPS through `gh auth git-credential`. To make plain `git push` work over HTTPS
too, run `gh auth setup-git` once.

## Commit conventions

- Keep the working tree lint-clean and tests green before committing.
- Stage specific files by name rather than `git add -A`.
- Vendor icon binaries and the unpacked asset packs (`assets/`, `.build-tools/`)
  are git-ignored — never commit them.
- Only create commits when the change is complete and verified.
