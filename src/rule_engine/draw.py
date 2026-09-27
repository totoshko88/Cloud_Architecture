"""Snapshot → ``DiagramSpec`` autogenerator core (Part J; design J2–J5).

This module is the **translator** half of the ``rule-engine-draw`` autogenerator
(release 1.10.0, ``.kiro/specs/provider-diagram-conventions``, Requirement 10,
closing ``docs/REVIEW.md`` gap **G8**). It turns a committed inventory Snapshot
into the *existing* coordinate-free :class:`~rule_engine.layout.model.DiagramSpec`
so the unchanged ``layout()`` + ``build_diagram()`` pipeline can place, route, and
serialize it. It adds **no** geometry type, **no** solver, and **no** lint rule —
it reuses machinery that already exists:

* **role resolution** — :func:`rule_engine.reconcile.role_of`, reused *verbatim*
  (never reimplemented). Every enumerated resource in the Snapshot's per-domain
  JSON is mapped to one of the 16 diagram roles; a resource with no resolvable
  role is **skipped**, never drawn with a look-alike icon (Requirement 10.2).
* **the declaration model** — the existing ``NodeSpec`` / ``EdgeSpec`` /
  ``ContainerSpec`` / ``DiagramSpec`` (design "no new geometry type for J").

The only genuinely new logic here is:

1. :func:`lane_of` — a pure, deterministic role → lane table, consistent with
   the fixed lane order in ``diagram-standards.md`` (Requirement 10.3), and
2. :func:`spec_from_snapshot` — the Snapshot → spec assembly (Requirement 10.4,
   10.5, 10.6, 10.7).

Everything is **pure and offline** (Decision D5): it reads only committed
Snapshot files, never provider state, never a socket, never the wall clock or a
random source. Two runs on the same Snapshot and inputs therefore produce an
identical :class:`DiagramSpec` (Requirement 10.6): resources are placed by a
**stable sort** of their identity, so slot assignment, node order, and container
order do not depend on dict iteration order.

The command front-end (the ``rule-engine-draw`` console script that hands the
spec to ``layout()`` + ``build_diagram()`` and writes the companion / triple) is
task 8, in :mod:`rule_engine.draw_cli`; this module is only the translator.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rule_engine.constants import PROVIDERS
from rule_engine.reconcile import (
    SnapshotReadError,
    iter_domain_resources,
    role_of,
)

try:  # package-relative when used as ``rule_engine.layout``
    from rule_engine.layout.model import (
        ContainerSpec,
        DiagramSpec,
        EdgeSpec,
        NodeSpec,
    )
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from layout.model import (  # type: ignore[no-redef]
        ContainerSpec,
        DiagramSpec,
        EdgeSpec,
        NodeSpec,
    )

# The landscape node-count ERROR bound (> 50) is owned by the Linter; import it
# so the "split the Snapshot" threshold cannot drift from the rule that would
# otherwise block the produced diagram (Requirement 10.7).
try:
    from rule_engine.linter import LANDSCAPE_NODE_ERROR
except ImportError:  # pragma: no cover - defensive; keep the module importable
    LANDSCAPE_NODE_ERROR = 50


__all__ = [
    "lane_of",
    "spec_from_snapshot",
    "DrawError",
    "SnapshotSplitRequired",
    "LANE_OF",
    "DIAGRAM_TYPES",
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DrawError(ValueError):
    """Raised when a Snapshot cannot be turned into a spec (a generation error).

    An unknown provider, an unknown diagram type, or a missing / unreadable
    Snapshot folder is a generation *error* — reported, never a silently empty
    diagram. A resource with no resolvable role is **not** an error (it is
    skipped per :func:`rule_engine.reconcile.role_of`).
    """


class SnapshotSplitRequired(DrawError):
    """Raised when a ``landscape`` exceeds the node-count ERROR bound (> 50).

    Per Requirement 10.7 an over-budget ``landscape`` is reported as "split the
    Snapshot" with **no spec emitted**, rather than emitting a diagram the
    ``node-count`` rule would block. The message names the role-bearing count and
    the bound so an operator knows how far over budget the Snapshot is.
    """


# --------------------------------------------------------------------------- #
# J3 — role → lane (pure, deterministic)
# --------------------------------------------------------------------------- #

# The role → lane table (design J3), consistent with the fixed lane order in
# diagram-standards.md:
#
#   actors → edge → router → async → workers → platform → data → on-premises
#
# (The canonical lane ids in rule_engine.layout.base.LANES spell the two
# multi-word lanes ``async`` and ``platform``; diagram-standards spells them
# "async messaging" and "platform core". The ids below are the LANES spellings,
# which _validate_spec accepts.)
#
# Every one of the 16 diagram roles (nine neutral types + seven presentation
# roles) has a lane. The mapping is total so no role-bearing resource is ever
# dropped for want of a lane.
LANE_OF: Dict[str, str] = {
    # Structural boundaries are drawn as containers, not lane-placed service
    # nodes; when a boundary resource is nonetheless surfaced as a node it sits
    # in the edge lane (the outermost tier), never inside a tier it would
    # visually contradict.
    "boundary": "edge",
    "network_boundary": "edge",
    # edge lane — the internet-facing presentation roles.
    "cdn": "edge",
    "dns": "edge",
    "waf": "edge",
    # router lane — load balancing.
    "lb": "router",
    # async lane — messaging.
    "message_queue": "async",
    # workers lane — the compute tiers.
    "serverless_fn": "workers",
    "managed_k8s": "workers",
    "compute_instance": "workers",
    # platform core lane — the model/inference platform.
    "llm_platform": "platform",
    # data lane — every store.
    "object_store": "data",
    "managed_sql": "data",
    "file_system": "data",
    "cache": "data",
    "secrets_store": "data",
}


def lane_of(role: str) -> str:
    """Return the canonical lane for a diagram ``role`` (design J3).

    Pure and deterministic: a fixed table lookup, consistent with the fixed lane
    order in ``diagram-standards.md``. ``role`` is one of the 16 diagram roles
    (:data:`rule_engine.constants.RESOURCE_TYPES`). Raises :class:`DrawError` for
    an unknown role rather than guessing a lane — an unmapped role is a
    programming error (``role_of`` only ever returns one of the 16), never a
    silent mis-placement.
    """
    try:
        return LANE_OF[role]
    except KeyError as exc:
        raise DrawError(f"no lane for role {role!r}") from exc


# --------------------------------------------------------------------------- #
# J4 / J5 — Snapshot → DiagramSpec assembly
# --------------------------------------------------------------------------- #

#: The three user-facing diagram types (diagram-standards → "Choosing the
#: diagram type after inventory"). ``simple`` / ``summary`` are the ``flow`` lint
#: class; ``landscape`` is the ``landscape`` class.
DIAGRAM_TYPES: Tuple[str, ...] = ("simple", "summary", "landscape")

#: The ``flow`` node budget (diagram-standards → Node Limit). A ``simple`` /
#: ``summary`` diagram shows the in-scope subset up to this many nodes.
_FLOW_NODE_BUDGET = 12


def _manifest_field(manifest_text: str, field: str) -> Optional[str]:
    """Extract one ``| field | value |`` cell from a Snapshot manifest table.

    The Collector writes the seven mandatory fields as a Markdown table in
    ``00-MANIFEST.md`` (inventory-standards §4), e.g. ``| boundary_id | 123 |``.
    Returns the trimmed value for ``field`` (case-insensitive on the key), or
    ``None`` when the field is absent. Pure text parsing — reads no provider
    state.
    """
    pattern = re.compile(
        r"^\s*\|\s*" + re.escape(field) + r"\s*\|\s*(.+?)\s*\|\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(manifest_text)
    if not m:
        return None
    value = m.group(1).strip()
    return value or None


def _read_manifest(snapshot_dir: Path) -> Tuple[str, str]:
    """Return ``(boundary_id, region)`` read from the Snapshot's manifest.

    Reads ``00-MANIFEST.md`` at the Snapshot root (inventory-standards §4) and
    extracts ``boundary_id`` and the first region of ``region_set``. Falls back
    to parsing the ``inventory-<provider>-<boundary>-<region>-<ts>`` folder name
    when a field is absent, so a Snapshot with a terse manifest still yields the
    container labels. Both are *labels* only — coordinate-free container
    metadata, never geometry.
    """
    boundary_id: Optional[str] = None
    region: Optional[str] = None
    manifest = snapshot_dir / "00-MANIFEST.md"
    if manifest.is_file():
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text:
            boundary_id = _manifest_field(text, "boundary_id")
            region_set = _manifest_field(text, "region_set")
            if region_set:
                # region_set may list several regions; take the first, stably.
                region = re.split(r"[,\s]+", region_set.strip())[0] or None

    # Fall back to the folder name convention when a field is missing.
    if boundary_id is None or region is None:
        fb_boundary, fb_region = _boundary_region_from_name(snapshot_dir.name)
        boundary_id = boundary_id or fb_boundary
        region = region or fb_region

    return boundary_id or "boundary", region or "region"


def _boundary_region_from_name(folder: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse ``inventory-<provider>-<boundary>-<region>-<YYYY-MM-DD_HHMM>``.

    The boundary and region can themselves contain hyphens, so the trailing
    ``<YYYY-MM-DD_HHMM>`` timestamp is stripped first, then the leading
    ``inventory-<provider>-`` prefix; what remains is ``<boundary>-<region>``. The
    region is taken as the final ``-``-segment and the boundary as the rest — a
    best-effort recovery used only when the manifest omits a field.
    """
    name = folder
    # Strip the trailing UTC timestamp: -YYYY-MM-DD_HHMM
    name = re.sub(r"-\d{4}-\d{2}-\d{2}_\d{4}$", "", name)
    parts = name.split("-")
    if len(parts) < 4 or parts[0] != "inventory":
        return None, None
    # parts[1] is the provider; the remainder is <boundary>...-<region>.
    remainder = parts[2:]
    if len(remainder) < 2:
        return None, None
    region = remainder[-1]
    boundary = "-".join(remainder[:-1])
    return boundary or None, region or None


def _resource_identity(resource: Mapping[str, Any]) -> str:
    """Return a stable identity string for a Snapshot resource.

    Prefers ``id`` then ``arn`` then ``name`` (the durable identifiers), falling
    back to a sorted-key repr so *every* resource has a deterministic identity to
    stable-sort by. Only identity/name metadata is read — never a secret value.
    Reused as the ``NodeSpec.id`` seed and as the stable-sort key.
    """
    for key in ("id", "arn", "name"):
        value = resource.get(key)
        if value is not None and str(value) != "":
            return str(value)
    # Deterministic fallback: sorted (key, value) pairs.
    return repr(sorted((str(k), str(v)) for k, v in resource.items()))


def _slug(text: str) -> str:
    """Filesystem/id-safe slug (lowercase, ``[a-z0-9_-]`` only).

    Matches the node-id character set the diagram standards allow unquoted and
    keeps ids stable across runs. An empty result collapses to ``node``.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return slug or "node"


def _iter_snapshot_resources(
    snapshot_dir: Path, provider: str
) -> List[Tuple[Mapping[str, Any], str]]:
    """Return every ``(resource, role)`` in the Snapshot, role-resolvable only.

    Walks the committed per-domain JSON files at the Snapshot root in **sorted
    filename order** (deterministic), maps each resource through the reused
    :func:`rule_engine.reconcile.role_of`, and keeps only those that resolve to a
    role — a resource with no role is skipped, never drawn (Requirement 10.2).
    ``failures.json`` is a collector artefact, not a domain file, and is skipped.

    Offline (Decision D5): reads only committed ``*.json`` files. Propagates
    :class:`rule_engine.reconcile.SnapshotReadError` as a :class:`DrawError` for
    a domain file that does not parse.
    """
    out: List[Tuple[Mapping[str, Any], str]] = []
    for domain_file in sorted(snapshot_dir.glob("*.json")):
        if domain_file.name == "failures.json":
            continue
        try:
            resources = list(iter_domain_resources(domain_file))
        except SnapshotReadError as exc:
            raise DrawError(str(exc)) from exc
        for resource in resources:
            role = role_of(resource, provider)
            if role is not None:
                out.append((resource, role))
    return out


def spec_from_snapshot(
    snapshot_dir: Any,
    provider: str,
    diagram_type: str,
    relationships: Optional[Sequence[Mapping[str, Any]]] = None,
) -> DiagramSpec:
    """Build a coordinate-free :class:`DiagramSpec` from a committed Snapshot.

    This is the design's J4/J5 assembly, reusing J2 (``reconcile.role_of``) and
    J3 (:func:`lane_of`):

    * **Resolve** every enumerated resource to a role via the reused
      :func:`rule_engine.reconcile.role_of`; skip a resource with no resolvable
      role — never draw a look-alike (Requirement 10.2).
    * **Lane** each role via :func:`lane_of` (Requirement 10.3).
    * **Containers** — derive an account ``ContainerSpec`` (and its label) from
      the manifest ``boundary_id`` / ``region_set`` (Requirement 10.3). A single
      account boundary is emitted; region/AZ nesting is left to a supplied
      topology (this core places every node in the account band, region ``""``).
    * **Nodes** — one :class:`NodeSpec` per role-bearing resource, its ``slot``
      assigned by a **stable sort** of ``(lane_index, resource_identity)`` within
      each lane so two runs produce identical specs (Requirement 10.6).
    * **Edges** — one :class:`EdgeSpec` per supplied Relationship_Input; **no**
      edge is invented when ``relationships`` is absent (Requirement 10.5).

    Coverage by type (Requirement 10.4, 10.7):

    * ``landscape`` — every role-bearing resource is a node (total coverage), so
      the produced diagram passes ``rule-engine-reconcile``. A ``landscape`` whose
      role-bearing count exceeds the ``node-count`` ERROR bound (> 50) raises
      :class:`SnapshotSplitRequired` with **no spec emitted**.
    * ``simple`` / ``summary`` — the in-scope subset, capped at the ``flow`` node
      budget (12); the first 12 role-bearing resources by the same stable order.

    Deterministic and offline: no wall-clock, no randomness, no dict-order
    dependence (Requirement 10.6, Decision D5).
    """
    provider = str(provider)
    if provider not in PROVIDERS:
        raise DrawError(f"unknown provider {provider!r} (expected one of {PROVIDERS})")
    diagram_type = str(diagram_type).lower()
    if diagram_type not in DIAGRAM_TYPES:
        raise DrawError(
            f"unknown diagram type {diagram_type!r} (expected one of {DIAGRAM_TYPES})"
        )

    snap = Path(snapshot_dir)
    if not snap.is_dir():
        raise DrawError(f"snapshot folder not found: {snap}")

    boundary_id, region = _read_manifest(snap)

    resolved = _iter_snapshot_resources(snap, provider)

    # Coverage-by-type + over-budget guard (Requirement 10.4, 10.7).
    is_landscape = diagram_type == "landscape"
    if is_landscape:
        if len(resolved) > LANDSCAPE_NODE_ERROR:
            raise SnapshotSplitRequired(
                f"landscape has {len(resolved)} role-bearing resources, over the "
                f"node-count ERROR bound of {LANDSCAPE_NODE_ERROR}; split the "
                "Snapshot into smaller boundaries and draw each separately"
            )

    # Stable ordering: sort every resolved resource by (lane index, identity) so
    # slot assignment is deterministic and independent of file/dict order.
    lane_names = _lane_order()
    lane_rank = {name: i for i, name in enumerate(lane_names)}

    ordered = sorted(
        resolved,
        key=lambda pair: (
            lane_rank.get(lane_of(pair[1]), len(lane_names)),
            _resource_identity(pair[0]),
        ),
    )

    if not is_landscape:
        # simple / summary: the in-scope subset, capped at the flow node budget.
        ordered = ordered[:_FLOW_NODE_BUDGET]

    # Build nodes with a per-lane slot counter (assigned in stable order) and a
    # unique, deterministic id per node.
    nodes: List[NodeSpec] = []
    slot_by_lane: Dict[str, int] = {}
    used_ids: Dict[str, int] = {}
    id_by_resource_identity: Dict[str, str] = {}
    for resource, role in ordered:
        lane = lane_of(role)
        slot = slot_by_lane.get(lane, 0)
        slot_by_lane[lane] = slot + 1

        identity = _resource_identity(resource)
        base_id = _slug(identity)
        node_id = base_id
        # Disambiguate the rare id collision deterministically.
        if node_id in used_ids:
            used_ids[base_id] += 1
            node_id = f"{base_id}-{used_ids[base_id]}"
        else:
            used_ids[base_id] = 0
        id_by_resource_identity.setdefault(identity, node_id)

        nodes.append(
            NodeSpec(
                id=node_id,
                role=role,
                lane=lane,
                region="",
                slot=slot,
            )
        )

    # Containers: one account boundary derived from the manifest boundary meta.
    containers: Tuple[ContainerSpec, ...] = (
        ContainerSpec(
            id="boundary-account",
            kind="account",
            region="",
            parent=None,
            label_key="account",
        ),
    )

    # Edges: one per supplied relationship; none invented when absent
    # (Requirement 10.5). A relationship names source/target by node id (the slug
    # of a resource identity) or by a raw resource identity we can map.
    edges = _edges_from_relationships(relationships, {n.id for n in nodes})

    axis = "north-south" if is_landscape else "left-right"
    diagram_id = f"{provider}-{_slug(boundary_id)}-{diagram_type}"
    diagram_name = diagram_id
    title = f"{provider} {diagram_type} — {boundary_id} / {region}"

    return DiagramSpec(
        diagram_id=diagram_id,
        diagram_name=diagram_name,
        axis=axis,
        nodes=tuple(nodes),
        edges=edges,
        containers=containers,
        flow_lines=(),
        title=title,
    )


def _lane_order() -> Tuple[str, ...]:
    """Return the canonical lane order (LANES), for stable per-lane ranking."""
    try:
        from rule_engine.layout.base import LANES
    except ImportError:  # pragma: no cover - flat-module fallback
        from layout.base import LANES  # type: ignore[no-redef]
    return tuple(LANES)


def _edges_from_relationships(
    relationships: Optional[Sequence[Mapping[str, Any]]],
    node_ids: Iterable[str],
) -> Tuple[EdgeSpec, ...]:
    """Turn a Relationship_Input list into ``EdgeSpec``s (design J4).

    Each relationship is a mapping ``{source, target, label}``. ``source`` /
    ``target`` are matched against a declared node id directly, or against the
    slug of a raw resource identity (so a caller may name a resource by its arn /
    id and still connect it). A relationship whose endpoints do not both resolve
    to a declared node is skipped — an edge is never dangled to a non-existent
    node (that would trip ``edge-endpoint``). No edge is invented: an empty /
    absent ``relationships`` yields no edges (Requirement 10.5). Edges are emitted
    in input order with stable ``e1``.. ids.
    """
    if not relationships:
        return ()
    ids = set(node_ids)
    edges: List[EdgeSpec] = []
    n = 0
    for rel in relationships:
        if not isinstance(rel, Mapping):
            continue
        source = _resolve_endpoint(rel.get("source"), ids)
        target = _resolve_endpoint(rel.get("target"), ids)
        if source is None or target is None or source == target:
            continue
        label = rel.get("label")
        marker = str(label) if label is not None and str(label) != "" else str(n + 1)
        n += 1
        edges.append(
            EdgeSpec(id=f"e{n}", source=source, target=target, marker=marker)
        )
    return tuple(edges)


def _resolve_endpoint(value: Any, node_ids: set) -> Optional[str]:
    """Resolve a relationship endpoint to a declared node id, or ``None``.

    Accepts the node id verbatim, or a raw resource identity whose slug is a
    declared node id (so a caller can name a resource by arn/id/name). Returns
    ``None`` when it resolves to no declared node.
    """
    if value is None:
        return None
    text = str(value)
    if text in node_ids:
        return text
    slug = _slug(text)
    if slug in node_ids:
        return slug
    return None
