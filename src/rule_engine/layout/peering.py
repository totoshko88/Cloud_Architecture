"""Peering-as-resource materialization (1.11.0, REVIEW.md G23).

A VPC/VCN peering is two things depending on the diagram.

* On a normal **data-flow** diagram a peering is just how two networks reach
  each other — a relationship, not a thing the reader cares to see as a box. It
  is drawn as a symmetric dashed line (``EdgeSpec.peering=True`` /
  ``diagram_layout.Edge.peering``) and documented in the Flow narrative; the
  peering word no longer prints on the canvas (see
  :func:`rule_engine.diagram_layout.edge_cell`).
* On a **network topology** diagram a peering reads as a **resource**: the
  published AWS network diagrams draw a *VPC Peering Connection* icon sitting
  BETWEEN the two VPCs/accounts, with the two peering legs attaching to it. That
  is the ``vpc_peering`` presentation role.

This module is the pure, deterministic, idempotent spec→spec transform that
turns the first form into the second — but only when a build script opts in by
setting :attr:`DiagramSpec.peering_as_node`. The flag is an **explicit
spec-level switch**, not an inference from the diagram type: ``diagram_type`` is
companion-frontmatter metadata the linter reads and is NOT visible to
:func:`~rule_engine.layout.layout`, so the materialization cannot (and must not)
be driven by inferring network-ness inside ``layout()``.

Contract:

* ``peering_as_node=False`` (the default) → :func:`materialize_peerings` is the
  identity (returns the spec unchanged), so every existing spec is
  byte-identical and no ``vpc_peering`` node is ever invented.
* ``peering_as_node=True`` → for each ``EdgeSpec`` with ``peering=True`` whose
  **both endpoints are nodes**, create ONE ``vpc_peering`` node placed in the
  lane BETWEEN the two endpoints (region-less, container-free), and replace the
  direct peering edge with TWO plain legs (``source → pcx``, ``pcx → target``)
  carrying the original step marker. The direct edge is dropped. The between-lane
  is vertically between the cloud source and the external peer, so both legs flow
  one way (no back-edge), and the pcx is kept OUT of the account envelope by the
  ``vpc_peering``-role exemption in
  :func:`rule_engine.layout.base._assign_nodes_to_leaves` — so it sits "between
  the boundaries, not inside either", even on a DENSE network diagram (several
  peerings from several VPC nodes). Without that exemption a region-less
  cloud-lane node would be wrapped by the account and the VPC box would overlap
  it — the G23 dense-case defect that tripped ``container-padding`` /
  ``container-overlap`` on 08/10. A peering edge that touches a CONTAINER
  endpoint is left unchanged (it is a boundary-to-boundary edge routed by the
  WS10 container-edge path, where the two boundary faces already read as the two
  networks). Node/edge ordering is preserved deterministically, so the transform
  is a pure function of the spec.
* **Idempotent.** After materialization the only remaining ``peering=True``
  edges touch containers, so running the transform again is a no-op — no second
  ``vpc_peering`` node is created.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Tuple

try:  # package-relative import when used as ``rule_engine.layout.peering``
    from .model import DiagramSpec, EdgeSpec, NodeSpec
    from .base import LANES, LANE_INDEX, EXTERNAL_LANES
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from layout.model import DiagramSpec, EdgeSpec, NodeSpec  # type: ignore[no-redef]
    from layout.base import LANES, LANE_INDEX, EXTERNAL_LANES  # type: ignore[no-redef]

#: Container kinds drawn as disjoint sibling boundaries OUTSIDE the primary cloud
#: account (the neutral grey peer-account / external-cloud box). A peer target
#: that is a member of one of these — or that sits in an external lane — is an
#: EXTERNAL endpoint, and the peering resource joins its band.
_EXTERNAL_CONTAINER_KINDS = frozenset({"external_cloud", "peer_account"})


#: The presentation role the materialized node resolves to (AWS *VPC Peering
#: Connection* and the per-provider equivalents, already mapped in
#: ``mappings/roles.yaml`` / ``mappings/<provider>-icons.yaml``). A node with
#: this role is a peering RESOURCE sitting between two boundaries; it is kept out
#: of the account envelope by the exemption in
#: :func:`rule_engine.layout.base._assign_nodes_to_leaves`.
_PEERING_ROLE = "vpc_peering"


def _between_lane(source: NodeSpec, target: NodeSpec) -> str:
    """The lane that sits BETWEEN the two endpoints (deterministic).

    The AWS network-diagram shape draws a VPC Peering Connection icon BETWEEN the
    two VPCs/accounts, with a leg to each. On the canonical lane axis the source
    (a VPC workload) and the target (an external peer) sit in different lanes, so
    the peering node goes in the lane at their midpoint — both legs then run from
    one endpoint INTO the peering node and on to the other, each a contract-legal
    forward run (no back-edge piercing a glyph). When both endpoints share a lane
    the peering node joins that lane. A whole-index midpoint keeps the choice a
    stable function of the two declared lanes.
    """
    a = LANE_INDEX[source.lane]
    b = LANE_INDEX[target.lane]
    return LANES[(a + b) // 2]


def materialize_peerings(spec: DiagramSpec) -> DiagramSpec:
    """Return ``spec`` with every node-to-node peering edge turned into a node.

    Pure / deterministic / idempotent — see the module docstring. A no-op (the
    identity) when ``spec.peering_as_node`` is falsy or the spec declares no
    materializable peering edge, so a spec that does not opt in is returned
    unchanged (byte-identical).
    """
    if not getattr(spec, "peering_as_node", False):
        return spec

    node_by_id: Dict[str, NodeSpec] = {n.id: n for n in spec.nodes}
    container_kind: Dict[str, str] = {c.id: c.kind for c in spec.containers}

    def _is_external(n: NodeSpec) -> bool:
        return (
            n.lane in EXTERNAL_LANES
            or container_kind.get(n.container or "", "") in _EXTERNAL_CONTAINER_KINDS
        )

    # The peering edges we will materialize: peering=True AND both endpoints are
    # NODES (a container endpoint stays on the WS10 boundary-edge path).
    to_materialize = [
        e for e in spec.edges
        if e.peering
        and e.source in node_by_id
        and e.target in node_by_id
    ]
    if not to_materialize:
        return spec

    # Split by whether the peer target is EXTERNAL. Almost every real peering is
    # {cloud VPC source → external peer}; for that case the pcx joins the peer's
    # external band (below). The rare {two in-cloud VPCs} peering has no external
    # endpoint — its pcx falls back to the legacy region-less between-lane
    # placement (kept out of the account by the ``vpc_peering`` exemption in
    # ``_assign_nodes_to_leaves``).
    ext_edges = [e for e in to_materialize if _is_external(node_by_id[e.target])
                 or _is_external(node_by_id[e.source])]
    fallback_edges = [e for e in to_materialize if e not in ext_edges]

    # One pcx per materializable peering, keyed by edge id, built in edge order
    # so the result is a pure function of the spec.
    pcx_for: Dict[str, NodeSpec] = {}
    # A peering joins ONE cloud VPC to an EXTERNAL peer. The peering RESOURCE is
    # placed in the peer target's own band, in the slot IMMEDIATELY BEFORE that
    # peer (same container / lane / region), so the two legs read cleanly:
    #   source (above) ──▼── pcx ──▶── peer   (drop into pcx, short forward hop)
    # Placing it to the LEFT of its peer (not appended far to the right) is what
    # keeps ``pcx → peer`` a forward left→right hop instead of a back-edge that
    # pierces the peer glyph, and being a MEMBER of the external peer box puts it
    # OUTSIDE the account and every VPC ("between the boundaries, not inside
    # either") — the G23 dense-case contract that a region-less cloud-lane
    # placement cannot satisfy (the lane midpoint of a cloud source and an
    # external target is itself a cloud band the account/VPC box encloses).
    #
    # The peers are renumbered to open a slot for each pcx: within each
    # (container, lane, region) band every declared node at or after an inserted
    # pcx's anchor slot shifts right, and the pcx takes the vacated column. The
    # shift is computed per band in a deterministic pass.
    # The external endpoint that anchors each pcx (the peer target when it is
    # external, else the external source).
    anchor_of: Dict[str, NodeSpec] = {}
    insert_at: Dict[Tuple[str, str, str], List[Tuple[int, str]]] = {}
    for e in ext_edges:
        tgt = node_by_id[e.target]
        anchor = tgt if _is_external(tgt) else node_by_id[e.source]
        anchor_of[e.id] = anchor
        band = (anchor.container or "", anchor.lane, anchor.region)
        insert_at.setdefault(band, []).append((anchor.slot, e.id))
        pcx_for[e.id] = NodeSpec(
            id=f"{e.id}-pcx",
            role=_PEERING_ROLE,
            lane=anchor.lane,
            region=anchor.region,
            slot=anchor.slot,       # provisional; finalised in the shift pass
            container=anchor.container,
        )

    # Deterministic slot assignment per band: walk the declared nodes and the
    # pcx anchors together in slot order, assigning consecutive slots so each
    # pcx sits immediately before the peer it anchors to and no slot collides.
    band_members: Dict[Tuple[str, str, str], List[NodeSpec]] = {}
    for n in spec.nodes:
        band_members.setdefault((n.container or "", n.lane, n.region), []).append(n)

    new_slot_of: Dict[str, int] = {}
    pcx_final: Dict[str, NodeSpec] = {}
    for band, anchors in insert_at.items():
        members = sorted(band_members.get(band, []), key=lambda n: n.slot)
        # Map anchor-slot -> list of pcx edge ids inserted before that slot.
        before: Dict[int, List[str]] = {}
        for anchor_slot, eid in sorted(anchors):
            before.setdefault(anchor_slot, []).append(eid)
        cursor = 0
        for m in members:
            for eid in before.get(m.slot, []):
                pcx_final[eid] = replace(pcx_for[eid], slot=cursor)
                cursor += 1
            new_slot_of[m.id] = cursor
            cursor += 1

    # Fallback pcx (no external endpoint): the legacy region-less between-lane
    # placement, container-free, next free slot in the between band.
    next_between: Dict[Tuple[str, str], int] = {}
    for n in spec.nodes:
        k = (n.lane, n.region)
        next_between[k] = max(next_between.get(k, -1), n.slot)
    next_between = {k: v + 1 for k, v in next_between.items()}
    for e in fallback_edges:
        lane = _between_lane(node_by_id[e.source], node_by_id[e.target])
        key = (lane, "")
        slot = next_between.get(key, 0)
        next_between[key] = slot + 1
        pcx_final[e.id] = NodeSpec(
            id=f"{e.id}-pcx", role=_PEERING_ROLE, lane=lane, region="",
            slot=slot, container=None,
        )

    # Rebuild the node list: declared nodes keep their id/role/etc but take their
    # (possibly shifted) new slot; each external pcx is inserted immediately
    # before its anchor peer (so its leg is a short forward hop); fallback pcx
    # nodes are appended at the end.
    new_nodes: List[NodeSpec] = []
    pcx_before_anchor: Dict[str, List[NodeSpec]] = {}
    for e in ext_edges:
        pcx_before_anchor.setdefault(anchor_of[e.id].id, []).append(pcx_final[e.id])
    for n in spec.nodes:
        for pcx in pcx_before_anchor.get(n.id, []):
            new_nodes.append(pcx)
        if n.id in new_slot_of:
            new_nodes.append(replace(n, slot=new_slot_of[n.id]))
        else:
            new_nodes.append(n)
    for e in fallback_edges:
        new_nodes.append(pcx_final[e.id])

    # Build the replacement edge list in the ORIGINAL edge order: a materialized
    # peering edge is replaced in place by its two legs; every other edge is kept
    # verbatim, so determinism and ordering are preserved.
    materialize_ids = {e.id for e in to_materialize}
    new_edges: List[EdgeSpec] = []
    for e in spec.edges:
        if e.id not in materialize_ids:
            new_edges.append(e)
            continue
        pcx_id = f"{e.id}-pcx"
        # Two plain legs. The peering is now a RESOURCE (the vpc_peering icon),
        # so the legs are ordinary (non-peering) edges; they keep the edge's
        # dashed/kind_hint presentation so a network view can still draw them
        # dashed if it declared so. They carry NO marker (empty): a peering leg
        # is a bare line into the VPC Peering icon — the step is documented in
        # the Flow narrative, not on the leg. An empty marker renders as NOTHING
        # (no badge disc) via ``diagram_layout._marker_value`` (G23, the
        # owner-flagged "empty black disc on peering legs" defect).
        new_edges.append(replace(
            e, id=f"{e.id}-a", source=e.source, target=pcx_id, peering=False,
            marker="",
        ))
        new_edges.append(replace(
            e, id=f"{e.id}-b", source=pcx_id, target=e.target, peering=False,
            marker="",
        ))

    return replace(spec, nodes=tuple(new_nodes), edges=tuple(new_edges))
