"""Unit tests for the Linter's rule severities and publication eligibility
(task 6.3).

Exercises ``src/rule_engine/linter.py`` (``lint``, ``lint_with_ruleset``,
``ruleset_available``, ``find_ruleset``, ``Artifact``, ``Edge``, ``Severity``,
the ``RULE_*`` name constants, and ``RULESET_UNAVAILABLE_ERROR``).

Coverage:

- Requirement 7.1 / 7.4-7.13: each of the ten lint rules, given an artifact that
  triggers exactly that rule, produces a finding carrying the rule name and its
  authoritative severity (node-count ERROR, edge-label WARNING, node-quote
  ERROR, legend-present ERROR, companion-doc ERROR, frontmatter CRITICAL,
  icon-resolved ERROR, secret-safety CRITICAL, title-versioned WARNING,
  mermaid-type WARNING).
- Requirement 7.2: a clean artifact yields zero findings and is eligible for
  publication.
- Requirement 7.2 / 7.3: eligibility is True for a WARNING-only artifact and
  flips to False as soon as an ERROR or CRITICAL finding is present.
- Requirement 7.14: when the authoritative ruleset is missing or unreadable,
  ``lint_with_ruleset`` reports every artifact as blocked from publication and
  returns the ``ruleset-unavailable`` error.

Tests import the rule engine directly and construct ``Artifact`` inputs; they do
not touch the on-disk ruleset except in the ruleset-unavailable tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rule_engine.linter import (
    Artifact,
    Edge,
    RULESET_UNAVAILABLE_ERROR,
    RULE_COMPANION_DOC,
    RULE_EDGE_LABEL,
    RULE_FRONTMATTER,
    RULE_ICON_RESOLVED,
    RULE_LEGEND_PRESENT,
    RULE_MERMAID_TYPE,
    RULE_NODE_COUNT,
    RULE_NODE_QUOTE,
    RULE_SECRET_SAFETY,
    RULE_TITLE_VERSIONED,
    Severity,
    find_ruleset,
    lint,
    lint_with_ruleset,
    ruleset_available,
)

# A complete, valid twelve-key frontmatter mapping (Requirement 8 AC1). Used to
# build clean document artifacts and as the base for the "one missing key"
# frontmatter test.
VALID_FRONTMATTER = {
    "id": "doc-1",
    "title": "A Document",
    "kb_namespace": "arch",
    "section": "diagrams",
    "category": "reference",
    "status": "draft",
    "updated": "2025-01-15",
    "owner": "platform-team",
    "author": "kiro",
    "next_review_date": "2025-07-15",
    "tags": ["cloud"],
    # related_docs may be empty (kb-frontmatter: 0-20 entries); since 1.6.1 the
    # linter accepts ``[]`` — see test_related_docs_may_be_an_empty_list below.
    "related_docs": ["doc-0"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rules(result):
    """Return the set of rule names present in a lint result's findings."""
    return {f["rule"] for f in result["findings"]}


def _severity_of(result, rule_name):
    """Return the severity string reported for ``rule_name`` in ``result``."""
    for f in result["findings"]:
        if f["rule"] == rule_name:
            return f["severity"]
    raise AssertionError(f"rule {rule_name!r} not found in {result['findings']!r}")


def _clean_diagram(**overrides) -> Artifact:
    """A diagram artifact that triggers no lint rules."""
    base = dict(
        kind="diagram",
        node_names=["Api", "Worker", "Db"],
        edges=[Edge(source="Api", target="Db", label="reads")],
        has_legend=True,
        icons=[{"resolved": True, "style": "shape=mxgraph.aws4.resourceIcon"}],
        title_cell="aws payments — 123456789012 / us-east-1 | 2025-01-15 | v1",
        source_format="plantuml",
        diagram_type="c4",
        is_drawio=True,
        has_companion_doc=True,
    )
    base.update(overrides)
    return Artifact(**base)


# ---------------------------------------------------------------------------
# Per-rule severity tests (Requirement 7 AC1, AC4–AC13)
# ---------------------------------------------------------------------------


def test_node_count_error():
    """node-count fires as ERROR when a diagram exceeds 12 nodes (AC4)."""
    art = _clean_diagram(node_names=[f"n{i}" for i in range(13)])
    result = lint(art)
    assert RULE_NODE_COUNT in _rules(result)
    assert _severity_of(result, RULE_NODE_COUNT) == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_edge_label_warning():
    """edge-label fires as WARNING when an edge has an empty label (AC5)."""
    art = _clean_diagram(edges=[Edge(source="Api", target="Db", label="")])
    result = lint(art)
    assert RULE_EDGE_LABEL in _rules(result)
    assert _severity_of(result, RULE_EDGE_LABEL) == Severity.WARNING.value


def test_node_quote_error():
    """node-quote fires as ERROR for an unquoted special-character name (AC6)."""
    art = _clean_diagram(node_names=["Api Gateway", "Db"])
    result = lint(art)
    assert RULE_NODE_QUOTE in _rules(result)
    assert _severity_of(result, RULE_NODE_QUOTE) == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_legend_present_error():
    """legend-present fires as ERROR when a diagram has no Legend (AC7)."""
    art = _clean_diagram(has_legend=False)
    result = lint(art)
    assert RULE_LEGEND_PRESENT in _rules(result)
    assert _severity_of(result, RULE_LEGEND_PRESENT) == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_companion_doc_error():
    """companion-doc fires as ERROR when a .drawio has no companion (AC8)."""
    art = _clean_diagram(is_drawio=True, has_companion_doc=False)
    result = lint(art)
    assert RULE_COMPANION_DOC in _rules(result)
    assert _severity_of(result, RULE_COMPANION_DOC) == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_frontmatter_critical():
    """frontmatter fires as CRITICAL when a required key is missing (AC9)."""
    fm = dict(VALID_FRONTMATTER)
    del fm["owner"]
    art = Artifact(kind="document", is_markdown=True, frontmatter=fm)
    result = lint(art)
    assert RULE_FRONTMATTER in _rules(result)
    assert _severity_of(result, RULE_FRONTMATTER) == Severity.CRITICAL.value
    assert result["eligible_for_publication"] is False


def test_icon_resolved_error():
    """icon-resolved fires as ERROR for an unresolved placeholder icon (AC10)."""
    art = _clean_diagram(icons=[{"placeholder": True}])
    result = lint(art)
    assert RULE_ICON_RESOLVED in _rules(result)
    assert _severity_of(result, RULE_ICON_RESOLVED) == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_secret_safety_critical():
    """secret-safety fires as CRITICAL when a snapshot holds a secret (AC11)."""
    art = Artifact(kind="snapshot", is_snapshot_file=True, contains_secret=True)
    result = lint(art)
    assert RULE_SECRET_SAFETY in _rules(result)
    assert _severity_of(result, RULE_SECRET_SAFETY) == Severity.CRITICAL.value
    assert result["eligible_for_publication"] is False


def test_title_versioned_warning():
    """title-versioned fires as WARNING when the title lacks version/date (AC12)."""
    art = _clean_diagram(title_cell="aws payments — acct / region")
    result = lint(art)
    assert RULE_TITLE_VERSIONED in _rules(result)
    assert _severity_of(result, RULE_TITLE_VERSIONED) == Severity.WARNING.value


def test_mermaid_type_warning():
    """mermaid-type fires as WARNING when Mermaid is used for a bad type (AC13)."""
    art = _clean_diagram(source_format="mermaid", diagram_type="c4")
    result = lint(art)
    assert RULE_MERMAID_TYPE in _rules(result)
    assert _severity_of(result, RULE_MERMAID_TYPE) == Severity.WARNING.value


# ---------------------------------------------------------------------------
# Clean artifact & eligibility behavior (Requirement 7 AC2, AC3)
# ---------------------------------------------------------------------------


def test_clean_diagram_yields_no_findings_and_is_eligible():
    """A clean diagram produces zero findings and is eligible (AC2)."""
    result = lint(_clean_diagram())
    assert result["findings"] == []
    assert result["eligible_for_publication"] is True


def test_clean_document_is_eligible():
    """A document with complete frontmatter produces no frontmatter finding."""
    art = Artifact(kind="document", is_markdown=True, frontmatter=VALID_FRONTMATTER)
    result = lint(art)
    assert RULE_FRONTMATTER not in _rules(result)
    assert result["eligible_for_publication"] is True


def test_related_docs_may_be_an_empty_list():
    """kb-frontmatter bounds related_docs at 0-20 entries ("empty list allowed").

    Before 1.6.1 the generic empty-collection check reported ``related_docs: []``
    as a missing key — a CRITICAL that blocked a document for having no related
    documents."""
    fm = dict(VALID_FRONTMATTER, related_docs=[])
    result = lint(Artifact(kind="document", is_markdown=True, frontmatter=fm))
    assert RULE_FRONTMATTER not in _rules(result)
    assert result["eligible_for_publication"] is True


def test_related_docs_parsed_from_real_markdown_may_be_empty(tmp_path):
    """The same through the CLI parser: ``related_docs: []`` in a real file."""
    from rule_engine.cli import parse_artifact

    doc = tmp_path / "kb-doc.md"
    doc.write_text(
        "---\n"
        "id: doc-1\ntitle: A Document\nkb_namespace: arch\nsection: diagrams\n"
        "category: reference\nstatus: draft\nupdated: 2025-01-15\n"
        "owner: platform-team\nauthor: kiro\nnext_review_date: 2025-07-15\n"
        "tags:\n  - cloud\nrelated_docs: []\n"
        "---\n\n# A Document\n",
        encoding="utf-8",
    )
    assert RULE_FRONTMATTER not in _rules(lint(parse_artifact(str(doc))))


@pytest.mark.parametrize(
    "overrides",
    [
        {"tags": []},  # tags still needs 1-20 entries
        {"related_docs": None},  # present but valueless is still missing
        {"related_docs": ""},
        {"related_docs": {}},
    ],
)
def test_empty_values_other_than_related_docs_list_are_still_missing(overrides):
    fm = dict(VALID_FRONTMATTER, **overrides)
    result = lint(Artifact(kind="document", is_markdown=True, frontmatter=fm))
    assert _severity_of(result, RULE_FRONTMATTER) == Severity.CRITICAL.value


def test_warning_only_stays_eligible():
    """WARNING-only findings never block publication (AC2)."""
    art = _clean_diagram(edges=[Edge(source="Api", target="Db", label="")])
    result = lint(art)
    assert _rules(result) == {RULE_EDGE_LABEL}
    assert _severity_of(result, RULE_EDGE_LABEL) == Severity.WARNING.value
    assert result["eligible_for_publication"] is True


def test_eligibility_flips_false_on_first_error():
    """Adding an ERROR finding to a WARNING-only artifact flips eligibility (AC3)."""
    warn_only = _clean_diagram(title_cell="aws payments — acct / region")
    assert lint(warn_only)["eligible_for_publication"] is True

    # Same artifact plus a legend-present ERROR -> blocked.
    with_error = _clean_diagram(
        title_cell="aws payments — acct / region", has_legend=False
    )
    result = lint(with_error)
    assert Severity.ERROR.value in {f["severity"] for f in result["findings"]}
    assert result["eligible_for_publication"] is False


def test_eligibility_false_on_critical():
    """A CRITICAL finding blocks publication (AC3)."""
    art = Artifact(kind="snapshot", is_snapshot_file=True, contains_secret=True)
    result = lint(art)
    assert Severity.CRITICAL.value in {f["severity"] for f in result["findings"]}
    assert result["eligible_for_publication"] is False


# ---------------------------------------------------------------------------
# Ruleset-unavailable behavior (Requirement 7 AC14)
# ---------------------------------------------------------------------------


def test_missing_ruleset_blocks_every_artifact(tmp_path):
    """A bogus workspace_root with no ruleset blocks every artifact (AC14)."""
    bogus_root = tmp_path / "no-such-workspace"
    # Sanity: the ruleset genuinely cannot be located under the bogus root.
    assert find_ruleset(workspace_root=str(bogus_root)) is None
    assert ruleset_available(workspace_root=str(bogus_root)) is False

    artifacts = [
        _clean_diagram(),  # otherwise-clean, still blocked
        _clean_diagram(has_legend=False),  # already has an ERROR
        Artifact(kind="document", is_markdown=True, frontmatter=VALID_FRONTMATTER),
    ]
    for art in artifacts:
        result = lint_with_ruleset(art, workspace_root=str(bogus_root))
        assert result["eligible_for_publication"] is False
        assert result["error"] == RULESET_UNAVAILABLE_ERROR
        assert result["findings"] == []


def test_missing_ruleset_via_bogus_path_blocks(tmp_path):
    """A bogus explicit ruleset_path also yields ruleset-unavailable (AC14)."""
    bogus_path = tmp_path / "nonexistent" / "diagram-lint.md"
    assert find_ruleset(ruleset_path=str(bogus_path)) is None

    result = lint_with_ruleset(_clean_diagram(), ruleset_path=str(bogus_path))
    assert result["eligible_for_publication"] is False
    assert result["error"] == RULESET_UNAVAILABLE_ERROR


def test_empty_ruleset_file_is_unavailable(tmp_path):
    """An empty ruleset file is treated as unreadable/unavailable (AC14)."""
    ruleset = tmp_path / "diagram-lint.md"
    ruleset.write_text("   \n", encoding="utf-8")
    assert ruleset_available(ruleset_path=str(ruleset)) is False

    result = lint_with_ruleset(_clean_diagram(), ruleset_path=str(ruleset))
    assert result["eligible_for_publication"] is False
    assert result["error"] == RULESET_UNAVAILABLE_ERROR
