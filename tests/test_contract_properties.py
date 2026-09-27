"""Property tests for the Rule Engine Contract publication gate (task 19.2).

Feature: honest-gates (release 1.7.0). These properties exercise the reworked
``contract.invoke`` (task 19.1), which stages its four outputs, lints the real
written files through the same path as ``rule-engine-lint --file``
(``cli.parse_artifacts`` + ``linter.lint_with_ruleset``), and only moves them
into ``output_root`` when every parsed artifact is eligible for publication.

Property 31 (design.md -> Correctness Properties): *For any* generated inventory
snapshot, ``contract.invoke`` either writes a set of files on which the Linter
reports no blocking finding and whose ``.drawio`` contains no edge, or raises
``ContractGenerationError`` and leaves the output root without any new file; and
when the snapshot has more resources than the class limit, the error names the
count and the limit.

Validates: Requirements 9.1, 9.2, 9.3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine import cli as cli_mod
from rule_engine import linter as linter_mod
from rule_engine.contract import (
    ContractGenerationError,
    invoke,
)
from tests.strategies import fs_settings

# Output filename suffixes the four contract artifacts carry (task 19.1).
_ARTIFACT_SUFFIXES = (
    ".drawio",
    ".drawio.png",
    ".diagram.md",
    "-existing-infrastructure.md",
)

# The four keys ``invoke`` returns.
_OUTPUT_KEYS = ("drawio", "drawio_png", "diagram_md", "existing_infrastructure_md")

# A node name / id alphabet that stays within the unquoted-safe set so the
# generated snapshot never trips lint rules unrelated to the property.
_NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"


@st.composite
def _resource(draw: st.DrawFn) -> Dict[str, Any]:
    """One Normalized Resource with a real neutral resource_type and a name."""
    return {
        "resource_type": draw(
            st.sampled_from(
                [
                    "object_store",
                    "serverless_fn",
                    "managed_sql",
                    "message_queue",
                    "managed_k8s",
                    "secrets_store",
                    "llm_platform",
                    "compute_instance",
                    "file_system",
                ]
            )
        ),
        "name": draw(st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=12)),
        "provider": "aws",
    }


def _snapshots(min_size: int, max_size: int) -> st.SearchStrategy[List[Dict[str, Any]]]:
    return st.lists(_resource(), min_size=min_size, max_size=max_size)


def _write_inputs(tmp_path: Path, snapshot: List[Dict[str, Any]]) -> Dict[str, str]:
    """Write ``snapshot`` as a JSON file and build a valid contract input map."""
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    return {
        "provider": "aws",
        "boundary_id": "123456789012",
        "region": "us-east-1",
        "previous_doc_path": str(tmp_path / "previous-nonexistent.md"),
        "inventory_snapshot_path": str(snap_path),
    }


def _output_artifact_names(output_root: Path) -> List[str]:
    """Names of the four contract-artifact files present under ``output_root``.

    Ignores the private ``.staging-*`` directory (which must never survive) and
    the input ``snapshot.json`` — only the four output artifacts count.
    """
    if not output_root.exists():
        return []
    return sorted(
        p.name
        for p in output_root.iterdir()
        if p.is_file() and p.name.endswith(_ARTIFACT_SUFFIXES)
    )


def _no_staging_survives(output_root: Path) -> bool:
    if not output_root.exists():
        return True
    return not any(
        p.name.startswith(".staging-") for p in output_root.iterdir()
    )


# --------------------------------------------------------------------------- #
# Property 31 — the Contract publishes only what the gate passed
# --------------------------------------------------------------------------- #


# Feature: honest-gates, Property 31: The Contract publishes only what the gate passed
@settings(fs_settings)
@given(snapshot=_snapshots(min_size=0, max_size=20), unique_root=st.integers(0, 1_000_000))
def test_invoke_publishes_only_gated_output_or_leaves_root_untouched(
    tmp_path_factory: Any, snapshot: List[Dict[str, Any]], unique_root: int
) -> None:
    """Either a full lint-eligible set lands in ``output_root``, or it raises
    ``ContractGenerationError`` and no output artifact survives (R9.1, R9.3).

    When ``invoke`` succeeds, ``output_root`` holds exactly the four returned
    files, each parsed artifact is eligible for publication through the same
    path the Contract used to gate them, and no ``.staging-*`` dir survives.

    When ``invoke`` raises ``ContractGenerationError``, ``output_root`` carries
    none of the four artifacts (no partial set), and a > 12-resource snapshot
    always takes this branch with the count and the limit named in the message.
    """
    base = tmp_path_factory.mktemp("contract")
    tmp_path = base / f"in-{unique_root}"
    tmp_path.mkdir()
    output_root = base / f"out-{unique_root}"

    inputs = _write_inputs(tmp_path, snapshot)

    try:
        result = invoke(inputs, output_root=output_root)
    except ContractGenerationError as exc:
        # OR-branch: nothing partial is left behind (R9.1 fail-closed).
        assert _output_artifact_names(output_root) == []
        assert _no_staging_survives(output_root)
        # A snapshot larger than the flow limit must be the reason, and the
        # message must name both the count and the limit (R9.3).
        if len(snapshot) > linter_mod.MAX_NODES:
            message = str(exc)
            assert str(len(snapshot)) in message
            assert str(linter_mod.MAX_NODES) in message
        return

    # Success branch: exactly the four returned files are present (R9.1).
    returned_names = sorted(Path(result[k]).name for k in _OUTPUT_KEYS)
    on_disk = _output_artifact_names(output_root)
    assert on_disk == returned_names
    assert len(on_disk) == 4
    assert _no_staging_survives(output_root)

    # A success implies the snapshot fit the class limit.
    assert len(snapshot) <= linter_mod.MAX_NODES

    # Every returned file is eligible for publication through the SAME path the
    # Contract gated them with (cli.parse_artifacts + linter.lint_with_ruleset).
    for key in _OUTPUT_KEYS:
        path = Path(result[key])
        assert path.exists()
        if path.name.endswith(".png"):
            continue  # the PNG stub is not a lint artifact
        for artifact in cli_mod.parse_artifacts(str(path)):
            lint_result = linter_mod.lint_with_ruleset(artifact)
            assert lint_result.get("eligible_for_publication", False), (
                f"{path.name} is not lint-eligible: "
                f"{lint_result.get('findings')}"
            )


# Feature: honest-gates, Property 31: The Contract publishes only what the gate passed
@settings(fs_settings)
@given(snapshot=_snapshots(min_size=0, max_size=12), unique_root=st.integers(0, 1_000_000))
def test_rendered_drawio_contains_no_invented_edges(
    tmp_path_factory: Any, snapshot: List[Dict[str, Any]], unique_root: int
) -> None:
    """The rendered ``.drawio`` never contains an edge cell (R9.2).

    The Contract has no relationship data, so it invents none: the source is a
    set of vertex cells with no ``edge="1"`` cell and no parsed edge endpoints.
    """
    base = tmp_path_factory.mktemp("contract-edges")
    tmp_path = base / f"in-{unique_root}"
    tmp_path.mkdir()
    output_root = base / f"out-{unique_root}"

    inputs = _write_inputs(tmp_path, snapshot)
    result = invoke(inputs, output_root=output_root)

    drawio_path = Path(result["drawio"])
    text = drawio_path.read_text(encoding="utf-8")
    assert 'edge="1"' not in text

    # And structurally: parsing the diagram yields no edge endpoints.
    for artifact in cli_mod.parse_artifacts(str(drawio_path)):
        endpoints = getattr(artifact, "edge_endpoints", None) or []
        assert list(endpoints) == []


# Feature: honest-gates, Property 31: The Contract publishes only what the gate passed
@settings(fs_settings)
@given(snapshot=_snapshots(min_size=13, max_size=25), unique_root=st.integers(0, 1_000_000))
def test_over_limit_snapshot_raises_naming_count_and_limit(
    tmp_path_factory: Any, snapshot: List[Dict[str, Any]], unique_root: int
) -> None:
    """A snapshot with more resources than the flow limit (12) raises
    ``ContractGenerationError`` naming the count and the limit, and writes
    nothing to ``output_root`` (R9.3)."""
    base = tmp_path_factory.mktemp("contract-overlimit")
    tmp_path = base / f"in-{unique_root}"
    tmp_path.mkdir()
    output_root = base / f"out-{unique_root}"

    inputs = _write_inputs(tmp_path, snapshot)

    try:
        invoke(inputs, output_root=output_root)
    except ContractGenerationError as exc:
        message = str(exc)
        assert str(len(snapshot)) in message
        assert str(linter_mod.MAX_NODES) in message
        assert _output_artifact_names(output_root) == []
        assert _no_staging_survives(output_root)
    else:  # pragma: no cover - the over-limit branch must raise
        raise AssertionError(
            f"snapshot of {len(snapshot)} resources must exceed the "
            f"{linter_mod.MAX_NODES}-node flow limit and raise"
        )


# --------------------------------------------------------------------------- #
# Property 32 — one ruleset location for CLI and Contract (task 19.3, R10.2)
# --------------------------------------------------------------------------- #
#
# The Contract (contract.invoke / invoke_result) and the Lint_CLI (cli.main)
# locate the authoritative diagram-lint.md the SAME way — both through
# rule_engine.ruleset.require_ruleset — and both fail closed when it is absent.
# A set-but-missing RULE_ENGINE_RULESET makes both fail closed with no
# fallthrough: the Contract raises ContractGenerationError (before any file is
# written) and the CLI returns exit 2 (EXIT_RULESET_UNAVAILABLE), with no
# artifact emitted / no silent pass.

import os as _os  # noqa: E402

import pytest  # noqa: E402

from rule_engine import contract as _contract_mod  # noqa: E402
from rule_engine import ruleset as _ruleset_mod  # noqa: E402
from rule_engine.ruleset import (  # noqa: E402
    RULESET_ENV_VAR,
    RULESET_RELATIVE_PATH,
    RulesetUnavailableError,
    require_ruleset,
)

# A tiny, well-formed ruleset body: enough for require_ruleset to treat a file
# as present-and-non-empty (mirrors tests/test_ruleset.py).
_MINIMAL_RULESET = "# Diagram Lint Ruleset\n\nplaceholder body\n"

# Five valid contract inputs, so the ONLY thing that can make the Contract fail
# is the ruleset gate (which runs before any file I/O).
_RULESET_VALID_INPUTS = {
    "provider": "aws",
    "boundary_id": "123456789012",
    "region": "us-east-1",
    "previous_doc_path": "does-not-exist-previous",
    "inventory_snapshot_path": "does-not-exist-snapshot",
}

_ENV_STATES = ("unset", "readable", "missing")
_WORKSPACE_STATES = ("present", "absent", "empty")
_CWD_STATES = ("present", "absent")


def _write_ruleset_at(root: Path, body: str = _MINIMAL_RULESET) -> Path:
    """Create ``<root>/.kiro/steering/diagram-lint.md`` and return its path."""
    path = root / RULESET_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# Feature: honest-gates, Property 32: One ruleset location for CLI and Contract
@settings(fs_settings, max_examples=120)
@given(
    env_state=st.sampled_from(_ENV_STATES),
    ws_state=st.sampled_from(_WORKSPACE_STATES),
    cwd_state=st.sampled_from(_CWD_STATES),
)
def test_contract_and_cli_locate_ruleset_identically(
    tmp_path_factory: Any, monkeypatch, env_state, ws_state, cwd_state
) -> None:
    """For any (env var, workspace-root, cwd) ruleset configuration the Contract
    and the Lint_CLI resolve the SAME ruleset path, and when none resolves both
    fail closed identically — Contract ``ContractGenerationError`` (nothing
    written), CLI exit 2 (R10.2)."""
    base = tmp_path_factory.mktemp("prop32")
    workspace_root = base / "workspace"
    cwd = base / "cwd"
    output_root = base / "out"
    workspace_root.mkdir()
    cwd.mkdir()
    output_root.mkdir()

    # 1. Workspace-root ruleset knob.
    if ws_state == "present":
        _write_ruleset_at(workspace_root)
    elif ws_state == "empty":
        _write_ruleset_at(workspace_root, body="\n\n")
    # "absent": nothing written.

    # 2. cwd ruleset knob; pin the process cwd so the "<cwd>/.kiro/…" candidate
    #    is deterministic.
    if cwd_state == "present":
        _write_ruleset_at(cwd)
    monkeypatch.chdir(cwd)

    # 3. Env-var knob (always pinned so the real repo checkout cannot leak in).
    if env_state == "unset":
        monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    elif env_state == "readable":
        env_ruleset = base / "env-rules.md"
        env_ruleset.write_text(_MINIMAL_RULESET, encoding="utf-8")
        monkeypatch.setenv(RULESET_ENV_VAR, str(env_ruleset))
    else:  # "missing"
        monkeypatch.setenv(RULESET_ENV_VAR, str(base / "missing-env-rules.md"))

    # The single reference resolution both gates must match.
    try:
        expected_path: Any = require_ruleset(workspace_root=str(workspace_root))
    except RulesetUnavailableError:
        expected_path = None

    # Spy on the shared require_ruleset so we observe what each gate resolves and
    # confirm both go through the one function.
    calls: List[Any] = []
    real_require = _ruleset_mod.require_ruleset

    def _spy(caller: str):
        def wrapped(workspace_root=None):  # noqa: ANN001 - mirrors real signature
            try:
                resolved = real_require(workspace_root=workspace_root)
            except RulesetUnavailableError:
                calls.append((caller, None))
                raise
            calls.append((caller, resolved))
            return resolved

        return wrapped

    # --- Drive the Contract (calls ruleset_mod.require_ruleset internally). ---
    monkeypatch.setattr(_ruleset_mod, "require_ruleset", _spy("contract"))
    contract_error = None
    try:
        _contract_mod.invoke_result(
            _RULESET_VALID_INPUTS,
            output_root=str(output_root),
            workspace_root=str(workspace_root),
        )
        contract_blocked = False
    except ContractGenerationError as exc:
        contract_blocked = True
        contract_error = exc

    contract_calls = [c for c in calls if c[0] == "contract"]
    assert contract_calls, "Contract did not resolve the ruleset via require_ruleset"
    contract_resolved = contract_calls[0][1]

    # --- Drive the Lint_CLI (cli.main calls the require_ruleset it imported). ---
    calls.clear()
    monkeypatch.setattr(cli_mod, "require_ruleset", _spy("cli"))
    cli_exit = cli_mod.main(["--all", "--workspace-root", str(workspace_root)])
    cli_calls = [c for c in calls if c[0] == "cli"]
    assert cli_calls, "CLI did not resolve the ruleset via require_ruleset"
    cli_resolved = cli_calls[0][1]

    # (a) Same resolution: both gates resolve exactly what the shared function
    #     resolves — the same path, or both None (unavailable).
    assert contract_resolved == expected_path
    assert cli_resolved == expected_path
    assert contract_resolved == cli_resolved

    if expected_path is None:
        # (b) Fail closed, identically (a set-but-missing env var lands here too,
        #     no fallthrough): Contract raised before writing; CLI exit 2.
        assert contract_blocked is True
        assert contract_error is not None
        assert any(
            f.get("rule") == "ruleset-unavailable"
            for f in contract_error.findings
        )
        assert cli_exit == cli_mod.EXIT_RULESET_UNAVAILABLE
        # No artifact written by the Contract on the fail-closed path.
        assert _output_artifact_names(output_root) == []
    else:
        # A readable ruleset resolved for both: the CLI passed its ruleset gate
        # (not exit 2), and any Contract block is NOT for the ruleset reason.
        assert cli_exit != cli_mod.EXIT_RULESET_UNAVAILABLE
        if contract_blocked:
            assert not any(
                f.get("rule") == "ruleset-unavailable"
                for f in contract_error.findings  # type: ignore[union-attr]
            )


# Feature: honest-gates, Property 32: One ruleset location for CLI and Contract
def test_set_but_missing_env_fails_both_closed_no_fallthrough(
    tmp_path: Path, monkeypatch
) -> None:
    """A set-but-missing env var fails both gates closed even with a valid
    workspace ruleset present (the "no fallthrough" corner, as an example
    alongside the property): the Contract writes no artifact and the CLI exits 2.
    """
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "out"
    workspace_root.mkdir()
    output_root.mkdir()
    _write_ruleset_at(workspace_root)  # a candidate that must NOT rescue the run
    monkeypatch.chdir(workspace_root)
    monkeypatch.setenv(RULESET_ENV_VAR, str(tmp_path / "gone.md"))

    with pytest.raises(ContractGenerationError) as excinfo:
        invoke(
            _RULESET_VALID_INPUTS,
            output_root=str(output_root),
            workspace_root=str(workspace_root),
        )
    assert any(
        f.get("rule") == "ruleset-unavailable" for f in excinfo.value.findings
    )
    assert _output_artifact_names(output_root) == []

    cli_exit = cli_mod.main(["--all", "--workspace-root", str(workspace_root)])
    assert cli_exit == cli_mod.EXIT_RULESET_UNAVAILABLE
