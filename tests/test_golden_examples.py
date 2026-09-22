"""Integration test validating every Golden Example against the Linter (task 9.7).

This test exercises the full parse → lint pipeline end-to-end, over the real
Golden Examples committed under ``examples/`` and using the real workspace
ruleset (``.kiro/steering/diagram-lint.md``). It is deliberately an integration
test rather than a unit test: it constructs no synthetic ``Artifact`` inputs,
instead discovering artifacts exactly as the ``rule-engine-lint`` CLI would
(:func:`rule_engine.cli.discover_artifacts` + :func:`rule_engine.cli.parse_artifact`)
and running them through :func:`rule_engine.linter.lint_with_ruleset`.

Coverage:

- Requirement 7.2 — a diagram/document with zero CRITICAL and zero ERROR
  findings is eligible for publication. Every Golden Example is a reference
  artifact that MUST pass every ERROR-level and CRITICAL-level lint rule
  (requirements.md Glossary: "Golden Example"), so each discovered example must
  lint ``eligible_for_publication == True``.
- Requirement 9.4 — exactly one Golden Example exists under ``examples/`` for
  each of the providers ``aws``, ``azure``, ``gcp``, ``oci``, and ``generic``.
  This test asserts at least one lintable artifact is discovered per provider
  directory so the coverage above is real rather than vacuous.

The ruleset is the authoritative on-disk ruleset, located via the workspace
root; if it were missing every artifact would be reported blocked (fail-closed,
Requirement 7.14), which would fail these assertions loudly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest

from rule_engine import cli
from rule_engine.linter import Severity, lint_with_ruleset, ruleset_available

# ---------------------------------------------------------------------------
# Workspace / examples discovery
# ---------------------------------------------------------------------------

# tests/ -> workspace root.
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_ROOT = WORKSPACE_ROOT / "examples"

# The five provider profiles that MUST each carry a Golden Example (Req 9.4).
PROVIDER_DIRS = ("aws", "azure", "gcp", "oci", "generic")

_BLOCKING = {Severity.CRITICAL.value, Severity.ERROR.value}


def _discover_example_artifacts() -> List[str]:
    """Discover every lintable Golden Example artifact under ``examples/``.

    Uses the same discovery the CLI uses (:func:`cli.discover_artifacts`) so the
    test lints exactly the ``.drawio`` and Markdown files the ``--all`` run
    would, then restricts to those under ``examples/``.
    """
    all_artifacts = cli.discover_artifacts(str(WORKSPACE_ROOT))
    examples_prefix = str(EXAMPLES_ROOT) + os.sep
    return sorted(a for a in all_artifacts if a.startswith(examples_prefix))


_EXAMPLE_ARTIFACTS = _discover_example_artifacts()


def _artifact_id(path: str) -> str:
    """Compact, stable test id: the artifact path relative to examples/."""
    return os.path.relpath(path, str(EXAMPLES_ROOT))


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def test_examples_directory_exists():
    """The Golden Examples tree exists under the workspace root."""
    assert EXAMPLES_ROOT.is_dir(), f"missing examples dir: {EXAMPLES_ROOT}"


def test_authoritative_ruleset_is_available():
    """The real workspace ruleset is present and readable (else fail-closed)."""
    assert ruleset_available(workspace_root=str(WORKSPACE_ROOT)) is True


def test_discovery_found_artifacts():
    """Discovery yielded at least one lintable Golden Example artifact."""
    assert _EXAMPLE_ARTIFACTS, (
        "no lintable .drawio/.md artifacts discovered under "
        f"{EXAMPLES_ROOT}"
    )


@pytest.mark.parametrize("provider", PROVIDER_DIRS)
def test_each_provider_has_at_least_one_golden_example(provider):
    """Each provider directory contributes at least one lintable example (Req 9.4).

    This guards against a vacuous "all examples pass" result: coverage is only
    real if every provider profile actually ships a Golden Example artifact.
    """
    provider_prefix = str(EXAMPLES_ROOT / provider) + os.sep
    provider_artifacts = [
        a for a in _EXAMPLE_ARTIFACTS if a.startswith(provider_prefix)
    ]
    assert provider_artifacts, (
        f"provider '{provider}' has no lintable Golden Example under "
        f"{EXAMPLES_ROOT / provider}"
    )


# ---------------------------------------------------------------------------
# The core assertion: every Golden Example is eligible for publication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("artifact_path", _EXAMPLE_ARTIFACTS, ids=_artifact_id)
def test_golden_example_is_eligible_for_publication(artifact_path):
    """Every Golden Example lints eligible for publication (Req 7.2).

    Parse the artifact exactly as the CLI does, then lint it through the real
    on-disk ruleset. The example must have zero CRITICAL and zero ERROR findings
    and therefore be eligible for publication. WARNING findings are permitted
    (they never block publication) but are surfaced in the failure message when
    a blocking finding is present.
    """
    artifact = cli.parse_artifact(artifact_path)
    result = lint_with_ruleset(artifact, workspace_root=str(WORKSPACE_ROOT))

    # The ruleset must have been available; a fail-closed result would carry an
    # error and block everything.
    assert result.get("error") is None, (
        f"unexpected lint error for {artifact_path}: {result.get('error')} "
        f"({result.get('error_detail')})"
    )

    blocking = [
        f for f in result["findings"] if f["severity"] in _BLOCKING
    ]
    assert result["eligible_for_publication"] is True, (
        f"Golden Example is blocked from publication: {artifact_path}\n"
        f"blocking findings: {blocking}\n"
        f"all findings: {result['findings']}"
    )
