"""WS5 (1.11.0) — clarify-gate tests."""

from __future__ import annotations

import pytest

from rule_engine.layout.clarify import (
    Assumption,
    ClarifyPolicy,
    ClarifyRequired,
    UncertaintyKind,
    clarify_gate,
    format_assumptions_markdown,
    scan_uncertainties,
)
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


def _spec(nodes, edges=(), containers=()):
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="left-right",
        nodes=tuple(nodes), edges=tuple(edges), containers=tuple(containers),
        flow_lines=(), title="t",
    )


def _clean_flow():
    # account-level flow, every node region="" so no membership gap, kind_hint
    # not needed (no region ambiguity because account-level + no containers).
    return _spec(
        nodes=[
            NodeSpec(id="a", role="lb", lane="edge", region="", slot=0),
            NodeSpec(id="b", role="serverless_fn", lane="workers", region="", slot=0),
        ],
        edges=[EdgeSpec(id="e1", source="a", target="b", marker="1", kind_hint="straight")],
    )


def test_clean_spec_scans_empty():
    assert scan_uncertainties(_clean_flow()) == ()


def test_missing_membership_detected():
    spec = _spec(
        nodes=[NodeSpec(id="n", role="serverless_fn", lane="workers", region="a", slot=0)],
        containers=[
            ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
            ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ],
    )
    found = scan_uncertainties(spec)
    kinds = {a.kind for a in found}
    assert UncertaintyKind.MISSING_MEMBERSHIP in kinds
    a = next(a for a in found if a.kind is UncertaintyKind.MISSING_MEMBERSHIP)
    assert a.target_id == "n" and a.default


def test_declared_membership_is_not_flagged():
    spec = _spec(
        nodes=[NodeSpec(id="n", role="serverless_fn", lane="workers", region="a", slot=0, container="vpc-a")],
        containers=[
            ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
            ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ],
    )
    assert all(a.kind is not UncertaintyKind.MISSING_MEMBERSHIP for a in scan_uncertainties(spec))


def test_unresolved_role_detected_only_with_resolver():
    spec = _spec(nodes=[NodeSpec(id="n", role="made_up_role", lane="edge", region="", slot=0)])
    # no resolver → not scanned
    assert all(a.kind is not UncertaintyKind.UNRESOLVED_ROLE for a in scan_uncertainties(spec))
    # resolver that rejects the role → flagged
    found = scan_uncertainties(spec, role_resolves=lambda r: r in {"lb", "serverless_fn"})
    assert any(a.kind is UncertaintyKind.UNRESOLVED_ROLE and a.target_id == "n" for a in found)


def test_ambiguous_edge_kind_detected():
    spec = _spec(
        nodes=[
            NodeSpec(id="a", role="lb", lane="edge", region="", slot=0),
            NodeSpec(id="b", role="serverless_fn", lane="workers", region="", slot=0),
        ],
        edges=[EdgeSpec(id="e1", source="a", target="b", marker="1")],  # no kind_hint
    )
    found = scan_uncertainties(spec)
    assert any(a.kind is UncertaintyKind.AMBIGUOUS_EDGE_KIND and a.target_id == "e1" for a in found)


def test_policy_auto_records_and_returns():
    spec = _spec(nodes=[NodeSpec(id="n", role="serverless_fn", lane="workers", region="a", slot=0)],
                 containers=[
                     ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
                     ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
                 ])
    sink: list[Assumption] = []
    found = clarify_gate(spec, ClarifyPolicy.AUTO, sink=sink)
    assert found and sink == list(found)


def test_policy_ask_and_error_raise():
    spec = _spec(nodes=[NodeSpec(id="n", role="serverless_fn", lane="workers", region="a", slot=0)],
                 containers=[
                     ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
                     ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
                 ])
    with pytest.raises(ClarifyRequired):
        clarify_gate(spec, "ask")
    with pytest.raises(ClarifyRequired):
        clarify_gate(spec, "error")


def test_clean_spec_passes_every_policy():
    spec = _clean_flow()
    for pol in ("ask", "auto", "error"):
        assert clarify_gate(spec, pol) == ()


def test_assumptions_markdown_round_trip():
    assert format_assumptions_markdown([]) == ""
    md = format_assumptions_markdown([
        Assumption(UncertaintyKind.MISSING_MEMBERSHIP, "n", "q?", "tier-band", "why"),
    ])
    assert "## Assumptions" in md and "`n`" in md and "tier-band" in md


# --------------------------------------------------------------------------- #
# WS5.3 — recorded_assumptions frontmatter key mirrors the ## Assumptions body.
# --------------------------------------------------------------------------- #


def test_recorded_assumptions_frontmatter_emitted_only_when_present():
    from rule_engine.draw_cli import build_companion

    empty = build_companion("aws", "simple", "s")
    assert "recorded_assumptions" not in empty
    # byte-identical whether the arg is omitted or an empty sequence
    assert empty == build_companion("aws", "simple", "s", assumptions=())

    withk = build_companion("aws", "simple", "s", assumptions=[
        Assumption(UncertaintyKind.MISSING_MEMBERSHIP, "api", "q", "tier-band 0", "why"),
        Assumption(UncertaintyKind.AMBIGUOUS_EDGE_KIND, "e3", "q", "sync", "why"),
    ])
    assert "recorded_assumptions:" in withk
    assert "  - missing_membership:api" in withk
    assert "  - ambiguous_edge_kind:e3" in withk


def test_companion_with_recorded_assumptions_passes_frontmatter_contract():
    from rule_engine.draw_cli import build_companion
    from rule_engine import kb_validator as kv

    doc = build_companion("aws", "simple", "s", assumptions=[
        Assumption(UncertaintyKind.MISSING_MEMBERSHIP, "api", "q", "tier-band 0", "why"),
    ])
    # the extra key must not trip the kb-frontmatter contract
    assert kv.validate_document(doc) == []
