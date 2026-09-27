"""Property tests for the ``rule-engine-init`` lock-file state machine.

Feature: honest-gates (release 1.7.0), task 15.2.

Task 15.1 implemented the lock-file state machine in
:mod:`rule_engine.init_workspace`: every bootstrap file is classified against a
recorded lock file into ``missing`` / ``current`` / ``stale`` / ``edited`` /
``extra``, ``--check`` reports those groups and exits non-zero when anything is
missing or stale (R7.2), a default run copies missing + stale files and leaves
edited files byte-identical (R7.3), and ``--force`` backs up every edited file
before overwriting it (R7.4). The lock a run writes records the sha256 of every
copied file (R7.1).

These properties drive that machine from :func:`tests.strategies.init_scenarios`,
which builds three trees (source / target / lock) plus the *expected* state of
every path, materialises them on disk, and asserts the machine's behaviour
against the predicted classification.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from hypothesis import given, settings

from rule_engine import init_workspace as iw

from tests.strategies import InitScenario, fs_settings, init_scenarios


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_tree(root: Path, tree: Mapping[str, str]) -> None:
    """Materialise a ``path -> content`` tree under ``root``."""
    for rel, content in tree.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")


def _write_lock(target: Path, lock_tree: Mapping[str, str]) -> None:
    """Write ``.kiro/rule-engine-init.lock.json`` from a ``path -> content`` map.

    The lock file records the sha256 of the content that was locked (design §9);
    the strategy hands back the *content* whose hash is the lock hash.
    """
    files = {rel: _sha256_text(content) for rel, content in lock_tree.items()}
    lock = {
        "lock_version": iw.LOCK_VERSION,
        "engine_version": "test",
        "source": "explicit",
        "files": dict(sorted(files.items())),
    }
    lock_path = target / iw.LOCK_REL
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def _materialise(scenario: InitScenario, base: Path) -> tuple[Path, Path]:
    """Lay a scenario's source + target + lock down on disk; return (source, target)."""
    source = base / "source"
    target = base / "target"
    source.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    _write_tree(source, scenario.source)
    _write_tree(target, scenario.target)
    if scenario.lock:
        _write_lock(target, scenario.lock)
    return source, target


def _expected_groups(scenario: InitScenario) -> dict[str, set[str]]:
    """Turn the scenario's per-path expected states into per-group sets."""
    groups: dict[str, set[str]] = {
        "missing": set(),
        "current": set(),
        "stale": set(),
        "edited": set(),
        "extra": set(),
    }
    for path, state in scenario.states.items():
        groups[state].add(path)
    return groups


# Feature: honest-gates, Property 27: rule-engine-init follows the lock-file state machine
@settings(fs_settings)
@given(scenario=init_scenarios())
def test_init_follows_the_lock_file_state_machine(
    scenario: InitScenario, tmp_path_factory
) -> None:
    """``--check`` classifies exactly as the state table predicts, and a default
    run + ``--force`` behave per R7.2/R7.3/R7.4.

    Feature: honest-gates, Property 27: rule-engine-init follows the lock-file state machine
    Validates: Requirements 7.1, 7.2, 7.3
    """
    base = tmp_path_factory.mktemp("init27")
    source, target = _materialise(scenario, base)
    expected = _expected_groups(scenario)

    # --- (1) --check classification matches the predicted state table (R7.2) --
    lock = iw.load_lock(target)
    groups = iw.classify(source, target, lock)
    for state in ("missing", "current", "stale", "edited", "extra"):
        assert set(groups[state]) == expected[state], (
            f"{state}: got {sorted(groups[state])}, "
            f"expected {sorted(expected[state])}"
        )

    # --- (2) --check exit code: non-zero iff missing or stale is non-empty ----
    rc = iw._report_check(source, target, groups)
    blocking = bool(expected["missing"] or expected["stale"])
    assert (rc != iw.EXIT_OK) == blocking

    # Snapshot the exact bytes of every edited file before a default run.
    edited_before = {
        rel: (target / rel).read_bytes() for rel in expected["edited"]
    }

    # --- (3) a default run: missing+stale -> source, edited untouched (R7.3) --
    result = iw.bootstrap(source, target, force=False, explicit=str(source))

    # Every missing / stale file now equals the source byte-for-byte.
    for rel in expected["missing"] | expected["stale"]:
        assert (target / rel).read_bytes() == (source / rel).read_bytes(), (
            f"{rel} was not brought up to the source"
        )
    # Every edited file is left byte-identical (a user edit is never clobbered).
    for rel, before in edited_before.items():
        assert (target / rel).read_bytes() == before, f"{rel} edit was clobbered"

    # After the write run nothing is missing or stale any more.
    post = iw.classify(source, target, iw.load_lock(target))
    assert not post["missing"]
    assert not post["stale"]

    # --- (4) the lock records unedited files at the source hash (R7.1) --------
    lock_after = iw.load_lock(target)
    locked = lock_after.get("files", {})
    for rel in expected["missing"] | expected["stale"] | expected["current"]:
        assert locked.get(rel) == iw._sha256_file(source / rel), (
            f"lock hash for {rel} does not match the source"
        )

    # --- (5) --force backs up the previous bytes of every edited file (R7.4) --
    if edited_before:
        iw.bootstrap(source, target, force=True, explicit=str(source))
        backup_root = target / iw.BACKUP_DIR_REL
        stamps = [p for p in backup_root.iterdir() if p.is_dir()]
        assert stamps, "no backup directory was created for --force"
        for rel, before in edited_before.items():
            found = [s / rel for s in stamps if (s / rel).is_file()]
            assert found, f"no backup stored for edited file {rel}"
            assert any(p.read_bytes() == before for p in found), (
                f"backup for {rel} does not hold the pre-overwrite bytes"
            )
            # …and the target now equals the source (edited was overwritten).
            assert (target / rel).read_bytes() == (source / rel).read_bytes()
