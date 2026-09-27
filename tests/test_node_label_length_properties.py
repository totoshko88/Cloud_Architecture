"""Property + unit tests for the ``node-label-length`` lint rule (1.10.0, Part B).

Requirement 2 (provider-diagram-conventions): a node label stays short — the
service name — and explanatory prose belongs in a callout (``overlay=callout``),
not crammed into the icon label (AWS ``diagram-as-code``: "do not embed
explanatory text into images; use short labels; use callouts"). A service-node
label trips the rule when it exceeds the word cap (> 4 words) OR the character
cap (> 40 characters).

Property 2 (design.md): the label cap is source-scoped — ``node-label-length``
fires only on service-node labels; Legend, Flow, title, and callout text cells
never trip it, regardless of length (the CLI populates ``node_names`` from
service icon cells only; text cells and the title cell are excluded).

**Validates: Requirements 2.1, 2.2**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from rule_engine.linter import (
    LABEL_CHAR_CAP,
    LABEL_WORD_CAP,
    RULE_NODE_LABEL_LENGTH,
    RULE_SEVERITIES,
    Artifact,
    Severity,
    lint,
)


def _flagged(node_names) -> bool:
    a = Artifact(kind="diagram", node_names=list(node_names))
    return RULE_NODE_LABEL_LENGTH in {f["rule"] for f in lint(a)["findings"]}


# --------------------------------------------------------------------------- #
# Unit cases — the concrete corners of the rule.
# --------------------------------------------------------------------------- #


def test_short_label_is_clean():
    """A short service name (few words, few chars) is never flagged."""
    assert not _flagged(["S3", "Lambda", "RDS Primary", "EKS cluster east"])


def test_five_words_is_flagged():
    """Exactly one word over the word cap trips it (5 > 4)."""
    assert _flagged(["one two three four five"])


def test_four_words_is_clean():
    """The word cap is exclusive: exactly 4 words is fine."""
    assert not _flagged(["one two three four"])


def test_over_char_cap_is_flagged():
    """A single long word (no spaces) still trips the character cap."""
    long_name = "x" * (LABEL_CHAR_CAP + 1)
    assert _flagged([long_name])


def test_exactly_char_cap_is_clean():
    """The character cap is exclusive: exactly 40 characters is fine."""
    assert not _flagged(["y" * LABEL_CHAR_CAP])


def test_empty_and_none_labels_are_ignored():
    """An empty / None label is not a defect (it is not a long label)."""
    assert not _flagged(["", None])


def test_rule_is_warning_both_classes():
    assert RULE_SEVERITIES[RULE_NODE_LABEL_LENGTH] == Severity.WARNING


def test_lint_surfaces_the_rule():
    a = Artifact(kind="diagram", node_names=["a b c d e f g really long label"])
    findings = {f["rule"] for f in lint(a)["findings"]}
    assert RULE_NODE_LABEL_LENGTH in findings


def test_long_legend_flow_callout_cells_not_flagged():
    """A long Legend / Flow / callout / title is a TEXT cell, not a node label.

    The CLI never puts a text cell or the title cell into ``node_names``, so an
    Artifact modelling those long strings elsewhere (never in ``node_names``)
    trips nothing. Modelled here by leaving ``node_names`` free of them: a
    diagram whose only long strings are legend/flow/callout text has no
    long node label."""
    a = Artifact(
        kind="diagram",
        node_names=["S3", "Lambda"],  # short service nodes
        # A long legend line, a long flow step, and a wordy callout live in
        # text cells — they are NOT node labels, so they are absent here.
        title_cell="aws agent-platform — 123 / us-east-1 | 2025-01-15 | v1",
    )
    assert RULE_NODE_LABEL_LENGTH not in {f["rule"] for f in lint(a)["findings"]}


# --------------------------------------------------------------------------- #
# Property 2 — the label cap is exact and source-scoped.
# --------------------------------------------------------------------------- #

_WORD = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6
)
_SHORT_LABEL = st.builds(
    " ".join,
    st.lists(_WORD, min_size=1, max_size=LABEL_WORD_CAP),
).filter(lambda s: len(s) <= LABEL_CHAR_CAP)


@given(
    words=st.lists(_WORD, min_size=1, max_size=10),
)
def test_property_word_or_char_cap_is_exact(words):
    """A service-node label is flagged iff it exceeds the word OR the char cap."""
    label = " ".join(words)
    expected = len(words) > LABEL_WORD_CAP or len(label) > LABEL_CHAR_CAP
    assert _flagged([label]) == expected


@given(short=_SHORT_LABEL)
def test_property_short_service_labels_never_flagged(short):
    """A label within both caps never trips the rule."""
    assert not _flagged([short])


@given(long_text=st.text(min_size=LABEL_CHAR_CAP + 1, max_size=200))
def test_property_long_text_only_matters_as_a_node_label(long_text):
    """Arbitrarily long text is a defect ONLY when it is a service-node label.

    Placed as a node label it trips the rule (it exceeds the char cap); the same
    text carried by a Legend/Flow/callout/title cell is not in ``node_names``,
    so a diagram with only short node labels stays clean regardless of that
    text's length — the source-scoped half of Property 2."""
    # As a node label: flagged (over the char cap by construction).
    assert _flagged([long_text])
    # As non-node text (never in node_names): the diagram is clean.
    clean = Artifact(kind="diagram", node_names=["S3"], title_cell=long_text)
    assert RULE_NODE_LABEL_LENGTH not in {
        f["rule"] for f in lint(clean)["findings"]
    }
