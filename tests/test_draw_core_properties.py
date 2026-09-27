"""Property + unit tests for the Snapshot→DiagramSpec autogenerator core.

Feature: provider-diagram-conventions (release 1.10.0), Part J, task 7 — the
``rule-engine-draw`` autogenerator *core* (``rule_engine.draw``): the pure
role→lane table :func:`lane_of` and the Snapshot→``DiagramSpec`` translator
:func:`spec_from_snapshot`. It reuses :func:`rule_engine.reconcile.role_of`
verbatim and emits the existing coordinate-free ``DiagramSpec`` — no new geometry
type, no lint rule.

Property 8 part 1 (design.md): the autogenerator is deterministic, offline, and
coverage-correct. This module asserts:

* **determinism** — two runs on the same fixture Snapshot yield identical specs
  (Requirement 10.6);
* **role coverage / skip** — a ``landscape`` covers every role-bearing resource,
  and an unresolved-role resource is skipped, never drawn (Requirement 10.2,
  10.4);
* **over-budget split** — a ``landscape`` whose role-bearing count exceeds the
  ``node-count`` ERROR bound (> 50) raises ``SnapshotSplitRequired`` and emits no
  spec (Requirement 10.7).

Every produced spec is also validated against the layout engine's
``_validate_spec`` (known lanes, unique ``(lane, region, slot)`` slots, no
dangling edges), so the core cannot emit a spec the pipeline would reject.

**Validates: Requirements 10.2, 10.3, 10.4, 10.6, 10.7**
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.constants import RESOURCE_TYPES
from rule_engine.draw import (
    DIAGRAM_TYPES,
    LANE_OF,
    DrawError,
    SnapshotSplitRequired,
    lane_of,
    spec_from_snapshot,
)
from rule_engine.layout.base import LANES, _validate_spec

# The committed golden AWS example Snapshot (6 role-bearing resources).
_AWS_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "aws"
    / "inventory-aws-123456789012-us-east-1-2026-09-22_1430"
)


# --------------------------------------------------------------------------- #
# Helpers — build a synthetic Snapshot folder on disk (offline fixture)
# --------------------------------------------------------------------------- #


def _write_snapshot(
    root: Path,
    provider: str,
    boundary_id: str,
    region: str,
    domains: Dict[str, List[dict]],
) -> Path:
    """Write a minimal conforming Snapshot (manifest + per-domain JSON) to disk."""
    folder = root / f"inventory-{provider}-{boundary_id}-{region}-2026-09-22_1430"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = (
        "---\nid: m\ntitle: t\n---\n\n# M\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"| provider | {provider} |\n"
        f"| boundary_id | {boundary_id} |\n"
        f"| region_set | {region} |\n"
    )
    (folder / "00-MANIFEST.md").write_text(manifest, encoding="utf-8")
    for domain, resources in domains.items():
        (folder / f"{domain}.json").write_text(
            json.dumps({"service": domain, "resources": resources}, sort_keys=True),
            encoding="utf-8",
        )
    return folder


def _resource(resource_type: str, rid: str, name: str) -> dict:
    return {
        "provider": "aws",
        "resource_type": resource_type,
        "id": rid,
        "name": name,
    }


# --------------------------------------------------------------------------- #
# lane_of — pure, total, consistent with the fixed lane order
# --------------------------------------------------------------------------- #


def test_lane_of_is_total_over_the_16_roles():
    # Every one of the 16 diagram roles has a lane (Requirement 10.3).
    for role in RESOURCE_TYPES:
        lane = lane_of(role)
        assert lane in LANES


def test_lane_of_matches_the_design_j3_table():
    # design J3: cdn/dns/waf→edge, lb→router, message_queue→async,
    # serverless_fn/managed_k8s/compute_instance→workers, llm_platform→platform,
    # object_store/managed_sql/file_system/cache/secrets_store→data.
    assert lane_of("cdn") == "edge"
    assert lane_of("dns") == "edge"
    assert lane_of("waf") == "edge"
    assert lane_of("lb") == "router"
    assert lane_of("message_queue") == "async"
    assert lane_of("serverless_fn") == "workers"
    assert lane_of("managed_k8s") == "workers"
    assert lane_of("compute_instance") == "workers"
    assert lane_of("llm_platform") == "platform"
    for store in ("object_store", "managed_sql", "file_system", "cache", "secrets_store"):
        assert lane_of(store) == "data"


def test_lane_of_rejects_an_unknown_role():
    with pytest.raises(DrawError):
        lane_of("not-a-role")


# --------------------------------------------------------------------------- #
# Property 8 part 1 — determinism on a committed fixture Snapshot
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("diagram_type", DIAGRAM_TYPES)
def test_two_runs_yield_identical_specs(diagram_type):
    # Requirement 10.6: run twice on the same Snapshot, get an identical spec.
    s1 = spec_from_snapshot(_AWS_SNAPSHOT, "aws", diagram_type)
    s2 = spec_from_snapshot(_AWS_SNAPSHOT, "aws", diagram_type)
    assert s1 == s2


@pytest.mark.parametrize("diagram_type", DIAGRAM_TYPES)
def test_produced_spec_validates(diagram_type):
    # The core never emits a spec the layout pipeline would reject.
    spec = spec_from_snapshot(_AWS_SNAPSHOT, "aws", diagram_type)
    _validate_spec(spec)


def test_landscape_covers_every_role_bearing_resource():
    # Requirement 10.4: total coverage on a landscape — the committed AWS
    # snapshot enumerates 6 role-bearing resources (1 network_boundary, eks,
    # lambda, bedrock, 2 s3 buckets), so all 6 are drawn.
    spec = spec_from_snapshot(_AWS_SNAPSHOT, "aws", "landscape")
    assert len(spec.nodes) == 6
    roles = sorted(n.role for n in spec.nodes)
    assert roles == sorted(
        [
            "network_boundary",
            "managed_k8s",
            "serverless_fn",
            "llm_platform",
            "object_store",
            "object_store",
        ]
    )


def test_no_edges_are_invented_without_relationships():
    # Requirement 10.5: absent a Relationship_Input, no edge is fabricated.
    spec = spec_from_snapshot(_AWS_SNAPSHOT, "aws", "landscape")
    assert spec.edges == ()


def test_supplied_relationships_become_edges():
    spec0 = spec_from_snapshot(_AWS_SNAPSHOT, "aws", "landscape")
    ids = [n.id for n in spec0.nodes]
    # name endpoints by node id and by raw resource identity (arn) — both resolve.
    rels = [
        {"source": ids[1], "target": ids[2], "label": "calls"},
        {"source": "arn:aws:s3:::agent-artifact-store", "target": ids[1], "label": "reads"},
    ]
    spec = spec_from_snapshot(_AWS_SNAPSHOT, "aws", "landscape", relationships=rels)
    assert len(spec.edges) == 2
    assert {e.marker for e in spec.edges} == {"calls", "reads"}
    # every edge endpoint resolves to a declared node (no dangling → validates).
    node_ids = {n.id for n in spec.nodes}
    for e in spec.edges:
        assert e.source in node_ids and e.target in node_ids
    _validate_spec(spec)


# --------------------------------------------------------------------------- #
# Property 8 part 1 — unresolved-role resources are skipped (synthetic snapshot)
# --------------------------------------------------------------------------- #


def test_unresolved_role_resource_is_skipped(tmp_path):
    # Requirement 10.2: a resource with no resolvable role is skipped, never
    # drawn with a look-alike icon. Here two typed resources resolve and one
    # typeless resource does not.
    folder = _write_snapshot(
        tmp_path,
        "aws",
        "111122223333",
        "us-east-1",
        {
            "storage": [
                _resource("object_store", "arn:aws:s3:::b1", "b1"),
                {"provider": "aws", "id": "mystery-1", "name": "no-type-here"},
            ],
            "compute": [
                _resource("serverless_fn", "arn:aws:lambda:::fn", "fn"),
            ],
        },
    )
    spec = spec_from_snapshot(folder, "aws", "landscape")
    # Only the two role-bearing resources are drawn; the typeless one is skipped.
    assert len(spec.nodes) == 2
    assert sorted(n.role for n in spec.nodes) == ["object_store", "serverless_fn"]
    _validate_spec(spec)


# --------------------------------------------------------------------------- #
# Property 8 part 1 — over-budget landscape reports split (synthetic snapshot)
# --------------------------------------------------------------------------- #


def test_over_budget_landscape_reports_split(tmp_path):
    # Requirement 10.7: a landscape over the node-count ERROR bound (> 50) raises
    # SnapshotSplitRequired and emits no spec. 60 object stores > 50.
    resources = [
        _resource("object_store", f"arn:aws:s3:::bucket-{i:03d}", f"bucket-{i:03d}")
        for i in range(60)
    ]
    folder = _write_snapshot(
        tmp_path, "aws", "444455556666", "us-east-1", {"storage": resources}
    )
    with pytest.raises(SnapshotSplitRequired):
        spec_from_snapshot(folder, "aws", "landscape")

    # The same over-budget snapshot as a simple/summary is capped, not split.
    simple = spec_from_snapshot(folder, "aws", "simple")
    assert len(simple.nodes) == 12


def test_simple_and_summary_cap_at_the_flow_budget(tmp_path):
    # Requirement 10.4: simple/summary emit the in-scope subset, capped at 12.
    resources = [
        _resource("object_store", f"arn:aws:s3:::b-{i:02d}", f"b-{i:02d}")
        for i in range(20)
    ]
    folder = _write_snapshot(
        tmp_path, "aws", "777788889999", "eu-west-1", {"storage": resources}
    )
    for dtype in ("simple", "summary"):
        spec = spec_from_snapshot(folder, "aws", dtype)
        assert len(spec.nodes) == 12
        _validate_spec(spec)


# --------------------------------------------------------------------------- #
# Determinism under input reordering (property)
# --------------------------------------------------------------------------- #


@settings(max_examples=40, deadline=None)
@given(
    seed=st.lists(
        st.tuples(
            st.sampled_from(sorted(set(RESOURCE_TYPES) - {"boundary", "network_boundary"})),
            st.integers(min_value=0, max_value=999),
        ),
        min_size=1,
        max_size=10,
        unique_by=lambda t: t[1],
    ),
    perm=st.randoms(use_true_random=False),
)
def test_spec_is_independent_of_resource_file_order(tmp_path_factory, seed, perm):
    # Requirement 10.6: the produced spec is a stable-sort function of the
    # resource set, independent of the order resources appear in the JSON. Two
    # snapshots with the SAME resources in a DIFFERENT order produce identical
    # specs (modulo the snapshot folder path, which is not part of DiagramSpec).
    resources = [
        _resource(rt, f"arn:aws:svc:::r-{n:04d}", f"r-{n:04d}") for rt, n in seed
    ]
    shuffled = list(resources)
    perm.shuffle(shuffled)

    root_a = tmp_path_factory.mktemp("a")
    root_b = tmp_path_factory.mktemp("b")
    folder_a = _write_snapshot(root_a, "aws", "acct", "us-east-1", {"storage": resources})
    folder_b = _write_snapshot(root_b, "aws", "acct", "us-east-1", {"storage": shuffled})

    spec_a = spec_from_snapshot(folder_a, "aws", "landscape")
    spec_b = spec_from_snapshot(folder_b, "aws", "landscape")

    # Node id/role/lane/slot tuples are identical regardless of input order.
    def _fingerprint(spec):
        return [(n.id, n.role, n.lane, n.region, n.slot) for n in spec.nodes]

    assert _fingerprint(spec_a) == _fingerprint(spec_b)
    _validate_spec(spec_a)
