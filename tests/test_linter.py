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


def _valid_kb_document(*, related_docs: str = "[]") -> str:
    """Return a complete, valid KB document satisfying the whole contract.

    Twelve-key frontmatter, exactly one H1, and the four required sections each
    within the 100-200-word bound (and 300-2000 words overall), with no fenced
    code block (so no ``Anti-patterns`` section is required). Used by tests that
    exercise a *single* frontmatter aspect end-to-end through the CLI parser, so
    the structural checks (also part of the ``frontmatter`` rule since 1.7.0) do
    not fire spuriously.
    """
    # A 130-word filler paragraph keeps each section within 100-200 words.
    para = " ".join(f"word{i}" for i in range(130))
    frontmatter = (
        "---\n"
        "id: doc-1\n"
        "title: A Document\n"
        "kb_namespace: arch\n"
        "section: diagrams\n"
        "category: reference\n"
        "status: draft\n"
        "updated: 2025-01-15\n"
        "owner: platform-team\n"
        "author: kiro\n"
        "next_review_date: 2025-07-15\n"
        "tags:\n  - cloud\n"
        f"related_docs: {related_docs}\n"
        "---\n"
    )
    body = (
        "\n# A Document\n\n"
        f"## Overview\n\n{para}\n\n"
        f"## Main Content\n\n{para}\n\n"
        f"## Troubleshooting\n\n{para}\n\n"
        f"## See Also\n\n{para}\n"
    )
    return frontmatter + body


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
    """node-quote fires as ERROR for an unquoted special-character *identifier*
    in a PlantUML/Mermaid source (AC6). draw.io labels are exempt (see the
    next test), so the ERROR case is a non-draw.io source."""
    art = _clean_diagram(node_names=["Api Gateway", "Db"],
                         source_format="plantuml", is_drawio=False)
    result = lint(art)
    assert RULE_NODE_QUOTE in _rules(result)
    assert _severity_of(result, RULE_NODE_QUOTE) == Severity.ERROR.value
    assert result["eligible_for_publication"] is False

def test_node_quote_exempts_drawio_display_labels():
    """v1.9.3: a draw.io cell ``value`` is a display label, not an identifier,
    so a spaced label like "IAM user sep" is NOT a node-quote defect — quoting
    it would render literal quotes on the canvas."""
    art = _clean_diagram(node_names=["IAM user sep", "AWS Organizations"],
                         source_format="drawio", is_drawio=True)
    result = lint(art)
    assert RULE_NODE_QUOTE not in _rules(result)


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
    """The same through the CLI parser: ``related_docs: []`` in a real file.

    As of 1.7.0 (task 10.3) the ``frontmatter`` rule validates the *whole*
    ``kb-frontmatter.md`` contract, structure included, for a KB document. So the
    document is authored as a complete, valid KB doc; ``related_docs: []`` must
    not, on its own, produce any ``frontmatter`` finding.
    """
    from rule_engine.cli import parse_artifact

    doc = tmp_path / "kb-doc.md"
    doc.write_text(_valid_kb_document(related_docs="[]"), encoding="utf-8")
    result = lint(parse_artifact(str(doc)))
    assert RULE_FRONTMATTER not in _rules(result), result["findings"]
    assert result["eligible_for_publication"] is True


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


def test_missing_ruleset_blocks_every_artifact(tmp_path, monkeypatch):
    """A set-but-missing ``RULE_ENGINE_RULESET`` blocks every artifact (AC14).

    honest-gates task 7.1 changed the ruleset resolution order so an unknown
    workspace root falls through to the repository checkout (and then the
    bundled payload), meaning a bogus ``workspace_root`` no longer yields
    unavailability. Genuine unavailability is forced the way an operator forces
    it: pin ``RULE_ENGINE_RULESET`` to a path that does not exist. That env var
    is authoritative and terminal — there is no fallthrough — so the ruleset is
    unavailable and the fail-closed AC14 behaviour applies.
    """
    from rule_engine.ruleset import RULESET_ENV_VAR

    missing_ruleset = tmp_path / "nonexistent" / "diagram-lint.md"
    monkeypatch.setenv(RULESET_ENV_VAR, str(missing_ruleset))
    # Sanity: the ruleset genuinely cannot be located.
    assert find_ruleset() is None
    assert ruleset_available() is False

    artifacts = [
        _clean_diagram(),  # otherwise-clean, still blocked
        _clean_diagram(has_legend=False),  # already has an ERROR
        Artifact(kind="document", is_markdown=True, frontmatter=VALID_FRONTMATTER),
    ]
    for art in artifacts:
        result = lint_with_ruleset(art)
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


# ---------------------------------------------------------------------------
# New rules and structural rewrites (honest-gates 1.7.0, task 10.2)
#   parse-error (R1.8/R1.9), edge-endpoint (R1.10), source-format (R10.3/D1);
#   legend-present / title-versioned / overlay-legend-coverage made structural
#   (R1.11, R1.12).
# ---------------------------------------------------------------------------

from rule_engine.linter import (  # noqa: E402
    RULE_EDGE_ENDPOINT,
    RULE_OVERLAY_LEGEND_COVERAGE,
    RULE_PARSE_ERROR,
    RULE_SOURCE_FORMAT,
    RULE_SEVERITIES,
)


def _finding(result, rule_name):
    """Return the finding dict for ``rule_name`` (or raise)."""
    for f in result["findings"]:
        if f["rule"] == rule_name:
            return f
    raise AssertionError(f"rule {rule_name!r} not found in {result['findings']!r}")


# --- parse-error ------------------------------------------------------------


def test_parse_error_severity_is_error():
    assert RULE_SEVERITIES[RULE_PARSE_ERROR] is Severity.ERROR


def test_parse_error_fires_on_parse_errors_and_blocks():
    """A non-empty ``parse_errors`` yields one ERROR naming the cause (R1.8)."""
    art = Artifact(kind="diagram", parse_errors=["dtd-or-entity-declaration"])
    result = lint(art)
    assert RULE_PARSE_ERROR in _rules(result)
    f = _finding(result, RULE_PARSE_ERROR)
    assert f["severity"] == Severity.ERROR.value
    assert f["offenders"] == ["dtd-or-entity-declaration"]
    assert result["eligible_for_publication"] is False


def test_parse_error_short_circuits_every_other_rule():
    """An unparsable artifact carries no model, so no other rule runs (R1.8).

    The Artifact below would otherwise trip node-count, node-quote, edge-label,
    legend-present and icon-resolved — but parse-error is the only finding.
    """
    art = Artifact(
        kind="diagram",
        parse_errors=["geometry:ValueError:bad", "not-text"],
        node_names=[f"n {i}" for i in range(20)],  # would trip node-count/quote
        edges=[Edge(source="a", target="b", label="")],  # would trip edge-label
        has_legend=False,  # would trip legend-present
        icons=[{"placeholder": True}],  # would trip icon-resolved
    )
    result = lint(art)
    assert _rules(result) == {RULE_PARSE_ERROR}
    # Both causes are reported as offenders on the single finding.
    assert _finding(result, RULE_PARSE_ERROR)["offenders"] == [
        "geometry:ValueError:bad",
        "not-text",
    ]


def test_no_parse_error_when_parse_errors_empty():
    """An empty ``parse_errors`` does not fire the rule."""
    assert RULE_PARSE_ERROR not in _rules(lint(_clean_diagram()))


# --- edge-endpoint ----------------------------------------------------------


def test_edge_endpoint_severity_is_warning_default():
    assert RULE_SEVERITIES[RULE_EDGE_ENDPOINT] is Severity.WARNING


def test_edge_endpoint_warning_on_flow():
    """A broken endpoint is a WARNING on a flow diagram (R1.10)."""
    art = _clean_diagram(edge_endpoints=["dangling-target:ghost"])
    result = lint(art)
    assert RULE_EDGE_ENDPOINT in _rules(result)
    f = _finding(result, RULE_EDGE_ENDPOINT)
    assert f["severity"] == Severity.WARNING.value
    assert f["offenders"] == ["dangling-target:ghost"]
    assert result["eligible_for_publication"] is True


def test_edge_endpoint_error_on_landscape():
    """The same broken endpoint is an ERROR on a landscape (R1.10)."""
    art = _clean_diagram(
        edge_endpoints=["missing-source"],
        diagram_class="landscape",
        summary_of="01-summary",
    )
    result = lint(art)
    f = _finding(result, RULE_EDGE_ENDPOINT)
    assert f["severity"] == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_edge_endpoint_reports_every_broken_endpoint():
    art = _clean_diagram(
        edge_endpoints=["missing-target", "dangling-source:x"],
    )
    f = _finding(lint(art), RULE_EDGE_ENDPOINT)
    assert f["offenders"] == ["missing-target", "dangling-source:x"]


def test_no_edge_endpoint_when_all_resolved():
    assert RULE_EDGE_ENDPOINT not in _rules(lint(_clean_diagram()))


# --- source-format ----------------------------------------------------------


def test_source_format_severity_is_error():
    assert RULE_SEVERITIES[RULE_SOURCE_FORMAT] is Severity.ERROR


def test_source_format_fires_on_a_puml_source_file():
    """A discovered ``.puml`` diagram (is_drawio False, raw text) blocks (D1)."""
    art = Artifact(
        kind="diagram",
        path="examples/x/diagram.puml",
        source_format="plantuml",
        is_drawio=False,
        text="@startuml\n@enduml\n",
    )
    result = lint(art)
    assert RULE_SOURCE_FORMAT in _rules(result)
    f = _finding(result, RULE_SOURCE_FORMAT)
    assert f["severity"] == Severity.ERROR.value
    assert f["offenders"] == ["plantuml"]
    assert result["eligible_for_publication"] is False


def test_source_format_fires_on_a_mmd_source_file():
    art = Artifact(
        kind="diagram",
        path="examples/x/diagram.mmd",
        source_format="mermaid",
        is_drawio=False,
        text="flowchart LR\n",
    )
    assert RULE_SOURCE_FORMAT in _rules(lint(art))


def test_source_format_does_not_fire_on_a_drawio_artifact():
    """A parsed .drawio artifact (source_format drawio) is fine."""
    art = _clean_diagram(source_format="drawio", is_drawio=True)
    assert RULE_SOURCE_FORMAT not in _rules(lint(art))


def test_source_format_does_not_fire_on_a_programmatic_artifact():
    """A hand-built diagram Artifact keeps the legacy plantuml default with no
    ``text``; source-format must not block it (else every test artifact fails)."""
    assert RULE_SOURCE_FORMAT not in _rules(lint(_clean_diagram()))


# --- structural legend-present ----------------------------------------------


def test_legend_present_reads_the_structural_flag():
    """``has_legend`` is set structurally by the CLI (a text cell whose first
    line is ``Legend``); the predicate simply reads it (R1.11)."""
    assert RULE_LEGEND_PRESENT in _rules(lint(_clean_diagram(has_legend=False)))
    assert RULE_LEGEND_PRESENT not in _rules(lint(_clean_diagram(has_legend=True)))


# --- structural title-versioned ---------------------------------------------


def test_title_versioned_fires_when_title_cell_is_none():
    """The CLI leaves ``title_cell`` None when no cell matches the full versioned
    title format; the rule then fires (R1.11)."""
    art = _clean_diagram(title_cell=None)
    result = lint(art)
    assert RULE_TITLE_VERSIONED in _rules(result)
    assert _severity_of(result, RULE_TITLE_VERSIONED) == Severity.WARNING.value


def test_title_versioned_clean_on_a_full_title():
    assert RULE_TITLE_VERSIONED not in _rules(lint(_clean_diagram()))


# --- structural overlay-legend-coverage -------------------------------------


def test_overlay_legend_coverage_fires_on_an_undocumented_marker():
    """An overlay marker not present as a whole token in the Legend lines is a
    WARNING, and the uncovered term is the offender (R1.12)."""
    art = _clean_diagram(
        overlay_markers=["standby", "observability-overlay"],
        legend_overlay_terms=["standby"],  # only standby is documented
    )
    result = lint(art)
    assert RULE_OVERLAY_LEGEND_COVERAGE in _rules(result)
    f = _finding(result, RULE_OVERLAY_LEGEND_COVERAGE)
    assert f["severity"] == Severity.WARNING.value
    assert f["offenders"] == ["observability-overlay"]


def test_overlay_legend_coverage_clean_when_every_marker_documented():
    art = _clean_diagram(
        overlay_markers=["standby"],
        legend_overlay_terms=["standby"],
    )
    assert RULE_OVERLAY_LEGEND_COVERAGE not in _rules(lint(art))


def test_overlay_legend_coverage_skips_a_diagram_with_no_markers():
    assert RULE_OVERLAY_LEGEND_COVERAGE not in _rules(lint(_clean_diagram()))
