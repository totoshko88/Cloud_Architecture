"""Guard: the build-time bootstrap payload and the init-time bundle map agree.

``build_backend._PAYLOAD`` stages the workspace bootstrap trees into the wheel;
``init_workspace._BUNDLE_MAP`` / ``_BOOTSTRAP_DIRS`` reconstruct them in a target
workspace. The two are documented as "keep in sync" but nothing enforced it — a
tree added to one and forgotten in the other ships in the wheel yet is never
copied out (or vice versa), a silent bootstrap gap. These tests make the sync a
checked contract.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from rule_engine import init_workspace as iw

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_build_backend():
    spec = importlib.util.spec_from_file_location(
        "build_backend", _REPO_ROOT / "build_backend.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_payload_sources_match_bootstrap_dirs():
    """Every workspace tree init copies (_BOOTSTRAP_DIRS) is staged by the build
    backend (_PAYLOAD), and vice versa — no tree is bundled-but-uncopied or
    copied-but-unbundled."""
    bb = _load_build_backend()
    payload_sources = set(bb._PAYLOAD.keys())
    bootstrap_dirs = set(iw._BOOTSTRAP_DIRS)
    assert payload_sources == bootstrap_dirs, (
        "build_backend._PAYLOAD and init_workspace._BOOTSTRAP_DIRS diverged: "
        f"only in _PAYLOAD={payload_sources - bootstrap_dirs}, "
        f"only in _BOOTSTRAP_DIRS={bootstrap_dirs - payload_sources}"
    )


def test_dot_free_remap_matches_between_backend_and_init():
    """The dot-directory remap (``.kiro/steering`` -> ``kiro/steering``) is
    identical in the build backend and init, so a bundled tree lands where init
    looks for it."""
    bb = _load_build_backend()
    # The backend's remap = payload entries whose destination differs from source.
    backend_remap = {
        src: dst for src, dst in bb._PAYLOAD.items() if src != dst
    }
    assert backend_remap == iw._BUNDLE_MAP, (
        "the dot-free remap differs between build_backend._PAYLOAD and "
        f"init_workspace._BUNDLE_MAP: backend={backend_remap}, init={iw._BUNDLE_MAP}"
    )


def test_agents_are_part_of_the_bootstrap_payload():
    """The three workflow agents ship and are copied out (v1.6.0).

    A clean-room install received the always-on steering rules and the icon
    mappings but **none** of the agents that apply them (diagram-author,
    inventory-collector, rule-engine-reviewer), so a fresh workspace had the
    standard without the roles. This asserts the tree is in both maps and that the
    three agent files actually exist to be copied.
    """
    bb = _load_build_backend()
    assert ".kiro/agents" in bb._PAYLOAD
    assert ".kiro/agents" in iw._BOOTSTRAP_DIRS
    assert iw._BUNDLE_MAP[".kiro/agents"] == "kiro/agents"

    agents_dir = _REPO_ROOT / ".kiro" / "agents"
    names = sorted(p.name for p in agents_dir.glob("*.md"))
    assert names == [
        "diagram-author.md",
        "inventory-collector.md",
        "rule-engine-reviewer.md",
    ], f"unexpected agent set: {names}"


def test_every_dot_kiro_payload_tree_is_remapped_dot_free():
    """setuptools drops dot-directories from package data, so every ``.kiro/*``
    tree in the payload MUST have a dot-free bundle destination — otherwise it is
    silently absent from the wheel."""
    bb = _load_build_backend()
    for src, dst in bb._PAYLOAD.items():
        if src.startswith("."):
            assert not dst.startswith("."), (
                f"payload tree {src!r} maps to {dst!r}, which setuptools will drop"
            )


# ---------------------------------------------------------------------------
# Skill duplication (v1.6.0)
# ---------------------------------------------------------------------------

_SKILL_RELATIVE = "rule-engine-artifacts/SKILL.md"
_WORKSPACE_SKILL = _REPO_ROOT / ".kiro" / "skills" / _SKILL_RELATIVE
_POWER_SKILL = (
    _REPO_ROOT / "powers" / "rule-engine-artifacts" / "skills" / _SKILL_RELATIVE
)


def test_the_two_skill_copies_are_identical():
    """``.kiro/skills`` and the Power's ``skills/`` ship the same SKILL.md.

    The skill is duplicated because a Power carries its own copy, but nothing
    enforced the sync the way ``_PAYLOAD``/``_BOOTSTRAP_DIRS`` is enforced above —
    and by 1.5.4 the two had drifted across four wording hunks. Drift here is
    worse than in prose: the skill is the agent's instruction sheet, so two
    versions mean two behaviours depending on how the engine was installed.
    """
    assert _WORKSPACE_SKILL.is_file(), f"missing {_WORKSPACE_SKILL}"
    assert _POWER_SKILL.is_file(), f"missing {_POWER_SKILL}"
    workspace = _WORKSPACE_SKILL.read_text(encoding="utf-8")
    power = _POWER_SKILL.read_text(encoding="utf-8")
    assert workspace == power, (
        "the two SKILL.md copies have drifted; copy "
        f"{_WORKSPACE_SKILL.relative_to(_REPO_ROOT)} over "
        f"{_POWER_SKILL.relative_to(_REPO_ROOT)}"
    )


def test_power_plugin_version_matches_the_engine():
    """``powers/…/plugin.json`` declares the engine version it ships.

    It sat at ``1.0.0`` through nine engine releases, so a user could not tell
    which engine a Power install carried.
    """
    import json

    from rule_engine.version_guard import read_version_file

    plugin = json.loads(
        (_REPO_ROOT / "powers" / "rule-engine-artifacts" / "plugin.json")
        .read_text(encoding="utf-8")
    )
    assert plugin["version"] == read_version_file(_REPO_ROOT)
