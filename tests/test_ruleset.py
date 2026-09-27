"""Unit tests for :mod:`rule_engine.ruleset` (honest-gates task 7.2).

Covers the ruleset *resolution order* (Requirement 10.2, design §3) and the
*rule-table parser* (Requirement 10.1):

* each step of :func:`find_ruleset`'s resolution order — explicit path, the
  ``RULE_ENGINE_RULESET`` env var, the ``workspace_root`` candidate, and the
  set-but-missing env var that yields ``None`` with **no fallthrough**;
* :func:`require_ruleset` raising :class:`RulesetUnavailableError` for a
  set-but-missing env var, and :func:`ruleset_available`;
* :func:`parse_rule_table` on the *current* ``diagram-lint.md`` (known rules
  parse with their default/landscape severities) and on a malformed table.

Every test that touches the env var monkeypatches it, and every test that
exercises the workspace/repo/bootstrap candidates pins ``RULE_ENGINE_RULESET``
off (``monkeypatch.delenv``) so the real repository checkout does not leak in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rule_engine.ruleset import (
    RULESET_ENV_VAR,
    RULESET_RELATIVE_PATH,
    RULESET_UNAVAILABLE_ERROR,
    RuleRow,
    RulesetUnavailableError,
    find_ruleset,
    parse_rule_table,
    require_ruleset,
    ruleset_available,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_RULESET = _REPO_ROOT / RULESET_RELATIVE_PATH

# A tiny, well-formed ruleset body: enough for ruleset_available/require_ruleset
# to treat a file as present-and-non-empty.
_MINIMAL_RULESET = "# Diagram Lint Ruleset\n\nplaceholder body\n"


def _write_ruleset(root: Path, body: str = _MINIMAL_RULESET) -> Path:
    """Create ``<root>/.kiro/steering/diagram-lint.md`` and return its path."""
    path = root / RULESET_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# find_ruleset — resolution order (Requirement 10.2)
# ---------------------------------------------------------------------------


def test_find_ruleset_explicit_path_is_authoritative(tmp_path, monkeypatch):
    """Step 1: an explicit, existing ``ruleset_path`` wins over everything."""
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    explicit = tmp_path / "custom-rules.md"
    explicit.write_text(_MINIMAL_RULESET, encoding="utf-8")

    assert find_ruleset(ruleset_path=str(explicit)) == str(explicit)


def test_find_ruleset_explicit_missing_path_returns_none(tmp_path, monkeypatch):
    """Step 1: an explicit path that does not exist yields ``None`` — no fallthrough."""
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    # A workspace ruleset exists, but the explicit missing path must not fall
    # through to it.
    _write_ruleset(tmp_path)
    missing = tmp_path / "nope.md"

    assert find_ruleset(
        ruleset_path=str(missing), workspace_root=str(tmp_path)
    ) is None


def test_find_ruleset_env_var_is_authoritative(tmp_path, monkeypatch):
    """Step 2: a set ``RULE_ENGINE_RULESET`` pointing at an existing file wins."""
    env_ruleset = tmp_path / "env-rules.md"
    env_ruleset.write_text(_MINIMAL_RULESET, encoding="utf-8")
    monkeypatch.setenv(RULESET_ENV_VAR, str(env_ruleset))

    # Even with a workspace candidate present, the env var is terminal.
    _write_ruleset(tmp_path)
    assert find_ruleset(workspace_root=str(tmp_path)) == str(env_ruleset)


def test_find_ruleset_env_var_set_but_missing_returns_none(tmp_path, monkeypatch):
    """Step 2: a *set-but-missing* env var yields ``None`` with no fallthrough.

    A workspace ruleset exists and would otherwise resolve, but a set env var is
    authoritative and terminal, so ``find_ruleset`` must return ``None``.
    """
    _write_ruleset(tmp_path)  # a valid workspace candidate that must be ignored
    missing = tmp_path / "does-not-exist.md"
    monkeypatch.setenv(RULESET_ENV_VAR, str(missing))

    assert find_ruleset(workspace_root=str(tmp_path)) is None


def test_find_ruleset_blank_env_var_is_treated_as_unset(tmp_path, monkeypatch):
    """A blank/whitespace env var is ignored, so the workspace candidate resolves."""
    workspace_ruleset = _write_ruleset(tmp_path)
    monkeypatch.setenv(RULESET_ENV_VAR, "   ")

    assert find_ruleset(workspace_root=str(tmp_path)) == str(workspace_ruleset)


def test_find_ruleset_workspace_root_candidate(tmp_path, monkeypatch):
    """Step 3: with no explicit/env path, the ``workspace_root`` candidate resolves."""
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    workspace_ruleset = _write_ruleset(tmp_path)

    assert find_ruleset(workspace_root=str(tmp_path)) == str(workspace_ruleset)


def test_find_ruleset_falls_back_to_cwd(tmp_path, monkeypatch):
    """Step 3: with no ``workspace_root``, the current working directory is used."""
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    workspace_ruleset = _write_ruleset(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert find_ruleset() == str(workspace_ruleset)


def test_find_ruleset_falls_back_to_repo_checkout(tmp_path, monkeypatch):
    """Step 4: when the workspace has none, the repo checkout (``parents[2]``) resolves.

    ``workspace_root`` points at an empty directory with no ``.kiro`` tree, so
    the workspace candidate misses; the repository checkout that ships this
    package still carries ``diagram-lint.md``.
    """
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()

    resolved = find_ruleset(workspace_root=str(empty))
    assert resolved is not None
    assert Path(resolved) == _REAL_RULESET


# ---------------------------------------------------------------------------
# ruleset_available
# ---------------------------------------------------------------------------


def test_ruleset_available_true_for_non_empty_file(tmp_path, monkeypatch):
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    _write_ruleset(tmp_path)
    assert ruleset_available(workspace_root=str(tmp_path)) is True


def test_ruleset_available_false_for_empty_file(tmp_path, monkeypatch):
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    _write_ruleset(tmp_path, body="   \n\n")
    assert ruleset_available(workspace_root=str(tmp_path)) is False


def test_ruleset_available_false_for_set_but_missing_env(tmp_path, monkeypatch):
    _write_ruleset(tmp_path)
    monkeypatch.setenv(RULESET_ENV_VAR, str(tmp_path / "missing.md"))
    assert ruleset_available(workspace_root=str(tmp_path)) is False


# ---------------------------------------------------------------------------
# require_ruleset — fail closed (Requirement 10.2)
# ---------------------------------------------------------------------------


def test_require_ruleset_returns_path_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    workspace_ruleset = _write_ruleset(tmp_path)
    assert require_ruleset(workspace_root=str(tmp_path)) == str(workspace_ruleset)


def test_require_ruleset_raises_for_set_but_missing_env(tmp_path, monkeypatch):
    """A set-but-missing env var makes ``require_ruleset`` fail closed — no fallthrough.

    Even with a valid workspace candidate present, the terminal env var means the
    ruleset is unavailable, and the error names the offending env path.
    """
    _write_ruleset(tmp_path)  # a candidate that must not rescue the run
    missing = tmp_path / "gone.md"
    monkeypatch.setenv(RULESET_ENV_VAR, str(missing))

    with pytest.raises(RulesetUnavailableError) as excinfo:
        require_ruleset(workspace_root=str(tmp_path))

    err = excinfo.value
    assert err.code == RULESET_UNAVAILABLE_ERROR
    assert err.path == str(missing)
    assert RULESET_ENV_VAR in str(err)


def test_require_ruleset_raises_for_empty_file(tmp_path, monkeypatch):
    monkeypatch.delenv(RULESET_ENV_VAR, raising=False)
    empty_ruleset = _write_ruleset(tmp_path, body="\n\n")

    with pytest.raises(RulesetUnavailableError) as excinfo:
        require_ruleset(workspace_root=str(tmp_path))

    assert excinfo.value.path == str(empty_ruleset)
    assert "empty" in str(excinfo.value)


# ---------------------------------------------------------------------------
# parse_rule_table — the current diagram-lint.md (Requirement 10.1)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_rules() -> dict:
    text = _REAL_RULESET.read_text(encoding="utf-8")
    return parse_rule_table(text)


def test_parse_rule_table_parses_the_real_ruleset(real_rules):
    """A representative spread of known rules parse from the shipped document."""
    for name in ("node-count", "edge-label", "node-quote", "frontmatter",
                 "secret-safety", "edge-direction", "container-padding"):
        assert name in real_rules, f"{name!r} missing from parsed rule table"


def test_parse_rule_table_node_count_default_severity(real_rules):
    """``node-count`` (cell ``ERROR/WARNING``) records ERROR as its default."""
    row = real_rules["node-count"]
    assert isinstance(row, RuleRow)
    assert row.default == "ERROR"
    # Both tokens are captured, in document order.
    assert set(row.severities) == {"ERROR", "WARNING"}


def test_parse_rule_table_edge_direction_landscape_escalation(real_rules):
    """``edge-direction`` is WARNING by default and escalates to ERROR on landscape.

    The default comes from the ``## Lint Rules`` cell (``WARNING/ERROR``) and the
    ``landscape`` value from the ``## Diagram Class`` escalation table.
    """
    row = real_rules["edge-direction"]
    assert row.default == "WARNING"
    assert row.landscape == "ERROR"


def test_parse_rule_table_frontmatter_is_critical(real_rules):
    """``frontmatter`` is a single-severity CRITICAL rule with no landscape override."""
    row = real_rules["frontmatter"]
    assert row.default == "CRITICAL"
    assert row.landscape is None
    assert row.severities == ("CRITICAL",)


def test_parse_rule_table_container_padding_escalates_on_landscape(real_rules):
    """``container-padding`` warns on flow and errors on landscape."""
    row = real_rules["container-padding"]
    assert row.default == "WARNING"
    assert row.landscape == "ERROR"


# ---------------------------------------------------------------------------
# parse_rule_table — malformed / empty input (Requirement 10.1)
# ---------------------------------------------------------------------------


def test_parse_rule_table_empty_string_yields_no_rules():
    assert parse_rule_table("") == {}


def test_parse_rule_table_no_lint_rules_section_yields_no_rules():
    text = "# A document\n\nSome prose with no rule tables at all.\n"
    assert parse_rule_table(text) == {}


def test_parse_rule_table_malformed_table_skips_non_rule_rows():
    """A garbled table (short rows, non-code first cells) yields no RuleRows.

    The header/delimiter are present so the section is recognised, but no data
    row carries an inline-code rule name, so nothing is collected.
    """
    text = (
        "## Lint Rules\n"
        "\n"
        "| Rule | Condition | Severity | Source |\n"
        "| --- | --- | --- | --- |\n"
        "| not-code | some condition | ERROR | ref |\n"  # first cell not `code`
        "| broken row without pipes\n"                      # not a table row
        "| `too-few` | only two cells |\n"                  # < 3 cells
    )
    assert parse_rule_table(text) == {}


def test_parse_rule_table_well_formed_minimal_table():
    """A minimal but well-formed table parses its one rule with both severities."""
    text = (
        "## Lint Rules\n"
        "\n"
        "| Rule | Condition | Severity | Source |\n"
        "| --- | --- | --- | --- |\n"
        "| `sample-rule` | some condition holds | WARNING/ERROR | ref |\n"
        "\n"
        "## Diagram Class\n"
        "\n"
        "| Rule | flow (default) | landscape |\n"
        "| --- | --- | --- |\n"
        "| `sample-rule` | WARNING | ERROR |\n"
    )
    rules = parse_rule_table(text)
    assert set(rules) == {"sample-rule"}
    row = rules["sample-rule"]
    assert row.default == "WARNING"
    assert row.landscape == "ERROR"
    assert row.severities == ("WARNING", "ERROR")
