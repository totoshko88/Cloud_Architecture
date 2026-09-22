"""Diagram & Inventory Rule Engine — Linter.

This module implements the lint ruleset engine defined by the authoritative
ruleset ``.kiro/steering/diagram-lint.md`` (Requirement 7). It evaluates a
single artifact (a diagram, a Markdown document, or a snapshot file) against
every applicable rule, assigns each finding a severity of ``CRITICAL``,
``ERROR``, or ``WARNING``, and reports publication eligibility.

Public interface::

    lint(artifact) -> {
        "findings": [ { "rule": str, "severity": str }, ... ],
        "eligible_for_publication": bool,   # True iff zero CRITICAL and zero ERROR
    }

An artifact is eligible for publication if and only if it has zero CRITICAL and
zero ERROR findings; WARNING findings never block publication (Requirement 7
AC2–AC3).

The ruleset-unavailable behavior (Requirement 7 AC14) and the ``rule-engine-lint``
CLI entry point (see :mod:`rule_engine.cli`) are implemented alongside the rule
engine here: :func:`lint_with_ruleset` and :func:`ruleset_available` guard every
evaluation on the presence and readability of the authoritative ruleset
``.kiro/steering/diagram-lint.md``. When the ruleset is missing or unreadable the
Linter returns a ``ruleset-unavailable`` error and reports every evaluated
artifact as blocked from publication.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

# Narrow raw-content secret vocabulary (single source of truth, REVIEW.md U2).
# The linter scans RAW snapshot content, so it uses the value-oriented
# SECRET_CONTENT_MARKERS — not the broad key-name list — to avoid false CRITICAL
# findings on secret-free metadata (e.g. the type value ``secrets_store``).
from rule_engine.constants import SECRET_CONTENT_MARKERS as _SECRET_MARKERS


# ---------------------------------------------------------------------------
# Severities and rule names
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """Lint finding severity scale (``diagram-lint.md`` — Severity Scale)."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"


# Stable rule names, aligned with the authoritative ruleset table.
RULE_NODE_COUNT = "node-count"
RULE_EDGE_LABEL = "edge-label"
RULE_NODE_QUOTE = "node-quote"
RULE_LEGEND_PRESENT = "legend-present"
RULE_COMPANION_DOC = "companion-doc"
RULE_FRONTMATTER = "frontmatter"
RULE_ICON_RESOLVED = "icon-resolved"
RULE_SECRET_SAFETY = "secret-safety"
RULE_TITLE_VERSIONED = "title-versioned"
RULE_MERMAID_TYPE = "mermaid-type"
RULE_MIN_FONT_SIZE = "min-font-size"
RULE_GRID_ALIGNMENT = "grid-alignment"
RULE_CONTAINER_PADDING = "container-padding"
RULE_EDGE_ROUTING = "edge-routing"
RULE_NODE_OVERLAP = "node-overlap"
RULE_ARROW_STYLE = "arrow-style"

# Severity assigned to each rule when its condition holds (authoritative table).
RULE_SEVERITIES: Dict[str, Severity] = {
    RULE_NODE_COUNT: Severity.ERROR,
    RULE_EDGE_LABEL: Severity.WARNING,
    RULE_NODE_QUOTE: Severity.ERROR,
    RULE_LEGEND_PRESENT: Severity.ERROR,
    RULE_COMPANION_DOC: Severity.ERROR,
    RULE_FRONTMATTER: Severity.CRITICAL,
    RULE_ICON_RESOLVED: Severity.ERROR,
    RULE_SECRET_SAFETY: Severity.CRITICAL,
    RULE_TITLE_VERSIONED: Severity.WARNING,
    RULE_MERMAID_TYPE: Severity.WARNING,
    RULE_MIN_FONT_SIZE: Severity.WARNING,
    RULE_GRID_ALIGNMENT: Severity.WARNING,
    RULE_CONTAINER_PADDING: Severity.WARNING,
    RULE_EDGE_ROUTING: Severity.WARNING,
    RULE_NODE_OVERLAP: Severity.WARNING,
    RULE_ARROW_STYLE: Severity.WARNING,
}

# Maximum node count for a single diagram (Requirement 1 AC4 / 7 AC4).
MAX_NODES = 12

# Minimum on-diagram font size, in px. AWS diagram conventions require a >= 12px
# floor for text readability/accessibility (diagram-standards.md "Accessibility &
# Contrast"). Any diagram text below this trips the advisory ``min-font-size``
# rule. Mirrors ``rule_engine.diagram_layout.MIN_FONT_SIZE``.
MIN_FONT_SIZE = 12

# Matches every ``fontSize=<n>`` occurrence in a draw.io style string.
_FONT_SIZE_RE = re.compile(r"fontSize=([0-9]+)")

# Allowed unquoted character set for a node name (Requirement 1 AC6 / 7 AC6).
_UNQUOTED_NODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Diagram types for which Mermaid is permitted (Requirement 1 AC2 / 7 AC13).
_MERMAID_ALLOWED_TYPES = frozenset({"sequence", "flow", "state"})

# The twelve required frontmatter keys (kb-frontmatter.md / Requirement 8 AC1).
REQUIRED_FRONTMATTER_KEYS = (
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

# ISO 8601 calendar date (YYYY-MM-DD) as used in title cells (Requirement 5 AC9).
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Version identifier vN, where N is a positive integer (Requirement 5 AC9).
_VERSION_RE = re.compile(r"\bv[1-9][0-9]*\b")


# ---------------------------------------------------------------------------
# Artifact input model
# ---------------------------------------------------------------------------


@dataclass
class Edge:
    """A diagram edge. ``label`` must be a non-empty string to satisfy
    ``edge-label`` (Requirement 1 AC7 / 7 AC5)."""

    source: str = ""
    target: str = ""
    label: Optional[str] = None


@dataclass
class Artifact:
    """Neutral input model for the Linter.

    A single ``Artifact`` can represent a diagram, a Markdown document, or a
    snapshot file. Fields that do not apply to an artifact's ``kind`` are simply
    left at their defaults; each rule only inspects the fields relevant to the
    condition it checks, and skips artifacts of the wrong kind.

    Attributes
    ----------
    kind:
        One of ``"diagram"``, ``"document"``, or ``"snapshot"``.
    path:
        Optional artifact path, used for reporting and for the companion-doc
        pairing check.

    Diagram fields
    --------------
    node_names:
        The names of the diagram's nodes. ``node-count`` counts these and
        ``node-quote`` inspects each for unquoted special characters.
    edges:
        The diagram's edges; ``edge-label`` requires each to carry a non-empty
        label.
    has_legend:
        Whether the diagram includes a Legend block (``legend-present``).
    icons:
        Icon descriptors for the diagram. Each may be a mapping with a
        ``resolved`` boolean / ``placeholder`` boolean, or a plain string
        (a bare ``"placeholder"`` string is treated as unresolved).
    title_cell:
        The diagram title-cell text; ``title-versioned`` requires both a
        version identifier and an ISO 8601 date.
    source_format:
        ``"plantuml"`` or ``"mermaid"``; ``mermaid-type`` fires when Mermaid is
        used for a diagram type outside sequence/flow/state.
    diagram_type:
        e.g. ``"sequence"``, ``"flow"``, ``"state"``, ``"c4"``, ``"component"``.
    is_drawio:
        Whether this diagram is authored as a ``.drawio`` source file.
    has_companion_doc:
        Whether a matching ``.diagram.md`` companion exists for a ``.drawio``
        source (``companion-doc``).

    Document fields
    ---------------
    frontmatter:
        The parsed YAML frontmatter mapping; ``frontmatter`` fires when any
        required key is absent or empty.
    is_markdown:
        Whether this artifact is a Markdown document (frontmatter applies).

    Snapshot fields
    ---------------
    is_snapshot_file:
        Whether this artifact is a snapshot file (secret-safety applies).
    contains_secret:
        Explicit flag that the snapshot file contains a secret value, key
        material, or SecureString value.
    content:
        Optional raw snapshot content, scanned heuristically for secrets when
        ``contains_secret`` is not set.
    """

    kind: str = "diagram"
    path: Optional[str] = None

    # Diagram
    node_names: Sequence[str] = field(default_factory=list)
    edges: Sequence[Edge] = field(default_factory=list)
    has_legend: bool = True
    icons: Sequence[Any] = field(default_factory=list)
    # Font sizes (px) of the diagram's text-bearing cells, harvested from the
    # draw.io ``fontSize=<n>`` style tokens. ``min-font-size`` flags any below
    # ``MIN_FONT_SIZE``. Empty means "not parsed" and the rule is skipped.
    font_sizes: Sequence[int] = field(default_factory=list)
    # Optional parsed geometry (rule_engine.geometry.DiagramGeometry). When the
    # CLI parses a .drawio file it attaches this so the geometry-aware rules
    # (grid-alignment, container-padding, edge-routing, node-overlap) can run.
    # Left None for programmatic artifacts; those rules then no-op.
    geometry: Any = None
    title_cell: Optional[str] = None
    source_format: str = "plantuml"
    diagram_type: Optional[str] = None
    is_drawio: bool = False
    has_companion_doc: bool = True

    # Document
    frontmatter: Optional[Mapping[str, Any]] = None
    is_markdown: bool = False

    # Snapshot
    is_snapshot_file: bool = False
    contains_secret: bool = False
    content: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ARTIFACT_FIELDS = {f for f in Artifact.__dataclass_fields__}


def _coerce_artifact(artifact: Any) -> Artifact:
    """Accept either an :class:`Artifact` or a plain mapping (dict)."""
    if isinstance(artifact, Artifact):
        return artifact
    if isinstance(artifact, Mapping):
        data = {k: v for k, v in artifact.items() if k in _ARTIFACT_FIELDS}
        edges = data.get("edges")
        if edges is not None:
            data["edges"] = [
                e if isinstance(e, Edge) else Edge(**{k: v for k, v in e.items()})
                if isinstance(e, Mapping)
                else e
                for e in edges
            ]
        return Artifact(**data)
    raise TypeError(
        "artifact must be an Artifact instance or a mapping, got "
        f"{type(artifact).__name__}"
    )


def _is_diagram(a: Artifact) -> bool:
    return a.kind == "diagram"


def _is_document(a: Artifact) -> bool:
    return a.kind == "document" or a.is_markdown


def _is_snapshot(a: Artifact) -> bool:
    return a.kind == "snapshot" or a.is_snapshot_file


def _icon_is_unresolved(icon: Any) -> bool:
    """Return True when an icon descriptor is an unresolved placeholder."""
    if isinstance(icon, Mapping):
        if icon.get("placeholder") is True:
            return True
        if "resolved" in icon:
            return not bool(icon.get("resolved"))
        # A descriptor with an empty/absent style string is unresolved.
        style = icon.get("style") or icon.get("style_string")
        return not style
    if isinstance(icon, str):
        return icon.strip().lower() in {"", "placeholder", "unresolved"}
    # An icon of None is unresolved; anything else is treated as resolved.
    return icon is None


# The heuristic markers for secret material in raw snapshot content are the
# shared _SECRET_MARKERS imported at the top of this module (REVIEW.md U2), used
# only when the caller has not set the explicit ``contains_secret`` flag.


def _content_has_secret(content: Optional[str]) -> bool:
    if not content:
        return False
    lowered = content.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


# ---------------------------------------------------------------------------
# Individual rule checks — each returns True when its finding condition holds
# ---------------------------------------------------------------------------


def _check_node_count(a: Artifact) -> bool:
    """node-count: a diagram contains more than 12 nodes (ERROR)."""
    return _is_diagram(a) and len(a.node_names) > MAX_NODES


def _check_edge_label(a: Artifact) -> bool:
    """edge-label: a diagram edge has no non-empty label (WARNING)."""
    if not _is_diagram(a):
        return False
    for edge in a.edges:
        label = getattr(edge, "label", None) if not isinstance(edge, Mapping) else edge.get("label")
        if label is None or str(label).strip() == "":
            return True
    return False


def _check_node_quote(a: Artifact) -> bool:
    """node-quote: a special-character node name is not double-quoted (ERROR)."""
    if not _is_diagram(a):
        return False
    for name in a.node_names:
        if name is None:
            continue
        text = str(name)
        # Already double-quoted names are compliant regardless of contents.
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            continue
        if not _UNQUOTED_NODE_RE.match(text):
            return True
    return False


def _check_legend_present(a: Artifact) -> bool:
    """legend-present: a diagram has no Legend (ERROR)."""
    return _is_diagram(a) and not a.has_legend


def _check_companion_doc(a: Artifact) -> bool:
    """companion-doc: a `.drawio` file has no matching `.diagram.md` (ERROR)."""
    if not _is_diagram(a):
        return False
    if not a.is_drawio:
        return False
    return not a.has_companion_doc


def _check_frontmatter(a: Artifact) -> bool:
    """frontmatter: a Markdown document is missing/empty a required key (CRITICAL)."""
    if not _is_document(a):
        return False
    fm = a.frontmatter
    if fm is None:
        # A Markdown document with no frontmatter at all is missing every key.
        return True
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in fm:
            return True
        value = fm[key]
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == "":
            return True
        if isinstance(value, (list, tuple, dict)) and len(value) == 0:
            return True
    return False


def _check_icon_resolved(a: Artifact) -> bool:
    """icon-resolved: a diagram icon is an unresolved placeholder (ERROR)."""
    if not _is_diagram(a):
        return False
    return any(_icon_is_unresolved(icon) for icon in a.icons)


def _check_secret_safety(a: Artifact) -> bool:
    """secret-safety: a snapshot file contains a secret/key/SecureString (CRITICAL)."""
    if not _is_snapshot(a):
        return False
    if a.contains_secret:
        return True
    return _content_has_secret(a.content)


def _check_title_versioned(a: Artifact) -> bool:
    """title-versioned: a title cell has no version identifier or no date (WARNING)."""
    if not _is_diagram(a):
        return False
    title = a.title_cell
    if title is None:
        # No title cell at all lacks both the version and the date.
        return True
    has_version = bool(_VERSION_RE.search(title))
    has_date = bool(_ISO_DATE_RE.search(title))
    return not (has_version and has_date)


def _check_min_font_size(a: Artifact) -> bool:
    """min-font-size: a diagram carries text below MIN_FONT_SIZE px (WARNING).

    AWS diagram conventions require a >= 12px font floor for readability and
    accessibility (diagram-standards.md "Accessibility & Contrast"). The check
    inspects ``font_sizes`` harvested from the diagram's ``fontSize=<n>`` style
    tokens; an empty list means the sizes were not parsed and the rule is
    skipped (never a false positive on a programmatic Artifact).
    """
    if not _is_diagram(a):
        return False
    return any(int(fs) < MIN_FONT_SIZE for fs in a.font_sizes)


def _check_mermaid_type(a: Artifact) -> bool:
    """mermaid-type: Mermaid used for a non sequence/flow/state diagram (WARNING)."""
    if not _is_diagram(a):
        return False
    if (a.source_format or "").lower() != "mermaid":
        return False
    dtype = (a.diagram_type or "").lower()
    return dtype not in _MERMAID_ALLOWED_TYPES


# --- Geometry-aware rules (REVIEW.md D2/D3/D6) ---------------------------------
# These operate on the optional ``geometry`` attached by the CLI .drawio parser
# (rule_engine.geometry.DiagramGeometry). When no geometry is present (a
# programmatic artifact or a non-diagram), each predicate returns False, so the
# rule never fires spuriously.


def _geometry_of(a: Artifact):
    return getattr(a, "geometry", None) if _is_diagram(a) else None


def _check_grid_alignment(a: Artifact) -> bool:
    """grid-alignment: a node's absolute x/y is not a multiple of the grid (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_grid_alignment(geo))


def _check_container_padding(a: Artifact) -> bool:
    """container-padding: a node sits <1 grid step from / straddles a container (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_container_padding(geo))


def _check_edge_routing(a: Artifact) -> bool:
    """edge-routing: a non-orthogonal edge, or a waypoint-free edge crossing a node (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_edge_routing(geo))


def _check_node_overlap(a: Artifact) -> bool:
    """node-overlap: two node icon boxes overlap (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_node_overlap(geo))


def _check_arrow_style(a: Artifact) -> bool:
    """arrow-style: an edge uses a filled/heavy arrowhead or a sub-1pt stroke (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_arrow_style(geo))


# Ordered rule registry: (rule name, predicate). Order defines finding order.
_RULES = (
    (RULE_NODE_COUNT, _check_node_count),
    (RULE_EDGE_LABEL, _check_edge_label),
    (RULE_NODE_QUOTE, _check_node_quote),
    (RULE_LEGEND_PRESENT, _check_legend_present),
    (RULE_COMPANION_DOC, _check_companion_doc),
    (RULE_FRONTMATTER, _check_frontmatter),
    (RULE_ICON_RESOLVED, _check_icon_resolved),
    (RULE_SECRET_SAFETY, _check_secret_safety),
    (RULE_TITLE_VERSIONED, _check_title_versioned),
    (RULE_MERMAID_TYPE, _check_mermaid_type),
    (RULE_MIN_FONT_SIZE, _check_min_font_size),
    (RULE_GRID_ALIGNMENT, _check_grid_alignment),
    (RULE_CONTAINER_PADDING, _check_container_padding),
    (RULE_EDGE_ROUTING, _check_edge_routing),
    (RULE_NODE_OVERLAP, _check_node_overlap),
    (RULE_ARROW_STYLE, _check_arrow_style),
)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

_BLOCKING_SEVERITIES = frozenset({Severity.CRITICAL, Severity.ERROR})


# ---------------------------------------------------------------------------
# Ruleset-unavailable handling (Requirement 7 AC14)
# ---------------------------------------------------------------------------

# The authoritative lint ruleset, relative to the workspace root.
RULESET_RELATIVE_PATH = os.path.join(".kiro", "steering", "diagram-lint.md")

# The error code the Linter returns when the ruleset is missing/unreadable.
RULESET_UNAVAILABLE_ERROR = "ruleset-unavailable"


class RulesetUnavailableError(RuntimeError):
    """Raised when the authoritative ``diagram-lint.md`` ruleset cannot be read.

    Carries the error code (``ruleset-unavailable``) and the resolved path that
    was probed, so callers can surface a precise blocking reason.
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


def find_ruleset(
    ruleset_path: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> Optional[str]:
    """Locate the authoritative ``diagram-lint.md`` ruleset.

    Resolution has two modes:

    **Explicit mode** — when ``ruleset_path`` or ``workspace_root`` is provided,
    only those explicit locations are probed (plus the ``RULE_ENGINE_RULESET``
    environment variable). No implicit cwd/module fallbacks are consulted, so a
    caller can deliberately point at a location with no ruleset (e.g. to test the
    ruleset-unavailable path) and get ``None``.

    **Implicit mode** — when neither argument is given, the search order is:

    1. The ``RULE_ENGINE_RULESET`` environment variable, when set.
    2. ``<cwd>/.kiro/steering/diagram-lint.md``.
    3. A search upward from this module's location for a ``.kiro/steering``
       directory (so the CLI works from within the installed package tree).

    Returns the first candidate path that exists as a file, or ``None`` when no
    candidate is found. Existence — not readability — is checked here;
    :func:`ruleset_available` performs the read check.
    """
    candidates: List[str] = []
    env_path = os.environ.get("RULE_ENGINE_RULESET")

    explicit = bool(ruleset_path or workspace_root)
    if explicit:
        if ruleset_path:
            candidates.append(ruleset_path)
        if workspace_root:
            candidates.append(os.path.join(workspace_root, RULESET_RELATIVE_PATH))
        if env_path:
            candidates.append(env_path)
    else:
        if env_path:
            candidates.append(env_path)
        candidates.append(os.path.join(os.getcwd(), RULESET_RELATIVE_PATH))
        # Walk upward from this file toward filesystem root looking for the
        # steering directory (covers `src/rule_engine/linter.py` -> workspace
        # root layouts).
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidates.append(str(parent / RULESET_RELATIVE_PATH))

    for candidate in candidates:
        try:
            if candidate and os.path.isfile(candidate):
                return candidate
        except OSError:
            continue
    return None


def ruleset_available(
    ruleset_path: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> bool:
    """Return True when the authoritative ruleset exists and is readable.

    A ruleset is considered available only when a candidate file is found and
    its contents can be read without raising (Requirement 7 AC14). An empty file
    is treated as unreadable/unavailable, since the ruleset would carry no rules.
    """
    resolved = find_ruleset(ruleset_path, workspace_root)
    if resolved is None:
        return False
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            return bool(fh.read().strip())
    except OSError:
        return False


def _blocked_result(reason: str, resolved: Optional[str]) -> Dict[str, Any]:
    """Build a fail-closed lint result for the ruleset-unavailable case."""
    return {
        "findings": [],
        "eligible_for_publication": False,
        "error": RULESET_UNAVAILABLE_ERROR,
        "error_detail": reason,
        "ruleset_path": resolved,
    }


def lint_with_ruleset(
    artifact: Any,
    ruleset_path: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Ruleset-guarded variant of :func:`lint` (Requirement 7 AC14).

    First confirms the authoritative ``diagram-lint.md`` ruleset is present and
    readable. When it is unavailable, no rules are evaluated: the artifact is
    reported as **blocked from publication** (``eligible_for_publication`` is
    ``False``) and the result carries the ``ruleset-unavailable`` error code.
    When the ruleset is available, this delegates to :func:`lint` and the result
    is identical to calling :func:`lint` directly.

    Returns
    -------
    dict
        On success, the same shape as :func:`lint`. On unavailability,
        ``{"findings": [], "eligible_for_publication": False,
        "error": "ruleset-unavailable", "error_detail": str,
        "ruleset_path": Optional[str]}``.
    """
    resolved = find_ruleset(ruleset_path, workspace_root)
    if resolved is None:
        return _blocked_result(
            f"ruleset not found at {RULESET_RELATIVE_PATH}", None
        )
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            if not fh.read().strip():
                return _blocked_result("ruleset file is empty", resolved)
    except OSError as exc:
        return _blocked_result(f"ruleset could not be read: {exc}", resolved)

    return lint(artifact)


def lint(artifact: Any) -> Dict[str, Any]:
    """Evaluate ``artifact`` against every applicable lint rule.

    Parameters
    ----------
    artifact:
        An :class:`Artifact` instance or an equivalent mapping.

    Returns
    -------
    dict
        ``{"findings": [{"rule": str, "severity": str}, ...],
        "eligible_for_publication": bool}``. Eligibility is True if and only if
        there are zero CRITICAL and zero ERROR findings (Requirement 7 AC2–AC3).
    """
    art = _coerce_artifact(artifact)

    findings: List[Dict[str, str]] = []
    for rule_name, predicate in _RULES:
        if predicate(art):
            findings.append(
                {"rule": rule_name, "severity": RULE_SEVERITIES[rule_name].value}
            )

    eligible = not any(
        Severity(f["severity"]) in _BLOCKING_SEVERITIES for f in findings
    )

    return {"findings": findings, "eligible_for_publication": eligible}


__all__ = [
    "Severity",
    "Edge",
    "Artifact",
    "lint",
    "lint_with_ruleset",
    "ruleset_available",
    "find_ruleset",
    "RulesetUnavailableError",
    "RULESET_UNAVAILABLE_ERROR",
    "RULESET_RELATIVE_PATH",
    "RULE_SEVERITIES",
    "REQUIRED_FRONTMATTER_KEYS",
    "MAX_NODES",
    "RULE_NODE_COUNT",
    "RULE_EDGE_LABEL",
    "RULE_NODE_QUOTE",
    "RULE_LEGEND_PRESENT",
    "RULE_COMPANION_DOC",
    "RULE_FRONTMATTER",
    "RULE_ICON_RESOLVED",
    "RULE_SECRET_SAFETY",
    "RULE_MIN_FONT_SIZE",
    "RULE_GRID_ALIGNMENT",
    "RULE_CONTAINER_PADDING",
    "RULE_EDGE_ROUTING",
    "RULE_NODE_OVERLAP",
    "RULE_ARROW_STYLE",
    "RULE_TITLE_VERSIONED",
    "RULE_MERMAID_TYPE",
]
