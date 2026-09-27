"""Validate KB documents against the ``kb-frontmatter.md`` contract (v1.7.0).

Why this exists
---------------
Before 1.7.0 the ``frontmatter`` rule tested only that the twelve required keys
were *present* and non-empty (``linter._frontmatter_missing_keys``), and the
frontmatter block was parsed with a lenient fallback parser that turned any YAML
error into a best-effort ``key: value`` scan. Two whole classes of defect walked
straight through that gate:

* a *malformed value* — ``status: bogus`` or the impossible calendar date
  ``updated: 2026-02-30`` — was accepted because the value was merely present;
* a document whose *body* broke the structural contract (wrong length, a missing
  or over-long required section, two H1s, a five-plus-column table, a code block
  with no ``Anti-patterns`` section) was never inspected at all.

This module is the single implementation of the whole ``kb-frontmatter.md``
contract — the twelve required keys and their value formats (§ Required
Frontmatter), the six structural rules (§ Document Length … § Anti-patterns
Section), and the fail-closed accept/reject behaviour (§ Accept / Reject
Behavior). It is imported by the linter's ``frontmatter`` rule and by
``contract.invoke`` so both check the *same* text against the *same* rules
(Requirement 2, review H3).

Every :class:`KbViolation` names the offending key or section, matching
``kb-frontmatter.md`` AC 8.9 / AC 8.10 ("an error indication MUST name the
offending key" / "name the violated constraint").

Dependency: PyYAML (already a runtime dependency of the engine).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, List, Mapping, Optional, Tuple

import yaml

__all__ = [
    "KbViolation",
    "REQUIRED_FRONTMATTER_KEYS",
    "STATUS_VALUES",
    "REQUIRED_SECTIONS",
    "split_frontmatter",
    "load_frontmatter",
    "validate_frontmatter",
    "validate_structure",
    "validate_document",
]


# The twelve required frontmatter keys (kb-frontmatter.md § Required Frontmatter
# / Requirement 8 AC1). Kept identical to ``linter.REQUIRED_FRONTMATTER_KEYS``.
REQUIRED_FRONTMATTER_KEYS: Tuple[str, ...] = (
    "id",
    "title",
    "kb_namespace",
    "section",
    "category",
    "status",
    "updated",
    "owner",
    "author",
    "next_review_date",
    "tags",
    "related_docs",
)

#: ``status`` accepts exactly these three values (§ Required Frontmatter).
STATUS_VALUES = ("draft", "review", "published")

#: The two frontmatter keys that must be ISO 8601 calendar dates.
_DATE_KEYS = ("updated", "next_review_date")

#: Optional companion metadata keys (Requirement 7, item G). Both are optional:
#: absent raises no finding. ``change_log`` is a list of ``{date, note}`` maps,
#: each ``date`` an ISO 8601 calendar date reusing ``_valid_iso_date``;
#: ``external_refs`` is a list. Neither is a *required* key — they never appear
#: in ``REQUIRED_FRONTMATTER_KEYS`` — so a document without them stays clean.
_CHANGE_LOG_KEY = "change_log"
_EXTERNAL_REFS_KEY = "external_refs"

#: The four sections every generated document must contain, each 100–200 words
#: (§ Required Sections). Compared casefolded against level-≥2 headings.
REQUIRED_SECTIONS = ("Overview", "Main Content", "Troubleshooting", "See Also")

# ``related_docs: []`` is explicitly allowed (0 entries); ``tags`` needs 1–20.
_TAGS_BOUNDS = (1, 20)
_RELATED_DOCS_BOUNDS = (0, 20)

# Total document length and per-section length bounds (words).
_DOC_LENGTH_BOUNDS = (300, 2000)
_SECTION_LENGTH_BOUNDS = (100, 200)

# YYYY-MM-DD, checked before ``date.fromisoformat`` so a stray timestamp or a
# relative date is rejected by shape, and ``2026-02-30`` is rejected by the
# calendar (fromisoformat raises).
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A UTF-8 BOM before the opening ``---`` (Requirement 2.6). ``split_frontmatter``
# strips it so a BOM never changes the verdict.
_BOM = "\ufeff"

# ``---\n … \n---`` frontmatter fence, CRLF-tolerant (Requirement 2.6).
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


@dataclass(frozen=True)
class KbViolation:
    """One breach of the ``kb-frontmatter.md`` contract.

    ``constraint`` is the machine-readable rule name (e.g. ``status-enum``,
    ``section-length``, ``h1-count``). ``key`` is the frontmatter key or section
    name the violation applies to, when one applies (``None`` otherwise).
    ``detail`` is the human-readable explanation.
    """

    constraint: str
    key: Optional[str]
    detail: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return self.detail


# ---------------------------------------------------------------------------
# Frontmatter block + YAML loading
# ---------------------------------------------------------------------------


class _KbLoader(yaml.SafeLoader):
    """A ``SafeLoader`` with the implicit ``timestamp`` resolver removed.

    PyYAML's default implicit resolvers turn ``updated: 2026-01-15`` into a
    ``datetime.date`` and raise a ``ValueError`` *inside the constructor* for the
    impossible ``2026-02-30`` — both of which would mask the real check. With the
    resolver removed, every scalar stays a ``str`` and the ``date-format`` rule
    (regex + ``date.fromisoformat``) is the single authority on date validity.
    """


# Copy the resolver map so we do not mutate ``SafeLoader``'s shared class state,
# then drop every implicit resolver that would produce a ``timestamp``.
_KbLoader.yaml_implicit_resolvers = {
    first_char: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def split_frontmatter(text: str) -> Tuple[Optional[str], str]:
    """Split ``text`` into ``(frontmatter_block, body)``.

    Strips a leading UTF-8 BOM (Requirement 2.6) and matches a CRLF-tolerant
    ``---`` … ``---`` fence at the very start. Returns ``(None, text)`` when the
    document has no frontmatter block (the body is then the whole text, minus a
    BOM).
    """
    if text.startswith(_BOM):
        text = text[len(_BOM) :]
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    block = match.group(1)
    body = text[match.end() :]
    return block, body


def load_frontmatter(block: str) -> Tuple[Optional[dict], List[KbViolation]]:
    """Parse a frontmatter block with :class:`_KbLoader`.

    Returns ``(mapping, [])`` on success. A ``yaml.YAMLError`` or a document that
    does not parse to a mapping yields ``(None, [KbViolation("yaml-parse", …)])``
    carrying the problem mark, so a malformed block is a hard failure rather than
    a lenient fallback (Requirement 2.5).
    """
    try:
        loaded = yaml.load(block, Loader=_KbLoader)  # noqa: S506 - _KbLoader is Safe
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        detail = "frontmatter is not valid YAML"
        if mark is not None:
            detail += f" (line {mark.line + 1}, column {mark.column + 1})"
        return None, [KbViolation("yaml-parse", None, detail)]
    if loaded is None:
        return None, [
            KbViolation("yaml-parse", None, "frontmatter block is empty")
        ]
    if not isinstance(loaded, Mapping):
        return None, [
            KbViolation(
                "yaml-parse",
                None,
                f"frontmatter is not a mapping (parsed as {type(loaded).__name__})",
            )
        ]
    return dict(loaded), []


# ---------------------------------------------------------------------------
# Frontmatter constraints (Requirement 2.1–2.3, 2.7)
# ---------------------------------------------------------------------------


def _is_empty_value(value: Any) -> bool:
    """True when a required key's value counts as empty.

    An empty list is *not* empty for ``related_docs`` (``related_docs: []`` is
    allowed); the count check owns list bounds. A ``None`` or an
    empty/whitespace-only string is empty.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def validate_frontmatter(fm: Mapping) -> List[KbViolation]:
    """Validate a parsed frontmatter mapping against the contract."""
    violations: List[KbViolation] = []

    # Presence + non-empty (§ Required Frontmatter). ``related_docs: []`` is
    # allowed, so the empty check exempts an empty list.
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in fm:
            violations.append(
                KbViolation("missing-key", key, f"required key {key!r} is absent")
            )
            continue
        value = fm[key]
        if key == "related_docs" and isinstance(value, list):
            # An empty related_docs list is allowed; count rule checks bounds.
            pass
        elif _is_empty_value(value):
            violations.append(
                KbViolation("empty-key", key, f"required key {key!r} is empty")
            )

    # status enumeration.
    if "status" in fm and not _is_empty_value(fm["status"]):
        if fm["status"] not in STATUS_VALUES:
            violations.append(
                KbViolation(
                    "status-enum",
                    "status",
                    f"status {fm['status']!r} is not one of {list(STATUS_VALUES)}",
                )
            )

    # Date format for updated / next_review_date.
    for key in _DATE_KEYS:
        if key not in fm:
            continue
        value = fm[key]
        if _is_empty_value(value):
            continue
        if not _valid_iso_date(value):
            violations.append(
                KbViolation(
                    "date-format",
                    key,
                    f"{key} {value!r} is not a real calendar date in YYYY-MM-DD form",
                )
            )

    # List type + count for tags / related_docs.
    violations.extend(
        _validate_list(fm, "tags", _TAGS_BOUNDS, "tags-count")
    )
    violations.extend(
        _validate_list(fm, "related_docs", _RELATED_DOCS_BOUNDS, "related_docs-count")
    )

    # Optional companion metadata (Requirement 7, item G): change_log /
    # external_refs. Both optional — absent raises nothing.
    violations.extend(_validate_change_log(fm))
    violations.extend(_validate_external_refs(fm))

    return violations


def _validate_change_log(fm: Mapping) -> List[KbViolation]:
    """Validate the optional ``change_log`` key (Requirement 7.1, 7.2, 7.3).

    Absent: no finding. Present, it must be a list of ``{date, note}`` mappings,
    each ``date`` a valid ISO 8601 calendar date (reusing ``_valid_iso_date``).
    A bad shape or a bad date raises a ``frontmatter`` finding naming the key.
    """
    if _CHANGE_LOG_KEY not in fm:
        return []
    value = fm[_CHANGE_LOG_KEY]
    if not isinstance(value, list):
        return [
            KbViolation(
                "change_log-shape",
                _CHANGE_LOG_KEY,
                f"{_CHANGE_LOG_KEY} must be a list of {{date, note}} entries, "
                f"got {type(value).__name__}",
            )
        ]
    violations: List[KbViolation] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            violations.append(
                KbViolation(
                    "change_log-shape",
                    _CHANGE_LOG_KEY,
                    f"{_CHANGE_LOG_KEY}[{index}] must be a {{date, note}} mapping, "
                    f"got {type(entry).__name__}",
                )
            )
            continue
        if "date" not in entry:
            violations.append(
                KbViolation(
                    "change_log-shape",
                    _CHANGE_LOG_KEY,
                    f"{_CHANGE_LOG_KEY}[{index}] is missing its 'date'",
                )
            )
        elif not _valid_iso_date(entry["date"]):
            violations.append(
                KbViolation(
                    "change_log-date",
                    _CHANGE_LOG_KEY,
                    f"{_CHANGE_LOG_KEY}[{index}] date {entry['date']!r} is not a "
                    "real calendar date in YYYY-MM-DD form",
                )
            )
    return violations


def _validate_external_refs(fm: Mapping) -> List[KbViolation]:
    """Validate the optional ``external_refs`` key (Requirement 7.1, 7.3).

    Absent: no finding. Present, it must be a list (of URLs or citations); a
    non-list value raises a ``frontmatter`` finding naming the key.
    """
    if _EXTERNAL_REFS_KEY not in fm:
        return []
    value = fm[_EXTERNAL_REFS_KEY]
    if not isinstance(value, list):
        return [
            KbViolation(
                "external_refs-shape",
                _EXTERNAL_REFS_KEY,
                f"{_EXTERNAL_REFS_KEY} must be a list, got {type(value).__name__}",
            )
        ]
    return []


def _valid_iso_date(value: Any) -> bool:
    """True when ``value`` is a string ``YYYY-MM-DD`` that is a real date."""
    if not isinstance(value, str):
        return False
    if not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_list(
    fm: Mapping, key: str, bounds: Tuple[int, int], count_constraint: str
) -> List[KbViolation]:
    """Validate that ``fm[key]`` is a list whose length is within ``bounds``."""
    if key not in fm:
        return []
    value = fm[key]
    if not isinstance(value, list):
        return [
            KbViolation(
                "list-type",
                key,
                f"{key} must be a list, got {type(value).__name__}",
            )
        ]
    low, high = bounds
    if not (low <= len(value) <= high):
        return [
            KbViolation(
                count_constraint,
                key,
                f"{key} has {len(value)} entries (allowed {low}\u2013{high})",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Structural constraints (Requirement 2.4)
# ---------------------------------------------------------------------------

# A fenced code block opens/closes with ``` or ~~~ (three or more), optionally
# indented and with an info string after the opener.
_FENCE_RE = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")

# ATX heading: 1–6 leading ``#`` then a space then text.
_ATX_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")

# A GFM table delimiter row: pipes and cells of ``-`` (optionally ``:`` aligned).
_DELIM_CELL_RE = re.compile(r"^\s*:?-+:?\s*$")

# A list-item marker: bullet (-, *, +) or ordered (1.  / 1) ).
_LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*+]|\d+[.)])\s+\S")


def _mask_fences(body: str) -> Tuple[List[str], bool]:
    """Return ``(lines_outside_fences, has_fenced_block)``.

    Lines inside a fenced code block are replaced with an empty string so
    heading, list, table and word-count detection never treats code as prose,
    while line indices are preserved. ``has_fenced_block`` records whether the
    body contained at least one fenced block (for ``anti-patterns-missing``).
    """
    lines = body.splitlines()
    out: List[str] = []
    in_fence = False
    fence_token = ""
    has_fence = False
    for line in lines:
        m = _FENCE_RE.match(line)
        if not in_fence:
            if m:
                in_fence = True
                fence_token = m.group("fence")[0]  # ` or ~
                has_fence = True
                out.append("")
                continue
            out.append(line)
        else:
            # A closing fence uses the same character; length ≥ the opener.
            if m and m.group("fence")[0] == fence_token and not m.group("info").strip():
                in_fence = False
            out.append("")
    return out, has_fence


def _iter_atx_headings(lines: List[str]) -> List[Tuple[int, int, str]]:
    """Return ``(line_index, level, text)`` for every ATX heading."""
    headings: List[Tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _ATX_RE.match(line)
        if m:
            headings.append((i, len(m.group("hashes")), m.group("text").strip()))
    return headings


def _count_h1(lines: List[str]) -> int:
    """Count H1 headings: ATX ``# `` and Setext ``===`` underlines."""
    count = 0
    for i, level, _text in _iter_atx_headings(lines):
        if level == 1:
            count += 1
    # Setext H1: a non-blank text line immediately followed by a line of ``=``.
    for i in range(len(lines) - 1):
        text = lines[i].strip()
        underline = lines[i + 1].strip()
        if text and underline and set(underline) == {"="} and not _ATX_RE.match(lines[i]):
            count += 1
    return count


def _words(text: str) -> int:
    """Word count over prose (``\\S+`` runs), matching how authors count."""
    return len(re.findall(r"\S+", text))


def _all_headings(lines: List[str]) -> List[Tuple[int, int, str]]:
    """Return ``(line_index, level, text)`` for ATX and Setext headings, in order."""
    headings = list(_iter_atx_headings(lines))
    atx_lines = {i for i, _l, _t in headings}
    for i in range(len(lines) - 1):
        if i in atx_lines:
            continue
        text = lines[i].strip()
        underline = lines[i + 1].strip()
        if not text or not underline:
            continue
        if set(underline) == {"="}:
            headings.append((i, 1, text))
        elif set(underline) == {"-"} and len(underline) >= 1:
            # A Setext H2 underline; but a lone ``-`` is a list item / hrule.
            # Require the text line not to be a list item and the underline to be
            # all dashes with length ≥ 2 to avoid false positives.
            if len(underline) >= 2 and not _LIST_ITEM_RE.match(lines[i]):
                headings.append((i, 2, text))
    headings.sort(key=lambda h: h[0])
    return headings


def _section_word_counts(lines: List[str]) -> dict:
    """Map a heading's casefolded text to the word count of its section body.

    A section runs from just after its heading line to the next heading of the
    same or higher level (smaller/equal level number).
    """
    headings = _all_headings(lines)
    counts: dict = {}
    for idx, (line_i, level, text) in enumerate(headings):
        end = len(lines)
        for later_line_i, later_level, _t in headings[idx + 1 :]:
            if later_level <= level:
                end = later_line_i
                break
        body = "\n".join(lines[line_i + 1 : end])
        counts[text.casefold()] = _words(body)
    return counts


def _max_list_depth(lines: List[str]) -> int:
    """Return the deepest list nesting level (1 = top-level item)."""
    # A stack of indentation widths; each new deeper indent is one more level.
    max_depth = 0
    indent_stack: List[int] = []
    for line in lines:
        m = _LIST_ITEM_RE.match(line)
        if not m:
            # A blank line does not reset nesting (a loose list); a non-list,
            # non-blank line at column 0 ends the current list.
            if line.strip() == "":
                continue
            if not line[:1].isspace():
                indent_stack = []
            continue
        indent = len(m.group("indent").expandtabs(4))
        while indent_stack and indent < indent_stack[-1]:
            indent_stack.pop()
        if not indent_stack or indent > indent_stack[-1]:
            indent_stack.append(indent)
        depth = len(indent_stack)
        max_depth = max(max_depth, depth)
    return max_depth


def _table_violations(lines: List[str]) -> List[KbViolation]:
    """Detect GFM tables wider than five columns or with a merged (ragged) cell."""
    violations: List[KbViolation] = []
    i = 0
    n = len(lines)
    seen_over_wide = False
    seen_merged = False
    while i < n - 1:
        header = lines[i]
        delim = lines[i + 1]
        if "|" in header and _is_delimiter_row(delim):
            delim_cols = _row_cells(delim)
            ncols = len(delim_cols)
            if ncols > 5 and not seen_over_wide:
                violations.append(
                    KbViolation(
                        "table-columns",
                        None,
                        f"a table has {ncols} columns (at most 5 allowed)",
                    )
                )
                seen_over_wide = True
            # Walk the body rows; a row whose cell count differs from the
            # delimiter row is how a merged cell shows up in GFM source.
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                if len(_row_cells(lines[j])) != ncols and not seen_merged:
                    violations.append(
                        KbViolation(
                            "table-merged-cell",
                            None,
                            "a table row's cell count differs from its header "
                            "(merged cells are not allowed)",
                        )
                    )
                    seen_merged = True
                j += 1
            i = j
            continue
        i += 1
    return violations


def _is_delimiter_row(line: str) -> bool:
    """True when ``line`` is a GFM table delimiter row (``| --- | :--: |``)."""
    if "|" not in line:
        return False
    cells = _row_cells(line)
    return bool(cells) and all(_DELIM_CELL_RE.match(c) for c in cells)


def _row_cells(line: str) -> List[str]:
    """Split a GFM table row into its cells, dropping the outer empty edges."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split("|")]


def validate_structure(body: str) -> List[KbViolation]:
    """Validate the document body against the six structural rules (R2.4)."""
    violations: List[KbViolation] = []
    lines, has_fence = _mask_fences(body)

    # doc-length: total words over prose outside fences.
    total_words = _words("\n".join(lines))
    low, high = _DOC_LENGTH_BOUNDS
    if not (low <= total_words <= high):
        violations.append(
            KbViolation(
                "doc-length",
                None,
                f"document has {total_words} words (allowed {low}\u2013{high})",
            )
        )

    # Required sections: presence + length.
    section_counts = _section_word_counts(lines)
    slow, shigh = _SECTION_LENGTH_BOUNDS
    for section in REQUIRED_SECTIONS:
        key = section.casefold()
        if key not in section_counts:
            violations.append(
                KbViolation(
                    "section-missing",
                    section,
                    f"required section {section!r} is missing",
                )
            )
            continue
        words = section_counts[key]
        if not (slow <= words <= shigh):
            violations.append(
                KbViolation(
                    "section-length",
                    section,
                    f"section {section!r} has {words} words (allowed {slow}\u2013{shigh})",
                )
            )

    # h1-count: exactly one H1 (ATX or Setext).
    h1 = _count_h1(lines)
    if h1 != 1:
        violations.append(
            KbViolation(
                "h1-count",
                None,
                f"document has {h1} H1 heading(s) (exactly one required)",
            )
        )

    # list-depth: no deeper than two levels.
    depth = _max_list_depth(lines)
    if depth > 2:
        violations.append(
            KbViolation(
                "list-depth",
                None,
                f"a list is nested {depth} levels deep (at most 2 allowed)",
            )
        )

    # table-columns / table-merged-cell.
    violations.extend(_table_violations(lines))

    # anti-patterns-missing: a fenced block requires an Anti-patterns section.
    if has_fence:
        heading_texts = {t.casefold() for _i, _l, t in _all_headings(lines)}
        if "anti-patterns" not in heading_texts:
            violations.append(
                KbViolation(
                    "anti-patterns-missing",
                    "Anti-patterns",
                    "document has a fenced code block but no 'Anti-patterns' section",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def validate_document(text: str) -> List[KbViolation]:
    """Validate a whole KB document (frontmatter + structure).

    Returns every :class:`KbViolation`; an empty list means the document
    satisfies the whole ``kb-frontmatter.md`` contract and is eligible for
    emission (§ Accept / Reject Behavior). A frontmatter block that is absent or
    unparseable short-circuits the frontmatter checks (the structural checks
    still run on the body).
    """
    block, body = split_frontmatter(text)
    violations: List[KbViolation] = []
    if block is None:
        # No frontmatter at all: every required key is missing.
        for key in REQUIRED_FRONTMATTER_KEYS:
            violations.append(
                KbViolation("missing-key", key, f"required key {key!r} is absent")
            )
    else:
        fm, load_violations = load_frontmatter(block)
        if fm is None:
            violations.extend(load_violations)
        else:
            violations.extend(validate_frontmatter(fm))
    violations.extend(validate_structure(body))
    return violations
