"""Guard: everything the Power installs is pinned, and the pins track the release.

Before 1.6.1 the Power's MCP server ran ``awslabs.aws-documentation-mcp-server@latest``
and ``bootstrap.sh`` installed the engine from the repository's default branch,
so a Power installed on two different days could run two different MCP servers
and two different engines — neither of them necessarily a release. These tests
keep every pin exact and keep the engine pins equal to ``pyproject.toml``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from rule_engine.version_guard import read_pyproject_version

_REPO = Path(__file__).resolve().parents[1]
_POWER = _REPO / "powers" / "rule-engine-artifacts"
_BOOTSTRAP = _POWER / "skills" / "rule-engine-artifacts" / "scripts" / "bootstrap.sh"
_EXACT = re.compile(r"@\d+\.\d+\.\d+$")


def _engine_version() -> str:
    return read_pyproject_version(_REPO)


def test_power_mcp_servers_are_pinned_to_an_exact_release():
    config = json.loads((_POWER / "mcp.json").read_text(encoding="utf-8"))
    for name, server in config["mcpServers"].items():
        packages = [a for a in server.get("args", []) if not a.startswith("-")]
        assert packages, f"{name}: no package argument"
        for package in packages:
            assert "@latest" not in package, f"{name}: {package} is unpinned"
            assert _EXACT.search(package), f"{name}: {package} is not pinned to X.Y.Z"


@pytest.mark.parametrize(
    "doc", ["docs/ARCHITECTURE.md", "docs/KIRO-UNIVERSITY-COMPLIANCE.md", "powers/rule-engine-artifacts/README.md"]
)
def test_documented_mcp_examples_match_the_power_pin(doc):
    pin = json.loads((_POWER / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["aws-docs"]["args"][0]
    text = (_REPO / doc).read_text(encoding="utf-8")
    assert "aws-documentation-mcp-server@latest" not in text
    for found in re.findall(r"awslabs\.aws-documentation-mcp-server@[\w.]+", text):
        assert found == pin, f"{doc} documents {found}, the Power runs {pin}"


def test_bootstrap_installs_the_release_it_ships_with():
    text = _BOOTSTRAP.read_text(encoding="utf-8")
    match = re.search(r'RULE_ENGINE_VERSION="\$\{RULE_ENGINE_VERSION:-([^}]+)\}"', text)
    assert match, "bootstrap.sh must default RULE_ENGINE_VERSION"
    assert match.group(1) == _engine_version()
    assert "@v${RULE_ENGINE_VERSION}" in text


def test_session_start_hint_names_the_current_release():
    hook = json.loads((_REPO / ".kiro" / "hooks" / "check-workspace-init.json").read_text(encoding="utf-8"))
    command = hook["hooks"][0]["action"]["command"]
    tags = re.findall(r"Cloud_Architecture\.git@v([\d.]+)", command)
    assert tags and set(tags) == {_engine_version()}


# ---------------------------------------------------------------------------
# bootstrap.sh, executed against stub installers
# ---------------------------------------------------------------------------


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def stub_env(tmp_path):
    """A PATH with stub ``uv`` / ``pip`` installers and no real engine CLI."""
    bin_dir = tmp_path / "bin"
    tool_bin = tmp_path / "uv-tools" / "bin"
    bin_dir.mkdir()
    tool_bin.mkdir(parents=True)
    log = tmp_path / "calls.log"
    init_stub = f'#!/bin/sh\necho "rule-engine-init $*" >> "{log}"\nexit 0\n'
    # `uv tool install X` "installs" rule-engine-init into the tool bin dir;
    # `uv tool dir --bin` reports that dir (not yet on PATH, like a fresh machine).
    _write_stub(
        bin_dir / "uv",
        f'echo "uv $*" >> "{log}"\n'
        f'if [ "$1 $2" = "tool install" ]; then printf \'%s\' \'{init_stub}\' > "{tool_bin}/rule-engine-init"; '
        f'chmod +x "{tool_bin}/rule-engine-init"; fi\n'
        f'if [ "$1 $2 $3" = "tool dir --bin" ]; then echo "{tool_bin}"; fi\n'
        "exit 0\n",
    )
    pip_stub = bin_dir / "pip-stub"
    _write_stub(
        pip_stub,
        f'echo "pip $*" >> "{log}"\n'
        f'printf \'%s\' \'{init_stub}\' > "{bin_dir}/rule-engine-init"; chmod +x "{bin_dir}/rule-engine-init"\n'
        "exit 0\n",
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return env, log, pip_stub, tmp_path


def _run_bootstrap(env, cwd, extra_env=None):
    full = dict(env, **(extra_env or {}))
    return subprocess.run(
        ["bash", str(_BOOTSTRAP), str(cwd / "ws")],
        cwd=cwd, env=full, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.skipif(os.name != "posix", reason="bootstrap.sh is a bash script")
def test_bootstrap_prefers_uv_and_installs_the_pinned_tag(stub_env):
    env, log, _pip, cwd = stub_env
    result = _run_bootstrap(env, cwd)
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    expected = f"uv tool install git+https://github.com/totoshko88/Cloud_Architecture.git@v{_engine_version()}"
    assert expected in calls
    assert f"rule-engine-init {cwd / 'ws'}" in calls
    assert f"rule-engine-init --check {cwd / 'ws'}" in calls


@pytest.mark.skipif(os.name != "posix", reason="bootstrap.sh is a bash script")
def test_bootstrap_uses_pip_when_pip_is_set(stub_env):
    env, log, pip_stub, cwd = stub_env
    result = _run_bootstrap(env, cwd, {"PIP": str(pip_stub)})
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8")
    assert "uv tool install" not in calls
    assert f"pip install git+https://github.com/totoshko88/Cloud_Architecture.git@v{_engine_version()}" in calls


@pytest.mark.skipif(os.name != "posix", reason="bootstrap.sh is a bash script")
def test_bootstrap_version_override_changes_the_tag(stub_env):
    env, log, _pip, cwd = stub_env
    result = _run_bootstrap(env, cwd, {"RULE_ENGINE_VERSION": "9.9.9"})
    assert result.returncode == 0, result.stderr
    assert "Cloud_Architecture.git@v9.9.9" in log.read_text(encoding="utf-8")


def test_bootstrap_script_is_valid_bash():
    result = subprocess.run(["bash", "-n", str(_BOOTSTRAP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
