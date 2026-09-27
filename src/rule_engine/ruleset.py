"""Diagram & Inventory Rule Engine — ruleset location and rule-table parser.

This module is the *single source* for two things every gate must agree on
(design §3, "One vocabulary, one module"):

1. **Where the authoritative ``diagram-lint.md`` ruleset lives.** The Lint_CLI
   and the Contract both resolve the ruleset through :func:`find_ruleset` /
   :func:`require_ruleset` and both fail closed (Requirement 10.2) when it is
   absent — via :class:`RulesetUnavailableError`.

2. **What the ``diagram-lint.md`` rule table and class-escalation table say.**
   :func:`parse_rule_table` reads the ``## Lint Rules`` table (the per-rule
   default severity, with cells such as ``WARNING/ERROR``) and the
   ``## Diagram Class`` escalation table (the ``landscape`` override). It exists
   for the sync test (Requirement 10.1) that keeps the document and the code's
   ``RULE_SEVERITIES`` / ``CLASS_ESCALATIONS`` from diverging; it is not used at
   lint time, where the severities in code stay authoritative.

``find_ruleset`` and ``ruleset_available`` moved here from
:mod:`rule_engine.linter`, which now re-exports them for backward compatibility.

Resolution order (Requirement 10.2, design §3):

1. ``RULE_ENGINE_RULESET`` — when set, this path is authoritative. A path that
   is *set but missing* means the ruleset is **unavailable**; there is no
   fallthrough to the later candidates.
2. ``<workspace_root or cwd>/.kiro/steering/diagram-lint.md``.
3. The repository checkout that contains this package (``parents[2]``).
4. The bundled payload ``_bootstrap/kiro/steering/diagram-lint.md``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


# The authoritative lint ruleset, relative to a workspace root.
RULESET_RELATIVE_PATH = os.path.join(".kiro", "steering", "diagram-lint.md")

# The environment variable that pins the ruleset location explicitly.
RULESET_ENV_VAR = "RULE_ENGINE_RULESET"

# The error code the Linter/Contract return when the ruleset is unavailable.
RULESET_UNAVAILABLE_ERROR = "ruleset-unavailable"


class RulesetUnavailableError(RuntimeError):
    """Raised when the authoritative ``diagram-lint.md`` ruleset cannot be read.

    Carries the error code (``ruleset-unavailable``) and the resolved path that
    was probed (when one was found), so callers can surface a precise blocking
    reason. The Lint_CLI maps this to exit code 2 and the Contract to a
    generation error, both *before* any file is written (Requirement 10.2).
    """

    def __init__(self, path: Optional[str] = None, reason: Optional[str] = None):
        self.code = RULESET_UNAVAILABLE_ERROR
        self.path = path
        self.reason = reason
        detail = f" ({reason})" if reason else ""
        where = f" at {path}" if path else ""
        super().__init__(
            f"{RULESET_UNAVAILABLE_ERROR}: lint ruleset diagram-lint.md is "
            f"missing or cannot be read{where}{detail}"
        )


def _env_ruleset() -> Optional[str]:
    """Return the ``RULE_ENGINE_RULESET`` value, or ``None`` when unset/blank."""
    value = os.environ.get(RULESET_ENV_VAR)
    if value is None:
        return None
    value = value.strip()
    return value or None


def find_ruleset(
    ruleset_path: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> Optional[str]:
    """Locate the authoritative ``diagram-lint.md`` ruleset.

    The resolution order (design §3, Requirement 10.2) is:

    1. An explicit ``ruleset_path`` argument, when given.
    2. The ``RULE_ENGINE_RULESET`` environment variable, when set. **A set env
       var is authoritative and terminal**: if it names a path that does not
       exist, the ruleset is *unavailable* and this function returns ``None``
       rather than falling through to the workspace/repo/bootstrap candidates.
    3. ``<workspace_root or cwd>/.kiro/steering/diagram-lint.md``.
    4. The repository checkout that contains this package (``parents[2]``).
    5. The bundled payload ``_bootstrap/kiro/steering/diagram-lint.md`` (both the
       ``.kiro`` and the setuptools-safe dot-free ``kiro`` layout).

    ``ruleset_path`` behaves like the env var: an explicit path that does not
    exist yields ``None`` (no fallthrough), so a caller can point at a location
    with no ruleset to exercise the unavailable path.

    Returns the first candidate path that exists as a file, or ``None``.
    Existence — not readability — is checked here; :func:`ruleset_available`
    performs the read check.
    """
    # 1. An explicit path argument is authoritative and terminal.
    if ruleset_path:
        return ruleset_path if _isfile(ruleset_path) else None

    # 2. A set env var is authoritative and terminal (set-but-missing => None).
    env_path = _env_ruleset()
    if env_path is not None:
        return env_path if _isfile(env_path) else None

    candidates: List[str] = []

    # 3. The workspace root (explicit argument) or the current working directory.
    base = workspace_root if workspace_root else os.getcwd()
    candidates.append(os.path.join(base, RULESET_RELATIVE_PATH))

    # 4. The repository checkout that contains this package. The module lives at
    #    ``<repo>/src/rule_engine/ruleset.py``, so ``parents[2]`` is the repo
    #    root of a source checkout.
    here = Path(__file__).resolve()
    parents = here.parents
    if len(parents) > 2:
        candidates.append(str(parents[2] / RULESET_RELATIVE_PATH))

    # 5. The bundled payload shipped inside the package. setuptools drops
    #    dot-directories, so the payload stores ``.kiro`` dot-free as ``kiro``;
    #    probe both layouts.
    bootstrap = here.parent / "_bootstrap"
    candidates.append(str(bootstrap / RULESET_RELATIVE_PATH))
    candidates.append(str(bootstrap / "kiro" / "steering" / "diagram-lint.md"))

    for candidate in candidates:
        if _isfile(candidate):
            return candidate
    return None


def _isfile(candidate: Optional[str]) -> bool:
    try:
        return bool(candidate) and os.path.isfile(candidate)
    except OSError:
        return False


def ruleset_available(
    ruleset_path: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> bool:
    """Return True when the authoritative ruleset exists and is readable.

    A ruleset is available only when a candidate file is found and its contents
    can be read without raising (Requirement 7 AC14). An empty file is treated
    as unavailable, since it would carry no rules.
    """
    resolved = find_ruleset(ruleset_path, workspace_root)
    if resolved is None:
        return False
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            return bool(fh.read().strip())
    except OSError:
        return False


def require_ruleset(workspace_root: Optional[str] = None) -> str:
    """Resolve the ruleset path or raise :class:`RulesetUnavailableError`.

    This is the single entry point the Lint_CLI and the Contract use to locate
    the ruleset and fail closed (Requirement 10.2). It resolves through
    :func:`find_ruleset` (so the ``RULE_ENGINE_RULESET`` env var,
    ``workspace_root`` and the fallbacks all apply), then confirms the file is
    readable and non-empty. On any failure it raises
    :class:`RulesetUnavailableError`, which the CLI maps to exit code 2 and the
    Contract to a generation error, both before any file is written.
    """
    resolved = find_ruleset(workspace_root=workspace_root)
    if resolved is None:
        env_path = _env_ruleset()
        if env_path is not None:
            raise RulesetUnavailableError(
                path=env_path,
                reason=f"{RULESET_ENV_VAR} is set but the path does not exist",
            )
        raise RulesetUnavailableError(
            reason=f"ruleset not found at {RULESET_RELATIVE_PATH}"
        )
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            if not fh.read().strip():
                raise RulesetUnavailableError(
                    path=resolved, reason="ruleset file is empty"
                )
    except OSError as exc:
        raise RulesetUnavailableError(
            path=resolved, reason=f"ruleset could not be read: {exc}"
        ) from exc
    return resolved


# ---------------------------------------------------------------------------
# Rule-table parser (Requirement 10.1)
# ---------------------------------------------------------------------------

# The severity tokens the ruleset uses, in the order the sync test treats as the
# "default" when a cell carries two (e.g. ``ERROR/WARNING`` / ``WARNING/ERROR``).
_SEVERITY_TOKENS = ("CRITICAL", "ERROR", "WARNING")

# A rule name rendered as an inline-code span in the first table column, e.g.
# ``| `node-count` | …``. The Diagram Class table sometimes decorates the name
# with a trailing qualifier (``| `edge-routing` (icon crossing) | …``); the
# leading code span is what identifies the rule.
_RULE_NAME_RE = re.compile(r"^`([a-z][a-z0-9-]*)`")


@dataclass(frozen=True)
class RuleRow:
    """One rule as declared in ``diagram-lint.md``.

    Attributes
    ----------
    name:
        The stable rule name (the inline-code span in the ``## Lint Rules``
        table's first column).
    default:
        The rule's default (``flow``) severity — the first severity token of the
        ``## Lint Rules`` "Severity" cell. A cell such as ``WARNING/ERROR`` or
        ``ERROR/WARNING`` records ``default`` as its first token and every token
        in :attr:`severities`.
    landscape:
        The ``landscape``-class severity from the ``## Diagram Class``
        escalation table, or ``None`` when the rule is not escalated there (its
        landscape severity then equals :attr:`default`).
    severities:
        Every severity token found in the "Severity" cell, in document order.
        For a single-severity rule this is a one-element tuple.
    """

    name: str
    default: Optional[str]
    landscape: Optional[str] = None
    severities: tuple = ()


def _split_row(line: str) -> Optional[List[str]]:
    """Split a Markdown table row into its cell texts, or ``None`` if not a row.

    A table row starts (ignoring leading whitespace) with ``|``. Leading and
    trailing empty cells introduced by the outer pipes are dropped.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    parts = stripped.split("|")
    # ``|a|b|`` -> ['', 'a', 'b', ''] — drop the outer empties.
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _is_delimiter_row(cells: List[str]) -> bool:
    """True for a GFM header delimiter row (``| --- | --- |``)."""
    return bool(cells) and all(set(c) <= {"-", ":", " "} and "-" in c for c in cells)


def _rule_name(cell: str) -> Optional[str]:
    match = _RULE_NAME_RE.match(cell.strip())
    return match.group(1) if match else None


def _severity_tokens(cell: str) -> List[str]:
    """Extract the severity tokens (in order) from a "Severity" cell.

    Handles ``ERROR``, ``WARNING``, ``CRITICAL``, slash-joined pairs
    (``WARNING/ERROR``), and bold-wrapped tokens (``**ERROR**``). Non-severity
    cells (``n/a``, prose, size budgets) yield an empty list.
    """
    upper = cell.upper()
    found: List[tuple] = []
    for token in _SEVERITY_TOKENS:
        start = 0
        while True:
            idx = upper.find(token, start)
            if idx == -1:
                break
            found.append((idx, token))
            start = idx + 1
    found.sort(key=lambda pair: pair[0])
    # De-duplicate while preserving first-seen order (a token may repeat in the
    # prose, e.g. "WARNING for flow; ERROR for landscape").
    seen = set()
    ordered: List[str] = []
    for _idx, token in found:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _iter_section_rows(text: str, heading: str):
    """Yield the split cells of every table row inside the given ``## heading``.

    A section runs from its ``## heading`` line to the next line beginning with
    ``## `` (or end of file). Header and delimiter rows are skipped.
    """
    lines = text.splitlines()
    in_section = False
    saw_delimiter = False
    heading_norm = heading.strip().casefold()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].strip().casefold()
            # Match on a prefix so "Diagram Class (flow vs landscape)" matches
            # the "Diagram Class" heading.
            entering = title == heading_norm or title.startswith(heading_norm)
            if entering:
                in_section = True
                saw_delimiter = False
                continue
            if in_section:
                break
            continue
        if not in_section:
            continue
        cells = _split_row(line)
        if cells is None:
            continue
        if _is_delimiter_row(cells):
            saw_delimiter = True
            continue
        if not saw_delimiter:
            # This is the header row (before the delimiter); skip it.
            continue
        yield cells


def parse_rule_table(text: str) -> Dict[str, RuleRow]:
    """Parse the ``## Lint Rules`` and ``## Diagram Class`` tables.

    Returns a mapping ``{rule_name: RuleRow}`` where ``default`` is the first
    severity token of the ``## Lint Rules`` "Severity" cell and ``landscape`` is
    the escalated severity from the ``## Diagram Class`` table (``None`` when the
    rule has no landscape escalation there).

    Only rows whose first cell is an inline-code rule name are collected; the
    Diagram Class table's non-rule rows (``numbered flow markers``,
    ``raster budget``) and its ``n/a`` cells are ignored. This mirrors the
    engine's ``RULE_SEVERITIES`` (defaults) and ``CLASS_ESCALATIONS`` (landscape
    overrides), so a sync test can compare the document with the code
    (Requirement 10.1).
    """
    rows: Dict[str, RuleRow] = {}

    # ## Lint Rules — columns: | Rule | Condition | Severity | Source |
    for cells in _iter_section_rows(text, "Lint Rules"):
        if len(cells) < 3:
            continue
        name = _rule_name(cells[0])
        if name is None:
            continue
        tokens = _severity_tokens(cells[2])
        default = tokens[0] if tokens else None
        rows[name] = RuleRow(
            name=name,
            default=default,
            landscape=None,
            severities=tuple(tokens),
        )

    # ## Diagram Class — columns: | Rule | flow (default) | landscape |
    for cells in _iter_section_rows(text, "Diagram Class"):
        if len(cells) < 3:
            continue
        name = _rule_name(cells[0])
        if name is None:
            continue
        landscape_tokens = _severity_tokens(cells[2])
        landscape = landscape_tokens[0] if landscape_tokens else None
        existing = rows.get(name)
        if existing is None:
            # A rule that only appears in the Diagram Class table (e.g.
            # ``orphan-landscape`` is in Lint Rules too, but be defensive).
            flow_tokens = _severity_tokens(cells[1])
            rows[name] = RuleRow(
                name=name,
                default=flow_tokens[0] if flow_tokens else None,
                landscape=landscape,
                severities=tuple(flow_tokens),
            )
        else:
            rows[name] = RuleRow(
                name=existing.name,
                default=existing.default,
                landscape=landscape,
                severities=existing.severities,
            )

    return rows


__all__ = [
    "RULESET_RELATIVE_PATH",
    "RULESET_ENV_VAR",
    "RULESET_UNAVAILABLE_ERROR",
    "RulesetUnavailableError",
    "find_ruleset",
    "ruleset_available",
    "require_ruleset",
    "RuleRow",
    "parse_rule_table",
]
