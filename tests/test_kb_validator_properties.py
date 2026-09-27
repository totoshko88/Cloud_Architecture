"""Property tests for ``rule_engine.kb_validator`` (honest-gates, release 1.7.0).

Feature: honest-gates — the KB validator is the single implementation of the
``kb-frontmatter.md`` contract, shared by the Linter's ``frontmatter`` rule and
by ``contract.invoke``. These property tests pin that contract against an
*independent* oracle: each expected-violation computation here is written from
the kb-frontmatter table directly, never by calling the module under test, so a
passing test means the implementation agrees with the contract rather than with
itself.

Task 6.2 lands Property 8 here; tasks 6.3 and 6.4 add Properties 9 and 10 to the
same file.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Mapping, Set

from hypothesis import given
from hypothesis import strategies as st

from rule_engine.kb_validator import (
    KbViolation,
    load_frontmatter,
    validate_frontmatter,
)

# ``tests/strategies.py`` is a sibling module, imported by path like the rest of
# the honest-gates property suite.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategies import (  # noqa: E402  (path insert must precede the import)
    FRONTMATTER_KEYS,
    frontmatter_mappings,
)

# The contract's own vocabulary, restated here as the oracle's constants so the
# test does not import them from the module it is checking.
_STATUS_VALUES = ("draft", "review", "published")
_DATE_KEYS = ("updated", "next_review_date")
_TAGS_BOUNDS = (1, 20)
_RELATED_DOCS_BOUNDS = (0, 20)


# --------------------------------------------------------------------------- #
# Independent oracle: expected frontmatter violations for a parsed mapping.
# --------------------------------------------------------------------------- #
#
# Each returned value is a ``(constraint, key)`` pair — ``constraint`` is the
# machine-readable rule name and ``key`` is the frontmatter key it applies to
# (``None`` when the constraint is not key-scoped). This mirrors the
# ``kb-frontmatter.md`` § Required Frontmatter table and Requirement 2.1–2.3/2.7
# without reusing the implementation's logic.


def _is_empty(value: object) -> bool:
    """A required value is empty when it is ``None`` or a blank/whitespace str.

    An empty *list* is not "empty" (``related_docs: []`` is allowed and the
    count rule owns list bounds).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _valid_iso_date(value: object) -> bool:
    """True iff ``value`` is a ``YYYY-MM-DD`` string that is a real date."""
    if not isinstance(value, str):
        return False
    parts = value.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return False
    if (len(parts[0]), len(parts[1]), len(parts[2])) != (4, 2, 2):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def expected_frontmatter_violations(fm: Mapping[str, object]) -> Set[tuple]:
    """Compute the (constraint, key) set the contract implies for ``fm``."""
    expected: Set[tuple] = set()

    # Presence + non-empty for every required key (related_docs: [] allowed).
    for key in FRONTMATTER_KEYS:
        if key not in fm:
            expected.add(("missing-key", key))
            continue
        value = fm[key]
        if key == "related_docs" and isinstance(value, list):
            pass  # empty list allowed; count rule below owns the bounds
        elif _is_empty(value):
            expected.add(("empty-key", key))

    # status enumeration (only when present and non-empty).
    if "status" in fm and not _is_empty(fm["status"]):
        if fm["status"] not in _STATUS_VALUES:
            expected.add(("status-enum", "status"))

    # date format for the two date keys (only when present and non-empty).
    for key in _DATE_KEYS:
        if key not in fm:
            continue
        value = fm[key]
        if _is_empty(value):
            continue
        if not _valid_iso_date(value):
            expected.add(("date-format", key))

    # tags / related_docs: list type, then count bounds.
    for key, (low, high), count_constraint in (
        ("tags", _TAGS_BOUNDS, "tags-count"),
        ("related_docs", _RELATED_DOCS_BOUNDS, "related_docs-count"),
    ):
        if key not in fm:
            continue
        value = fm[key]
        if not isinstance(value, list):
            expected.add(("list-type", key))
        elif not (low <= len(value) <= high):
            expected.add((count_constraint, key))

    return expected


def _actual_violation_set(violations) -> Set[tuple]:
    """Reduce a list of :class:`KbViolation` to a ``(constraint, key)`` set."""
    return {(v.constraint, v.key) for v in violations}


# --------------------------------------------------------------------------- #
# Property 8: Frontmatter validation matches the contract
# --------------------------------------------------------------------------- #


# Feature: honest-gates, Property 8: Frontmatter validation matches the contract
@given(fm=frontmatter_mappings())
def test_property_8_frontmatter_validation_matches_contract(
    fm: Mapping[str, object],
) -> None:
    """`validate_frontmatter` accepts iff every key satisfies the table.

    The verdict — the set of ``(constraint, key)`` pairs — must equal the set an
    independent oracle computes straight from the kb-frontmatter contract, for a
    valid mapping (empty set) and for every injected near-miss (statuses outside
    the enum, impossible/non-padded/timestamp dates, 0–25-entry lists, non-list
    scalars, dropped and emptied keys).

    Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.7
    """
    violations = validate_frontmatter(fm)
    expected = expected_frontmatter_violations(fm)

    assert _actual_violation_set(violations) == expected

    # Acceptance is exactly "no violations", i.e. the oracle agrees there are
    # none (Requirement 2.1: emit iff every constraint holds).
    assert (len(violations) == 0) == (len(expected) == 0)

    # Every violation carries a non-empty constraint, and names its key wherever
    # one applies (Requirement 2.7 / kb-frontmatter AC 8.9). The key-scoped
    # constraints always name a key; ``list-type``/count constraints do too.
    key_scoped = {
        "missing-key",
        "empty-key",
        "status-enum",
        "date-format",
        "list-type",
        "tags-count",
        "related_docs-count",
    }
    for v in violations:
        assert isinstance(v, KbViolation)
        assert v.constraint, "constraint must be non-empty"
        if v.constraint in key_scoped:
            assert v.key, f"{v.constraint} must name its key"


# Feature: honest-gates, Property 8: Frontmatter validation matches the contract
@given(fm=frontmatter_mappings(valid=True))
def test_property_8_conformant_mapping_is_accepted(
    fm: Mapping[str, object],
) -> None:
    """A mapping forced valid yields no frontmatter violations at all.

    This pins the accept direction of "accept iff conformant" (Requirement 2.1):
    when every key satisfies the table, the verdict is empty.

    Validates: Requirements 2.1
    """
    assert validate_frontmatter(fm) == []


# Feature: honest-gates, Property 8: Frontmatter validation matches the contract
@given(fm=frontmatter_mappings(valid=False))
def test_property_8_near_miss_mapping_is_rejected_and_named(
    fm: Mapping[str, object],
) -> None:
    """A mapping with an injected near-miss is rejected, matching the oracle.

    This pins the reject direction (Requirement 2.7): at least one violation, and
    the reported ``(constraint, key)`` set equals the independent oracle's.

    Validates: Requirements 2.1, 2.7
    """
    violations = validate_frontmatter(fm)
    assert violations, "an injected near-miss must be rejected"
    assert _actual_violation_set(violations) == expected_frontmatter_violations(fm)


# Feature: honest-gates, Property 8: Frontmatter validation matches the contract
@given(
    prefix=st.text(max_size=20),
    body=st.text(max_size=40),
)
def test_property_8_malformed_yaml_is_a_named_yaml_parse_violation(
    prefix: str, body: str,
) -> None:
    """Frontmatter text that does not parse to a mapping is a named failure.

    Property 8 covers "malformed YAML text": ``load_frontmatter`` must return a
    single ``yaml-parse`` violation with a non-empty constraint rather than a
    lenient best-effort scan (Requirement 2.5). A block that is a bare scalar or
    a sequence is "not a mapping" and is rejected the same way.

    Validates: Requirements 2.5, 2.7
    """
    # A YAML sequence never parses to a mapping; an unterminated flow mapping is
    # a hard YAMLError. Both must yield exactly one non-empty ``yaml-parse``.
    for block in (f"- {prefix}\n- {body}", f"{{{prefix}: {body}"):
        fm, violations = load_frontmatter(block)
        assert fm is None
        assert len(violations) == 1
        v = violations[0]
        assert v.constraint == "yaml-parse"
        assert v.detail, "yaml-parse must carry a non-empty detail"


# --------------------------------------------------------------------------- #
# Property 9: Structural validation matches a document model
# --------------------------------------------------------------------------- #
#
# The oracle below computes the expected structural-constraint set directly from
# the KbStructureModel and the *rendered body text* (the renderer is test
# infrastructure, not the module under test), never by calling
# ``validate_structure``. Word counts use the same public rule the contract
# states — a "word" is a maximal run of non-whitespace (``\S+``) over prose with
# fenced code blocks masked out — re-implemented here so the oracle owns its own
# arithmetic. Every other constraint (H1 count, list depth, table shape, the
# Anti-patterns rule) is read straight from the model fields, which fix exactly
# what the renderer emits.

import re  # noqa: E402

from rule_engine.kb_validator import validate_structure  # noqa: E402
from strategies import (  # noqa: E402
    REQUIRED_SECTIONS as KB_REQUIRED_SECTIONS,
    KbStructureModel,
    kb_structure_models,
    render_kb_document_body,
)

# The structural bounds, restated from the kb-frontmatter contract as the
# oracle's own constants (never imported from the module under test).
_DOC_LENGTH_BOUNDS = (300, 2000)
_SECTION_LENGTH_BOUNDS = (100, 200)

# A fenced code block delimiter: ``` or ~~~ (three or more), optional indent and
# info string. Mirrors the contract's masking rule so the oracle counts prose,
# not code.
_ORACLE_FENCE_RE = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")


def _oracle_mask_fences(body: str) -> list:
    """Blank out lines inside fenced code blocks; return the surviving lines.

    Independent re-implementation of the contract's "fences masked" rule so the
    oracle's word counts see only prose, exactly as the contract states.
    """
    out: list = []
    in_fence = False
    fence_char = ""
    for line in body.splitlines():
        m = _ORACLE_FENCE_RE.match(line)
        if not in_fence:
            if m:
                in_fence = True
                fence_char = m.group("fence")[0]
                out.append("")
                continue
            out.append(line)
        else:
            if m and m.group("fence")[0] == fence_char and not m.group("info").strip():
                in_fence = False
            out.append("")
    return out


def _oracle_word_count(text: str) -> int:
    """Count words as maximal runs of non-whitespace (``\\S+``)."""
    return len(re.findall(r"\S+", text))


def _oracle_section_word_counts(lines: list) -> dict:
    """Map each ATX heading's casefolded text to its section-body word count.

    A section runs from just after its heading to the next heading of the same
    or higher level. The renderer emits only ATX headings (``#``/``##``), so an
    independent ATX scan is sufficient and faithful.
    """
    atx = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
    headings = []
    for i, line in enumerate(lines):
        m = atx.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))
    counts: dict = {}
    for idx, (line_i, level, text) in enumerate(headings):
        end = len(lines)
        for later_i, later_level, _t in headings[idx + 1 :]:
            if later_level <= level:
                end = later_i
                break
        body = "\n".join(lines[line_i + 1 : end])
        counts[text.casefold()] = _oracle_word_count(body)
    return counts


def expected_structure_constraints(model: KbStructureModel) -> Set[str]:
    """Compute the set of ``constraint`` names the contract implies for ``model``.

    Read straight from the model and the rendered prose; never calls
    ``validate_structure``.
    """
    body = render_kb_document_body(model)
    lines = _oracle_mask_fences(body)
    expected: Set[str] = set()

    # doc-length: total prose words over the fence-masked body.
    total = _oracle_word_count("\n".join(lines))
    low, high = _DOC_LENGTH_BOUNDS
    if not (low <= total <= high):
        expected.add("doc-length")

    # Required sections: presence + per-section length.
    section_counts = _oracle_section_word_counts(lines)
    slow, shigh = _SECTION_LENGTH_BOUNDS
    for section in KB_REQUIRED_SECTIONS:
        key = section.casefold()
        if key not in section_counts:
            expected.add("section-missing")
        elif not (slow <= section_counts[key] <= shigh):
            expected.add("section-length")

    # h1-count: exactly one H1 required. The renderer emits ATX ``# Title N``
    # headings, one per ``h1_count``.
    if model.h1_count != 1:
        expected.add("h1-count")

    # list-depth: deeper than two levels is a violation. The renderer's list
    # reaches exactly ``list_depth`` levels (0 = no list).
    if model.list_depth > 2:
        expected.add("list-depth")

    # table-columns: more than five columns. table-merged-cell: a ragged body
    # row (only rendered when ragged and columns > 1).
    if model.table_columns > 5:
        expected.add("table-columns")
    if model.table_ragged and model.table_columns > 1:
        expected.add("table-merged-cell")

    # anti-patterns-missing: a fenced block with no Anti-patterns section.
    if model.fenced_block and not model.anti_patterns:
        expected.add("anti-patterns-missing")

    return expected


# Feature: honest-gates, Property 9: Structural validation matches a document model
@given(model=kb_structure_models())
def test_property_9_structural_validation_matches_document_model(
    model: KbStructureModel,
) -> None:
    """`validate_structure` returns exactly the model's structural constraints.

    The set of ``constraint`` values returned by ``validate_structure`` over a
    document rendered from the structure model must equal the set an independent
    oracle computes from the same model (word count per section, presence of the
    four required sections, H1 count, list depth, table width and ragged rows,
    fenced blocks and an Anti-patterns section).

    Validates: Requirements 2.4
    """
    body = render_kb_document_body(model)
    violations = validate_structure(body)

    actual = {v.constraint for v in violations}
    expected = expected_structure_constraints(model)

    assert actual == expected

    # Every returned violation carries a non-empty constraint, and the
    # section-scoped ones name their section (kb-frontmatter AC 8.10).
    for v in violations:
        assert isinstance(v, KbViolation)
        assert v.constraint, "constraint must be non-empty"
        if v.constraint in {"section-missing", "section-length"}:
            assert v.key, f"{v.constraint} must name its section"


# --------------------------------------------------------------------------- #
# Property 10: A BOM does not change the verdict
# --------------------------------------------------------------------------- #
#
# Requirement 2.6: the Linter ignores a UTF-8 BOM before the opening ``---``.
# ``split_frontmatter`` strips a leading ``\ufeff`` before it matches the fence,
# so prepending a BOM to any document must leave the whole ``validate_document``
# verdict — the ordered list of ``KbViolation``s — unchanged. ``KbViolation`` is
# a frozen dataclass, so equality is by value; comparing the lists directly also
# pins the order, not merely the set.

from rule_engine.kb_validator import validate_document  # noqa: E402
from strategies import (  # noqa: E402
    frontmatter_mappings as _fm_strategy,
    kb_structure_models as _kb_models,
    render_kb_document,
)

_BOM = "\ufeff"


@st.composite
def _kb_documents(draw: st.DrawFn) -> str:
    """A full KB document (frontmatter + structured body), valid or not."""
    fm = draw(_fm_strategy())
    model = draw(_kb_models())
    return render_kb_document(fm, model)


# Feature: honest-gates, Property 10: A BOM does not change the verdict
@given(document=_kb_documents())
def test_property_10_bom_invariance_on_kb_documents(document: str) -> None:
    """A leading BOM does not change the verdict for a rendered KB document.

    ``validate_document("\ufeff" + d)`` must equal ``validate_document(d)`` for a
    document ``d`` drawn from the full KB-document strategy (a frontmatter block
    plus a structured body, spanning conformant and near-miss cases). The BOM is
    stripped before the frontmatter fence is matched, so neither the frontmatter
    verdict nor the structural verdict may shift.

    Validates: Requirements 2.6
    """
    assert validate_document(_BOM + document) == validate_document(document)


# Feature: honest-gates, Property 10: A BOM does not change the verdict
@given(document=st.text(max_size=400))
def test_property_10_bom_invariance_on_arbitrary_text(document: str) -> None:
    """The BOM is invisible to the verdict for *any* Markdown document text.

    The property is universal over document text, not only well-formed KB
    documents: arbitrary text (including text with no frontmatter fence at all,
    and text that itself already begins with a BOM) must produce the same
    ``validate_document`` result with or without a prepended BOM.

    Validates: Requirements 2.6
    """
    assert validate_document(_BOM + document) == validate_document(document)
