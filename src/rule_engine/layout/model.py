"""Coordinate-free declaration model and placed-geometry model types.

This module is the first slice of the ``layout/`` package split (scored-router
release 1.8.0, Phase A, task 1.1). It holds the frozen-dataclass *declaration*
model (:class:`NodeSpec`, :class:`EdgeSpec`, :class:`ContainerSpec`,
:class:`DiagramSpec`) and the *placed-geometry* model (:class:`PlacedEdge`,
:class:`PlacedDiagram`), relocated verbatim from ``layout_engine.py``.

This is a **behavior-preserving mechanical relocation**: every type field, name
and default is identical to its pre-split definition. No logic moved with these
types — placement, contacts, corridors and routers relocate in later tasks.

**Coordinates are the engine's output, never its input.** The declaration
dataclasses deliberately carry *no* ``x``/``y``/``w``/``h``/``exit``/``entry``/
``points`` fields, so a coordinate cannot be expressed in a declaration
(Req 1.4). The placed model (:class:`PlacedEdge`/:class:`PlacedDiagram`) is the
engine's output and *does* carry geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout.model``
    from ..geometry import Box
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from geometry import Box  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Contact / Point primitives
# ---------------------------------------------------------------------------

#: A contact point is a unit-square fraction on a node face: ``(fx, fy)`` where
#: ``fx`` grows to the right and ``fy`` grows downward (draw.io convention).
Contact = Tuple[float, float]

#: A waypoint is an absolute ``(x, y)`` model coordinate on a corridor line.
Point = Tuple[float, float]


# ---------------------------------------------------------------------------
# Declaration data model (Req 1) — coordinate-free, frozen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeSpec:
    """A node declaration: role + lane + region + slot only (Req 1.1).

    No ``x``/``y``: placement is derived by the engine from ``(lane, region,
    slot, sub)`` and the canonical constants.
    """

    id: str
    role: str  # resolves to an icon via the provider skin / icon-index
    lane: str  # one of the eight canonical lanes (see LANES)
    region: str  # "a" | "b" | "" (account-level, e.g. an edge row)
    slot: int  # 0-indexed position within (lane, region)
    sub: int = 0  # optional secondary offset for a sub-row (api / monitoring)
    #: Optional **declared** container membership — the id of the leaf container
    #: this node belongs to (an ``az`` box, or a region ``vpc`` for a service-row
    #: node that sits in the VPC directly rather than any AZ). This is
    #: coordinate-free: it names a container, never geometry. When set, the
    #: node's container membership is authoritative (used by
    #: :func:`_assign_nodes_to_leaves`); when ``None`` the engine falls back to
    #: the geometric tier-band partition (preserving synthetic-spec behavior).
    #: Validated by :func:`_validate_spec` to name a real, region-matching leaf
    #: container.
    container: Optional[str] = None
    #: Optional **overlay marker** term from the Overlay Vocabulary
    #: (diagram-standards), e.g. ``"standby"``. An overlay-marked node declares
    #: why it is drawn the way it is; in particular a ``standby`` passive peer is
    #: exempt from ``node-connectivity`` because the marker — double-encoded as a
    #: dashed outline, a label token, and a Legend entry — states that it mirrors
    #: an active peer with its edges omitted for clarity. Coordinate-free: it
    #: names a vocabulary term, never geometry.
    overlay: Optional[str] = None


@dataclass(frozen=True)
class EdgeSpec:
    """An edge declaration: source/target/marker only (Req 1.2).

    No ``exit``/``entry``/``points``: contact points and waypoints are the
    engine's output. The edge *class* is derived from the source/target lane +
    region relationship; ``kind_hint`` is an optional override, not a coordinate.
    """

    id: str
    source: str
    target: str
    marker: str
    dashed: bool = False
    kind_hint: Optional[str] = None
    #: Engine-derived (never authored): ``True`` when both endpoints belong to
    #: the same non-empty region, ``False`` for two different regions, ``None``
    #: when unknown. Set by ``layout()`` from the node declarations so the
    #: geometric classifier never calls an in-region hop ``cross-region`` just
    #: because it is long (1.10.3). Not a coordinate.
    same_region: Optional[bool] = None


@dataclass(frozen=True)
class ContainerSpec:
    """A container declaration: kind + region + nesting only (Req 1.3).

    No ``x``/``y``/``w``/``h``: the engine sizes each container around its
    children's footprints.
    """

    id: str
    kind: str  # "account" | "region" | "vpc" | "az"
    region: str
    parent: Optional[str]  # nesting: az.parent = vpc, vpc.parent = account
    label_key: str  # the skin fills the concrete label


@dataclass(frozen=True)
class DiagramSpec:
    """A whole coordinate-free diagram declaration."""

    diagram_id: str
    diagram_name: str
    axis: str  # "north-south" | "left-right"
    nodes: Tuple[NodeSpec, ...]
    edges: Tuple[EdgeSpec, ...]
    containers: Tuple[ContainerSpec, ...]
    flow_lines: Tuple[str, ...]
    title: str
    #: Compact the primary axis for a small flow diagram: place the *occupied*
    #: lanes at **consecutive** steps rather than at their absolute lane index,
    #: so a ``lb → app → db`` chain reads as three adjacent rows with no empty
    #: tier bands between them (the hand-drawn summary composition). Off by
    #: default so the landscape and every synthetic spec keep absolute-lane
    #: placement byte-unchanged. Only affects **non-banded** nodes (a compact
    #: flow declares no az/vpc container membership).
    compact: bool = False
    #: Optional presentation of each container — ``(container_id, caption)`` and
    #: ``(container_id, draw.io style)`` pairs the skin will draw (1.10.6). Not
    #: geometry: the engine never reads a coordinate from them. They let the
    #: layout oracle and the scored solver judge the diagram the linter will see —
    #: a caption is sized from its real text and drawn where its real style puts
    #: it, so ``edge-crosses-container-label`` is scored during layout instead of
    #: discovered afterwards. Absent → the oracle's stub caption (the id) and
    #: stub style, exactly as before.
    container_captions: Tuple[Tuple[str, str], ...] = ()
    container_styles: Tuple[Tuple[str, str], ...] = ()
    #: Reserve a corridor lane below the caption strip of every container whose
    #: first row is entered from the side (``layout.base._top_lane_containers``,
    #: 1.10.6). Off in a declaration; the scored placement loop tries it as the
    #: ``caption-lane`` move and keeps it only when the finished diagram scores
    #: better — it removes a caption crossing on one diagram and adds crossings on
    #: another, so it is a measured choice, not a rule. Not a coordinate.
    caption_lanes: bool = False
    #: Optional ``(node_id, display label)`` pairs (1.10.7). Presentation only,
    #: like ``container_captions``: the engine reads nothing from them but the
    #: caption WIDTH, so the right-margin Flow/Legend clears a wide caption
    #: (``layout.repair.place_legend_for``). Not a coordinate.
    #:
    #: Who must set it: any caller that builds a ``DiagramSpec`` itself — by
    #: hand, or through private builder APIs such as ``_boundaries_from`` /
    #: ``_edges_from``. ``rule-engine-draw`` (``draw_cli.build_drawio``) already
    #: does. Absent → each caption is taken as icon-wide, so ``placed.legend_x``
    #: can land over a wide caption on a node right of the account and lint
    #: reports ``legend-placement`` ``overlaps-node-<id>`` (ERROR). Pass the same
    #: text given to ``diagram_layout.Node(label=…)``, e.g.
    #: ``node_labels=tuple({"users": "Quick users"}.items())``.
    node_labels: Tuple[Tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------
# Placed-geometry model — the engine's output
# ---------------------------------------------------------------------------


@dataclass
class PlacedEdge:
    """One fully-placed edge: its spec plus the engine's emitted geometry.

    ``exit``/``entry`` are the contact points the ladder chose and ``points`` the
    corridor-aligned waypoints the router emitted — exactly the fields
    :class:`diagram_layout.Edge` consumes, so a ``PlacedEdge`` serializes with no
    further geometry work (Req 1.2: geometry is the engine's output)."""

    spec: EdgeSpec
    exit: Contact
    entry: Contact
    points: List[Point]


@dataclass
class PlacedDiagram:
    """A fully-placed diagram, ready to hand to ``build_diagram`` (design.md §9).

    Holds the placed node boxes, the sized container boxes, the routed edges, and
    the right-margin ``legend_x``/``legend_w`` — everything ``build_diagram``
    needs, and everything the oracle adapter re-parses. The declaration
    (``spec``) is retained so a repair can re-run a pipeline step (e.g. re-centre
    a region's block) deterministically."""

    spec: DiagramSpec
    nodes: Dict[str, Box]
    containers: Dict[str, Box]
    edges: List[PlacedEdge]
    legend_x: int
    legend_w: int
    #: Blocking oracle findings the bounded repair loop could not clear
    #: (``"<rule>: <payload>"``, deterministic order), 1.10.7. Empty for an
    #: oracle-clean layout. A non-strict :func:`~rule_engine.layout.layout`
    #: returns its best candidate with these surfaced instead of raising.
    layout_warnings: Tuple[str, ...] = ()
    #: ``True`` when the scored or the legacy finish of this candidate ended with
    #: residual findings — the case in which a strict layout would have raised
    #: (1.10.7). A golden builder lays out with ``strict=True`` so it never ships
    #: a degraded diagram.
    degraded: bool = False
