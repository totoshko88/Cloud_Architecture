#!/usr/bin/env bash
# Rule Engine — power bootstrap helper.
#
# A Kiro Power ships this skill + steering + MCP, but NOT the `rule-engine-*`
# console scripts (those come from the `rule-engine` Python package) and NOT the
# workspace rule files. Installing a power does not run pip. So on a fresh machine
# the CLI the workflow depends on is absent. This script closes that gap in one
# idempotent step:
#
#   1. ensure the `rule-engine` package is installed (so `rule-engine-init` and
#      the gate CLIs are on PATH);
#   2. bootstrap the CURRENT workspace with the always-on rules + mappings +
#      schema + hooks (copied from the installed package's bundled payload);
#   3. optionally fetch the official GCP/OCI icon packs (`--with-assets`).
#
# Usage:
#   bootstrap.sh                 # install package (if needed) + bootstrap CWD
#   bootstrap.sh --with-assets   # ALSO download GCP/OCI icon packs (needs network)
#   bootstrap.sh /path/to/ws     # bootstrap an explicit workspace dir
#
# Env overrides:
#   RULE_ENGINE_SPEC   pip target for the package (default: the public git repo).
#   PIP                pip command to use (default: `python3 -m pip`).
set -euo pipefail

WITH_ASSETS=0
TARGET="."
for arg in "$@"; do
  case "$arg" in
    --with-assets) WITH_ASSETS=1 ;;
    *) TARGET="$arg" ;;
  esac
done

PIP="${PIP:-python3 -m pip}"
# Install the engine package straight from the public repo by default. Override
# RULE_ENGINE_SPEC to point at a local checkout (e.g. `-e /path/to/repo`) or a
# pinned tag (`...@v1.5.0`).
RULE_ENGINE_SPEC="${RULE_ENGINE_SPEC:-git+https://github.com/totoshko88/Cloud_Architecture.git}"

if ! command -v rule-engine-init >/dev/null 2>&1; then
  echo "bootstrap: rule-engine-init not found; installing the rule-engine package..."
  echo "bootstrap: \$ ${PIP} install \"${RULE_ENGINE_SPEC}\""
  # shellcheck disable=SC2086
  ${PIP} install "${RULE_ENGINE_SPEC}"
fi

if ! command -v rule-engine-init >/dev/null 2>&1; then
  echo "bootstrap: rule-engine-init still not on PATH after install." >&2
  echo "bootstrap: ensure your pip target's bin dir is on PATH (e.g. a venv)," >&2
  echo "           or set PIP to a pip inside an active virtualenv." >&2
  exit 1
fi

echo "bootstrap: copying steering rules + mappings + schema + hooks into ${TARGET}..."
rule-engine-init "${TARGET}"

if [ "${WITH_ASSETS}" -eq 1 ]; then
  echo "bootstrap: fetching official GCP/OCI icon packs (needs network)..."
  rule-engine-init --with-assets "${TARGET}"
fi

echo "bootstrap: done. Verifying..."
rule-engine-init --check "${TARGET}"
