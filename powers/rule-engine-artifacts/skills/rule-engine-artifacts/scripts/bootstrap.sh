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
# Installer (v1.6.1): when `uv` is available the package is installed with
# `uv tool install`, into its own isolated environment with a Python that meets
# the package's `requires-python` (uv fetches one if the machine has none). That
# avoids the two ways a bare `python3 -m pip install` fails on a fresh macOS:
# the system Python is older than the engine supports, and a Homebrew Python
# refuses to install into itself (PEP 668). Without uv, pip is used as before.
#
# Env overrides:
#   RULE_ENGINE_VERSION  engine release to install (default: the release this
#                        script ships with). Installs the matching git tag.
#   RULE_ENGINE_SPEC     full install target, overriding the version — one
#                        argument, e.g. a local checkout `/path/to/repo` or a
#                        different git ref (`git+https://…@main`).
#   PIP                  pip command to use (default: `python3 -m pip`). Setting
#                        it forces pip even when uv is available.
set -euo pipefail

WITH_ASSETS=0
TARGET="."
for arg in "$@"; do
  case "$arg" in
    --with-assets) WITH_ASSETS=1 ;;
    *) TARGET="$arg" ;;
  esac
done

# v1.6.1: pinned to the release this script ships with. The default used to be
# the repository's default branch, so a Power installed today could pull
# tomorrow's unreleased code. tests/test_version_pins.py keeps this in step with
# pyproject.toml.
RULE_ENGINE_VERSION="${RULE_ENGINE_VERSION:-1.6.1}"
RULE_ENGINE_SPEC="${RULE_ENGINE_SPEC:-git+https://github.com/totoshko88/Cloud_Architecture.git@v${RULE_ENGINE_VERSION}}"

if ! command -v rule-engine-init >/dev/null 2>&1; then
  echo "bootstrap: rule-engine-init not found; installing the rule-engine package..."
  if [ -z "${PIP:-}" ] && command -v uv >/dev/null 2>&1; then
    echo "bootstrap: \$ uv tool install \"${RULE_ENGINE_SPEC}\""
    uv tool install "${RULE_ENGINE_SPEC}"
    # uv puts tool entry points in its own bin dir, which may not be on PATH
    # yet; add it for the rest of this run.
    UV_BIN_DIR="$(uv tool dir --bin 2>/dev/null || true)"
    if [ -n "${UV_BIN_DIR}" ]; then
      PATH="${UV_BIN_DIR}:${PATH}"
      export PATH
    fi
  else
    PIP="${PIP:-python3 -m pip}"
    echo "bootstrap: \$ ${PIP} install \"${RULE_ENGINE_SPEC}\""
    # shellcheck disable=SC2086
    ${PIP} install "${RULE_ENGINE_SPEC}"
  fi
fi

if ! command -v rule-engine-init >/dev/null 2>&1; then
  echo "bootstrap: rule-engine-init still not on PATH after install." >&2
  echo "bootstrap: with uv, add \`uv tool dir --bin\` to PATH (or run \`uv tool update-shell\`);" >&2
  echo "           with pip, ensure the pip target's bin dir is on PATH (e.g. a venv)," >&2
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
