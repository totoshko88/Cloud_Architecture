"""In-tree PEP 517 build backend that bundles the workspace bootstrap payload.

The Rule Engine's authoritative rules live in ``.kiro/steering/*.md`` and the
icon/role tables in ``mappings/`` — plus ``schemas/`` and the automation hooks in
``.kiro/hooks/``. These are **workspace** files, not Python code, so historically
they were only reachable from the repo root (``parents[2]``). A user who installs
only the engine package (via pip, or transitively behind a Kiro Power) got the
``rule_engine`` code but **not** those trees, so ``rule-engine-init`` could not
find a source to copy and a fresh workspace stayed empty.

This backend closes that gap without duplicating the files in git: at build time
it copies the four trees into ``src/rule_engine/_bootstrap/`` so they ship as
package data inside the wheel/sdist. ``init_workspace.resolve_source`` then treats
that bundled directory as a valid source tree. The copied ``_bootstrap/`` dir is
git-ignored — the repo keeps a single source of truth (the top-level trees), and
every built artifact carries a fresh snapshot of them.

It is a thin wrapper: it stages the payload, then delegates every PEP 517 hook to
setuptools' own ``build_meta`` backend.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# setuptools is a BUILD-time dependency (declared in [build-system].requires), so
# it is always present when a build frontend invokes the PEP 517 hooks below.
# It is NOT a runtime dependency, so it may be absent when this module is merely
# IMPORTED for its constants (e.g. the payload-sync tests read ``_PAYLOAD``). Guard
# the import so importing the module never requires setuptools; the hooks that
# actually need it fail clearly only if called without it.
try:
    from setuptools import build_meta as _orig
    from setuptools.build_meta import *  # noqa: F401,F403  (re-export PEP 517 hooks)
    _HAVE_SETUPTOOLS = True
except ModuleNotFoundError:  # pragma: no cover - only when imported without setuptools
    _orig = None  # type: ignore[assignment]
    _HAVE_SETUPTOOLS = False

_ROOT = Path(__file__).resolve().parent
_BOOTSTRAP = _ROOT / "src" / "rule_engine" / "_bootstrap"

# (source dir relative to repo root) -> (destination relative to _bootstrap/).
#
# IMPORTANT: setuptools' package-data collection SKIPS dot-directories, so a
# payload staged under ``.kiro/...`` is silently dropped from the wheel. The
# bundle therefore stores everything under DOT-FREE directory names; the
# workspace-relative target (``.kiro/steering`` etc.) is reconstructed at copy
# time by ``init_workspace._BUNDLE_MAP``. Keep these two maps in sync.
_PAYLOAD = {
    ".kiro/steering": "kiro/steering",
    ".kiro/hooks": "kiro/hooks",
    # .kiro/agents (v1.6.0): the three agents that encode the workflow —
    # diagram-author, inventory-collector, rule-engine-reviewer. A clean-room
    # install got the steering rules and the icon mappings but NONE of the agents,
    # so a fresh workspace had the rules without the roles that apply them. They
    # are small Markdown files and, like steering, are pure configuration.
    ".kiro/agents": "kiro/agents",
    "mappings": "mappings",
    "schemas": "schemas",
    # profiles/terminology.yaml is the terminology source of truth loaded by
    # rule_engine.constants at import time. Without it, every CLI that imports
    # constants (lint, verify-icon, index-assets, build-icon-sets, …) crashes on
    # a fresh pip/Power install with FileNotFoundError. Bundle it too.
    "profiles": "profiles",
}


def _stage_bootstrap() -> None:
    """Copy the bootstrap payload into src/rule_engine/_bootstrap/ (idempotent)."""
    if _BOOTSTRAP.exists():
        shutil.rmtree(_BOOTSTRAP)
    _BOOTSTRAP.mkdir(parents=True, exist_ok=True)
    (_BOOTSTRAP / "__init__.py").write_text(
        '"""Bundled workspace bootstrap payload (generated at build time).\n\n'
        "Do not edit by hand — this tree is a build-time copy of the repo's\n"
        ".kiro/steering, .kiro/hooks, mappings, and schemas so rule-engine-init\n"
        'can bootstrap a workspace from the installed package alone.\n"""\n',
        encoding="utf-8",
    )
    for src_rel, dst_rel in _PAYLOAD.items():
        src = _ROOT / src_rel
        if not src.is_dir():
            continue
        dst = _BOOTSTRAP / dst_rel
        shutil.copytree(src, dst)


# --- PEP 517 hooks: stage the payload, then delegate to setuptools ---------- #


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _stage_bootstrap()
    return _orig.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _stage_bootstrap()
    return _orig.build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    _stage_bootstrap()
    return _orig.build_editable(wheel_directory, config_settings, metadata_directory)
