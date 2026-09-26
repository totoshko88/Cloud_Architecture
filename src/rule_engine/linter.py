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
RULE_ORPHAN_LANDSCAPE = "orphan-landscape"
RULE_OVERLAY_LEGEND_COVERAGE = "overlay-legend-coverage"
RULE_CONTAINER_OVERLAP = "container-overlap"
RULE_EDGE_DIRECTION = "edge-direction"
RULE_TEXT_PADDING = "text-padding"
RULE_CORRIDOR_SHARING = "corridor-sharing"
RULE_EDGE_FLOAT = "edge-float"
RULE_EXIT_THIRDS = "exit-thirds"
RULE_ENTRY_THIRDS = "entry-thirds"
RULE_EDGE_CROSSES_LABEL = "edge-crosses-label"
RULE_EDGE_CROSSES_CONTAINER_LABEL = "edge-crosses-container-label"
RULE_LEGEND_PLACEMENT = "legend-placement"
RULE_FLOW_LEGEND = "flow-legend"
RULE_NODE_CONNECTIVITY = "node-connectivity"
RULE_EDGE_APPROACH = "edge-approach"

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
    RULE_ORPHAN_LANDSCAPE: Severity.ERROR,
    RULE_OVERLAY_LEGEND_COVERAGE: Severity.WARNING,
    # container-overlap and edge-direction default to WARNING; both are raised
    # to ERROR for the ``landscape`` class (see their predicates), where nested
    # boundaries and a strict directional contract are what keep a large
    # as-built legible.
    RULE_CONTAINER_OVERLAP: Severity.WARNING,
    RULE_EDGE_DIRECTION: Severity.WARNING,
    # Text-box padding and long-edge corridor sharing are WARNINGs for both
    # classes. edge-float (no explicit contact points) is a WARNING for flow and
    # raised to ERROR for landscape (a dense diagram must fix every contact side).
    RULE_TEXT_PADDING: Severity.WARNING,
    RULE_CORRIDOR_SHARING: Severity.WARNING,
    RULE_EDGE_FLOAT: Severity.WARNING,
    # Same-side fan-out must use the centred / even-thirds split, and a side may
    # carry at most three exits (diagram-standards → Label-safe exits). A WARNING
    # for both classes: it surfaces cramped or lopsided fan-outs without blocking.
    RULE_EXIT_THIRDS: Severity.WARNING,
    # entry-thirds (v1.5.1): the entry-side mirror of exit-thirds — several edges
    # arriving on one target face at the same/merged contact point. WARNING for
    # flow; raised to ERROR for landscape (see the predicate), matching the other
    # routing-family escalations.
    RULE_ENTRY_THIRDS: Severity.WARNING,
    # An edge whose routed polyline crosses another node's label band (caption
    # strip below the icon). Advisory WARNING for both classes: it catches a run
    # cutting through a service name that the icon-box geometry rules miss.
    RULE_EDGE_CROSSES_LABEL: Severity.WARNING,
    # edge-crosses-container-label (v1.5.1): a routed edge whose polyline runs
    # through a Boundary container's top caption band (e.g. a cross-region
    # corridor slicing the ``vpc-passive`` label). Advisory WARNING for both
    # classes — the mirror of edge-crosses-label for container captions.
    RULE_EDGE_CROSSES_CONTAINER_LABEL: Severity.WARNING,
    # legend-placement (v1.6.0): the Flow/Legend furniture must sit in the right
    # margin, past the outermost container and clear of the cloud boxes. A
    # clean-room install parked both blocks in the LEFT margin and linted clean.
    RULE_LEGEND_PLACEMENT: Severity.WARNING,
    # flow-legend: numeric flow markers on edges require a ``Flow`` legend cell
    # covering every marker. Documented in diagram-lint.md since v1.0.0 but only
    # IMPLEMENTED in v1.6.0 — a ruleset/code drift of the same kind 1.5.3/1.5.4
    # closed for other rules.
    RULE_FLOW_LEGEND: Severity.WARNING,
    # node-connectivity (v1.6.0): a role-bearing node drawn with zero incident
    # edges. The engine draws an inventory rather than an architecture when two
    # thirds of the nodes float (the 2026-09-25 audit's headline finding: 20 of
    # 34 nodes on every HA landscape). WARNING for both classes to start.
    RULE_NODE_CONNECTIVITY: Severity.WARNING,
    # edge-approach (v1.6.0): a route leg that is not axis-aligned, or a contact
    # leg that does not meet its face head-on. An orthogonalEdgeStyle edge never
    # draws a diagonal — draw.io inserts its OWN corner and picks the direction —
    # so an unaligned pair is a corner the author did not specify, and every other
    # geometry check reads the points as given and cannot see it.
    RULE_EDGE_APPROACH: Severity.WARNING,
}

# Maximum node count for a single diagram (Requirement 1 AC4 / 7 AC4).
MAX_NODES = 12

# Landscape (as-built / inventory) node-count thresholds (v1.3.0). A landscape
# diagram relaxes the flow 12-node cap because its job is completeness on one
# canvas; readability is instead enforced by the geometry rules (container
# padding raised to ERROR, edge routing, node overlap) and the summary
# cross-link contract.
LANDSCAPE_NODE_WARN = 30
LANDSCAPE_NODE_ERROR = 50

# The two diagram classes. ``flow`` (default) keeps every legacy rule exactly
# as before, so all pre-1.3.0 artifacts lint unchanged. ``landscape`` branches
# the node-count severity and enables the pair-contract and overlay rules.
DIAGRAM_CLASS_FLOW = "flow"
DIAGRAM_CLASS_LANDSCAPE = "landscape"

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

    # Diagram class (v1.3.0). ``"flow"`` (default) keeps the 12-node cap and all
    # legacy rules unchanged. ``"landscape"`` is an as-built / inventory diagram:
    # relaxed node-count (WARNING>30, ERROR>50), container-padding raised to
    # ERROR, and a required cross-link to a <=12-node flow summary.
    diagram_class: str = "flow"
    # Cross-link contract. A landscape declares ``summary_of`` (path/stem of its
    # flow summary); a flow may declare ``detailed_view`` (path/stem of its
    # landscape). Parsed from the companion .diagram.md frontmatter by the CLI.
    summary_of: Optional[str] = None
    detailed_view: Optional[str] = None
    # Overlay vocabulary (findings/state). When the diagram carries double-encoded
    # overlay markers, ``overlay_markers`` lists them and ``legend_overlay_terms``
    # lists the terms the Legend documents; overlay-legend-coverage fires when a
    # marker is not covered by the legend.
    overlay_markers: Sequence[str] = field(default_factory=list)
    legend_overlay_terms: Sequence[str] = field(default_factory=list)
    # Text-box padding (v1.3.x). ``text_padding_offenders`` lists the styles of
    # any ``text;`` cell missing uniform inner padding (spacing* tokens); a
    # non-empty list trips ``text-padding``. None means "not parsed" (skip).
    text_padding_offenders: Optional[Sequence[str]] = None
    # Numbered Flow legend (v1.6.0). The rendered lines of the ``Flow`` text cell
    # (first line exactly ``Flow``), used by ``flow-legend`` to verify every
    # numeric edge marker has a matching ``N. <description>`` line. ``None``
    # means "not parsed" (e.g. a programmatic artifact) and the rule is skipped;
    # an empty list means the diagram has no Flow cell at all.
    flow_legend_lines: Optional[Sequence[str]] = None

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


def _check_node_count(a: Artifact):
    """node-count: too many nodes for the diagram class (bool | Severity).

    ``flow`` (default): more than ``MAX_NODES`` (12) is an ERROR, unchanged from
    pre-1.3.0. ``landscape``: relaxed cap — more than ``LANDSCAPE_NODE_ERROR``
    (50) is an ERROR, more than ``LANDSCAPE_NODE_WARN`` (30) is a WARNING,
    otherwise the rule does not fire. Returning an explicit :class:`Severity`
    lets one rule carry class-dependent severity through the aggregator.
    """
    if not _is_diagram(a):
        return False
    n = len(a.node_names)
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        if n > LANDSCAPE_NODE_ERROR:
            return Severity.ERROR
        if n > LANDSCAPE_NODE_WARN:
            return Severity.WARNING
        return False
    return Severity.ERROR if n > MAX_NODES else False


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


#: Required keys whose value is a list that may legitimately be EMPTY.
#: kb-frontmatter bounds ``related_docs`` at 0–20 entries ("empty list
#: allowed"); every other required key must hold a non-empty value. Before
#: 1.6.1 the generic empty-collection test below flagged ``related_docs: []`` as
#: a CRITICAL "missing key", so a document that simply had no related documents
#: was blocked from publication — and callers (contract._frontmatter_dict)
#: worked around it by inventing a related-doc id.
_EMPTY_LIST_ALLOWED_KEYS = frozenset({"related_docs"})


def _check_frontmatter(a: Artifact) -> bool:
    """frontmatter: a Markdown document is missing/empty a required key (CRITICAL).

    A key is missing when it is absent, ``None``, a blank string, or an empty
    collection — except that a key in :data:`_EMPTY_LIST_ALLOWED_KEYS` may hold
    an explicitly empty *list* (``related_docs: []``), which kb-frontmatter
    permits. ``tags`` still needs at least one entry.
    """
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
        if isinstance(value, (list, tuple)) and len(value) == 0:
            if key in _EMPTY_LIST_ALLOWED_KEYS:
                continue
            return True
        if isinstance(value, dict) and len(value) == 0:
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


def _check_container_padding(a: Artifact):
    """container-padding: a node sits <1 grid step from / straddles a container.

    WARNING for ``flow`` (unchanged). Raised to ERROR for ``landscape``, where
    nested labelled containers are what keep a big as-built legible, so a
    padding defect must block publication (v1.3.0).
    """
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    if not bool(_geo.check_container_padding(geo)):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        return Severity.ERROR
    return True


def _check_edge_routing(a: Artifact):
    """edge-routing: a non-orthogonal edge, or an edge whose run crosses a node.

    v1.5.1: an edge whose polyline passes through an unrelated node icon
    (``*-through-*``) is a hard routing defect on ANY class — a line drawn over
    an icon it does not connect (the ALB→S3 corridor cutting the S3 glyph). That
    escalates to ERROR so it blocks publication, not merely warns. A
    non-orthogonal edge with no node crossing stays a WARNING (a style nit, not a
    correctness failure).

    v1.5.4: the ``*-through-*`` family now also covers a **waypointed** edge
    whose real *orthogonal knee* path (not the raw diagonal between points)
    slices an unrelated icon (``knee-through-<node>``) — the devoxx ``e8``
    horizontal stub cutting the RDS glyph. It matches the same ``through-``
    escalation below, so it blocks publication like any other icon crossing."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_routing(geo)
    if not findings:
        return False
    # A run cutting through a node icon — an unrelated node (``*-through-*``) or
    # the edge's own target reached from the wrong side (``pierces-target-*``) —
    # is a hard routing defect and blocks publication. A bare non-orthogonal
    # edge (no crossing) stays a WARNING.
    if any(("through-" in r) or ("pierces-" in r) for _eid, r in findings):
        return Severity.ERROR
    return True


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


def _check_container_overlap(a: Artifact):
    """container-overlap: two sibling boundary containers overlap.

    A proper nesting (Account ⊃ Region ⊃ AZ) is fine; two peer boundaries that
    partially overlap put shared canvas area under two labelled groups at once,
    so a node there is ambiguous about which boundary owns it. WARNING for
    ``flow``; raised to ERROR for ``landscape``, where the nested boundary
    hierarchy is the primary device keeping a big as-built legible (v1.3.x)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    if not bool(_geo.check_container_overlap(geo)):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        return Severity.ERROR
    return True


def _check_edge_direction(a: Artifact):
    """edge-direction: an edge breaks the exit-right/bottom, enter-left/top contract.

    Every edge with explicit contact points must exit its source on the right or
    bottom half and enter its target on the left or top half — the single
    directional rule that removes most crossings on a dense diagram. WARNING for
    ``flow``; raised to ERROR for ``landscape``, where a violated contact side is
    a routing defect that must block publication of the as-built (v1.3.x)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    if not bool(_geo.check_edge_direction(geo)):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        return Severity.ERROR
    return True


def _check_text_padding(a: Artifact) -> bool:
    """text-padding: a text/legend/note box lacks uniform inner padding (WARNING).

    Every ``text;`` cell must set all four spacing* tokens so no line abuts the
    border (borderless title cells are exempt). ``text_padding_offenders`` is the
    list of offending styles harvested by the CLI parser; None means not parsed
    (rule skipped)."""
    if not _is_diagram(a):
        return False
    offenders = a.text_padding_offenders
    if offenders is None:
        return False
    return bool(offenders)


def _check_corridor_sharing(a: Artifact) -> bool:
    """corridor-sharing: two long edges share one straight corridor (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_corridor_sharing(geo))


def _check_exit_thirds(a: Artifact) -> bool:
    """exit-thirds: same-side fan-out is not centred / even-thirds, or >3 exits (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_exit_thirds(geo))


def _check_edge_crosses_label(a: Artifact) -> bool:
    """edge-crosses-label: a routed edge polyline crosses another node's label band (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_edge_crosses_label(geo))


def _check_edge_crosses_container_label(a: Artifact) -> bool:
    """edge-crosses-container-label: a routed edge crosses a container's top caption (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_edge_crosses_container_label(geo))


def _check_entry_thirds(a: Artifact):
    """entry-thirds: several edges arrive on one target face at merged/duplicate points.

    The entry-side mirror of ``exit-thirds`` (v1.5.1). Two edges landing on one
    target face at the same contact point read as a single doubled line at the
    glyph (the buggy example's two ``EC2 → RDS`` edges both at ``entryX=0,
    entryY=0.5``). WARNING for ``flow``; raised to ERROR for ``landscape``, where
    a dense as-built must keep every arrival distinct — matching how the other
    routing-family rules (``edge-direction``/``edge-float``) escalate."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    if not bool(_geo.check_entry_thirds(geo)):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        return Severity.ERROR
    return True


def _check_edge_float(a: Artifact):
    """edge-float: an edge declares no explicit exit/entry contact point.

    WARNING for ``flow``; raised to ERROR for ``landscape``, where every edge
    must fix its contact points so the directional contract is enforceable and
    the perimeter router cannot drift a side (v1.3.x)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    if not bool(_geo.check_edge_float(geo)):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        return Severity.ERROR
    return True


# A numeric flow marker used as an on-edge label: "1", "2", … (see
# diagram-standards → Mandatory Edge Labels / Numbered Flow Legend).
_NUMERIC_MARKER_RE = re.compile(r"^\s*(\d+)\s*$")


def _numeric_flow_markers(a: Artifact) -> List[int]:
    """Return the numeric flow markers used as edge labels, ascending."""
    markers = []
    for e in a.edges:
        label = getattr(e, "label", None)
        if label is None:
            continue
        m = _NUMERIC_MARKER_RE.match(str(label))
        if m:
            markers.append(int(m.group(1)))
    return sorted(set(markers))


def _check_flow_legend(a: Artifact) -> bool:
    """flow-legend: numeric edge markers without a covering ``Flow`` legend (WARNING).

    diagram-standards (*Numbered Flow Legend*): when a diagram labels its edges
    with numeric markers, it must carry a ``Flow`` legend cell listing one
    ``N. <description>`` line per marker, in ascending order. Diagrams that use
    descriptive prose labels instead of numeric markers are unaffected.

    Documented in ``diagram-lint.md`` since the first ruleset but only implemented
    in v1.6.0: the generator emitted the Flow cell, so every generated diagram
    happened to comply and the missing check went unnoticed — a ruleset/code drift
    of the same kind 1.5.3 and 1.5.4 closed for other rules. A hand-authored
    diagram that numbered its edges and forgot the legend linted clean.
    """
    if not _is_diagram(a):
        return False
    markers = _numeric_flow_markers(a)
    if not markers:
        return False
    if a.flow_legend_lines is None:
        # Not parsed (programmatic artifact): skip rather than assume a failure.
        return False
    lines = [str(line).strip() for line in a.flow_legend_lines]
    if not lines:
        return True  # numeric markers used, but there is no Flow cell at all
    # Line 1 is the heading ``Flow``; the rest must cover every marker.
    covered = set()
    for line in lines[1:]:
        m = re.match(r"^(\d+)\s*[.)]", line)
        if m:
            covered.add(int(m.group(1)))
    return not set(markers).issubset(covered)


def _check_edge_approach(a: Artifact) -> bool:
    """edge-approach: a route leg is not axis-aligned, or misses its face (WARNING).

    ``orthogonalEdgeStyle`` never draws a diagonal, so an unaligned pair of points
    is a corner **draw.io** chooses — which is how an edge slides along a border or
    grazes a glyph while every waypoint looks deliberate. Measured across the
    corpus before v1.6.0, 30 routed edges had such a leg. See
    ``geometry.check_edge_approach``."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_edge_approach(geo))


def _check_node_connectivity(a: Artifact) -> bool:
    """node-connectivity: a role-bearing node is drawn with no incident edge (WARNING).

    The audit's headline finding (2026-09-25): each HA landscape drew 34 nodes
    joined by 12 edges, leaving 20 nodes entirely unconnected. Boundary containers
    and overlay-marked nodes (e.g. a ``standby`` passive peer that declares why it
    carries no edges) are exempt — see ``geometry.check_node_connectivity``."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_node_connectivity(geo))


def _check_legend_placement(a: Artifact) -> bool:
    """legend-placement: a Flow/Legend box is not in the right margin (WARNING).

    The furniture must sit at least one grid step past the outermost container's
    right edge, clear of the cloud boundaries (diagram-standards → *Reserve the
    right margin for Flow/Legend*). Unenforced before v1.6.0: a clean-room
    install produced an otherwise-clean diagram with both blocks parked in the
    LEFT margin under the external user, while every shipped golden puts them on
    the right."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    return bool(_geo.check_legend_placement(geo))


def _stem_of(path_or_stem):
    """Return the comparable stem of a path/stem reference (basename, no ext)."""
    if not path_or_stem:
        return ""
    base = os.path.basename(str(path_or_stem).strip())
    for ext in (".drawio", ".diagram.md", ".md"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return base


def _check_orphan_landscape(a: Artifact) -> bool:
    """orphan-landscape: a landscape diagram has no valid flow-summary cross-link.

    A ``landscape`` diagram must declare ``summary_of`` pointing at a sibling
    ``flow`` summary (the <=12-node overview). A landscape with an empty or
    missing ``summary_of`` is an ERROR — this encodes the "summary + detailed"
    pair as a checked contract rather than a convention (v1.3.0). ``flow``
    diagrams are unaffected.
    """
    if not _is_diagram(a):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() != DIAGRAM_CLASS_LANDSCAPE:
        return False
    return not _stem_of(a.summary_of)


def _check_overlay_legend_coverage(a: Artifact) -> bool:
    """overlay-legend-coverage: an overlay marker is not covered by the Legend (WARNING).

    When a diagram carries double-encoded overlay markers (findings / state,
    e.g. "spec-required-not-deployed", "observability-overlay", change markers),
    every marker term must be documented in the Legend. An uncovered marker is a
    WARNING. Diagrams with no overlay markers are unaffected.
    """
    if not _is_diagram(a):
        return False
    if not a.overlay_markers:
        return False
    covered = {str(t).strip().lower() for t in a.legend_overlay_terms}
    for marker in a.overlay_markers:
        if str(marker).strip().lower() not in covered:
            return True
    return False


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
    (RULE_CONTAINER_OVERLAP, _check_container_overlap),
    (RULE_EDGE_DIRECTION, _check_edge_direction),
    (RULE_TEXT_PADDING, _check_text_padding),
    (RULE_CORRIDOR_SHARING, _check_corridor_sharing),
    (RULE_EDGE_FLOAT, _check_edge_float),
    (RULE_EXIT_THIRDS, _check_exit_thirds),
    (RULE_ENTRY_THIRDS, _check_entry_thirds),
    (RULE_EDGE_CROSSES_LABEL, _check_edge_crosses_label),
    (RULE_EDGE_CROSSES_CONTAINER_LABEL, _check_edge_crosses_container_label),
    (RULE_LEGEND_PLACEMENT, _check_legend_placement),
    (RULE_FLOW_LEGEND, _check_flow_legend),
    (RULE_NODE_CONNECTIVITY, _check_node_connectivity),
    (RULE_EDGE_APPROACH, _check_edge_approach),
    (RULE_ORPHAN_LANDSCAPE, _check_orphan_landscape),
    (RULE_OVERLAY_LEGEND_COVERAGE, _check_overlay_legend_coverage),
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
        # Bundled-payload fallback (v1.5.1): a pip/Power install ships the
        # steering rules inside the package at ``rule_engine/_bootstrap`` — but
        # ``parents[2]`` is NOT the repo root there, so the upward walk above
        # misses them, and the linter fail-closed on a correctly-installed
        # package that had not yet run ``rule-engine-init``. Because setuptools
        # drops dot-directories, the payload stores ``.kiro`` dot-free as
        # ``kiro/``; probe both so the ruleset resolves with no workspace
        # bootstrap.
        bootstrap = Path(__file__).resolve().parent / "_bootstrap"
        candidates.append(str(bootstrap / RULESET_RELATIVE_PATH))
        candidates.append(
            str(bootstrap / "kiro" / "steering" / "diagram-lint.md")
        )

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
        result = predicate(art)
        if not result:
            continue
        # A predicate may return a bare True (use the rule's default severity
        # from RULE_SEVERITIES) or an explicit Severity for class-dependent
        # rules (e.g. node-count: ERROR for flow, WARNING/ERROR for landscape).
        severity = result if isinstance(result, Severity) else RULE_SEVERITIES[rule_name]
        findings.append({"rule": rule_name, "severity": severity.value})

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
    "RULE_ORPHAN_LANDSCAPE",
    "RULE_OVERLAY_LEGEND_COVERAGE",
    "RULE_CONTAINER_OVERLAP",
    "RULE_EDGE_DIRECTION",
    "RULE_TEXT_PADDING",
    "RULE_CORRIDOR_SHARING",
    "RULE_EDGE_FLOAT",
    "RULE_EXIT_THIRDS",
    "RULE_ENTRY_THIRDS",
    "RULE_EDGE_CROSSES_LABEL",
    "RULE_EDGE_CROSSES_CONTAINER_LABEL",
    "RULE_LEGEND_PLACEMENT",
    "RULE_FLOW_LEGEND",
    "RULE_NODE_CONNECTIVITY",
    "RULE_EDGE_APPROACH",
    "LANDSCAPE_NODE_WARN",
    "LANDSCAPE_NODE_ERROR",
    "DIAGRAM_CLASS_FLOW",
    "DIAGRAM_CLASS_LANDSCAPE",
]
