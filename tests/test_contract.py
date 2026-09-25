"""Unit tests for the Rule Engine Contract input validation and outputs
(task 11.3).

Exercises ``src/rule_engine/contract.py`` (``invoke``, ``invoke_result``,
``validate_inputs``, ``ContractInputError`` with ``.invalid_input``,
``ContractGenerationError``, ``REQUIRED_INPUTS``, ``PROVIDERS``).

Coverage:

- Requirement 9.6: a fully-specified valid invocation (all five required inputs,
  ``provider`` in the enumeration) is accepted and produces the four outputs.
- Requirement 9.8: the four outputs — ``.drawio``, ``.drawio.png``,
  ``.diagram.md``, and the versioned ``NN-existing-infrastructure.md`` — are
  written to disk, the ``NN`` prefix is a two-digit sequence in ``01``–``99``,
  and the Markdown documents are lint-clean (a blocking finding would raise
  ``ContractGenerationError``, so a successful return implies publication
  eligibility).
- Requirement 9.7: each missing/empty required input, and an out-of-enumeration
  ``provider``, is rejected with an error naming the offending input and no
  output documents are produced. Verified through both the raising
  (``invoke`` -> ``ContractInputError.invalid_input``) and non-raising
  (``invoke_result`` -> ``{"error", "invalid_input"}``) styles.
- All five providers produce a valid output set for a valid invocation.

Tests use ``tmp_path`` for ``output_root`` so nothing is written outside the
pytest temp tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine.contract import (
    PROVIDERS,
    REQUIRED_INPUTS,
    ContractInputError,
    invoke,
    invoke_result,
    validate_inputs,
)

# The four output keys the contract returns (Requirement 9.8).
OUTPUT_KEYS = ("drawio", "drawio_png", "diagram_md", "existing_infrastructure_md")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_snapshot(tmp_path: Path) -> Path:
    """Write a small JSON snapshot (a list of Normalized Resources)."""
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
        # previous_doc_path may point at a nonexistent path (first version).
        "previous_doc_path": str(tmp_path / "previous-nonexistent.md"),
        "inventory_snapshot_path": str(snapshot),
    }


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
# Requirement 9.6 / 9.8 — valid invocation produces the four outputs
# --------------------------------------------------------------------------- #


def test_valid_invocation_returns_four_output_keys(tmp_path: Path) -> None:
    """A fully-specified valid invocation is accepted and returns four keys."""
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    assert set(result.keys()) == set(OUTPUT_KEYS)


def test_valid_invocation_writes_all_four_files(tmp_path: Path) -> None:
    """Each of the four returned paths exists on disk (Requirement 9.8)."""
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    for key in OUTPUT_KEYS:
        path = Path(result[key])
        assert path.exists(), f"expected output {key} to exist at {path}"
        assert path.stat().st_size > 0, f"expected output {key} to be non-empty"


def test_valid_invocation_nn_prefix_in_01_to_99(tmp_path: Path) -> None:
    """The NN sequence prefix on every artifact is a two-digit 01–99 value."""
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    for key in OUTPUT_KEYS:
        name = Path(result[key]).name
        prefix = name[:2]
        assert prefix.isdigit(), f"{name} does not begin with two digits"
        assert 1 <= int(prefix) <= 99, f"{name} NN prefix {prefix} outside 01-99"


def test_valid_invocation_produces_expected_artifact_triple(tmp_path: Path) -> None:
    """The outputs form the mandatory triple plus the versioned inventory doc."""
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    assert result["drawio"].endswith(".drawio")
    assert result["drawio_png"].endswith(".drawio.png")
    assert result["diagram_md"].endswith(".diagram.md")
    assert result["existing_infrastructure_md"].endswith(
        "-existing-infrastructure.md"
    )


def test_valid_invocation_documents_are_lint_clean(tmp_path: Path) -> None:
    """A successful return implies the generated documents are lint-eligible.

    ``invoke`` runs each generated Markdown document through the Linter and
    raises ``ContractGenerationError`` if it is blocked from publication, so a
    return without raising means the ``.diagram.md`` and
    ``existing-infrastructure.md`` cleared every CRITICAL/ERROR lint rule
    (Requirement 9.8). We additionally assert both docs carry YAML frontmatter.
    """
    output_root = tmp_path / "out"
    result = invoke(_valid_inputs(tmp_path), output_root=output_root)

    for key in ("diagram_md", "existing_infrastructure_md"):
        text = Path(result[key]).read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{key} missing YAML frontmatter block"
        # Exactly one H1 heading (kb-frontmatter heading rule).
        assert sum(1 for line in text.splitlines() if line.startswith("# ")) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_provider_produces_valid_outputs(
    provider: str, tmp_path: Path
) -> None:
    """All five providers produce a complete, on-disk output set."""
    output_root = tmp_path / f"out-{provider}"
    result = invoke(_valid_inputs(tmp_path, provider=provider), output_root=output_root)

    assert set(result.keys()) == set(OUTPUT_KEYS)
    for key in OUTPUT_KEYS:
        assert Path(result[key]).exists(), f"{provider}: {key} missing on disk"


def test_validate_inputs_accepts_and_normalizes(tmp_path: Path) -> None:
    """validate_inputs accepts a valid mapping and returns the required keys."""
    normalized = validate_inputs(_valid_inputs(tmp_path))
    assert set(REQUIRED_INPUTS).issubset(normalized.keys())
    assert normalized["provider"] == "aws"


# --------------------------------------------------------------------------- #
# Requirement 9.7 — missing/empty required inputs are rejected, no outputs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("missing_key", REQUIRED_INPUTS)
def test_missing_required_input_raises_naming_error_no_outputs(
    missing_key: str, tmp_path: Path
) -> None:
    """Omitting each required input rejects with a naming error and no outputs."""
    output_root = tmp_path / "out"
    inputs = _valid_inputs(tmp_path)
    del inputs[missing_key]

    with pytest.raises(ContractInputError) as exc_info:
        invoke(inputs, output_root=output_root)

    assert exc_info.value.invalid_input == missing_key
    assert _output_dir_is_empty(output_root), (
        f"no output documents must be produced when {missing_key} is missing"
    )


@pytest.mark.parametrize("empty_key", REQUIRED_INPUTS)
def test_empty_required_input_raises_naming_error_no_outputs(
    empty_key: str, tmp_path: Path
) -> None:
    """Setting each required input to an empty string is rejected, no outputs."""
    output_root = tmp_path / "out"
    inputs = _valid_inputs(tmp_path)
    inputs[empty_key] = "   "  # whitespace-only -> empty after strip

    with pytest.raises(ContractInputError) as exc_info:
        invoke(inputs, output_root=output_root)

    assert exc_info.value.invalid_input == empty_key
    assert _output_dir_is_empty(output_root)


@pytest.mark.parametrize("missing_key", REQUIRED_INPUTS)
def test_invoke_result_reports_missing_input_form(
    missing_key: str, tmp_path: Path
) -> None:
    """invoke_result returns {error, invalid_input} rather than raising."""
    output_root = tmp_path / "out"
    inputs = _valid_inputs(tmp_path)
    del inputs[missing_key]

    result = invoke_result(inputs, output_root=output_root)

    assert result["invalid_input"] == missing_key
    assert "error" in result and result["error"]
    # Not an output mapping.
    assert not set(OUTPUT_KEYS).intersection(result.keys())
    assert _output_dir_is_empty(output_root)


# --------------------------------------------------------------------------- #
# Requirement 9.7 — out-of-enumeration provider is rejected, no outputs
# --------------------------------------------------------------------------- #


def test_out_of_enum_provider_raises_naming_error_no_outputs(tmp_path: Path) -> None:
    """An unrecognized provider is rejected naming 'provider', with no outputs."""
    output_root = tmp_path / "out"
    inputs = _valid_inputs(tmp_path)
    inputs["provider"] = "digitalocean"

    with pytest.raises(ContractInputError) as exc_info:
        invoke(inputs, output_root=output_root)

    assert exc_info.value.invalid_input == "provider"
    assert _output_dir_is_empty(output_root)


def test_invoke_result_reports_out_of_enum_provider_form(tmp_path: Path) -> None:
    """invoke_result flags an out-of-enum provider as invalid_input='provider'."""
    output_root = tmp_path / "out"
    inputs = _valid_inputs(tmp_path)
    inputs["provider"] = "digitalocean"

    result = invoke_result(inputs, output_root=output_root)

    assert result["invalid_input"] == "provider"
    assert "error" in result and result["error"]
    assert not set(OUTPUT_KEYS).intersection(result.keys())
    assert _output_dir_is_empty(output_root)


def test_non_mapping_inputs_rejected_no_outputs(tmp_path: Path) -> None:
    """A non-mapping ``inputs`` value is rejected and produces no outputs."""
    output_root = tmp_path / "out"

    with pytest.raises(ContractInputError) as exc_info:
        invoke(["not", "a", "mapping"], output_root=output_root)  # type: ignore[arg-type]

    assert exc_info.value.invalid_input == "inputs"
    assert _output_dir_is_empty(output_root)


# --------------------------------------------------------------------------- #
# Requirement 7 AC14 — the generation gate fail-closes on a missing ruleset
# --------------------------------------------------------------------------- #


def test_generation_blocks_when_ruleset_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the authoritative diagram-lint.md ruleset cannot be found, the
    contract's publication gate must block generation (Requirement 7 AC14).

    The contract now lints through ``linter.lint_with_ruleset`` rather than the
    unguarded ``linter.lint``, so a missing ruleset yields a blocked result and
    ``invoke`` raises ``ContractGenerationError``. We force the unavailable path
    by making ``find_ruleset`` report the ruleset absent everywhere.
    """
    from rule_engine import contract as contract_mod
    from rule_engine.contract import ContractGenerationError

    monkeypatch.setattr(
        contract_mod.linter_mod, "find_ruleset", lambda *a, **k: None
    )

    output_root = tmp_path / "out"
    with pytest.raises(ContractGenerationError):
        invoke(_valid_inputs(tmp_path), output_root=output_root)
