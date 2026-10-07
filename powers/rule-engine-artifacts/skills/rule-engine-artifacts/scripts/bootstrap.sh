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
RULE_ENGINE_VERSION="${RULE_ENGINE_VERSION:-1.10.8}"
RULE_ENGINE_SPEC="${RULE_ENGINE_SPEC:-git+https://github.com/totoshko88/Cloud_Architecture.git@v${RULE_ENGINE_VERSION}}"

# Decide whether to install/upgrade. A Power is installed once but the engine
# it pulls is PINNED (RULE_ENGINE_VERSION); a user who bootstrapped an older
# release keeps an on-PATH `rule-engine-init` forever, so "install only when
# absent" would leave them on stale rules and a stale CLI indefinitely (the
# exact 1.9.0-stuck defect this hotfix closes). So: install when the CLI is
# ABSENT, and upgrade when the installed engine is OLDER than the pinned one.
# `rule-engine-init --version` (added 1.9.3) prints the installed version; an
# older CLI without that flag prints usage to stderr and nothing to stdout, so
# an empty/parse-failed version is treated as "needs upgrade".
_installed_version=""
if command -v rule-engine-init >/dev/null 2>&1; then
  _installed_version="$(rule-engine-init --version 2>/dev/null | head -n1 | tr -d '[:space:]')"
fi

# Return 0 (true) when $1 is strictly older than $2, comparing dotted integers.
_version_lt() {
  [ "$1" = "$2" ] && return 1
  # sort -V puts the smaller version first; if $1 sorts first AND differs, it is older.
  _smaller="$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)"
  [ "$_smaller" = "$1" ]
}

_need_install=0
if [ -z "$_installed_version" ]; then
  _need_install=1
  echo "bootstrap: rule-engine-init not found (or too old to report --version); installing the pinned engine..."
elif _version_lt "$_installed_version" "$RULE_ENGINE_VERSION"; then
  _need_install=1
  echo "bootstrap: installed engine ${_installed_version} is older than the pinned ${RULE_ENGINE_VERSION}; upgrading (else the workspace gets stale rules)..."
else
  echo "bootstrap: installed engine ${_installed_version} satisfies the pin ${RULE_ENGINE_VERSION}; not reinstalling."
fi

if [ "$_need_install" -eq 1 ]; then
  if [ -z "${PIP:-}" ] && command -v uv >/dev/null 2>&1; then
    # `uv tool install --force` also UPGRADES an already-installed tool to the
    # requested spec, so it covers both the fresh-install and the stale-upgrade
    # cases in one command.
    echo "bootstrap: \$ uv tool install --force \"${RULE_ENGINE_SPEC}\""
    uv tool install --force "${RULE_ENGINE_SPEC}"
    # uv puts tool entry points in its own bin dir, which may not be on PATH
    # yet; add it for the rest of this run.
    UV_BIN_DIR="$(uv tool dir --bin 2>/dev/null || true)"
    if [ -n "${UV_BIN_DIR}" ]; then
      PATH="${UV_BIN_DIR}:${PATH}"
      export PATH
    fi
  else
    PIP="${PIP:-python3 -m pip}"
    # --upgrade so a stale pip install is bumped to the pinned tag, not left as-is.
    echo "bootstrap: \$ ${PIP} install --upgrade \"${RULE_ENGINE_SPEC}\""
    # shellcheck disable=SC2086
    ${PIP} install --upgrade "${RULE_ENGINE_SPEC}"
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
# 1.10.7: pass the pin through the environment (an older CLI simply ignores
# it) so --check warns — and fails — when the engine on PATH is still older
# than the release this script pins, and warns when the workspace lock was
# written by an older engine.
RULE_ENGINE_PIN="${RULE_ENGINE_VERSION}" rule-engine-init --check "${TARGET}"
