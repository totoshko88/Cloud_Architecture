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

The 1.7.0 release gate (task 22.10) extends this to assert the full contract on
every committed example ``.drawio``:

- Requirement 4.3 — ``rule-engine-verify-icon --strict`` resolves every diagram
  against the committed manifests (OCI via ``oci-stencil-digests.json``): zero
  ``unresolved`` and zero ``unverified`` references, and at least one resolved
  reference on any file that has service vertices.
- Requirement 8.3 — the raster gate is green for the corpus: each diagram's
  exported PNG is within its class-aware width/size/height budget, carries
  provenance matching its current source, and has an opaque white background.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest

from rule_engine import cli
from rule_engine.linter import Severity, lint_with_ruleset, ruleset_available
from rule_engine.raster_gate import check_rasters
from rule_engine.verify_icon import verify_drawio

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


def _discover_example_drawios() -> List[str]:
    """Every committed ``.drawio`` source under ``examples/`` (CLI discovery).

    Restricts :data:`_EXAMPLE_ARTIFACTS` to the ``.drawio`` sources — these are
    the diagrams the release gate runs ``verify-icon --strict`` against and the
    raster gate exports.
    """
    return [a for a in _EXAMPLE_ARTIFACTS if a.lower().endswith(".drawio")]


_EXAMPLE_DRAWIOS = _discover_example_drawios()


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

# ---------------------------------------------------------------------------
# The 1.7.0 release-gate contract on every committed .drawio (task 22.10)
# ---------------------------------------------------------------------------


def test_discovery_found_drawios():
    """Discovery yielded at least one committed ``.drawio`` example source."""
    assert _EXAMPLE_DRAWIOS, (
        f"no .drawio sources discovered under {EXAMPLES_ROOT}"
    )


@pytest.mark.parametrize("drawio_path", _EXAMPLE_DRAWIOS, ids=_artifact_id)
def test_golden_example_verifies_strict(drawio_path):
    """Every committed ``.drawio`` resolves under ``verify-icon --strict`` (Req 4.3).

    Runs the real verifier against the committed manifests exactly as
    ``rule-engine-verify-icon --all --strict`` does. A Golden Example must have
    **zero unresolved** references (a well-formed but non-existent id) and, under
    strict verification, **zero unverified** service vertices (a node with no
    verifiable icon reference). This is the regression gate for the OCI
    ``--strict`` bug fixed in ``icon_refs``: the OCI examples embed their glyph in
    child ``-gN`` sub-cells and carry an ``ociSlug=`` marker, so their group nodes
    must resolve while the sub-cells are never counted as service vertices.

    GCP file-path (``image=``) refs that need the fetched asset packs resolve by
    the committed path rule, so no pack needs to be present locally; when a
    reference's only source is genuinely absent it is ``skipped`` (fail-honest),
    which strict treats as not-verified — so a ``skipped`` ref would surface here
    rather than passing silently. The committed corpus has none.
    """
    report = verify_drawio(drawio_path, workspace_root=str(WORKSPACE_ROOT))

    assert report["unresolved"] == 0, (
        f"{drawio_path}: {report['unresolved']} unresolved icon reference(s)\n"
        + "\n".join(
            f"  - {r['kind']} {r['reference']} ({r['cell_id']}): {r['detail']}"
            for r in report["references"]
            if r["status"] == "unresolved"
        )
    )
    assert report["unverified"] == 0, (
        f"{drawio_path}: {report['unverified']} unverified service vertex(es) "
        f"under --strict\n"
        + "\n".join(
            f"  - {r['cell_id']}: {r['detail']}"
            for r in report["references"]
            if r["status"] == "unverified"
        )
    )
    # A file with service vertices must have verified at least one reference —
    # the third clause of the strict exit contract (a file of all-skipped refs
    # would pass "0 unresolved" while checking nothing).
    if report["service_vertices"]:
        assert report["resolved"] > 0, (
            f"{drawio_path}: has {report['service_vertices']} service vertices "
            f"but zero resolved references (strict would fail)"
        )


def test_golden_example_corpus_verifies_strict_as_one_gate():
    """The whole corpus verifies strict as one gate (mirrors ``--all --strict``).

    An aggregate assertion over every committed ``.drawio`` so a single failing
    diagram is reported alongside the corpus-wide totals, matching the CI
    ``rule-engine-verify-icon --all --strict`` step (Req 4.3).
    """
    failures = []
    for drawio_path in _EXAMPLE_DRAWIOS:
        report = verify_drawio(drawio_path, workspace_root=str(WORKSPACE_ROOT))
        strict_ok = (
            report["unresolved"] == 0
            and report["unverified"] == 0
            and not (report["service_vertices"] and not report["resolved"])
        )
        if not strict_ok:
            failures.append(
                f"{_artifact_id(drawio_path)}: "
                f"{report['resolved']} resolved, {report['unresolved']} unresolved, "
                f"{report['skipped']} skipped, {report['unverified']} unverified "
                f"({report['service_vertices']} service vertices)"
            )
    assert not failures, "verify-icon --strict failed on:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# The raster gate is green for the committed corpus (task 22.10)
# ---------------------------------------------------------------------------


def test_golden_example_rasters_within_budget():
    """Every committed example raster is within its class-aware budget (Req 8.3).

    Exercises the real raster gate (:func:`rule_engine.raster_gate.check_rasters`)
    over the committed ``examples/`` corpus, mirroring the CI
    ``rule-engine-check-rasters`` step. Each ``NN-topic.drawio`` must ship a
    matching ``NN-topic.drawio.png`` that is within the width, size and height
    ceiling for its ``diagram_class``, carries provenance matching its current
    source, and has an opaque white background.
    """
    refs = check_rasters(EXAMPLES_ROOT, repo_root=WORKSPACE_ROOT)
    assert refs, f"no exported rasters discovered under {EXAMPLES_ROOT}"

    offenders = []
    for ref in refs:
        if not ref.within_budget:
            reasons = []
            if not ref.exists:
                reasons.append("missing PNG")
            if not ref.width_ok:
                reasons.append(f"width {ref.width}>{ref.max_width}")
            if not ref.size_ok:
                sz = None if ref.size_bytes is None else ref.size_bytes // 1024
                reasons.append(f"size {sz}KB>{ref.max_size // 1024}KB")
            if not ref.height_ok:
                reasons.append(f"height {ref.height}>{ref.max_height}")
            if not ref.provenance_ok:
                reasons.append("stale/absent provenance")
            if not ref.background_ok:
                reasons.append("non-white/transparent background")
            offenders.append(f"{ref.source} [{ref.diagram_class}]: {', '.join(reasons)}")
    assert not offenders, "rasters out of budget:\n" + "\n".join(offenders)
