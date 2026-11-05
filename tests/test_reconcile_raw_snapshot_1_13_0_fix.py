"""1.13.0 G45: reconcile reads raw-CLI-shaped snapshots and skips non-domain files.

Before 1.13.0 ``rule-engine-reconcile`` exited 3 on any hand-collected snapshot:
every ``*.json`` had to be ``{"resources": [...]}``, so an ``identity.json`` or a
raw ``aws s3api list-buckets`` dump was a fatal gate error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine import reconcile as rc

REPO = Path(__file__).resolve().parents[1]


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _types(path: Path, provider: str = "aws"):
    return sorted(r["resource_type"] for r in rc.iter_domain_resources(path, provider))


def test_resources_shape_unchanged(tmp_path):
    f = tmp_path / "storage.json"
    _write(f, {"service": "storage", "resources": [{"resource_type": "object_store", "name": "b"}]})
    assert list(rc.iter_domain_resources(f, "aws")) == [
        {"resource_type": "object_store", "name": "b"}
    ]


def test_raw_ai_file_maps_to_llm_platform(tmp_path):
    f = tmp_path / "ai.json"
    _write(f, {"bedrock_foundation_models": {"modelSummaries": [{"modelId": "m1"}, {"modelId": "m2"}]}})
    assert _types(f) == ["llm_platform", "llm_platform"]


def test_raw_storage_file_maps_buckets_and_efs(tmp_path):
    f = tmp_path / "storage.json"
    item = {"Name": "bucket-a"}
    _write(f, {
        "buckets": {"Buckets": [item], "Owner": {"ID": "x"}},
        "efs": {"FileSystems": [{"FileSystemId": "fs-1"}]},
        "fsx": {"FileSystems": []},
    })
    assert _types(f) == ["file_system", "object_store"]


def test_raw_items_are_copies(tmp_path):
    f = tmp_path / "compute.json"
    data = {"reservations": {"Reservations": [{"Instances": [{"InstanceId": "i-1"}, {"InstanceId": "i-2"}]}]}}
    _write(f, data)
    out = list(rc.iter_domain_resources(f, "aws"))
    assert [r["InstanceId"] for r in out] == ["i-1", "i-2"]
    assert {r["resource_type"] for r in out} == {"compute_instance"}


def test_wafv2_prefix_and_nested_envelope(tmp_path):
    f = tmp_path / "edge.json"
    _write(f, {
        "cloudfront_distributions": {"DistributionList": {"Items": [{"Id": "E1"}]}},
        "wafv2_regional_euc1": {"WebACLs": [{"Name": "acl"}]},
        "acm_us_east_1": {"CertificateSummaryList": [{"CertificateArn": "arn"}]},
    })
    assert _types(f) == ["cdn", "waf"]


def test_raw_table_only_holds_valid_roles():
    for table in rc._RAW_COLLECTION_ROLES.values():
        assert set(table.values()) <= rc._VALID_ROLES


def test_non_domain_file_raises_not_a_domain_file(tmp_path):
    f = tmp_path / "identity.json"
    _write(f, {"caller_identity": {"Account": "123456789012"}})
    with pytest.raises(rc.NotADomainFile):
        list(rc.iter_domain_resources(f, "aws"))


def test_invalid_json_is_still_fatal(tmp_path):
    f = tmp_path / "storage.json"
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(rc.SnapshotReadError) as exc:
        list(rc.iter_domain_resources(f, "aws"))
    assert not isinstance(exc.value, rc.NotADomainFile)


def _snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "inventory-aws-123456789012-us-east-1-2026-10-31_2044"
    snap.mkdir()
    _write(snap / "ai.json", {"bedrock_foundation_models": {"modelSummaries": [{"modelId": "m1"}]}})
    _write(snap / "storage.json", {"buckets": {"Buckets": [{"Name": "b"}]}, "efs": {"FileSystems": [{"FileSystemId": "fs-1"}]}})
    _write(snap / "identity.json", {"caller_identity": {"Account": "123456789012"}})
    _write(snap / "failures.json", {"failures": [{"service": "x", "reason": "y"}]})
    return snap


def test_reconcile_skips_and_lists_non_domain_files(tmp_path):
    snap = _snapshot(tmp_path)
    diagram = REPO / "examples/aws/02-aws-ha-multiregion-landscape.drawio"
    report = rc.reconcile(snap, diagram, "aws")
    assert report.skipped_files == ["identity.json"]
    assert report.to_dict()["skipped_files"] == ["identity.json"]
    assert report.expected_roles == frozenset({"llm_platform", "object_store", "file_system"})
    assert report.enumerated_count == 3
    roles = list(rc.iter_snapshot_roles(snap, "aws"))
    assert sorted(r for _res, r in roles) == ["file_system", "llm_platform", "object_store"]


def test_main_prints_skipped_warning_and_never_exits_3(tmp_path, capsys):
    snap = _snapshot(tmp_path)
    diagram = REPO / "examples/aws/02-aws-ha-multiregion-landscape.drawio"
    code = rc.main(["--provider", "aws", "--snapshot", str(snap), "--diagram", str(diagram)])
    assert code in (rc.EXIT_OK, rc.EXIT_BLOCKED)
    assert "[WARNING] skipped 1 non-domain file(s): identity.json" in capsys.readouterr().out


def test_main_invalid_json_exits_usage(tmp_path):
    snap = _snapshot(tmp_path)
    (snap / "broken.json").write_text("{", encoding="utf-8")
    diagram = REPO / "examples/aws/02-aws-ha-multiregion-landscape.drawio"
    code = rc.main(["--provider", "aws", "--snapshot", str(snap), "--diagram", str(diagram)])
    assert code == rc.EXIT_USAGE


def test_release_reconcile_pairs_still_pass(monkeypatch):
    monkeypatch.chdir(REPO)
    import importlib.util

    spec = importlib.util.spec_from_file_location("_release", REPO / "scripts/release.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    for provider, snap, diagram in release.RECONCILE_PAIRS:
        report = rc.reconcile(REPO / snap, REPO / diagram, provider)
        assert report.eligible, (provider, report.omissions)
        assert report.skipped_files == []


def test_landscape_example_report_unchanged():
    """The collector-shaped example snapshot reads as before (one known omission)."""
    report = rc.reconcile(
        REPO / "examples/aws/inventory-aws-123456789012-us-east-1-2026-09-22_1430",
        REPO / "examples/aws/02-aws-ha-multiregion-landscape.drawio",
        "aws",
    )
    assert report.coverage_class == "landscape"
    assert report.skipped_files == []
    assert report.omissions == [{"role": "llm_platform", "resource": "agent-reasoning"}]
