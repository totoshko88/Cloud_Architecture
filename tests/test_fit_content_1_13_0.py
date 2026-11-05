"""L6 (1.13.0): till-content peer-container sizing via ``ContainerSpec.fit_content``.

A peer container (an AZ / VPC with a region-sibling of the same kind) is widened
by ``_equalize_peer_widths`` to the WIDER peer's size, so the pair reads as one
mirror-symmetric stack. When one peer's content is far narrower than its
sibling's — an asymmetric SEP account where one AZ holds a wide service row and
the other a single node — that widening leaves hundreds of px of dead-space
(``container-dead-space``), which is why diagram 10 is hand-pinned.

``ContainerSpec.fit_content=True`` opts a peer out of the widen step: it keeps
its OWN content + padding width, and is excluded from the pair target so its
sibling is not dragged wider either.

Proven here on synthetic specs:
* the defect: with symmetric-content equalization off, an asymmetric peer AZ is
  stretched to its wide sibling's width (hundreds of px of dead-space);
* the lever: ``fit_content=True`` sizes that AZ till its own content + one pad,
  without widening the sibling;
* default-off: ``fit_content=False`` is byte-identical to today;
* a symmetric peer pair (every shipped HA golden) is unaffected either way,
  because equalize is already a no-op there.
"""

from __future__ import annotations

from dataclasses import replace

from rule_engine.layout_engine import layout
from rule_engine.layout.model import (
    ContainerSpec as C,
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
)

_PAD_BOTH = 120  # a snug peer box is content + one CONTAINER_PAD on each side


def _spec(fit_b: bool, wide_a: int = 4):
    """account > region > vpc > az, two regions. az-a1 holds ``wide_a`` nodes
    (a wide service row); az-b1 holds ONE node (narrow content)."""
    conts = [
        C(id="acct", kind="account", region="", parent=None, label_key="a"),
        C(id="reg-a", kind="region", region="a", parent="acct", label_key="ra"),
        C(id="reg-b", kind="region", region="b", parent="acct", label_key="rb"),
        C(id="vpc-a", kind="vpc", region="a", parent="reg-a", label_key="va"),
        C(id="vpc-b", kind="vpc", region="b", parent="reg-b", label_key="vb"),
        C(id="az-a1", kind="az", region="a", parent="vpc-a", label_key="aa"),
        C(id="az-b1", kind="az", region="b", parent="vpc-b", label_key="ab",
          fit_content=fit_b),
    ]
    nodes = [NodeSpec(id=f"wa{i}", role="compute", lane="workers", region="a",
                      slot=i, container="az-a1") for i in range(wide_a)]
    nodes.append(NodeSpec(id="nb", role="compute", lane="workers", region="b",
                          slot=0, container="az-b1"))
    return DiagramSpec(diagram_id="l6", diagram_name="l6", axis="north-south",
                       nodes=tuple(nodes),
                       edges=(EdgeSpec(id="e1", source="wa0", target="nb",
                                       marker="classic"),),
                       containers=tuple(conts), flow_lines=(), title="l6")


def _content_w(placed, cid):
    s = placed.spec
    kids = [placed.containers[c.id] for c in s.containers if c.parent == cid]
    kids += [placed.nodes[n.id] for n in s.nodes
             if getattr(n, "container", None) == cid]
    return (max(k.right for k in kids) - min(k.x for k in kids)) if kids else 0


# --------------------------------------------------------------------------- #
# the defect
# --------------------------------------------------------------------------- #

def test_asymmetric_peer_is_stretched_without_the_lever():
    placed = layout(_spec(fit_b=False))
    az_b = placed.containers["az-b1"]
    content = _content_w(placed, "az-b1")
    # az-b1 is dragged to az-a1's wide width -> large dead-space.
    assert az_b.w - content > _PAD_BOTH * 2


# --------------------------------------------------------------------------- #
# the lever
# --------------------------------------------------------------------------- #

def test_fit_content_sizes_az_till_its_own_content():
    placed = layout(_spec(fit_b=True))
    az_b = placed.containers["az-b1"]
    content = _content_w(placed, "az-b1")
    # snug: content + one CONTAINER_PAD each side, no stretch to the sibling.
    assert az_b.w - content <= _PAD_BOTH


def test_fit_content_does_not_widen_the_sibling():
    off = layout(_spec(fit_b=False)).containers["az-a1"]
    on = layout(_spec(fit_b=True)).containers["az-a1"]
    # the wide peer keeps its own content width in both cases.
    assert on.w == off.w


def test_fit_content_shrinks_the_box():
    off = layout(_spec(fit_b=False)).containers["az-b1"]
    on = layout(_spec(fit_b=True)).containers["az-b1"]
    assert on.w < off.w


# --------------------------------------------------------------------------- #
# byte-inert safety
# --------------------------------------------------------------------------- #

def test_default_off_is_the_current_behaviour():
    # fit_content defaults to False; the box is the equalized (stretched) one.
    placed = layout(_spec(fit_b=False))  # peers default False
    az_b = placed.containers["az-b1"]
    content = _content_w(placed, "az-b1")
    assert az_b.w - content > _PAD_BOTH * 2


def test_symmetric_peers_are_unaffected_by_the_lever():
    # Both AZs hold the SAME content (4 nodes each) -> equalize is a no-op, so
    # fit_content on one changes nothing (the shipped HA goldens' situation).
    def sym(fit_b):
        conts = [
            C(id="acct", kind="account", region="", parent=None, label_key="a"),
            C(id="reg-a", kind="region", region="a", parent="acct", label_key="ra"),
            C(id="reg-b", kind="region", region="b", parent="acct", label_key="rb"),
            C(id="vpc-a", kind="vpc", region="a", parent="reg-a", label_key="va"),
            C(id="vpc-b", kind="vpc", region="b", parent="reg-b", label_key="vb"),
            C(id="az-a1", kind="az", region="a", parent="vpc-a", label_key="aa"),
            C(id="az-b1", kind="az", region="b", parent="vpc-b", label_key="ab",
              fit_content=fit_b),
        ]
        nodes = [NodeSpec(id=f"wa{i}", role="compute", lane="workers",
                          region="a", slot=i, container="az-a1") for i in range(4)]
        nodes += [NodeSpec(id=f"wb{i}", role="compute", lane="workers",
                           region="b", slot=i, container="az-b1") for i in range(4)]
        return DiagramSpec(diagram_id="l6s", diagram_name="l6s",
                           axis="north-south", nodes=tuple(nodes),
                           edges=(EdgeSpec(id="e1", source="wa0", target="wb0",
                                           marker="classic"),),
                           containers=tuple(conts), flow_lines=(), title="l6s")

    off = layout(sym(False)).containers
    on = layout(sym(True)).containers
    assert on["az-a1"].w == off["az-a1"].w
    assert on["az-b1"].w == off["az-b1"].w
