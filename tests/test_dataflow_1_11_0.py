"""WS8 (1.11.0) — dataflow diagram type: profile + data-classification lint."""

from __future__ import annotations

from rule_engine.diagram_profiles import TypeProfile, load_type_profile
from rule_engine.linter import Artifact, lint


def _df(diagram_class="landscape", names=(), diagram_type="dataflow"):
    return Artifact(
        kind="diagram", is_drawio=True, source_format="drawio",
        node_names=list(names), diagram_class=diagram_class,
        diagram_type=diagram_type,
    )


def _rule(a, rule):
    return [f for f in lint(a)["findings"] if f["rule"] == rule]


# --- profile (Req 8 AC1) --------------------------------------------------- #


def test_dataflow_profile_fields():
    p = load_type_profile("dataflow")
    assert isinstance(p, TypeProfile)
    assert p.name == "dataflow"
    assert p.base_class == "landscape"
    assert p.axis == "left-right"
    assert p.lint_profile == "dataflow"


# --- data-classification (Req 8 AC3) --------------------------------------- #


def test_pii_store_without_classification_is_flagged():
    a = _df(names=["users-db (PII)"])
    assert [f["severity"] for f in _rule(a, "data-classification")] == ["ERROR"]


def test_pii_store_with_classification_marker_is_clean():
    assert _rule(_df(names=["users-db (PII, encrypted)"]), "data-classification") == []
    assert _rule(_df(names=["orders (personal, tokenized)"]), "data-classification") == []


def test_flow_dataflow_is_warning_landscape_is_error():
    assert [f["severity"] for f in _rule(_df("flow", ["db (gdpr)"]), "data-classification")] == ["WARNING"]
    assert [f["severity"] for f in _rule(_df("landscape", ["db (gdpr)"]), "data-classification")] == ["ERROR"]


def test_non_dataflow_diagram_is_not_evaluated():
    assert _rule(_df(diagram_type="network", names=["db (PII)"]), "data-classification") == []
    assert _rule(_df(diagram_type=None, names=["db (PII)"]), "data-classification") == []


def test_non_pii_store_is_clean():
    assert _rule(_df(names=["cache", "queue", "app-db"]), "data-classification") == []


# --- ip-range applies to dataflow (Req 8 AC2) ------------------------------ #


def test_ip_range_applies_to_dataflow():
    a = _df(names=["edge 8.8.8.8"])
    assert [f["severity"] for f in _rule(a, "ip-range")] == ["WARNING"]


def test_documentation_ip_not_flagged_on_dataflow():
    # RFC5737 TEST-NET is never flagged, even on a dataflow diagram.
    assert _rule(_df(names=["edge 203.0.113.9"]), "ip-range") == []
