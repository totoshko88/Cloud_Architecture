"""Guard: the hooks and CI pipelines actually enforce the gates they describe.

Before 1.6.1 several gates were wired so that they could not fail:

* both CI pipelines ran ``rule-engine-build-icon-sets --check … || echo WARNING``,
  so a stale icon index was a log line (while asset-packs.md said CI fails on it);
* the GitHub release job re-ran only lint + schema validation — no tests, no
  icon / raster / snapshot gates — and never compared the tag with pyproject.toml;
* GitLab ran no tests at all, and nothing ran ``version_guard --triple``, although
  CHANGELOG 1.6.0 and the triple tests said CI did;
* the validate-on-task hook swallowed schema failures with ``|| true`` and skipped
  schema validation whenever lint failed; every hook exited 0 in silence when the
  CLI was missing.

These tests pin the fixes: structural checks on the pipeline YAML, and
behavioural checks that execute each hook command under ``/bin/sh`` with stub
CLIs on ``PATH``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rule_engine import build_icon_sets_cli

_REPO = Path(__file__).resolve().parents[1]
_HOOKS = _REPO / ".kiro" / "hooks"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load_yaml(rel: str) -> dict:
    return yaml.safe_load((_REPO / rel).read_text(encoding="utf-8"))


def _on(workflow: dict) -> dict:
    # PyYAML (YAML 1.1) reads the bare key ``on`` as the boolean True.
    return workflow.get("on", workflow.get(True)) or {}


def _steps_text(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def _script_text(job: dict) -> str:
    lines = []
    for key in ("before_script", "script"):
        for item in job.get(key, []) or []:
            if isinstance(item, list):
                lines.extend(str(x) for x in item)
            else:
                lines.append(str(item))
    return "\n".join(lines)


def _hook_command(name: str) -> str:
    data = json.loads((_HOOKS / f"{name}.json").read_text(encoding="utf-8"))
    return data["hooks"][0]["action"]["command"]


def _stub(bin_dir: Path, name: str, exit_code: int, marker: Path) -> None:
    script = bin_dir / name
    script.write_text(
        f'#!/bin/sh\necho "{name} $*" >> "{marker}"\nexit {exit_code}\n', encoding="utf-8"
    )
    script.chmod(0o755)


def _run_hook(command: str, bin_dir: Path, cwd: Path, stdin: str = "") -> subprocess.CompletedProcess:
    # python3 is resolved through the stub dir so the real venv (which holds the
    # real rule-engine CLIs) is never on PATH.
    (bin_dir / "python3").symlink_to(sys.executable)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(cwd)}
    return subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture()
def sandbox(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    work = tmp_path / "ws"
    work.mkdir()
    return bin_dir, work, tmp_path / "calls.log"


# ---------------------------------------------------------------------------
# GitHub Actions
# ---------------------------------------------------------------------------


def test_ci_workflow_is_reusable_by_the_release():
    assert "workflow_call" in _on(_load_yaml(".github/workflows/ci.yml"))


def test_ci_icon_index_check_is_blocking():
    ci = _load_yaml(".github/workflows/ci.yml")
    runs = [str(s.get("run", "")) for s in ci["jobs"]["validate"]["steps"]]
    check = [r for r in runs if "build-icon-sets --check" in r]
    assert len(check) == 1
    assert "||" not in check[0]
    assert "--allow-missing" in check[0]


def test_release_requires_the_full_ci_workflow():
    release = _load_yaml(".github/workflows/release.yml")
    jobs = release["jobs"]
    ci_jobs = [jid for jid, job in jobs.items() if job.get("uses") == "./.github/workflows/ci.yml"]
    assert ci_jobs, "release.yml must call the CI workflow"
    needs = jobs["release"].get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert set(ci_jobs) <= set(needs)


def test_release_checks_the_version_triple_after_writing_version():
    text = _steps_text(_load_yaml(".github/workflows/release.yml")["jobs"]["release"])
    assert "> VERSION" in text and "version_guard --triple" in text
    assert text.index("> VERSION") < text.index("version_guard --triple")


def test_release_token_can_only_write_in_the_release_job():
    release = _load_yaml(".github/workflows/release.yml")
    assert release.get("permissions") == {"contents": "read"}
    assert release["jobs"]["release"]["permissions"] == {"contents": "write"}


# ---------------------------------------------------------------------------
# GitLab CI
# ---------------------------------------------------------------------------


def _gitlab() -> dict:
    return _load_yaml(".gitlab-ci.yml")


def test_gitlab_runs_the_test_suite():
    jobs = {k: v for k, v in _gitlab().items() if isinstance(v, dict) and "script" in v}
    assert any("pytest" in _script_text(job) for job in jobs.values())


def test_gitlab_release_stages_need_the_tests():
    cfg = _gitlab()
    for job in ("version-guard", "build"):
        assert "test" in cfg[job]["needs"], f"{job} must need the test job"


def test_gitlab_build_checks_the_version_triple_after_writing_version():
    text = _script_text(_gitlab()["build"])
    assert text.index("> VERSION") < text.index("version_guard --triple")


def test_gitlab_icon_index_check_is_blocking():
    text = _script_text(_gitlab()["validate"])
    lines = [line for line in text.splitlines() if "build-icon-sets --check" in line]
    assert len(lines) == 1
    assert "||" not in lines[0] and "--allow-missing" in lines[0]


# ---------------------------------------------------------------------------
# rule-engine-build-icon-sets --allow-missing
# ---------------------------------------------------------------------------


def test_check_skips_missing_packs_only_when_allowed(tmp_path, capsys):
    missing_root = tmp_path / "no-packs"
    base = ["--check", "--no-fetch", "--asset-root", str(missing_root)]
    assert build_icon_sets_cli.main(base) == build_icon_sets_cli.EXIT_FAIL
    assert build_icon_sets_cli.main(base + ["--allow-missing"]) == build_icon_sets_cli.EXIT_OK
    assert "SKIPPED" in capsys.readouterr().err


def test_an_empty_pack_directory_counts_as_missing(tmp_path, capsys):
    """A failed unpack used to leave an empty pack dir, reported as STALE."""
    asset_root = tmp_path / "packs"
    for rel in build_icon_sets_cli._PACK_ROOTS.values():
        (asset_root / rel).parent.mkdir(parents=True, exist_ok=True)
        if not (asset_root / rel).suffix:
            (asset_root / rel).mkdir(parents=True, exist_ok=True)  # present but empty
        else:
            (asset_root / rel).write_text("{}", encoding="utf-8")
    base = ["--check", "--no-fetch", "--asset-root", str(asset_root)]
    assert build_icon_sets_cli.main(base + ["--allow-missing"]) == build_icon_sets_cli.EXIT_OK
    assert "SKIPPED" in capsys.readouterr().err


def test_unpacking_a_non_zip_download_creates_no_pack_directory(tmp_path):
    import zipfile

    from rule_engine import fetch_assets

    bogus = tmp_path / "pack.zip"
    bogus.write_text("<html>rate limited</html>", encoding="utf-8")
    out_dir = tmp_path / "assets" / "vendor" / "aws-icons"
    with pytest.raises(zipfile.BadZipFile):
        fetch_assets._unpack(bogus, out_dir)
    assert not out_dir.exists()


def test_allow_missing_does_not_hide_a_stale_index(tmp_path, monkeypatch):
    """With every pack present, a mismatching committed index still exits 1."""
    asset_root = tmp_path / "packs"
    for rel in build_icon_sets_cli._PACK_ROOTS.values():
        target = asset_root / rel
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "icon.svg").write_text("<svg/>", encoding="utf-8")  # a non-empty pack
    stale = tmp_path / "icon-index.json"
    stale.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        build_icon_sets_cli,
        "build_icon_index",
        lambda roots, full_packs=False: {"roles": {}, "pack_summary": {}},
    )
    rc = build_icon_sets_cli.main(
        ["--check", "--no-fetch", "--allow-missing", "--asset-root", str(asset_root), "--out", str(stale)]
    )
    assert rc == build_icon_sets_cli.EXIT_FAIL


# ---------------------------------------------------------------------------
# Hooks (executed)
# ---------------------------------------------------------------------------


def test_validate_on_task_fails_when_schema_validation_fails(sandbox):
    bin_dir, work, calls = sandbox
    _stub(bin_dir, "rule-engine-lint", 0, calls)
    _stub(bin_dir, "rule-engine-validate-schema", 1, calls)
    result = _run_hook(_hook_command("validate-on-task"), bin_dir, work)
    assert result.returncode != 0


def test_validate_on_task_still_validates_schema_when_lint_fails(sandbox):
    bin_dir, work, calls = sandbox
    _stub(bin_dir, "rule-engine-lint", 1, calls)
    _stub(bin_dir, "rule-engine-validate-schema", 0, calls)
    result = _run_hook(_hook_command("validate-on-task"), bin_dir, work)
    assert result.returncode != 0
    assert "rule-engine-validate-schema" in calls.read_text(encoding="utf-8")


def test_validate_on_task_passes_when_both_gates_pass(sandbox):
    bin_dir, work, calls = sandbox
    _stub(bin_dir, "rule-engine-lint", 0, calls)
    _stub(bin_dir, "rule-engine-validate-schema", 0, calls)
    assert _run_hook(_hook_command("validate-on-task"), bin_dir, work).returncode == 0


@pytest.mark.parametrize("hook", ["validate-on-task", "lint-on-save"])
def test_gate_hooks_say_so_when_the_cli_is_missing(sandbox, hook):
    bin_dir, work, _calls = sandbox
    result = _run_hook(_hook_command(hook), bin_dir, work, stdin='{"filePath": "x.md"}')
    assert result.returncode == 0
    assert "not on PATH" in result.stderr


def test_lint_on_save_lints_the_saved_file(sandbox):
    bin_dir, work, calls = sandbox
    _stub(bin_dir, "rule-engine-lint", 0, calls)
    result = _run_hook(
        _hook_command("lint-on-save"), bin_dir, work, stdin='{"filePath": "docs/x.md"}'
    )
    assert result.returncode == 0
    assert "rule-engine-lint --file docs/x.md" in calls.read_text(encoding="utf-8")


def test_session_start_hook_explains_a_missing_install(sandbox):
    bin_dir, work, _calls = sandbox
    result = _run_hook(_hook_command("check-workspace-init"), bin_dir, work)
    assert result.returncode == 0
    assert "not installed" in result.stdout


def test_session_start_hook_is_quiet_on_a_bootstrapped_workspace(sandbox):
    bin_dir, work, calls = sandbox
    _stub(bin_dir, "rule-engine-init", 0, calls)
    result = _run_hook(_hook_command("check-workspace-init"), bin_dir, work)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_no_hook_swallows_a_gate_failure():
    for path in sorted(_HOOKS.glob("*.json")):
        command = json.loads(path.read_text(encoding="utf-8"))["hooks"][0]["action"]["command"]
        assert "|| true; }" not in command, path.name
        assert "validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json' || true" not in command


@pytest.mark.skipif(os.name != "posix", reason="hooks are POSIX shell commands")
def test_every_hook_command_is_valid_posix_shell():
    for path in sorted(_HOOKS.glob("*.json")):
        command = json.loads(path.read_text(encoding="utf-8"))["hooks"][0]["action"]["command"]
        result = subprocess.run(["/bin/sh", "-n", "-c", command], capture_output=True, text=True)
        assert result.returncode == 0, f"{path.name}: {result.stderr}"
