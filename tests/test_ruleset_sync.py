"""Rule-table sync test (honest-gates task 21.2, Requirement 10.1).

The authoritative ``diagram-lint.md`` rule table (``## Lint Rules``) and the
class-escalation table (``## Diagram Class``) are prose, while the Linter's
severities live in code as the ``RULES`` registry of :class:`RuleSpec`, from
which :data:`RULE_SEVERITIES` (each rule's default / ``flow`` severity) and
:data:`CLASS_ESCALATIONS` (each rule's ``landscape`` override) are derived.

Requirement 10.1 requires a test that parses both tables and **fails on any
mismatch** with the code, so the document and the engine cannot drift apart
unnoticed. This module is that test. It locates the shipped ruleset through
:func:`rule_engine.ruleset.require_ruleset`, parses it with
:func:`rule_engine.ruleset.parse_rule_table`, and asserts:

1. the *set* of rules is identical in the document and in the code (no rule in
   the doc that code does not implement, and none in code missing from the doc);
2. every rule's **default** severity matches between the doc's ``## Lint Rules``
   "Severity" cell and :data:`RULE_SEVERITIES`;
3. every **landscape escalation** matches between the doc's ``## Diagram Class``
   table and :data:`CLASS_ESCALATIONS`;
4. the two documented escalations that the code models *without* a
   ``RuleSpec.landscape`` — ``node-count`` (per-hit severity) and
   ``edge-routing`` (``reason_escalations`` for an icon crossing) — are still
   reflected in the doc's Diagram Class table.

If any of these diverge, the test fails, which is its entire purpose.
"""

from __future__ import annotations

import pytest

from rule_engine.linter import (
    CLASS_ESCALATIONS,
    RULE_SEVERITIES,
    RULE_EDGE_ROUTING,
    RULE_NODE_COUNT,
    RULE_SPECS,
    Severity,
)
from rule_engine.ruleset import parse_rule_table, require_ruleset


# ``node-count`` and ``edge-routing`` carry a landscape/class-dependent severity
# that the code expresses NOT as ``RuleSpec.landscape`` but as a per-hit
# severity (``node-count``: WARNING > 30, ERROR > 50) and as
# ``reason_escalations`` (``edge-routing``: an icon crossing is ERROR on either
# class). They therefore appear in the doc's ``## Diagram Class`` table with a
# landscape severity that differs from their flow default, yet are absent from
# ``CLASS_ESCALATIONS``. They are checked explicitly below instead.
_ESCALATION_MODELLED_ELSEWHERE = frozenset({RULE_NODE_COUNT, RULE_EDGE_ROUTING})


@pytest.fixture(scope="module")
def doc_rules() -> dict:
    """The parsed rule + class-escalation tables from the shipped diagram-lint.md."""
    path = require_ruleset()
    with open(path, "r", encoding="utf-8") as fh:
        return parse_rule_table(fh.read())


# ---------------------------------------------------------------------------
# 1. The rule *set* is identical in the document and in the code.
# ---------------------------------------------------------------------------


def test_rule_sets_match(doc_rules):
    """Every rule in the doc is in the code and vice versa — no orphans either way."""
    doc_names = set(doc_rules)
    code_names = set(RULE_SEVERITIES)

    missing_from_doc = code_names - doc_names
    missing_from_code = doc_names - code_names

    assert not missing_from_doc, (
        "rules in RULE_SEVERITIES but absent from diagram-lint.md "
        f"## Lint Rules table: {sorted(missing_from_doc)}"
    )
    assert not missing_from_code, (
        "rules in the diagram-lint.md ## Lint Rules table but absent from "
        f"RULE_SEVERITIES: {sorted(missing_from_code)}"
    )


# ---------------------------------------------------------------------------
# 2. Default (flow) severities match.
# ---------------------------------------------------------------------------


def test_default_severities_match(doc_rules):
    """The doc's default severity for every rule equals RULE_SEVERITIES."""
    mismatches = []
    for name, code_sev in sorted(RULE_SEVERITIES.items()):
        row = doc_rules.get(name)
        if row is None:
            # Covered by test_rule_sets_match; skip here to keep this focused.
            continue
        doc_default = row.default
        if doc_default != code_sev.value:
            mismatches.append(
                f"{name}: doc default={doc_default!r} code={code_sev.value!r}"
            )
    assert not mismatches, "default-severity mismatches:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# 3. Landscape escalations match.
# ---------------------------------------------------------------------------


def test_landscape_escalations_match(doc_rules):
    """CLASS_ESCALATIONS equals the doc's ## Diagram Class landscape overrides.

    The comparison is over *real* escalations: a rule whose Diagram Class
    landscape severity differs from its flow default. ``node-count`` and
    ``edge-routing`` are the two documented exceptions the code models without a
    ``RuleSpec.landscape`` — they are asserted separately below.
    """
    # The doc's escalation set: rules whose landscape severity differs from the
    # rule's default (flow) severity, minus the two modelled-elsewhere rules.
    doc_escalations = {}
    for name, row in doc_rules.items():
        if name in _ESCALATION_MODELLED_ELSEWHERE:
            continue
        if row.landscape is None:
            continue
        if row.landscape != row.default:
            doc_escalations[name] = row.landscape

    code_escalations = {
        name: sev.value for name, sev in CLASS_ESCALATIONS.items()
    }

    assert code_escalations == doc_escalations, (
        "landscape escalation mismatch between diagram-lint.md ## Diagram Class "
        f"and CLASS_ESCALATIONS.\n  doc:  {sorted(doc_escalations.items())}\n"
        f"  code: {sorted(code_escalations.items())}"
    )


# ---------------------------------------------------------------------------
# 4. The two escalations modelled outside RuleSpec.landscape are still in the doc.
# ---------------------------------------------------------------------------


def test_node_count_class_severity_reflected_in_doc(doc_rules):
    """``node-count`` is per-hit (flow ERROR; landscape WARNING/ERROR by count).

    It carries no ``RuleSpec.landscape`` (its landscape severity depends on the
    node count, not the class alone), so it must NOT be in CLASS_ESCALATIONS,
    but the Diagram Class table must still document a class-dependent severity.
    """
    assert RULE_NODE_COUNT not in CLASS_ESCALATIONS
    row = doc_rules[RULE_NODE_COUNT]
    # flow default is ERROR; the landscape cell records a differing (WARNING)
    # first token — i.e. the table documents a class-dependent severity.
    assert row.default == Severity.ERROR.value
    assert row.landscape is not None
    assert row.landscape != row.default


def test_edge_routing_icon_crossing_escalation_reflected_in_doc(doc_rules):
    """``edge-routing`` escalates an icon crossing to ERROR via reason_escalations.

    The escalation is class-independent (ERROR on flow *and* landscape for a
    ``*-through-*`` / ``pierces-target-*`` reason), so it is modelled as
    ``reason_escalations`` rather than ``CLASS_ESCALATIONS``. Assert both the
    code shape and that the doc's Diagram Class row documents the ERROR crossing.
    """
    assert RULE_EDGE_ROUTING not in CLASS_ESCALATIONS

    spec = RULE_SPECS[RULE_EDGE_ROUTING]
    assert spec.default == Severity.WARNING
    # The icon-crossing markers both escalate to ERROR.
    assert spec.reason_escalations, "edge-routing must carry reason_escalations"
    assert set(spec.reason_escalations.values()) == {Severity.ERROR}

    # The doc's Diagram Class row for the icon-crossing case shows ERROR on both
    # columns; parse_rule_table keys it under the base rule name.
    row = doc_rules[RULE_EDGE_ROUTING]
    # The ## Lint Rules "Severity" cell is WARNING/ERROR (default WARNING, with
    # the ERROR crossing escalation captured among the tokens).
    assert row.default == Severity.WARNING.value
    assert Severity.ERROR.value in row.severities
