"""1.13.0 phase 3 (item 12a): companion-declared reconcile coverage scope.

A landscape that is a deliberate network-slice / dataflow view, or that
justifies specific role omissions, is no longer forced to total coverage:

* ``coverage_class: flow`` / ``scope: network-slice|dataflow`` scopes coverage;
* ``reconcile_exempt: [{role, reason}]`` removes those roles from omissions and
  records the justification;
* a ``reconcile_exempt`` entry with no ``reason`` is a usage error (fail-closed).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine.reconcile import ReconcileError, reconcile


def _snapshot(d: Path):
    """A minimal raw-CLI snapshot with an S3 bucket and a Bedrock model."""
    snap = d / "inventory-aws-123-us-east-1-2026-01-01_0000"
    snap.mkdir(parents=True)
    (snap / "storage.json").write_text(
        json.dumps({"buckets": [{"Name": "data-bucket"}]}), encoding="utf-8")
    (snap / "ai.json").write_text(
        json.dumps({"bedrock_foundation_models": [{"modelId": "claude"}]}),
        encoding="utf-8")
    return snap


def _diagram(d: Path, name: str, frontmatter: str):
    # a landscape that draws neither the bucket nor the model (both omitted).
    src = d / f"{name}.drawio"
    src.write_text(
        '<mxGraphModel gridSize="10"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="t" value="aws net — 123 / us-east-1 | 2026-01-01 | v1" style="text;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="200" height="20" as="geometry"/></mxCell>'
        "</root></mxGraphModel>", encoding="utf-8")
    (d / f"{name}.diagram.md").write_text(frontmatter, encoding="utf-8")
    return src


def test_landscape_without_scope_reports_omissions(tmp_path):
    snap = _snapshot(tmp_path)
    dia = _diagram(tmp_path, "10-net", "---\ndiagram_class: landscape\n---\n")
    r = reconcile(snap, dia, "aws")
    roles = {o["role"] for o in r.omissions}
    assert "object_store" in roles and "llm_platform" in roles
    assert not r.eligible


def test_scope_network_slice_maps_to_flow_coverage(tmp_path):
    snap = _snapshot(tmp_path)
    dia = _diagram(tmp_path, "10-net",
                   "---\ndiagram_class: landscape\nscope: network-slice\n---\n")
    r = reconcile(snap, dia, "aws")
    assert r.coverage_class == "flow"
    assert r.eligible  # scoped coverage: out-of-scope roles are not omissions


def test_reconcile_exempt_removes_the_role_and_records_the_reason(tmp_path):
    snap = _snapshot(tmp_path)
    fm = ("---\ndiagram_class: landscape\n"
          "reconcile_exempt:\n"
          "  - role: object_store\n    reason: regional, drawn on 03\n"
          "  - role: llm_platform\n    reason: AI scope, drawn on 13\n---\n")
    dia = _diagram(tmp_path, "10-net", fm)
    r = reconcile(snap, dia, "aws")
    assert r.eligible
    reasons = {e["role"]: e["reason"] for e in r.exempted}
    assert reasons["object_store"] == "regional, drawn on 03"
    assert reasons["llm_platform"] == "AI scope, drawn on 13"
    assert "exempted" in r.to_dict()


def test_reconcile_exempt_without_reason_is_a_usage_error(tmp_path):
    snap = _snapshot(tmp_path)
    fm = ("---\ndiagram_class: landscape\n"
          "reconcile_exempt:\n  - role: object_store\n---\n")
    dia = _diagram(tmp_path, "10-net", fm)
    with pytest.raises(ReconcileError):
        reconcile(snap, dia, "aws")
