"""Example (unit) tests: the Contract lints the same frontmatter it writes
(task 19.4).

Validates **Requirement 9.4**: ``contract.invoke`` writes its four outputs into
a private staging directory and lints the *real files there* through the same
path as ``rule-engine-lint --file`` — :func:`rule_engine.cli.parse_artifacts`
followed by :func:`rule_engine.linter.lint_with_ruleset` — rather than through a
synthetic :class:`~rule_engine.linter.Artifact`. So the frontmatter (and body)
that the ``frontmatter`` rule sees is exactly the bytes the Contract wrote.

Two guarantees are exercised:

* **Positive path** — a valid invocation writes a ``.diagram.md`` companion and a
  versioned ``NN-existing-infrastructure.md``. Reading those files back off disk
  and linting them through the *real* path yields **no ``frontmatter`` finding**
  (and, being CRITICAL, none blocks publication). This is the "lints what it
  writes" guarantee: the same real text passes when re-linted.

* **Negative path** — if the Contract's companion renderer is forced to emit
  invalid frontmatter (``status: bogus``), the staging-then-lint gate catches it:
  ``invoke`` raises :class:`ContractGenerationError` and **no artifact lands in
  the output root** (the staging directory is removed, ``output_root`` untouched).

Tests use ``tmp_path`` for ``output_root`` so nothing is written outside the
pytest temp tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine import cli as cli_mod
from rule_engine import contract as contract_mod
from rule_engine import linter as linter_mod
from rule_engine.contract import ContractGenerationError, invoke
from rule_engine.linter import RULE_FRONTMATTER

# The four output keys the contract returns (Requirement 9.8).
OUTPUT_KEYS = ("drawio", "drawio_png", "diagram_md", "existing_infrastructure_md")

# The two generated Markdown documents that carry kb-frontmatter frontmatter.
DOC_KEYS = ("diagram_md", "existing_infrastructure_md")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_snapshot(tmp_path: Path) -> Path:
    """Write a small valid JSON snapshot (a list of Normalized Resources)."""
    snapshot = [
        {
            "resource_type": "object_store",
            "id": "my-bucket",
            "name": "my-bucket",
            "provider": "aws",
        },
        {
            "resource_type": "serverless_fn",
            "id": "my-fn",
            "name": "my-fn",
            "provider": "aws",
        },
    ]
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    return path


def _valid_inputs(tmp_path: Path, provider: str = "aws") -> dict:
    """Build a fully-specified valid input mapping for ``provider``."""
    snapshot = _write_snapshot(tmp_path)
    return {
        "provider": provider,
        "boundary_id": "123456789012",
        "region": "us-east-1",
        "previous_doc_path": str(tmp_path / "previous-nonexistent.md"),
        "inventory_snapshot_path": str(snapshot),
    }


def _lint_file_findings(path: Path) -> list:
    """Lint a written file through the REAL path and return all findings.

    Mirrors exactly what the Contract's own gate does (and what
    ``rule-engine-lint --file`` does): parse the real bytes on disk with
    :func:`cli.parse_artifacts`, then evaluate each parsed artifact with
    :func:`linter.lint_with_ruleset`. Returns the concatenated findings across
    every artifact the file parses into.
    """
    findings: list = []
    for artifact in cli_mod.parse_artifacts(str(path)):
        result = linter_mod.lint_with_ruleset(artifact)
        findings.extend(result.get("findings", []))
    return findings


def _output_dir_is_empty(output_root: Path) -> bool:
    """True when ``output_root`` contains none of the four output artifacts."""
    if not output_root.exists():
        return True
    names = {p.name for p in output_root.iterdir()}
    return not any(
        n.endswith((".drawio", ".drawio.png", ".diagram.md"))
        or n.endswith("existing-infrastructure.md")
        for n in names
    )


# --------------------------------------------------------------------------- #
# Positive path — the frontmatter the Contract WRITES passes when re-linted
# --------------------------------------------------------------------------- #


def test_written_docs_have_no_frontmatter_finding_when_relinted(
    tmp_path: Path,
) -> None:
    """Re-linting the written docs off disk yields no ``frontmatter`` finding.

    This is the "lints what it writes" guarantee (R9.4): the Contract stages the
    real files and lints them, and independently re-linting the same bytes off
    disk through the same real path agrees — the frontmatter it wrote is valid.
    """
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    for key in DOC_KEYS:
        path = Path(result[key])
        assert path.exists(), f"expected {key} on disk at {path}"
        findings = _lint_file_findings(path)
        frontmatter_findings = [
            f for f in findings if f.get("rule") == RULE_FRONTMATTER
        ]
        assert frontmatter_findings == [], (
            f"{key} carries frontmatter findings after re-lint: "
            f"{frontmatter_findings}"
        )


def test_written_docs_are_publication_eligible_on_frontmatter(
    tmp_path: Path,
) -> None:
    """No CRITICAL ``frontmatter`` finding blocks the written docs.

    The ``frontmatter`` rule is CRITICAL, so its absence is what makes the docs
    publication-eligible on that axis. A successful ``invoke`` already implies
    this (the Contract's own gate would have raised otherwise); here we verify it
    directly against the bytes on disk.
    """
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    for key in DOC_KEYS:
        path = Path(result[key])
        for artifact in cli_mod.parse_artifacts(str(path)):
            res = linter_mod.lint_with_ruleset(artifact)
            critical_frontmatter = [
                f
                for f in res.get("findings", [])
                if f.get("rule") == RULE_FRONTMATTER
                and f.get("severity") == "CRITICAL"
            ]
            assert critical_frontmatter == [], (
                f"{key} has a blocking CRITICAL frontmatter finding: "
                f"{critical_frontmatter}"
            )


def test_written_docs_start_with_frontmatter_block(tmp_path: Path) -> None:
    """Both generated docs actually begin with a YAML frontmatter fence.

    A sanity anchor for the positive path: the frontmatter the rule validated
    really is the leading ``---`` block of the file on disk (not injected by the
    parser), so "lints what it writes" is about real bytes.
    """
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    for key in DOC_KEYS:
        text = Path(result[key]).read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{key} missing leading frontmatter fence"


# --------------------------------------------------------------------------- #
# Negative path — invalid written frontmatter is caught by the gate
# --------------------------------------------------------------------------- #


def test_invalid_written_frontmatter_blocks_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A companion renderer that writes ``status: bogus`` makes ``invoke`` raise.

    The Contract lints the *real* staged file, so an invalid ``status`` value
    (rejected by the kb-frontmatter ``status`` enumeration) is a CRITICAL
    ``frontmatter`` finding that blocks publication. ``invoke`` must raise
    :class:`ContractGenerationError` and leave the output root empty — the
    staging directory is removed and no partial artifact set survives (R9.4).
    """
    real_render = contract_mod._render_companion_doc

    def _broken_companion(*args, **kwargs) -> str:
        # Render the real, otherwise-valid companion, then corrupt exactly the
        # frontmatter ``status`` value to an out-of-enumeration token. This is
        # the one field we tamper with, so the finding is unambiguously the
        # ``status`` enum (a CRITICAL frontmatter finding).
        doc = real_render(*args, **kwargs)
        corrupted = doc.replace("status: draft", "status: bogus", 1)
        assert corrupted != doc, "expected the real companion to carry status: draft"
        return corrupted

    monkeypatch.setattr(contract_mod, "_render_companion_doc", _broken_companion)

    output_root = tmp_path / "out"
    with pytest.raises(ContractGenerationError) as exc_info:
        invoke(_valid_inputs(tmp_path), output_root=output_root)

    # The blocking finding names the frontmatter rule.
    rules = {f.get("rule") for f in exc_info.value.findings}
    assert RULE_FRONTMATTER in rules, (
        f"expected a {RULE_FRONTMATTER!r} finding, got {exc_info.value.findings}"
    )
    # No artifact landed in the output root, and no staging dir was left behind.
    assert _output_dir_is_empty(output_root)
    leftover_staging = list(output_root.glob(".staging-*")) if output_root.exists() else []
    assert leftover_staging == [], f"staging dir was not cleaned up: {leftover_staging}"


def test_valid_status_precondition_for_negative_test(tmp_path: Path) -> None:
    """Guard: the real companion writes ``status: draft`` (a valid enum value).

    The negative test flips this exact token to ``status: bogus``; if the
    contract ever changed its default status, this precondition would fail loudly
    rather than the negative test silently becoming a no-op.
    """
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)
    companion_text = Path(result["diagram_md"]).read_text(encoding="utf-8")
    assert "status: draft" in companion_text
