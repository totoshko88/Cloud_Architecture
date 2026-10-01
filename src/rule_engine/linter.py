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

import ipaddress
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

# honest-gates 1.7.0 (task 10.3): the ``frontmatter`` and ``secret-safety`` rules
# delegate to the shared single-source modules rather than to substring lists.
# ``kb_validator`` implements the whole ``kb-frontmatter.md`` contract; ``secret_safety``
# is the one secret vocabulary the Collector, Normalizer and Linter share (design §5),
# so the redactor and the Linter cannot disagree about what a secret is. The pre-1.7
# substring scan (``constants.SECRET_CONTENT_MARKERS`` via ``_content_has_secret``) is
# gone: it produced both false CRITICALs on metadata and false negatives on real secrets.
from rule_engine import kb_validator as _kb_validator
from rule_engine import secret_safety as _secret_safety


# ---------------------------------------------------------------------------
# Severities and rule names
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """Lint finding severity scale (``diagram-lint.md`` — Severity Scale)."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"


# The two diagram classes. ``flow`` (default) keeps every legacy rule exactly
# as before, so all pre-1.3.0 artifacts lint unchanged. ``landscape`` branches
# the node-count severity and enables the pair-contract and overlay rules.
# (Defined here, ahead of ``RuleSpec``, because ``RuleSpec.severity_for`` uses
# ``DIAGRAM_CLASS_FLOW`` as a default argument.)
DIAGRAM_CLASS_FLOW = "flow"
DIAGRAM_CLASS_LANDSCAPE = "landscape"


# ---------------------------------------------------------------------------
# Rule registry model (honest-gates 1.7.0, task 10.1 / R1.13, R10.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleSpec:
    """Declarative description of one lint rule.

    A rule's per-class and per-reason severity escalations move out of the
    predicate bodies and into data here, so the ``diagram-lint.md`` rule table
    (parsed by the sync test, R10.1) and the runtime severities can be checked
    against one another, and so a predicate only has to report *what* it found
    (the offender ids and a reason) rather than *how severe* the class makes it.

    Attributes
    ----------
    name:
        The stable rule name (``node-count``, ``edge-direction``, …).
    default:
        The severity when the condition holds on a ``flow`` diagram — the rule's
        baseline severity, and the value exported through ``RULE_SEVERITIES``.
    landscape:
        The severity when the condition holds on a ``landscape`` diagram, when
        it differs from ``default``. ``None`` means the class does not change the
        severity. This replaces the per-predicate ``if landscape: return
        Severity.ERROR`` branches for ``container-padding``, ``edge-direction``,
        ``edge-float``, ``entry-thirds`` and ``container-overlap``.
    reason_escalations:
        A mapping of reason *substring* → severity. When a finding's ``reason``
        contains one of these keys, that severity applies (independent of
        class). This models the ``edge-routing`` escalation, where an
        icon-crossing reason (``knee-through-``, ``straight-through-``,
        ``pierces-target-``) is an ERROR on either class while a bare
        non-orthogonal edge stays a WARNING.
    """

    name: str
    default: Severity
    landscape: Optional[Severity] = None
    reason_escalations: Mapping[str, Severity] = field(default_factory=dict)

    def severity_for(self, diagram_class: str = DIAGRAM_CLASS_FLOW, reason: str = "") -> Severity:
        """Resolve the severity for one finding of this rule.

        A matching ``reason_escalations`` substring wins first (a routing
        icon-crossing is an ERROR regardless of class), then the ``landscape``
        class escalation, otherwise the ``default``.
        """
        if reason and self.reason_escalations:
            for marker, sev in self.reason_escalations.items():
                if marker in reason:
                    return sev
        if (
            self.landscape is not None
            and (diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE
        ):
            return self.landscape
        return self.default


@dataclass(frozen=True)
class RuleHit:
    """One finding produced by a rule predicate.

    A predicate may return a single ``RuleHit``, a list of them, or (for
    backward compatibility with programmatic callers) a bare ``bool`` /
    ``Severity``. The offender ids and the reason are the values the geometry
    checks already compute today and the pre-1.7.0 ``lint()`` threw away.

    Attributes
    ----------
    offenders:
        The identifiers of the offending node(s), edge(s) or container(s).
    reason:
        A short machine-readable reason string (e.g. ``knee-through-rds`` or a
        constraint name), also used to resolve ``reason_escalations``.
    severity:
        An explicit severity override for this hit (used by ``node-count``,
        whose severity depends on the node count, not the class alone). ``None``
        means "use the RuleSpec's ``severity_for``".
    """

    offenders: Tuple[str, ...] = ()
    reason: str = ""
    severity: Optional[Severity] = None


# A predicate returns a hit or hits, a bare bool, or an explicit Severity.
_PredicateResult = Union[RuleHit, List[RuleHit], bool, Severity]


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
RULE_CONTAINER_DEAD_SPACE = "container-dead-space"
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
RULE_EDGE_CROSSES_CONTAINER = "edge-crosses-container"
RULE_EDGE_ON_CONTAINER_BORDER = "edge-on-container-border"
RULE_LEGEND_PLACEMENT = "legend-placement"
RULE_FLOW_LEGEND = "flow-legend"
RULE_NODE_CONNECTIVITY = "node-connectivity"
RULE_EDGE_APPROACH = "edge-approach"
# honest-gates 1.7.0 (task 10.2): three new rules.
#   parse-error   — the artifact could not be parsed (R1.8/R1.9); a Blocking
#                   ERROR that short-circuits every other rule for that artifact.
#   edge-endpoint — an edge references a missing/dangling source or target
#                   (R1.10); WARNING for flow, ERROR for landscape.
#   source-format — a diagram authored in a non-canonical source (.puml/.mmd);
#                   draw.io is the only publishable diagram source (D1, R10.3).
RULE_PARSE_ERROR = "parse-error"
RULE_EDGE_ENDPOINT = "edge-endpoint"
RULE_SOURCE_FORMAT = "source-format"
# provider-diagram-conventions 1.10.0 (Part A / Requirement 1).
#   edge-bidirectional — a double-headed arrow (both a non-``none`` startArrow
#                        and a non-``none`` endArrow); WARNING, both classes.
RULE_EDGE_BIDIRECTIONAL = "edge-bidirectional"
# provider-diagram-conventions 1.10.0 (Part B / Requirement 2).
#   node-label-length — a service-node label longer than the word / char cap;
#                       WARNING, both classes. Legend/Flow/title/callout text
#                       cells are not node labels and are exempt.
RULE_NODE_LABEL_LENGTH = "node-label-length"
# provider-diagram-conventions 1.10.0 (Part C / Requirement 3).
#   ip-range — on-diagram text in a Network_Diagram carries a Public_IP_Literal
#              (a routable public IP that is neither a Documentation_Range nor
#              private); WARNING. Only a Network_Diagram is evaluated.
RULE_IP_RANGE = "ip-range"

# edge-hygiene 1.10.5 (Feature B). Three edge-legibility rules plus a structural
# integrity cross-check adapted from the awesome-copilot draw.io validator.
#   marker-collision     — two edge flow-markers render closer than the merge
#                          threshold (they overprint into one number); WARNING.
#   edge-crossing-excess — the diagram's edge-crossing count exceeds a
#                          per-diagram cap proportional to the edge count;
#                          WARNING.
#   detour-hook          — an edge's routed length far exceeds the manhattan
#                          distance between its contacts (it loops out and
#                          back); WARNING.
#   structural-integrity — an edge endpoint resolves to no placeable box, or a
#                          node carries no geometry; WARNING. (Duplicate ids and
#                          parent cycles are caught earlier — see the check.)
RULE_MARKER_COLLISION = "marker-collision"
RULE_EDGE_CROSSING_EXCESS = "edge-crossing-excess"
RULE_DETOUR_HOOK = "detour-hook"
RULE_STRUCTURAL_INTEGRITY = "structural-integrity"

# deterministic-engine 1.10.6. Three routing rules the engine now minimises as
# part of its scored objective, published as advisory WARNINGs so a HAND-authored
# diagram is held to the same standard the engine already meets:
#   edge-escapes-container — a route between two nodes of one container leaves
#                            that container (into the region/account gap or the
#                            right margin); WARNING.
#   edge-crosses-legend    — a route runs through, or along within one grid step
#                            of, a Flow / Legend box; WARNING. (edge-routing
#                            always described this but never read the text boxes.)
#   edge-jog               — an edge between two DIRECTLY FACING nodes (next on
#                            the row, or directly below) is drawn with a jog
#                            instead of one straight segment; WARNING.
RULE_EDGE_ESCAPES_CONTAINER = "edge-escapes-container"
RULE_EDGE_CROSSES_LEGEND = "edge-crosses-legend"
RULE_EDGE_JOG = "edge-jog"

# ``RULE_SEVERITIES`` and ``CLASS_ESCALATIONS`` are DERIVED from the ``RULES``
# registry (defined near the end of this module, once every predicate exists) —
# see ``_derive_severities``. The registry is the single source of truth for a
# rule's default severity, its ``landscape`` escalation, and its
# ``reason_escalations`` (task 10.1 / R10.1), so the ``diagram-lint.md`` rule
# table and the runtime severities can be checked against one another.

# Maximum node count for a single diagram (Requirement 1 AC4 / 7 AC4).
MAX_NODES = 12

# Landscape (as-built / inventory) node-count thresholds (v1.3.0). A landscape
# diagram relaxes the flow 12-node cap because its job is completeness on one
# canvas; readability is instead enforced by the geometry rules (container
# padding raised to ERROR, edge routing, node overlap) and the summary
# cross-link contract.
LANDSCAPE_NODE_WARN = 30
LANDSCAPE_NODE_ERROR = 50

# Minimum on-diagram font size, in px. AWS diagram conventions require a >= 12px
# floor for text readability/accessibility (diagram-standards.md "Accessibility &
# Contrast"). Any diagram text below this trips the advisory ``min-font-size``
# rule. Mirrors ``rule_engine.diagram_layout.MIN_FONT_SIZE``.
MIN_FONT_SIZE = 12

# Matches every ``fontSize=<n>`` occurrence in a draw.io style string.
_FONT_SIZE_RE = re.compile(r"fontSize=([0-9]+)")

# Node-label length caps (provider-diagram-conventions 1.10.0, Part B / R2 AC1).
# A service-node label exceeding EITHER cap trips ``node-label-length``: node
# labels stay short (the service name); explanatory prose belongs in a callout
# (``overlay=callout``), not in the icon label. AWS diagram guidance: "do not
# embed explanatory text into images; use short labels; use callouts".
LABEL_WORD_CAP = 4
LABEL_CHAR_CAP = 40

# Documentation IP ranges (provider-diagram-conventions 1.10.0, Part C / R3).
# These are the ranges reserved for documentation and examples: the IPv4
# TEST-NET blocks (RFC5737) and the IPv6 documentation prefix (RFC3849). An
# on-diagram address in one of these — or in a private range — is never a
# ``ip-range`` finding; only a routable *public* literal in a Network_Diagram is.
# IPv6 must be written per RFC5952 (lowercase, compressed) in on-diagram text.
DOCUMENTATION_RANGES = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "192.0.2.0/24",  # RFC5737 TEST-NET-1
        "198.51.100.0/24",  # RFC5737 TEST-NET-2
        "203.0.113.0/24",  # RFC5737 TEST-NET-3
        "2001:db8::/32",  # RFC3849 documentation prefix
    )
)

# Shared-address / carrier-grade-NAT ranges that ``ipaddress.is_private`` does
# not classify as private on every stdlib version: RFC6598 (100.64.0.0/10) and
# RFC6815 (the benchmarking range 198.18.0.0/15). Treated as non-public so a
# lab/benchmark address in a diagram is not flagged.
_EXTRA_NONPUBLIC_RANGES = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "100.64.0.0/10",  # RFC6598 shared address space (CGNAT)
        "198.18.0.0/15",  # RFC6815 / RFC2544 benchmarking range
    )
)

# Diagram types (companion ``diagram_type``) that, alongside a ``landscape``
# class, make a diagram a Network_Diagram for the ``ip-range`` rule (R3.3).
_NETWORK_DIAGRAM_TYPES = frozenset({"network", "infrastructure", "deployment"})

# Conservative IPv4 / IPv6 literal matcher used to pull candidate addresses out
# of on-diagram text. A match that does not parse under ``ipaddress`` is ignored
# (never a finding), so prose that merely looks address-like is not mis-flagged.
_IP_CANDIDATE_RE = re.compile(
    r"(?<![\w.])"  # not preceded by a word char or dot
    r"(?:"
    r"\d{1,3}(?:\.\d{1,3}){3}"  # dotted-quad IPv4
    r"|"
    r"(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}"  # colon-hex IPv6
    r")"
    r"(?![\w.])"  # not followed by a word char or dot
)

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
    # honest-gates 1.7.0 (task 10.4 / R4.5): the manifest-resolvable icon
    # references the CLI extracts from the parsed page — ``resIcon`` / ``grIcon``
    # (aws4), ``azure2`` and ``oci-slug`` / ``oci-glyph`` refs. ``icon-resolved``
    # resolves each against the committed manifests (``aws4-icons.json``,
    # ``azure2-shapes.json``, ``oci-stencil-digests.json``) via
    # ``icon_refs.resolve`` and emits an ERROR (with the offending cell id) for an
    # unknown id — a guessed/typo stencil id renders as an empty box. File-path
    # (``image``) refs are left to the Icon_Verifier (assets may be absent at lint
    # time), and a ``skipped`` status (a manifest not present) never blocks. Each
    # entry is a ``rule_engine.icon_refs.IconRef``; empty for a programmatic
    # artifact, so this half of the rule then no-ops.
    icon_refs: Sequence[Any] = field(default_factory=list)
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

    # honest-gates 1.7.0 (task 9.3): fields the parsed-model CLI populates. A
    # multi-page ``.drawio`` yields one Artifact per page; ``page`` names it and
    # ``label`` is ``<file>#<page>`` for a multi-page file (plain ``<file>`` for a
    # single page), which the Lint_CLI prints (R1.3, R1.13).
    page: Optional[str] = None
    label: Optional[str] = None
    # Parse failures (R1.8): a ``DrawioParseError`` or a geometry exception makes
    # the CLI hand back an Artifact carrying the machine-readable cause string(s)
    # here. The ``parse-error`` rule (task 10.2) fires on a non-empty list; every
    # other rule is skipped for such an artifact.
    parse_errors: Sequence[str] = field(default_factory=list)
    # The model grid step (``mxGraphModel@gridSize``, else 10), carried through
    # from the parsed Page (R1.7).
    grid_size: int = 10
    # The rendered lines of the structurally-detected Legend cell (a text cell
    # whose first non-empty line, casefolded, is ``legend``). Used by the
    # structural legend/overlay checks (R1.11, R1.12). None means "not parsed".
    legend_lines: Optional[Sequence[str]] = None
    # Per-edge endpoint status (R1.10): one string per edge naming a broken
    # endpoint (``missing-source``, ``missing-target``, ``dangling-source:<id>``,
    # ``dangling-target:<id>``). The ``edge-endpoint`` rule (task 10.2) reports
    # these; an edge with both endpoints resolved contributes nothing.
    edge_endpoints: Sequence[str] = field(default_factory=list)
    # True when the artifact lives inside an ``inventory-*`` snapshot folder, so
    # ``secret-safety`` applies to its text regardless of kind (R3.5, discovery
    # is task 9.4).
    in_snapshot: bool = False
    # The raw UTF-8 text of a non-diagram snapshot/document artifact, scanned by
    # ``secret-safety`` (task 10.3). None for a diagram.
    text: Optional[str] = None
    # True when a Markdown document is a generated KB document the structural
    # KB checks apply to (design §4 / R2.8). The CLI sets this from
    # ``cli._is_kb_document(path)``: a companion / versioned KB document is
    # ``is_kb=True`` (frontmatter *and* structure are validated), while a
    # snapshot ``00-MANIFEST.md`` is ``is_kb=False`` (D5 — it is scanned only for
    # secrets, as an in-snapshot text file). Programmatic ``Artifact(frontmatter=…)``
    # callers leave it False, so only the frontmatter checks run for them.
    is_kb: bool = False


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
    """node-quote: a special-character node name is not double-quoted (ERROR).

    The rule originates in PlantUML/Mermaid, where a node *identifier* that
    contains a space or punctuation must be double-quoted or the source does
    not parse. In a **draw.io** cell, by contrast, the ``value`` this reads is
    the node's **display label** — free text rendered on the canvas — not an
    identifier, and adding literal double quotes to satisfy the rule makes the
    quotes show up in the drawing (the "IAM user sep" -> "IAM-user-sep"
    workaround an author was forced into). draw.io is the only publishable
    source (D1), so a draw.io label is always a valid display string; the rule
    therefore applies only to non-draw.io sources (``.puml`` / ``.mmd``), where
    quoting genuinely governs parsing (v1.9.3).
    """
    if not _is_diagram(a):
        return False
    # draw.io labels are display text, not identifiers — never a node-quote
    # defect. Keep the check for PlantUML/Mermaid identifier sources.
    if a.is_drawio:
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
    """legend-present: a diagram has no Legend (ERROR).

    Structural in 1.7.0 (R1.11): the CLI sets ``has_legend`` from the parsed
    model — true only when a *text cell* whose first non-empty line, casefolded,
    is ``legend`` exists (its lines are captured in ``legend_lines``). A stray
    occurrence of the word ``legend`` in an id or a note no longer satisfies the
    rule. The predicate simply reads that structural flag, so it stays correct
    for both the parsed CLI path and programmatic callers that set ``has_legend``
    directly.
    """
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


def _violation_hit(violation: "_kb_validator.KbViolation") -> RuleHit:
    """Turn one :class:`kb_validator.KbViolation` into a CRITICAL ``RuleHit``.

    ``reason`` is the machine-readable constraint (``status-enum``,
    ``date-format``, ``section-length``, …); the offender is the key or section
    the violation names, else the constraint itself, so every finding names what
    it is about (kb-frontmatter AC 8.9 / AC 8.10, R2.7).
    """
    offender = violation.key if violation.key else violation.constraint
    return RuleHit(offenders=(offender,), reason=violation.constraint)


def _check_frontmatter(a: Artifact):
    """frontmatter: a KB document breaks the ``kb-frontmatter.md`` contract (CRITICAL).

    honest-gates 1.7.0 (task 10.3 / R2): the whole contract is delegated to
    :mod:`rule_engine.kb_validator`, so a document with ``status: bogus`` or the
    impossible date ``2026-02-30`` is rejected, not merely a document with an
    absent key. The rule returns **one CRITICAL** :class:`RuleHit` **per**
    :class:`~rule_engine.kb_validator.KbViolation`, each carrying the constraint
    as its ``reason`` and the offending key/section as its offender.

    The **frontmatter** checks (the twelve keys, the ``status`` enum, the date
    format, the list bounds) run for every Markdown document **except an
    in-snapshot manifest** — a ``00-MANIFEST.md`` (or other in-snapshot Markdown
    that is not a KB document) is excluded from the KB rule entirely under D5
    (R2.8) and scanned only for secrets. The **structural** checks (length, the
    four required sections, the H1 count, list depth, table width, the
    Anti-patterns section) run **only for a KB document** (``a.is_kb``), and a
    programmatic ``Artifact(frontmatter=…)`` caller (``is_kb`` False, no
    ``text``) gets only the frontmatter checks.

    When the artifact carries its raw ``text``, the validator sees the real
    document (so the ``yaml-parse`` case — a frontmatter block that is not valid
    YAML — is a finding rather than a lenient fallback, R2.5); a programmatic
    artifact with only a ``frontmatter`` mapping is validated as that mapping.
    """
    if not _is_document(a):
        return False

    # D5 (R2.8): a snapshot ``00-MANIFEST.md`` — and any other in-snapshot
    # Markdown that is not a generated KB document — is *excluded from the KB
    # rule entirely*, not merely from its structural half. The Collector's table
    # manifest is owned by ``snapshot_gate``; the Linter runs only
    # ``secret-safety`` on it (design §2 — "the Lint_CLI no longer applies the KB
    # rule to it"). Such an artifact is marked ``in_snapshot`` and ``is_kb`` is
    # False, so the whole frontmatter/structure contract is skipped here. A
    # companion / versioned KB document inside the same folder is ``is_kb=True``
    # and still validated; a programmatic ``Artifact(frontmatter=…)`` caller is
    # ``in_snapshot=False`` and unaffected.
    if getattr(a, "in_snapshot", False) and not a.is_kb:
        return False

    violations: List["_kb_validator.KbViolation"] = []

    if a.text is not None:
        # The real document: split off the frontmatter block and validate it,
        # then (for a KB document only) the body structure.
        block, body = _kb_validator.split_frontmatter(a.text)
        if block is None:
            # No frontmatter block at all: every required key is missing.
            violations.extend(
                _kb_validator.KbViolation(
                    "missing-key", key, f"required key {key!r} is absent"
                )
                for key in REQUIRED_FRONTMATTER_KEYS
            )
        else:
            fm, load_violations = _kb_validator.load_frontmatter(block)
            if fm is None:
                violations.extend(load_violations)
            else:
                violations.extend(_kb_validator.validate_frontmatter(fm))
        if a.is_kb:
            violations.extend(_kb_validator.validate_structure(body))
    else:
        # Programmatic caller: validate the parsed frontmatter mapping. A
        # ``None`` mapping means the document had no (parseable) frontmatter, so
        # every required key is missing. No ``text`` means no structural checks.
        fm = a.frontmatter
        if fm is None:
            violations.extend(
                _kb_validator.KbViolation(
                    "missing-key", key, f"required key {key!r} is absent"
                )
                for key in REQUIRED_FRONTMATTER_KEYS
            )
        else:
            violations.extend(_kb_validator.validate_frontmatter(fm))

    if not violations:
        return False
    return [_violation_hit(v) for v in violations]


# honest-gates 1.7.0 (task 10.4 / R4.5): the icon-reference kinds the linter
# resolves against the **committed manifests** via ``icon_refs.resolve``. An
# ``unresolved`` status among them is an ERROR naming the offending cell id — a
# guessed/typo id renders as an empty box:
#
#   * ``resIcon`` / ``grIcon`` — an ``mxgraph.aws4.<id>`` against ``aws4-icons.json``;
#   * ``azure2``               — an ``img/lib/azure2/…`` path against ``azure2-shapes.json``;
#   * ``oci-slug``             — an ``ociSlug=<slug>`` marker against ``oci-stencil-digests.json``.
#
# Deliberately excluded here (design §6, R4.5):
#   * ``image`` (file-path) refs — the on-disk asset may be absent at lint time,
#     so path→asset verification is the Icon_Verifier's business, not the
#     linter's; the linter never blocks on a well-formed asset path.
#   * ``oci-glyph`` — the page-level glyph digest binds to a **slug** only when
#     both are present, a page-level pairing the standalone linter cannot do
#     (``icon_refs._glyph_sibling_slug`` returns ``None`` on the linter path).
#     A committed OCI golden example carries the embedded glyph but no
#     ``ociSlug=`` marker yet (task 5.2 emits the marker from the builder), so
#     the glyph→slug binding is the Icon_Verifier's job (R4.1), which walks the
#     whole page. The linter would otherwise reverse-look-up a page-wide digest
#     against per-slug digests and never match — a false ERROR on every OCI node.
#   * ``generic-shape`` — a base draw.io shape, resolved against
#     ``generic-icons.yaml`` by the verifier, not a manifest id.
_MANIFEST_REF_KINDS = frozenset({"resIcon", "grIcon", "azure2", "oci-slug"})


def _workspace_root_for(path: Optional[str]):
    """Best-effort workspace root for an artifact path.

    Walk up from the artifact's directory to the nearest ancestor that contains
    a ``mappings/`` directory (the committed manifests live there). When none is
    found — a programmatic artifact, or a file outside a workspace — return
    ``None`` so ``icon_refs.load_sources`` falls back to the manifests bundled
    with the package (design §6 — "committed manifests only", never the fetched
    packs).
    """
    from pathlib import Path as _Path

    if not path:
        return None
    try:
        here = _Path(path).resolve().parent
    except OSError:
        return None
    for candidate in (here, *here.parents):
        if (candidate / "mappings").is_dir():
            return candidate
    return None


# ``icon_refs.load_sources`` reads several JSON/YAML manifests off disk; cache
# the loaded :class:`IconSources` per workspace root so linting a whole tree does
# not re-read the manifests for every page. Keyed by the resolved root (or
# ``None`` for the bundled fallback).
_ICON_SOURCES_CACHE: Dict[Any, Any] = {}


def _icon_sources_for(path: Optional[str]):
    """Return the cached :class:`icon_refs.IconSources` for ``path``'s workspace."""
    from pathlib import Path as _Path

    from rule_engine import icon_refs as _icon_refs

    root = _workspace_root_for(path)
    key = str(root) if root is not None else None
    if key not in _ICON_SOURCES_CACHE:
        _ICON_SOURCES_CACHE[key] = _icon_refs.load_sources(
            root if root is not None else _Path(".")
        )
    return _ICON_SOURCES_CACHE[key]


def _check_icon_resolved(a: Artifact):
    """icon-resolved: an unresolved placeholder OR an unknown manifest id (ERROR).

    honest-gates 1.7.0 (task 10.4 / R4.5) keeps the pre-1.7 **placeholder**
    behaviour — an empty style, ``shape=none``, or a ``data:image/svg`` URI is an
    unresolved icon — *and* additionally resolves the parsed
    ``resIcon`` / ``grIcon`` / ``azure2`` / ``oci-*`` references against the
    **committed manifests** (``aws4-icons.json``, ``azure2-shapes.json``,
    ``oci-stencil-digests.json``) via :func:`icon_refs.resolve`. An
    ``unresolved`` status among those kinds — a guessed or mistyped stencil id
    that would render as an empty box — is an ERROR whose offender is the
    **cell id** carrying it.

    Since 1.10.2, an ``image=data:image/svg...`` inline glyph is a **resolved**
    icon when it carries an ``iconRef=<assets/vendor/...>`` companion token
    (``diagram_layout.image_icon`` emits that pair so the glyph renders in the
    draw.io editor while the asset path stays reverse-identifiable): the
    placeholder check exempts it (see ``cli._icon_descriptor_for_style``), and
    the manifest-backed check takes the ``image`` ref's identity from ``iconRef``
    (see ``icon_refs.extract_refs``). A **bare** ``image=data:...`` with no
    companion path is still an unresolved placeholder.

    File-path (``image``) refs are **not** resolved here: they are the
    Icon_Verifier's business because the referenced asset may be absent at lint
    time (design §6). A ``skipped`` status (a manifest not committed) never
    blocks — fail-honest — and a ``resolved`` id passes silently.
    """
    if not _is_diagram(a):
        return False

    hits: List[RuleHit] = []

    # (1) Placeholder markers — unchanged pre-1.7 behaviour.
    if any(_icon_is_unresolved(icon) for icon in a.icons):
        hits.append(RuleHit(reason="unresolved-placeholder"))

    # (2) Manifest-backed resolution of the parsed references (committed
    # manifests only). Import lazily so a programmatic artifact with no
    # ``icon_refs`` never pays the manifest-load cost.
    refs = list(getattr(a, "icon_refs", ()) or ())
    manifest_refs = [r for r in refs if getattr(r, "kind", None) in _MANIFEST_REF_KINDS]
    if manifest_refs:
        from rule_engine import icon_refs as _icon_refs

        sources = _icon_sources_for(a.path)
        for ref in manifest_refs:
            status, detail = _icon_refs.resolve(ref, sources)
            if status == _icon_refs.UNRESOLVED:
                hits.append(
                    RuleHit(
                        offenders=(ref.cell_id,) if ref.cell_id else (),
                        reason=detail or f"unresolved-{ref.kind}",
                    )
                )

    return hits if hits else False


def _secret_applies(a: Artifact) -> bool:
    """True when ``secret-safety`` applies to this artifact.

    It applies to any snapshot file, and — per R3.5 — to *any* artifact inside
    an ``inventory-*`` folder regardless of kind (a KB ``.md`` companion in a
    snapshot folder is scanned for secrets as well as validated as a document).
    """
    return _is_snapshot(a) or bool(getattr(a, "in_snapshot", False))


def _secret_hits(a: Artifact) -> List[RuleHit]:
    """Return the ``secret-safety`` hits for one artifact (offenders locate only).

    honest-gates 1.7.0 (task 10.3 / R3): a ``.json`` snapshot is parsed and walked
    with :func:`secret_safety.find_secrets` (RFC 6901 pointers); any other text —
    ``.md`` / ``.yaml`` / ``.txt`` / ``.csv``, or a ``.json`` that does not parse —
    goes through :func:`secret_safety.scan_text` (``line:<n>`` locations). Every
    offender is a **JSON pointer or a line number**; a secret *value* is never
    placed in a finding (design §2 — "a finding never includes a secret value").
    An unparsable ``.json`` snapshot is scanned as text here *and* also carries a
    ``parse-error`` (set by ``cli._parse_snapshot``); the two coexist because a
    snapshot has no model to skip.
    """
    text = a.text if a.text is not None else a.content
    is_json = bool(a.path) and str(a.path).lower().endswith(".json")

    hits: List["_secret_safety.SecretHit"] = []
    if text is not None:
        if is_json:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                # An unparsable snapshot .json: fall back to a text scan so a
                # secret in a malformed file is still caught (the parse-error is
                # reported separately by the parse-error rule).
                hits = _secret_safety.scan_text(text)
            else:
                hits = _secret_safety.find_secrets(parsed)
        else:
            hits = _secret_safety.scan_text(text)

    rule_hits = [
        RuleHit(offenders=(hit.location,) if hit.location else (), reason=hit.kind)
        for hit in hits
    ]
    if a.contains_secret and not rule_hits:
        # A programmatic caller that asserts the file contains a secret without
        # supplying text: honour the flag with a value-free finding.
        rule_hits.append(RuleHit(reason="contains-secret"))
    return rule_hits


def _check_secret_safety(a: Artifact):
    """secret-safety: a snapshot file contains a secret/key/SecureString (CRITICAL).

    Delegates to :mod:`rule_engine.secret_safety`, the single shared vocabulary
    (design §5), so the Linter and the redactor cannot disagree about what a
    secret is. Applies to any snapshot file and any in-snapshot text (R3.5). Each
    finding's offender is a JSON pointer or a ``line:<n>`` location only — never
    the secret value.
    """
    if not _secret_applies(a):
        return False
    hits = _secret_hits(a)
    return hits if hits else False


def _check_title_versioned(a: Artifact) -> bool:
    """title-versioned: a diagram has no fully-formed versioned title (WARNING).

    Structural in 1.7.0 (R1.11): the CLI sets ``title_cell`` only when a text
    cell's label matches the *whole* title format
    (``<provider> <workload> — <boundary> / <region> | <date> | vN``) **and**
    ``date`` is a real calendar date. So a ``title_cell`` of ``None`` means no
    cell matched the full format — the rule fires. A stray ``vN`` token in an
    unrelated cell no longer satisfies it.

    For programmatic callers that still pass a plain title string, the legacy
    version+date substring check is kept as a fallback so a partial title
    (missing the version or the date) also fires.
    """
    if not _is_diagram(a):
        return False
    title = a.title_cell
    if title is None:
        # No cell matched the full versioned-title format.
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


def _offender_ids(findings) -> Tuple[str, ...]:
    """Flatten a geometry check's return value into a tuple of offender ids.

    The geometry checks return either ``List[str]`` (node/edge ids),
    ``List[Tuple[str, str]]`` (an id pair, or an ``(id, reason)`` pair), or
    ``List[Tuple[str, str, float]]`` (id pair + gap). Every leading string in
    each tuple that is not the trailing reason is an offender id. To keep the
    behaviour simple and stable, we collect every ``str`` element of each entry
    that is not the last element when the last element is a reason string; for
    ``(id, reason)`` shapes this keeps the id, and for ``(idA, idB)`` /
    ``(idA, idB, gap)`` shapes it keeps both ids. Duplicates are removed while
    preserving order.
    """
    ids: List[str] = []

    def _add(value: str) -> None:
        if value and value not in ids:
            ids.append(value)

    for entry in findings:
        if isinstance(entry, str):
            _add(entry)
        elif isinstance(entry, (tuple, list)):
            for element in entry:
                if isinstance(element, str):
                    _add(element)
    return tuple(ids)


def _first_reason(findings) -> str:
    """Return the first reason string among the geometry findings, if any.

    Used to drive ``reason_escalations`` (e.g. ``edge-routing``'s
    ``*-through-*`` / ``pierces-target-*`` crossing escalation). For an
    ``(id, reason)`` tuple the reason is the last element; a bare-id shape has
    no reason.
    """
    reasons = []
    for entry in findings:
        if isinstance(entry, (tuple, list)) and len(entry) >= 2 and isinstance(entry[-1], str):
            reasons.append(entry[-1])
    # Prefer a reason that triggers an escalation so the strongest severity wins
    # even when it is not the first offender in document order.
    for reason in reasons:
        if ("through-" in reason) or ("pierces-" in reason):
            return reason
    return reasons[0] if reasons else ""


def _check_grid_alignment(a: Artifact):
    """grid-alignment: a node's absolute x/y is not a multiple of the grid (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_grid_alignment(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="off-grid")


def _check_container_padding(a: Artifact):
    """container-padding: a node sits <1 grid step from / straddles a container.

    WARNING for ``flow``; the ``landscape`` escalation to ERROR now lives in the
    ``RuleSpec`` (task 10.1), so the predicate only reports the offenders.
    """
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_container_padding(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="padding")


def _check_container_dead_space(a: Artifact):
    """container-dead-space: a container is sized far larger than its children.

    The mirror of ``container-padding``: it flags a Boundary container whose area
    exceeds the summed footprint+padding demand of its direct children by more
    than the calibrated ratio (``geometry.DEAD_SPACE_RATIO`` = 5.0, set above the
    sparsest legitimate corpus tier so no shipped diagram false-positives).
    Advisory WARNING on both classes; a container with no direct children is
    skipped, never divided by zero (placement-and-gates Part C, R3.1/3.2/3.4).
    """
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_container_dead_space(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="dead-space")


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
    escalation below, so it blocks publication like any other icon crossing.

    The icon-crossing escalation now lives in the ``RuleSpec``'s
    ``reason_escalations`` (task 10.1); the predicate reports the offending edge
    ids and a reason, and the RuleSpec raises ``*-through-*`` /
    ``pierces-target-*`` to ERROR on either class."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_routing(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_node_overlap(a: Artifact):
    """node-overlap: two node icon boxes overlap (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_node_overlap(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="overlap")


def _check_arrow_style(a: Artifact):
    """arrow-style: an edge uses a filled/heavy arrowhead or a sub-1pt stroke (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_arrow_style(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_edge_bidirectional(a: Artifact):
    """edge-bidirectional: a double-headed arrow (WARNING, both classes).

    A two-way relationship is drawn as two single-ended edges (preferred) or an
    edge annotated request/response — never a single double-headed arrow, which
    hides an ambiguous dependency (AWS ``diagram-as-code``). An edge trips this
    when it sets both a non-``none`` ``startArrow`` and a non-``none``
    ``endArrow``; a single-head edge (the common case) never does. Requirement
    1 (Part A)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_bidirectional(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_node_label_length(a: Artifact):
    """node-label-length: a service-node label is too long (WARNING, both classes).

    Node labels stay short — the service name — and explanatory prose belongs in
    a callout (``overlay=callout``), not crammed into the icon label, so the
    diagram stays localizable and accessible (AWS ``diagram-as-code``: "do not
    embed explanatory text into images; use short labels; use callouts"). A
    label trips the rule when it exceeds the word cap (> 4 whitespace-delimited
    words) OR the character cap (> 40 characters).

    The rule reads ``a.node_names`` only, which the CLI populates from **service
    icon cells** — Legend, Flow, title, and callout text cells are structurally
    excluded from ``node_names`` (they are text cells / the title cell), so a
    long legend or callout is never flagged. Requirement 2 (Part B)."""
    if not _is_diagram(a):
        return False
    offenders: List[str] = []
    for name in a.node_names:
        if not name:
            continue
        words = name.split()
        if len(words) > LABEL_WORD_CAP or len(name) > LABEL_CHAR_CAP:
            offenders.append(name)
    if not offenders:
        return False
    return RuleHit(offenders=offenders, reason="label-too-long")


def _is_documentation_ip(ip: "ipaddress._BaseAddress") -> bool:
    """True when ``ip`` falls inside a reserved Documentation_Range.

    The documentation ranges are the IPv4 TEST-NET blocks (RFC5737) and the
    IPv6 documentation prefix (RFC3849) — the ranges an example diagram should
    use. Part C / R3.2."""
    return any(ip in net for net in DOCUMENTATION_RANGES)


def _is_private_ip(ip: "ipaddress._BaseAddress") -> bool:
    """True when ``ip`` is private / non-routable and so not a public literal.

    Covers stdlib ``is_private`` (RFC1918 and friends, loopback, link-local,
    unspecified, reserved, multicast) plus the shared-address / benchmarking
    ranges RFC6598 and RFC6815 that older ``is_private`` implementations miss.
    Part C / R3.2."""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if getattr(ip, "is_unspecified", False) or getattr(ip, "is_reserved", False):
        return True
    return any(ip in net for net in _EXTRA_NONPUBLIC_RANGES)


def _is_network_diagram(a: Artifact) -> bool:
    """True when ``a`` is a Network_Diagram for the purposes of ``ip-range``.

    A Network_Diagram is a diagram whose ``diagram_class`` is ``landscape`` OR
    whose companion ``diagram_type`` is one of network / infrastructure /
    deployment. A flow/application diagram that incidentally mentions an address
    is not evaluated (R3.3)."""
    if not _is_diagram(a):
        return False
    if (a.diagram_class or DIAGRAM_CLASS_FLOW).lower() == DIAGRAM_CLASS_LANDSCAPE:
        return True
    dtype = (a.diagram_type or "").strip().lower()
    return dtype in _NETWORK_DIAGRAM_TYPES


def _on_diagram_text(a: Artifact) -> List[str]:
    """Collect the artifact's on-diagram text: node labels, edge labels, the
    Legend, and the Flow list (which carries callout-style prose lines).

    These are the text surfaces ``ip-range`` scans for an address literal
    (design C3). Each source is optional; a programmatic Artifact that sets only
    some of them contributes just those."""
    texts: List[str] = []
    for name in a.node_names:
        if name:
            texts.append(str(name))
    for edge in a.edges:
        label = (
            getattr(edge, "label", None)
            if not isinstance(edge, Mapping)
            else edge.get("label")
        )
        if label:
            texts.append(str(label))
    for lines in (a.legend_lines, a.flow_legend_lines):
        if lines:
            texts.extend(str(line) for line in lines if line)
    if a.title_cell:
        texts.append(str(a.title_cell))
    return texts


def _check_ip_range(a: Artifact):
    """ip-range: a Network_Diagram's on-diagram text carries a public IP (WARNING).

    Examples should use the reserved Documentation_Ranges (RFC5737 / RFC3849) or
    a private range, never a routable public address that could leak or clash
    with a real network (AWS Networking convention). The rule fires WHEN a
    Public_IP_Literal — a parseable global IP that is neither a
    Documentation_Range nor private — appears in the on-diagram text of a
    Network_Diagram.

    Scope (R3.3): only a Network_Diagram is evaluated — ``diagram_class ==
    landscape`` OR companion ``diagram_type`` in {network, infrastructure,
    deployment}. A flow/application diagram is skipped entirely.

    A token that looks address-like but does not parse under ``ipaddress`` is
    ignored (never a finding), so prose is not mis-flagged. Part C /
    Requirement 3."""
    if not _is_network_diagram(a):
        return False
    offenders: List[str] = []
    for text in _on_diagram_text(a):
        for match in _IP_CANDIDATE_RE.findall(text):
            try:
                ip = ipaddress.ip_address(match)
            except ValueError:
                continue  # address-like but not a real address — ignore.
            if _is_documentation_ip(ip) or _is_private_ip(ip):
                continue
            if not ip.is_global:
                continue
            offenders.append(match)
    if not offenders:
        return False
    return RuleHit(offenders=offenders, reason="public-ip-literal")


def _check_container_overlap(a: Artifact):
    """container-overlap: two sibling boundary containers overlap.

    A proper nesting (Account ⊃ Region ⊃ AZ) is fine; two peer boundaries that
    partially overlap put shared canvas area under two labelled groups at once,
    so a node there is ambiguous about which boundary owns it. WARNING for
    ``flow``; raised to ERROR for ``landscape``, where the nested boundary
    hierarchy is the primary device keeping a big as-built legible (v1.3.x). The
    ``landscape`` escalation to ERROR now lives in the ``RuleSpec`` (task
    10.1)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_container_overlap(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="sibling-overlap")


def _check_edge_direction(a: Artifact):
    """edge-direction: an edge breaks the exit-right/bottom, enter-left/top contract.

    Every edge with explicit contact points must exit its source on the right or
    bottom half and enter its target on the left or top half — the single
    directional rule that removes most crossings on a dense diagram. WARNING for
    ``flow``; the ``landscape`` escalation to ERROR now lives in the ``RuleSpec``
    (task 10.1)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_direction(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


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
    if not offenders:
        return False
    return RuleHit(offenders=tuple(str(o) for o in offenders), reason="no-inner-padding")


def _check_corridor_sharing(a: Artifact):
    """corridor-sharing: two long edges share one straight corridor (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_corridor_sharing(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="shared-corridor")


def _check_exit_thirds(a: Artifact):
    """exit-thirds: same-side fan-out is not centred / even-thirds, or >3 exits (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_exit_thirds(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_edge_crosses_label(a: Artifact):
    """edge-crosses-label: a routed edge polyline crosses another node's label band (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_crosses_label(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="crosses-label-band")


def _check_edge_crosses_container_label(a: Artifact):
    """edge-crosses-container-label: a routed edge crosses a container's top caption (WARNING)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_crosses_container_label(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="crosses-container-caption")


def _check_edge_crosses_container(a: Artifact):
    """edge-crosses-container: a routed edge cuts through a Boundary container
    that neither endpoint belongs to (WARNING). A stronger companion to
    ``edge-crosses-container-label`` — that one guards only the top caption
    strip, this the whole interior."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_crosses_container(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="crosses-container-interior")


def _check_edge_on_container_border(a: Artifact):
    """edge-on-container-border: a long axis-aligned edge leg coincides with a
    Boundary container border it does not belong to (WARNING). A grid-aligned
    corridor allocated beside a non-grid-aligned container edge lands ~2px off
    it and reads as riding the border (diagram-standards: *a long vertical never
    coincides with a container border*)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_on_container_border(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="rides-container-border")


def _check_edge_escapes_container(a: Artifact):
    """edge-escapes-container: a route between two nodes of ONE container leaves
    that container's interior (1.10.6, WARNING). An edge whose endpoints share a
    Boundary box is drawn inside that box; a run that steps out of it — into the
    strip between a region and its account, or out of the account into the right
    margin — reads as a relationship with something outside the box and crosses
    its border twice for nothing."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_escapes_container(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="leaves-common-container")


def _check_edge_crosses_legend(a: Artifact):
    """edge-crosses-legend: a route runs through, or along within one grid step
    of, a Flow / Legend box (1.10.6, WARNING). ``edge-routing`` always described
    keeping edges clear of the right-side furniture but never read the text
    boxes, so a run riding the Flow box's left border linted clean."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_crosses_legend(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="crosses-flow-legend-box")


def _check_edge_jog(a: Artifact):
    """edge-jog: an edge between two DIRECTLY FACING nodes (the next node on the
    same row, or directly below in the same column, nothing between) is drawn
    with a jog instead of one straight segment (1.10.6, WARNING). A straight line
    is the most readable route there is, so a directly-opposite target keeps it
    and the siblings spread around it (diagram-standards → *straight line keeps
    the centre*)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_jog(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=findings[0][1])


def _check_entry_thirds(a: Artifact):
    """entry-thirds: several edges arrive on one target face at merged/duplicate points.

    The entry-side mirror of ``exit-thirds`` (v1.5.1). Two edges landing on one
    target face at the same contact point read as a single doubled line at the
    glyph (the buggy example's two ``EC2 → RDS`` edges both at ``entryX=0,
    entryY=0.5``). WARNING for ``flow``; raised to ERROR for ``landscape``, where
    a dense as-built must keep every arrival distinct — matching how the other
    routing-family rules (``edge-direction``/``edge-float``) escalate. The
    ``landscape`` escalation to ERROR now lives in the ``RuleSpec`` (task
    10.1)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_entry_thirds(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_edge_float(a: Artifact):
    """edge-float: an edge declares no explicit exit/entry contact point.

    WARNING for ``flow``; the ``landscape`` escalation to ERROR now lives in the
    ``RuleSpec`` (task 10.1), where every edge must fix its contact points so the
    directional contract is enforceable and the perimeter router cannot drift a
    side."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_float(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="no-contact-points")


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


def _check_edge_approach(a: Artifact):
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
    findings = _geo.check_edge_approach(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_node_connectivity(a: Artifact):
    """node-connectivity: a role-bearing node is drawn with no incident edge (WARNING).

    The audit's headline finding (2026-09-25): each HA landscape drew 34 nodes
    joined by 12 edges, leaving 20 nodes entirely unconnected. Boundary containers
    and overlay-marked nodes (e.g. a ``standby`` passive peer that declares why it
    carries no edges) are exempt — see ``geometry.check_node_connectivity``."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_node_connectivity(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="no-incident-edge")


def _check_legend_placement(a: Artifact):
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
    findings = _geo.check_legend_placement(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


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


def _check_overlay_legend_coverage(a: Artifact):
    """overlay-legend-coverage: an overlay marker is not covered by the Legend (WARNING).

    When a diagram carries double-encoded overlay markers (findings / state,
    e.g. "spec-required-not-deployed", "observability-overlay", change markers),
    every marker term must be documented in the Legend. An uncovered marker is a
    WARNING. Diagrams with no overlay markers are unaffected.

    Structural in 1.7.0 (R1.12): overlay markers come from the ``overlay`` style
    key of each cell, and a term is *covered* only when it appears as a **whole
    token** in the structurally-detected Legend lines. The CLI computes
    ``legend_overlay_terms`` by whole-token matching against ``legend_lines``
    (the pre-1.7 check counted the marker's own style occurrences), so the
    predicate reports any marker not present in that covered set, naming the
    uncovered term(s) as the offenders.
    """
    if not _is_diagram(a):
        return False
    if not a.overlay_markers:
        return False
    covered = {str(t).strip().lower() for t in a.legend_overlay_terms}
    uncovered = [
        str(marker)
        for marker in a.overlay_markers
        if str(marker).strip().lower() not in covered
    ]
    if not uncovered:
        return False
    # De-duplicate while preserving document order.
    offenders: List[str] = []
    for term in uncovered:
        if term not in offenders:
            offenders.append(term)
    return RuleHit(offenders=tuple(offenders), reason="undocumented-overlay")


# ---------------------------------------------------------------------------
# New rules (honest-gates 1.7.0, task 10.2)
# ---------------------------------------------------------------------------


def _check_parse_error(a: Artifact):
    """parse-error: the artifact could not be parsed (ERROR, R1.8/R1.9).

    A ``DrawioParseError`` (a file that does not parse as XML, a page that
    cannot be decompressed, a DTD/entity declaration, a parent cycle, …) or a
    geometry-construction exception makes ``cli.parse_artifacts`` hand back an
    Artifact carrying the machine-readable cause string(s) in ``parse_errors``
    instead of silently skipping the geometry rules. This rule fires on a
    non-empty ``parse_errors`` and names the causes as offenders; ``lint()``
    short-circuits every other rule for such an artifact (there is no model to
    evaluate).
    """
    causes = list(a.parse_errors or ())
    if not causes:
        return False
    return RuleHit(offenders=tuple(causes), reason="parse-error")


def _check_edge_endpoint(a: Artifact):
    """edge-endpoint: an edge references a missing/dangling source or target.

    R1.10: the CLI records, per edge, ``missing-source``, ``missing-target``,
    ``dangling-source:<id>`` or ``dangling-target:<id>`` in ``edge_endpoints``.
    An edge with both endpoints resolved contributes nothing. WARNING for
    ``flow``, ERROR for ``landscape`` (the class escalation lives in the
    ``RuleSpec``), matching how the routing-family rules escalate on a dense
    as-built.
    """
    if not _is_diagram(a):
        return False
    endpoints = list(a.edge_endpoints or ())
    if not endpoints:
        return False
    return RuleHit(offenders=tuple(endpoints), reason="broken-edge-endpoint")


def _check_source_format(a: Artifact):
    """source-format: a diagram authored in a non-canonical source (ERROR).

    draw.io is the only publishable diagram source in 1.7.0 (D1, R10.3). A
    ``.puml`` / ``.mmd`` file is discovered by ``--all`` and carries its
    ``source_format`` (``plantuml`` / ``mermaid``); it becomes a diagram
    Artifact with ``is_drawio`` false. This rule fires on any diagram whose
    source format is not ``drawio``, naming the format as the offender.
    """
    if not _is_diagram(a):
        return False
    # Only a discovered source *file* (a ``.puml`` / ``.mmd`` parsed by the CLI,
    # which sets ``is_drawio=False`` and carries the raw ``text``) is judged. A
    # programmatic diagram Artifact keeps the legacy ``source_format="plantuml"``
    # default with no ``text`` and ``is_drawio`` unset, and must not trip this
    # ERROR — that would block every hand-built test artifact.
    if a.is_drawio or a.text is None:
        return False
    fmt = (a.source_format or "").lower()
    if fmt in ("", "drawio"):
        return False
    return RuleHit(offenders=(fmt,), reason=f"non-drawio-source:{fmt}")


# ---------------------------------------------------------------------------
# Edge-hygiene checks (1.10.5, Feature B)
# ---------------------------------------------------------------------------


def _check_marker_collision(a: Artifact):
    """marker-collision: two edge flow-markers render closer than the merge
    threshold and overprint into one number (WARNING). offenders = the edge ids
    carrying the colliding markers."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_marker_collision(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="markers-overprint")


def _check_edge_crossing_excess(a: Artifact):
    """edge-crossing-excess: the diagram's edge-crossing count exceeds a
    per-diagram cap proportional to the edge count (WARNING). offenders = the
    crossing edge-id pairs."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_edge_crossing_excess(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason="crossings-over-cap")


def _check_detour_hook(a: Artifact):
    """detour-hook: an edge's routed length far exceeds the manhattan distance
    between its contacts — it loops out and back (WARNING). offenders = the
    edge id."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_detour_hook(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


def _check_structural_integrity(a: Artifact):
    """structural-integrity: an edge endpoint resolves to no placeable box, or a
    node carries no geometry (WARNING). A cross-check adapted from the
    awesome-copilot draw.io validator; duplicate ids and parent cycles are
    caught earlier (the single parser dedupes ids; ``absolute_origin`` raises on
    a cycle, surfaced as ``parse-error``)."""
    geo = _geometry_of(a)
    if geo is None:
        return False
    from rule_engine import geometry as _geo
    findings = _geo.check_structural_integrity(geo)
    if not findings:
        return False
    return RuleHit(offenders=_offender_ids(findings), reason=_first_reason(findings))


# ---------------------------------------------------------------------------
# The RULES registry (task 10.1 / R10.1) — the single source of truth
# ---------------------------------------------------------------------------
#
# Each entry pairs a :class:`RuleSpec` (the rule's name, default severity, the
# optional ``landscape`` class escalation, and any ``reason_escalations``) with
# its predicate. Registry order defines the order findings appear in a result.
#
# ``RULE_SEVERITIES`` and ``CLASS_ESCALATIONS`` are derived from this registry
# below, so a rule's severity is declared once, here, rather than in a parallel
# dict plus an ``if landscape:`` branch inside the predicate.
RULES: Tuple[Tuple[RuleSpec, Callable[[Artifact], _PredicateResult]], ...] = (
    (RuleSpec(RULE_NODE_COUNT, Severity.ERROR), _check_node_count),
    (RuleSpec(RULE_EDGE_LABEL, Severity.WARNING), _check_edge_label),
    (RuleSpec(RULE_NODE_QUOTE, Severity.ERROR), _check_node_quote),
    (RuleSpec(RULE_LEGEND_PRESENT, Severity.ERROR), _check_legend_present),
    (RuleSpec(RULE_COMPANION_DOC, Severity.ERROR), _check_companion_doc),
    (RuleSpec(RULE_FRONTMATTER, Severity.CRITICAL), _check_frontmatter),
    (RuleSpec(RULE_ICON_RESOLVED, Severity.ERROR), _check_icon_resolved),
    (RuleSpec(RULE_SECRET_SAFETY, Severity.CRITICAL), _check_secret_safety),
    (RuleSpec(RULE_TITLE_VERSIONED, Severity.WARNING), _check_title_versioned),
    (RuleSpec(RULE_MERMAID_TYPE, Severity.WARNING), _check_mermaid_type),
    (RuleSpec(RULE_MIN_FONT_SIZE, Severity.WARNING), _check_min_font_size),
    (RuleSpec(RULE_GRID_ALIGNMENT, Severity.WARNING), _check_grid_alignment),
    # container-padding: WARNING for flow, ERROR for landscape (nested labelled
    # containers are load-bearing on an as-built).
    (
        RuleSpec(RULE_CONTAINER_PADDING, Severity.WARNING, landscape=Severity.ERROR),
        _check_container_padding,
    ),
    # container-dead-space: advisory WARNING on BOTH classes (the mirror of
    # container-padding — a container sized far larger than its children). Never
    # blocks alone; no landscape escalation (placement-and-gates Part C).
    (
        RuleSpec(RULE_CONTAINER_DEAD_SPACE, Severity.WARNING),
        _check_container_dead_space,
    ),
    # edge-routing: a bare non-orthogonal edge is a WARNING, but a run cutting
    # through an icon it does not connect (``*-through-*``) or into its own
    # target from the wrong side (``pierces-target-*``) is an ERROR on either
    # class. Modelled as reason_escalations so the sync test can read it.
    (
        RuleSpec(
            RULE_EDGE_ROUTING,
            Severity.WARNING,
            reason_escalations={
                "through-": Severity.ERROR,
                "pierces-": Severity.ERROR,
            },
        ),
        _check_edge_routing,
    ),
    (RuleSpec(RULE_NODE_OVERLAP, Severity.WARNING), _check_node_overlap),
    (RuleSpec(RULE_ARROW_STYLE, Severity.WARNING), _check_arrow_style),
    # edge-bidirectional: a double-headed arrow (WARNING, both classes). No
    # landscape escalation — advisory on both, like arrow-style (1.10.0, Part A).
    (RuleSpec(RULE_EDGE_BIDIRECTIONAL, Severity.WARNING), _check_edge_bidirectional),
    # node-label-length: a service-node label longer than the word/char cap
    # (WARNING, both classes). No landscape escalation — advisory on both; the
    # cap is on the icon label only, callouts carry the prose (1.10.0, Part B).
    (RuleSpec(RULE_NODE_LABEL_LENGTH, Severity.WARNING), _check_node_label_length),
    # ip-range: a public IP literal in a Network_Diagram's on-diagram text
    # (WARNING). No landscape escalation — advisory on both; the rule is already
    # scoped to a Network_Diagram (landscape OR a network/infra/deployment
    # diagram_type), so it does not fire on a flow diagram at all (1.10.0, Part C).
    (RuleSpec(RULE_IP_RANGE, Severity.WARNING), _check_ip_range),
    # container-overlap: WARNING for flow, ERROR for landscape (sibling
    # boundaries must not overlap on an as-built).
    (
        RuleSpec(RULE_CONTAINER_OVERLAP, Severity.WARNING, landscape=Severity.ERROR),
        _check_container_overlap,
    ),
    # edge-direction: WARNING for flow, ERROR for landscape (the directional
    # contract is strict on a dense as-built).
    (
        RuleSpec(RULE_EDGE_DIRECTION, Severity.WARNING, landscape=Severity.ERROR),
        _check_edge_direction,
    ),
    (RuleSpec(RULE_TEXT_PADDING, Severity.WARNING), _check_text_padding),
    (RuleSpec(RULE_CORRIDOR_SHARING, Severity.WARNING), _check_corridor_sharing),
    # edge-float: WARNING for flow, ERROR for landscape (every edge must pin its
    # contact points on a dense diagram).
    (
        RuleSpec(RULE_EDGE_FLOAT, Severity.WARNING, landscape=Severity.ERROR),
        _check_edge_float,
    ),
    (RuleSpec(RULE_EXIT_THIRDS, Severity.WARNING), _check_exit_thirds),
    # entry-thirds: WARNING for flow, ERROR for landscape (arrivals on one face
    # must stay distinct on a dense diagram).
    (
        RuleSpec(RULE_ENTRY_THIRDS, Severity.WARNING, landscape=Severity.ERROR),
        _check_entry_thirds,
    ),
    (RuleSpec(RULE_EDGE_CROSSES_LABEL, Severity.WARNING), _check_edge_crosses_label),
    (
        RuleSpec(RULE_EDGE_CROSSES_CONTAINER_LABEL, Severity.WARNING),
        _check_edge_crosses_container_label,
    ),
    (
        RuleSpec(RULE_EDGE_CROSSES_CONTAINER, Severity.WARNING),
        _check_edge_crosses_container,
    ),
    (
        RuleSpec(RULE_EDGE_ON_CONTAINER_BORDER, Severity.WARNING),
        _check_edge_on_container_border,
    ),
    # deterministic-engine 1.10.6: three advisory routing rules (both classes).
    (
        RuleSpec(RULE_EDGE_ESCAPES_CONTAINER, Severity.WARNING),
        _check_edge_escapes_container,
    ),
    (RuleSpec(RULE_EDGE_CROSSES_LEGEND, Severity.WARNING), _check_edge_crosses_legend),
    (RuleSpec(RULE_EDGE_JOG, Severity.WARNING), _check_edge_jog),
    (RuleSpec(RULE_LEGEND_PLACEMENT, Severity.WARNING), _check_legend_placement),
    (RuleSpec(RULE_FLOW_LEGEND, Severity.WARNING), _check_flow_legend),
    (RuleSpec(RULE_NODE_CONNECTIVITY, Severity.WARNING), _check_node_connectivity),
    (RuleSpec(RULE_EDGE_APPROACH, Severity.WARNING), _check_edge_approach),
    (RuleSpec(RULE_ORPHAN_LANDSCAPE, Severity.ERROR), _check_orphan_landscape),
    (
        RuleSpec(RULE_OVERLAY_LEGEND_COVERAGE, Severity.WARNING),
        _check_overlay_legend_coverage,
    ),
    # honest-gates 1.7.0 (task 10.2). ``source-format`` is an ERROR: draw.io is
    # the only publishable diagram source (D1). ``edge-endpoint`` is WARNING for
    # flow, ERROR for landscape (a dense as-built must resolve every endpoint).
    (RuleSpec(RULE_SOURCE_FORMAT, Severity.ERROR), _check_source_format),
    (
        RuleSpec(RULE_EDGE_ENDPOINT, Severity.WARNING, landscape=Severity.ERROR),
        _check_edge_endpoint,
    ),
    # edge-hygiene 1.10.5 (Feature B). Four edge-legibility / structural rules,
    # all WARNING on both classes (advisory — like arrow-style / node-overlap;
    # they never block publication, matching Requirement 7's WARNING contract).
    (RuleSpec(RULE_MARKER_COLLISION, Severity.WARNING), _check_marker_collision),
    (
        RuleSpec(RULE_EDGE_CROSSING_EXCESS, Severity.WARNING),
        _check_edge_crossing_excess,
    ),
    (RuleSpec(RULE_DETOUR_HOOK, Severity.WARNING), _check_detour_hook),
    (
        RuleSpec(RULE_STRUCTURAL_INTEGRITY, Severity.WARNING),
        _check_structural_integrity,
    ),
)

# ``parse-error`` is not iterated with the other rules: when it fires, every
# other rule is skipped for that artifact (there is no model to evaluate), so
# ``lint()`` checks it first and short-circuits. Its RuleSpec is declared here so
# its severity is derived into ``RULE_SEVERITIES`` like every other rule.
PARSE_ERROR_SPEC = RuleSpec(RULE_PARSE_ERROR, Severity.ERROR)

# Severity assigned to each rule when its condition holds, DERIVED from the
# RULES registry (authoritative table). ``RULE_SEVERITIES`` is a rule's default
# (flow) severity; ``CLASS_ESCALATIONS`` maps a rule to its ``landscape``
# severity when it differs (used by the diagram-lint.md sync test, R10.1).
RULE_SEVERITIES: Dict[str, Severity] = {
    PARSE_ERROR_SPEC.name: PARSE_ERROR_SPEC.default,
    **{spec.name: spec.default for spec, _ in RULES},
}
CLASS_ESCALATIONS: Dict[str, Severity] = {
    spec.name: spec.landscape for spec, _ in RULES if spec.landscape is not None
}

# The RuleSpec for each rule, keyed by name, for callers that need the full
# declaration (severity_for, reason_escalations).
RULE_SPECS: Dict[str, RuleSpec] = {
    PARSE_ERROR_SPEC.name: PARSE_ERROR_SPEC,
    **{spec.name: spec for spec, _ in RULES},
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

_BLOCKING_SEVERITIES = frozenset({Severity.CRITICAL, Severity.ERROR})


def _as_hits(result: _PredicateResult) -> List[RuleHit]:
    """Normalize a predicate return value into a list of :class:`RuleHit`.

    Accepts a ``RuleHit``, a list of ``RuleHit``, a bare ``True`` (one hit with
    no offenders and the rule's default severity), or an explicit ``Severity``
    (one hit whose severity overrides ``severity_for`` — used by ``node-count``).
    A falsy result never reaches here (the caller skips it).
    """
    if isinstance(result, RuleHit):
        return [result]
    if isinstance(result, Severity):
        return [RuleHit(severity=result)]
    if isinstance(result, list):
        hits: List[RuleHit] = []
        for item in result:
            if isinstance(item, RuleHit):
                hits.append(item)
            elif isinstance(item, Severity):
                hits.append(RuleHit(severity=item))
            else:
                hits.append(RuleHit())
        return hits
    # A bare True (or any other truthy non-hit): one default hit.
    return [RuleHit()]


# ---------------------------------------------------------------------------
# Ruleset-unavailable handling (Requirement 7 AC14)
# ---------------------------------------------------------------------------

# The ruleset location and the ``ruleset-unavailable`` handling moved to
# :mod:`rule_engine.ruleset` in 1.7.0 (task 7.1 / Requirement 10.2), so the
# Lint_CLI and the Contract locate the ruleset the same way and fail closed
# identically. They are re-exported here so existing callers of
# ``linter.find_ruleset`` / ``linter.ruleset_available`` / the constants keep
# working unchanged.
from rule_engine.ruleset import (  # noqa: E402  (re-export after module setup)
    RULESET_RELATIVE_PATH,
    RULESET_UNAVAILABLE_ERROR,
    RulesetUnavailableError,
    find_ruleset,
    require_ruleset,
    ruleset_available,
)


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
    diagram_class = (getattr(art, "diagram_class", None) or DIAGRAM_CLASS_FLOW)

    findings: List[Dict[str, Any]] = []

    # parse-error handling (task 10.2 / R1.8, R1.9). An artifact the CLI could
    # not parse carries the cause(s) in ``parse_errors``. For a *diagram* there
    # is no model, so parse-error is the ONLY finding and every other rule is
    # skipped. A *snapshot* that carries a parse-error still has scannable text
    # (an unparsable ``.json`` is scanned as text — task 10.3 / R3.5), so its
    # parse-error is emitted and the remaining rules — chiefly ``secret-safety``
    # — still run: the two findings coexist, exactly as the design requires.
    parse_hit = _check_parse_error(art)
    if parse_hit:
        for hit in _as_hits(parse_hit):
            findings.append(
                {
                    "rule": PARSE_ERROR_SPEC.name,
                    "severity": PARSE_ERROR_SPEC.severity_for(
                        diagram_class, hit.reason
                    ).value,
                    "offenders": list(hit.offenders),
                    "reason": hit.reason,
                }
            )
        # A snapshot / in-snapshot artifact with scannable text does not
        # short-circuit — secret-safety must still see the text. Everything
        # else (a diagram with no model, a binary snapshot with no text) does.
        has_scannable_text = _secret_applies(art) and (
            art.text is not None or art.content is not None
        )
        if not has_scannable_text:
            return {
                "findings": findings,
                "eligible_for_publication": False,
                "label": getattr(art, "label", None),
            }

    for spec, predicate in RULES:
        result = predicate(art)
        if not result:
            continue
        # A predicate may return:
        #   * a ``RuleHit`` (or list of hits) carrying offenders + reason;
        #   * a bare ``True`` (use the RuleSpec's severity_for, no offenders); or
        #   * an explicit ``Severity`` (node-count, whose severity depends on the
        #     node count itself, not on the class alone).
        for hit in _as_hits(result):
            reason = hit.reason
            if hit.severity is not None:
                severity = hit.severity
            else:
                severity = spec.severity_for(diagram_class, reason)
            findings.append(
                {
                    "rule": spec.name,
                    "severity": severity.value,
                    "offenders": list(hit.offenders),
                    "reason": reason,
                }
            )

    eligible = not any(
        Severity(f["severity"]) in _BLOCKING_SEVERITIES for f in findings
    )

    result_dict: Dict[str, Any] = {
        "findings": findings,
        "eligible_for_publication": eligible,
        # Each result carries the artifact's label (``<file>#<page>`` for a
        # multi-page file, else the file path) so the Lint_CLI can name what was
        # evaluated (R1.13). ``None`` for a programmatic artifact with no label.
        "label": getattr(art, "label", None),
    }
    return result_dict


__all__ = [
    "Severity",
    "RuleSpec",
    "RuleHit",
    "RULES",
    "RULE_SPECS",
    "CLASS_ESCALATIONS",
    "Edge",
    "Artifact",
    "lint",
    "lint_with_ruleset",
    "ruleset_available",
    "find_ruleset",
    "require_ruleset",
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
    "RULE_CONTAINER_DEAD_SPACE",
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
    "RULE_EDGE_CROSSES_CONTAINER",
    "RULE_EDGE_ON_CONTAINER_BORDER",
    "RULE_EDGE_ESCAPES_CONTAINER",
    "RULE_EDGE_CROSSES_LEGEND",
    "RULE_EDGE_JOG",
    "RULE_LEGEND_PLACEMENT",
    "RULE_FLOW_LEGEND",
    "RULE_NODE_CONNECTIVITY",
    "RULE_EDGE_APPROACH",
    "RULE_PARSE_ERROR",
    "RULE_EDGE_ENDPOINT",
    "RULE_SOURCE_FORMAT",
    "PARSE_ERROR_SPEC",
    "LANDSCAPE_NODE_WARN",
    "LANDSCAPE_NODE_ERROR",
    "DIAGRAM_CLASS_FLOW",
    "DIAGRAM_CLASS_LANDSCAPE",
]
