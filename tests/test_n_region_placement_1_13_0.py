"""Tests for the 1.13.0 generalisation of peer-region placement to N bands.

Before 1.13.0 the layout engine spread exactly TWO peer region bands — region
``a`` at the base origin and region ``b`` translated along the secondary axis.
Any third/fourth region token (``c``, ``d``, …) received no offset and landed on
top of region ``a``'s block, producing ``container-overlap`` (an ERROR on a
landscape). ``_region_band_offsets`` generalises the two existing helpers
(``_region_secondary_offset`` + ``_region_primary_rebase``) to any number of
bands, laid out as disjoint side-by-side columns.

Golden safety: the generalisation reduces to IDENTICAL math for N=2, so every
shipped a/b example stays byte-identical (anchored by
``tests/test_golden_examples.py`` and ``scripts/regen_examples.py --check``).
These tests exercise only the NEW N>=3 branch plus the N=2 reduction.
"""

from __future__ import annotations

from rule_engine.layout import layout
from rule_engine.layout.base import (
    _place_base,
    _region_band_offsets,
    _region_primary_rebase,
    _region_secondary_offset,
    _ORIGIN,
)
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


def _ns_spec(region_tokens):
    """A minimal cluster with one namespace band per region token.

    Each band holds a single ``k8s_service`` node in the ``router`` lane (so the
    bands are structurally identical and differ only by region), wrapped in a
    ``namespace`` leaf container nested in an ``account`` cluster. Mirrors the
    kubernetes profile's Cluster ⊃ Namespace model.
    """
    containers = [
        ContainerSpec(id="cluster", kind="account", region="", parent=None,
                      label_key="cluster"),
    ]
    nodes = []
    edges = []
    prev = None
    for tok in region_tokens:
        cid = f"ns-{tok}"
        containers.append(ContainerSpec(id=cid, kind="namespace", region=tok,
                                        parent="cluster", label_key=cid,
                                        fit_content=True))
        nid = f"svc-{tok}"
        nodes.append(NodeSpec(id=nid, role="k8s_service", lane="router",
                              region=tok, slot=0, container=cid))
        if prev is not None:
            edges.append(EdgeSpec(id=f"e-{prev}-{tok}", source=f"svc-{prev}",
                                  target=nid, marker=str(len(edges) + 1),
                                  kind_hint="cross-region"))
        prev = tok
    return DiagramSpec(
        diagram_id="nreg", diagram_name="nreg", axis="north-south",
        nodes=tuple(nodes), edges=tuple(edges), containers=tuple(containers),
        flow_lines=("Flow",), title="n-region test",
    )


def _boxes_overlap(a, b):
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def test_four_peer_bands_are_disjoint_and_side_by_side():
    """Four peer region bands place as disjoint side-by-side columns."""
    spec = _ns_spec(("a", "b", "c", "d"))
    placed = layout(spec, strict=False)
    ns = [placed.containers[f"ns-{t}"] for t in ("a", "b", "c", "d")]
    # No two namespace boxes overlap.
    for i in range(len(ns)):
        for j in range(i + 1, len(ns)):
            assert not _boxes_overlap(ns[i], ns[j]), (
                f"ns-{'abcd'[i]} overlaps ns-{'abcd'[j]}"
            )
    # They are ordered left-to-right by region token (side-by-side columns).
    xs = [b.x for b in ns]
    assert xs == sorted(xs), f"bands not left-to-right ordered: {xs}"
    # Each later band starts to the RIGHT of the previous band's right edge.
    for i in range(1, len(ns)):
        assert ns[i].x >= ns[i - 1].right, (
            f"ns-{'abcd'[i]} does not clear ns-{'abcd'[i-1]}"
        )


def test_three_peer_bands_no_container_overlap():
    """Three peer bands: the linter's container-overlap check is clean."""
    from rule_engine import geometry as geo

    spec = _ns_spec(("a", "b", "c"))
    placed = layout(spec, strict=False)
    ns = [placed.containers[f"ns-{t}"] for t in ("a", "b", "c")]
    for i in range(len(ns)):
        for j in range(i + 1, len(ns)):
            assert not _boxes_overlap(ns[i], ns[j])


def test_n2_reduces_to_the_two_region_helpers():
    """For N=2 the generalised offsets equal the original a/b helpers exactly."""
    spec = _ns_spec(("a", "b"))
    base = _place_base(spec, *_ORIGIN)
    offsets = _region_band_offsets(spec, base)
    assert offsets["a"] == (0, 0)
    assert offsets["b"] == (
        _region_secondary_offset(spec, base),
        _region_primary_rebase(spec, base),
    )


def test_single_region_offset_is_zero():
    """A lone band (region a) is never translated."""
    spec = _ns_spec(("a",))
    base = _place_base(spec, *_ORIGIN)
    offsets = _region_band_offsets(spec, base)
    assert offsets == {"a": (0, 0)}


def test_kubernetes_landscape_has_no_container_overlap():
    """The redesigned k8s landscape (4 namespaces) is container-overlap-free."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_kubernetes_example as k8s  # type: ignore

    placed = layout(k8s.landscape_spec(), strict=False)
    ns_ids = [c.id for c in k8s.landscape_spec().containers
              if c.kind == "namespace"]
    boxes = [placed.containers[i] for i in ns_ids]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _boxes_overlap(boxes[i], boxes[j]), (
                f"{boxes[i].id} overlaps {boxes[j].id}"
            )
    assert len(ns_ids) == 4
