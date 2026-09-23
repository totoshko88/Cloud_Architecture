"""Tests for the v1.3.0 diagram-class rules (flow vs landscape).

These tests pin the class-branching contract introduced in v1.3.0:

- ``node-count`` is class-aware: ``flow`` keeps the 12-node ERROR cap unchanged;
  ``landscape`` relaxes to WARNING > 30 and ERROR > 50.
- ``orphan-landscape`` (ERROR) requires every ``landscape`` diagram to declare a
  ``summary_of`` cross-link to its flow summary.
- ``container-padding`` is raised from WARNING to ERROR for ``landscape``.
- ``overlay-legend-coverage`` (WARNING) fires when a declared overlay marker is
  not covered by the Legend.
- Every legacy ``flow`` behaviour is unchanged (regression guard).

The tests construct synthetic ``Artifact`` inputs directly (no file parsing), so
they exercise the rule engine in isolation from the CLI parser.
"""

from __future__ import annotations

from rule_engine.linter import (
    Artifact,
    LANDSCAPE_NODE_ERROR,
    LANDSCAPE_NODE_WARN,
    Severity,
    lint,
)


def _sev(result, rule):
    """Return the severity string reported for ``rule``, or None if absent."""
    return next(
        (f["severity"] for f in result["findings"] if f["rule"] == rule), None
    )


def _nodes(n):
    return [f"n{i}" for i in range(n)]


# ---------------------------------------------------------------------------
# node-count — flow (legacy, unchanged)
# ---------------------------------------------------------------------------


def test_flow_at_cap_is_clean():
    result = lint(Artifact(kind="diagram", node_names=_nodes(12)))
    assert _sev(result, "node-count") is None
    assert result["eligible_for_publication"] is True


def test_flow_over_cap_is_error():
    result = lint(Artifact(kind="diagram", node_names=_nodes(13)))
    assert _sev(result, "node-count") == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_flow_is_the_default_class():
    """An artifact with no diagram_class behaves as flow (12-node ERROR cap)."""
    result = lint(Artifact(kind="diagram", node_names=_nodes(20)))
    assert _sev(result, "node-count") == Severity.ERROR.value


# ---------------------------------------------------------------------------
# node-count — landscape (relaxed 30 / 50)
# ---------------------------------------------------------------------------


def test_landscape_under_warn_threshold_is_clean():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(LANDSCAPE_NODE_WARN),  # exactly 30, not over
            summary_of="01-topic-summary",
        )
    )
    assert _sev(result, "node-count") is None
    assert result["eligible_for_publication"] is True


def test_landscape_over_warn_is_warning_not_blocking():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(LANDSCAPE_NODE_WARN + 5),  # 35
            summary_of="01-topic-summary",
        )
    )
    assert _sev(result, "node-count") == Severity.WARNING.value
    assert result["eligible_for_publication"] is True


def test_landscape_over_error_threshold_blocks():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(LANDSCAPE_NODE_ERROR + 1),  # 51
            summary_of="01-topic-summary",
        )
    )
    assert _sev(result, "node-count") == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_landscape_at_error_threshold_is_warning():
    """Exactly 50 nodes is the boundary: WARNING (over 30), not ERROR (over 50)."""
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(LANDSCAPE_NODE_ERROR),  # 50
            summary_of="01-topic-summary",
        )
    )
    assert _sev(result, "node-count") == Severity.WARNING.value


# ---------------------------------------------------------------------------
# orphan-landscape — the summary+detailed pair contract
# ---------------------------------------------------------------------------


def test_landscape_without_summary_link_is_orphan_error():
    result = lint(
        Artifact(kind="diagram", diagram_class="landscape", node_names=_nodes(20))
    )
    assert _sev(result, "orphan-landscape") == Severity.ERROR.value
    assert result["eligible_for_publication"] is False


def test_landscape_with_summary_link_is_not_orphan():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(20),
            summary_of="01-topic-summary",
        )
    )
    assert _sev(result, "orphan-landscape") is None


def test_flow_is_never_orphan():
    """orphan-landscape only applies to landscape diagrams."""
    result = lint(Artifact(kind="diagram", node_names=_nodes(5)))
    assert _sev(result, "orphan-landscape") is None


# ---------------------------------------------------------------------------
# overlay-legend-coverage
# ---------------------------------------------------------------------------


def test_uncovered_overlay_marker_is_warning():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(5),
            summary_of="01-topic-summary",
            overlay_markers=["spec-required-not-deployed"],
            legend_overlay_terms=[],
        )
    )
    assert _sev(result, "overlay-legend-coverage") == Severity.WARNING.value
    # A WARNING never blocks publication on its own.
    assert result["eligible_for_publication"] is True


def test_covered_overlay_marker_is_clean():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(5),
            summary_of="01-topic-summary",
            overlay_markers=["spec-required-not-deployed"],
            legend_overlay_terms=["spec-required-not-deployed"],
        )
    )
    assert _sev(result, "overlay-legend-coverage") is None


def test_no_overlay_markers_no_finding():
    result = lint(
        Artifact(
            kind="diagram",
            diagram_class="landscape",
            node_names=_nodes(5),
            summary_of="01-topic-summary",
        )
    )
    assert _sev(result, "overlay-legend-coverage") is None


# ---------------------------------------------------------------------------
# Regression: legacy flow rules unchanged under the new model
# ---------------------------------------------------------------------------


def test_legacy_node_quote_still_error():
    result = lint(Artifact(kind="diagram", node_names=["a b"]))
    assert _sev(result, "node-quote") == Severity.ERROR.value


def test_legacy_mapping_input_still_supported():
    result = lint({"kind": "diagram", "node_names": ["a", "b"]})
    assert result["eligible_for_publication"] is True
