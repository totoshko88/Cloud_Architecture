"""Example (unit) tests for ``rule-engine-init`` flag & source handling.

Feature: honest-gates (release 1.7.0), task 15.3.

Task 15.1 implemented the lock-file state machine and the ``--force`` /
``--check`` / ``--with-assets`` flags plus repo-vs-bundle source resolution in
:mod:`rule_engine.init_workspace`. Task 15.2 covers the *state machine* itself
with a property test (``tests/test_init_properties.py``). These are the
targeted example tests for the individual flag / source behaviours that the
property test does not pin directly:

  * R7.4 — ``--force`` backs up every edited file before overwriting it.
  * R7.5 — ``--check`` does NOT create the target directory.
  * R7.6 — ``--with-assets`` (and every write) stays inside the target workspace.
  * R7.7 — an in-repo run uses the repository tree, not the (possibly stale)
    bundled ``_bootstrap`` payload.

Plus the ``--check`` edge behaviours from R7.2 (five-group reporting, exit
code, no writes).

Each test lays a small hand-built source + target tree on disk (rather than the
generated scenarios the property test uses) so the assertions read as concrete
examples of one behaviour each.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine import init_workspace as iw


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_source(root: Path, files: dict[str, str] | None = None) -> Path:
    """Build a minimal engine-source tree under ``root`` and return it.

    A source needs a ``.kiro/steering`` tree and a ``mappings`` dir for
    :func:`iw._looks_like_source` to accept it. Extra ``files`` (workspace-rel
    path -> content) are layered on top.
    """
    source = root / "source"
    payload = {
        ".kiro/steering/diagram-standards.md": "# standards v1\n",
        ".kiro/steering/diagram-lint.md": "# lint v1\n",
        "mappings/roles.yaml": "roles: {}\n",
    }
    if files:
        payload.update(files)
    for rel, content in payload.items():
        dst = source / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
    return source


def _write(root: Path, rel: str, content: str) -> Path:
    dst = root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")
    return dst


# ---------------------------------------------------------------------------
# R7.4 — --force backs up every edited file before overwriting it
# ---------------------------------------------------------------------------
def test_force_backs_up_edited_file_before_overwriting(tmp_path: Path) -> None:
    """``--force`` writes the pre-overwrite bytes to a backup, then installs the
    source content over the user's edit.

    Validates: Requirements 7.4
    """
    source = _make_source(tmp_path)
    target = tmp_path / "target"

    # A first bootstrap installs the steering file and locks it.
    iw.bootstrap(source, target, explicit=str(source))
    edited_rel = ".kiro/steering/diagram-standards.md"

    # The user edits that file (its hash no longer matches source or lock).
    user_content = "# standards v1 — MY LOCAL EDIT\n"
    (target / edited_rel).write_text(user_content, encoding="utf-8")

    # A bare run must classify it as edited and keep it untouched.
    bare = iw.classify(source, target, iw.load_lock(target))
    assert edited_rel in bare["edited"]

    # --force: back up the edit, then overwrite from source.
    iw.bootstrap(source, target, force=True, explicit=str(source))

    # The target now equals the source (edit was overwritten).
    assert (target / edited_rel).read_text(encoding="utf-8") == "# standards v1\n"

    # A timestamped backup holds the user's pre-overwrite bytes.
    backup_root = target / iw.BACKUP_DIR_REL
    assert backup_root.is_dir(), "no backup dir created under --force"
    backups = [d for d in backup_root.iterdir() if d.is_dir()]
    assert backups, "no timestamped backup subdir created"
    stored = [b / edited_rel for b in backups if (b / edited_rel).is_file()]
    assert stored, f"edited file {edited_rel} was not backed up"
    assert any(
        p.read_text(encoding="utf-8") == user_content for p in stored
    ), "backup does not contain the pre-overwrite user bytes"


def test_force_does_not_back_up_unedited_files(tmp_path: Path) -> None:
    """A bare (unedited) file is not copied into the backup dir under --force.

    Only files classified ``edited`` are backed up (R7.4 backs up *edited*
    files). Missing/stale files are just (over)written; current files are kept.

    Validates: Requirements 7.4
    """
    source = _make_source(tmp_path)
    target = tmp_path / "target"
    iw.bootstrap(source, target, explicit=str(source))  # everything current now

    # No edits; a --force run has nothing to back up.
    iw.bootstrap(source, target, force=True, explicit=str(source))
    backup_root = target / iw.BACKUP_DIR_REL
    if backup_root.exists():
        for sub in backup_root.iterdir():
            assert not any(sub.rglob("*.md")), "backed up a non-edited file"


# ---------------------------------------------------------------------------
# R7.5 — --check does NOT create the target directory
# ---------------------------------------------------------------------------
def test_check_does_not_create_missing_target_directory(tmp_path: Path) -> None:
    """``rule-engine-init --check <missing-dir>`` reports all-missing and never
    creates the target directory.

    Validates: Requirements 7.5
    """
    source = _make_source(tmp_path)
    target = tmp_path / "does-not-exist"
    assert not target.exists()

    rc = iw.main(["--check", "--source", str(source), str(target)])

    # Missing/stale => non-zero exit (R7.2); and crucially the dir was NOT made.
    assert rc == iw.EXIT_FAIL
    assert not target.exists(), "--check created the target directory"


def test_check_on_missing_target_reports_every_file_missing(tmp_path: Path) -> None:
    """When the target does not exist, classification reports every source file
    as missing (nothing current/stale/edited/extra).

    Validates: Requirements 7.5, 7.2
    """
    source = _make_source(tmp_path)
    target = tmp_path / "absent"

    groups = iw.classify(source, target, {})
    assert set(groups["missing"]) == set(iw._source_files(source).keys())
    assert groups["current"] == []
    assert groups["stale"] == []
    assert groups["edited"] == []
    assert groups["extra"] == []
    assert not target.exists()


# ---------------------------------------------------------------------------
# R7.2 — --check edge behaviour (five groups, exit code, no writes)
# ---------------------------------------------------------------------------
def test_check_reports_five_groups_and_writes_nothing(tmp_path: Path) -> None:
    """``--check`` classifies missing/current/stale/edited/extra and never
    writes into the target.

    Validates: Requirements 7.2, 7.5
    """
    # Source with two files; we will drive each into a distinct group.
    source = _make_source(
        tmp_path,
        {".kiro/steering/extra-doc.md": "# extra source doc\n"},
    )
    src_files = iw._source_files(source)

    target = tmp_path / "target"
    # current: byte-identical to source.
    _write(target, ".kiro/steering/diagram-standards.md", "# standards v1\n")
    # edited: differs from both source and lock.
    _write(target, ".kiro/steering/diagram-lint.md", "# lint LOCAL\n")
    # roles.yaml missing entirely.
    # stale: matches the lock hash but not the (moved-on) source.
    _write(target, ".kiro/steering/extra-doc.md", "# extra OLD\n")
    # extra: present in a bootstrap dir, absent from source.
    _write(target, ".kiro/steering/unknown.md", "# not from source\n")

    # Lock records the *old* hash for extra-doc.md (=> stale, not edited).
    import hashlib

    def _h(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    lock = {
        "lock_version": iw.LOCK_VERSION,
        "engine_version": "test",
        "source": "explicit",
        "files": {".kiro/steering/extra-doc.md": _h("# extra OLD\n")},
    }
    lock_path = target / iw.LOCK_REL
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    # Snapshot the target tree so we can prove --check writes nothing.
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}

    groups = iw.classify(source, target, iw.load_lock(target))
    assert ".kiro/steering/diagram-standards.md" in groups["current"]
    assert ".kiro/steering/diagram-lint.md" in groups["edited"]
    assert "mappings/roles.yaml" in groups["missing"]
    assert ".kiro/steering/extra-doc.md" in groups["stale"]
    assert ".kiro/steering/unknown.md" in groups["extra"]

    rc = iw.main(["--check", "--source", str(source), str(target)])
    assert rc == iw.EXIT_FAIL  # missing + stale present

    after = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert after == before, "--check modified the target tree"
    _ = src_files  # (documents that source has the extra doc)


def test_check_exit_ok_when_nothing_missing_or_stale(tmp_path: Path) -> None:
    """``--check`` exits zero when every file is current or edited (no missing,
    no stale) — an edit alone does not block.

    Validates: Requirements 7.2
    """
    source = _make_source(tmp_path)
    target = tmp_path / "target"
    iw.bootstrap(source, target, explicit=str(source))  # all current

    # Edit one file: edited, but nothing missing/stale.
    (target / ".kiro/steering/diagram-lint.md").write_text(
        "# lint edited\n", encoding="utf-8"
    )
    rc = iw.main(["--check", "--source", str(source), str(target)])
    assert rc == iw.EXIT_OK


# ---------------------------------------------------------------------------
# R7.6 — every write stays inside the target workspace
# ---------------------------------------------------------------------------
def test_all_writes_stay_inside_target(tmp_path: Path) -> None:
    """A normal bootstrap writes only under the target; nothing appears beside
    it (source is untouched apart from being read).

    Validates: Requirements 7.6
    """
    source = _make_source(tmp_path)
    target = tmp_path / "ws"

    source_before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}

    iw.bootstrap(source, target, explicit=str(source))

    # Every file written landed under target/.
    for p in target.rglob("*"):
        if p.is_file():
            assert iw._within(target, p), f"{p} escaped the target"

    # The source tree was only read, never mutated.
    source_after = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert source_after == source_before, "bootstrap mutated the source tree"


def test_lock_path_within_target_guard_rejects_escape(tmp_path: Path) -> None:
    """The write-safety guard refuses a destination outside the target (R7.6).

    ``_within`` is the primitive every write path checks before touching disk;
    a path outside the target must be rejected.
    """
    target = tmp_path / "ws"
    target.mkdir()
    inside = target / ".kiro" / "steering" / "x.md"
    outside = tmp_path / "elsewhere" / "x.md"
    assert iw._within(target, inside) is True
    assert iw._within(target, outside) is False


def test_with_assets_requires_asset_sources_in_target(tmp_path: Path) -> None:
    """``--with-assets`` without ``mappings/asset-sources.yaml`` in the target
    fails cleanly and writes nothing outside the target.

    The minimal source here has no ``asset-sources.yaml``, so the fetch step is
    refused before any network/asset write — proving --with-assets never writes
    outside the target (R7.6).

    Validates: Requirements 7.6
    """
    source = _make_source(tmp_path)
    target = tmp_path / "ws"

    outside = tmp_path / "outside-marker"
    rc = iw.main(["--with-assets", "--source", str(source), str(target)])

    # The copy step succeeded (target created), but asset fetch was refused for
    # lack of asset-sources.yaml — a clean non-zero, not a crash.
    assert rc == iw.EXIT_FAIL
    assert target.is_dir()
    assert not outside.exists()
    # Nothing was written outside the target by the (refused) asset step.
    assert not (tmp_path / "assets").exists()


# ---------------------------------------------------------------------------
# R7.7 — an in-repo run prefers the repository tree over the bundle
# ---------------------------------------------------------------------------
def test_is_repo_checkout_true_for_engine_repo() -> None:
    """The real engine checkout is recognised as a repo source (R7.7).

    ``_REPO_ROOT`` is this checkout; it has ``pyproject.toml`` naming
    ``rule-engine`` and a ``.kiro/steering`` tree, so it must classify as a repo.
    """
    assert iw._is_repo_checkout(iw._REPO_ROOT) is True


def test_is_repo_checkout_false_without_pyproject(tmp_path: Path) -> None:
    """A tree with steering but no rule-engine pyproject is not a repo checkout.

    This is the shape of the bundled ``_bootstrap`` payload — steering present,
    but no ``pyproject.toml`` naming the engine — so it must NOT be treated as
    the repo source.

    Validates: Requirements 7.7
    """
    (tmp_path / ".kiro" / "steering").mkdir(parents=True)
    (tmp_path / ".kiro" / "steering" / "x.md").write_text("# x\n", encoding="utf-8")
    assert iw._is_repo_checkout(tmp_path) is False


def test_resolve_source_prefers_repo_over_bundle(tmp_path: Path, monkeypatch) -> None:
    """When run from inside a repo checkout, ``resolve_source`` returns the repo
    tree, not the bundled ``_bootstrap`` payload (R7.7).

    We stand up a fake repo (with a rule-engine pyproject + steering + mappings)
    and a distinct fake bundle, point the module's ``_REPO_ROOT`` / ``_BUNDLED``
    at them, and assert the repo wins even though the bundle is also usable.

    Validates: Requirements 7.7
    """
    # Fake repo checkout: pyproject names rule-engine, has steering + mappings.
    repo = tmp_path / "repo"
    (repo / ".kiro" / "steering").mkdir(parents=True)
    (repo / ".kiro" / "steering" / "diagram-standards.md").write_text(
        "# repo standards\n", encoding="utf-8"
    )
    (repo / "mappings").mkdir()
    (repo / "mappings" / "roles.yaml").write_text("roles: {}\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "rule-engine"\nversion = "1.7.0"\n', encoding="utf-8"
    )

    # Fake bundle: dot-free layout, also a usable source.
    bundle = tmp_path / "bundle"
    (bundle / "kiro" / "steering").mkdir(parents=True)
    (bundle / "kiro" / "steering" / "diagram-standards.md").write_text(
        "# BUNDLE standards (stale)\n", encoding="utf-8"
    )
    (bundle / "mappings").mkdir()
    (bundle / "mappings" / "roles.yaml").write_text("roles: {}\n", encoding="utf-8")

    monkeypatch.setattr(iw, "_REPO_ROOT", repo)
    monkeypatch.setattr(iw, "_BUNDLED", bundle)

    resolved = iw.resolve_source(None)
    assert resolved == repo, "resolve_source did not prefer the repo checkout"
    assert iw.source_kind(resolved, None) == "repo"


def test_resolve_source_falls_back_to_bundle_without_repo(
    tmp_path: Path, monkeypatch
) -> None:
    """With no repo checkout, ``resolve_source`` returns the bundled payload.

    Validates: Requirements 7.7
    """
    # _REPO_ROOT points at a non-repo dir (no pyproject / not a source).
    not_repo = tmp_path / "not-repo"
    not_repo.mkdir()

    bundle = tmp_path / "bundle"
    (bundle / "kiro" / "steering").mkdir(parents=True)
    (bundle / "kiro" / "steering" / "x.md").write_text("# x\n", encoding="utf-8")
    (bundle / "mappings").mkdir()
    (bundle / "mappings" / "roles.yaml").write_text("roles: {}\n", encoding="utf-8")

    monkeypatch.setattr(iw, "_REPO_ROOT", not_repo)
    monkeypatch.setattr(iw, "_BUNDLED", bundle)
    monkeypatch.setattr(iw, "_POWER_REPO", tmp_path / "no-power")

    resolved = iw.resolve_source(None)
    assert resolved == bundle
    assert iw.source_kind(resolved, None) == "bundle"


def test_explicit_source_wins_over_repo_and_bundle(tmp_path: Path, monkeypatch) -> None:
    """An explicit ``--source`` takes precedence over the repo and the bundle.

    Validates: Requirements 7.7
    """
    explicit = _make_source(tmp_path)  # tmp_path/source, dot-prefixed layout

    # A usable repo and bundle both exist, but --source must win.
    repo = tmp_path / "repo"
    (repo / ".kiro" / "steering").mkdir(parents=True)
    (repo / ".kiro" / "steering" / "x.md").write_text("# x\n", encoding="utf-8")
    (repo / "mappings").mkdir()
    (repo / "mappings" / "roles.yaml").write_text("roles: {}\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "rule-engine"\n', encoding="utf-8"
    )
    monkeypatch.setattr(iw, "_REPO_ROOT", repo)

    resolved = iw.resolve_source(str(explicit))
    assert resolved == explicit.resolve()
    assert iw.source_kind(resolved, str(explicit)) == "explicit"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
