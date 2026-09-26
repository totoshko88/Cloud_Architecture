"""Tests for the inventory Snapshot folder-shape gate (v1.6.0).

The gate exists because a clean-room install produced a snapshot that linted
**completely clean** while breaking two mandated contracts: ``resources/`` was
created but left empty though 400-plus items had been enumerated, and the
manifest recorded ``file_count: 12`` against 13 real files. The linter checks
snapshot file *content* (frontmatter, secret-safety); nothing checked the shape of
the folder, so a hand-written snapshot degraded silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rule_engine import snapshot_gate as sg

_REPO_ROOT = Path(__file__).resolve().parents[1]

_GOOD_NAME = "inventory-aws-123456789012-us-east-1-2026-09-22_1430"

_MANIFEST_TABLE = """\
# Inventory Snapshot Manifest

| Field | Value |
| --- | --- |
| provider | aws |
| boundary_id | 123456789012 |
| region_set | us-east-1 |
| caller_identity | arn:aws:iam::123456789012:role/inventory-readonly |
| tool_versions | aws-cli 2.15.0 |
| file_count | {file_count} |
| delta_instructions | Diff each domain JSON against this folder |
"""

_MANIFEST_BULLETS = """\
# Inventory Snapshot Manifest

- **provider**: aws
- **boundary_id**: 123456789012
- **region_set**: us-east-1
- **caller_identity**: arn:aws:sts::123456789012:assumed-role/ro (read-only)
- **tool_versions**: aws-cli/2.37.0
- **file_count**: {file_count}
- **delta_instructions**: Re-run the same read-only enumeration and diff.
"""


def _resource(rid: str = "arn:aws:s3:::bucket-a") -> dict:
    return {
        "provider": "aws",
        "resource_type": "object_store",
        "native_type": "AWS::S3::Bucket",
        "id": rid,
        "name": rid.rsplit(":", 1)[-1],
        "boundary": "123456789012",
        "region": "us-east-1",
        "tags": {"env": "prod"},
        "config_digest": "a" * 64,
    }


def _make_snapshot(
    tmp_path: Path,
    name: str = _GOOD_NAME,
    manifest: str | None = _MANIFEST_TABLE,
    domains: dict[str, list[dict]] | None = None,
    resource_dirs: int | None = None,
    file_count: int | None = None,
) -> Path:
    """Build a snapshot folder on disk. ``resource_dirs=None`` means "one per
    enumerated resource" (the conforming case)."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    domains = {"storage": [_resource()]} if domains is None else domains
    for domain, resources in domains.items():
        (root / f"{domain}.json").write_text(
            json.dumps({"service": domain, "resources": resources}), encoding="utf-8"
        )
    total_resources = sum(len(v) for v in domains.values())
    want_dirs = total_resources if resource_dirs is None else resource_dirs
    resources_dir = root / "resources"
    resources_dir.mkdir(exist_ok=True)
    for i in range(want_dirs):
        sub = resources_dir / f"storage-bucket-{i}"
        sub.mkdir(exist_ok=True)
        (sub / "resource.json").write_text(json.dumps(_resource()), encoding="utf-8")
    if manifest is not None:
        # Count the files that exist so far, +1 for the manifest itself.
        actual = sum(1 for p in root.rglob("*") if p.is_file()) + 1
        (root / "00-MANIFEST.md").write_text(
            manifest.format(file_count=file_count if file_count is not None else actual),
            encoding="utf-8",
        )
    return root


# =========================================================================== #
# The conforming case
# =========================================================================== #


def test_conforming_snapshot_is_ok(tmp_path):
    report = sg.check_snapshot(_make_snapshot(tmp_path))
    assert report.findings == []
    assert report.ok is True


def test_conforming_snapshot_reports_its_shape(tmp_path):
    report = sg.check_snapshot(_make_snapshot(tmp_path))
    assert report.domain_files == ["storage.json"]
    assert report.resource_dirs == 1
    assert report.file_count_recorded == report.file_count_actual


# =========================================================================== #
# §3 folder name
# =========================================================================== #


@pytest.mark.parametrize("name", [
    "inventory-aws-123456789012-us-east-1",           # no timestamp
    "inventory-aws-123456789012-us-east-1-2026-09-22",  # no HHMM
    "snapshot-aws-123456789012-us-east-1-2026-09-22_1430",  # wrong prefix
    "inventory-aws-123456789012-us-east-1-2026-9-22_1430",  # unpadded month
])
def test_malformed_folder_name_is_an_error(tmp_path, name):
    report = sg.check_snapshot(_make_snapshot(tmp_path, name=name))
    assert "folder-name" in {f.rule for f in report.errors}


def test_unknown_provider_segment_is_an_error(tmp_path):
    report = sg.check_snapshot(
        _make_snapshot(tmp_path, name="inventory-ibm-acct-region-2026-09-22_1430")
    )
    rules = {f.rule for f in report.errors}
    assert "folder-name" in rules


def test_impossible_timestamp_is_an_error(tmp_path):
    report = sg.check_snapshot(
        _make_snapshot(tmp_path,
                       name="inventory-aws-123456789012-us-east-1-2026-09-22_9999")
    )
    assert "folder-name" in {f.rule for f in report.errors}


def test_multi_hyphen_boundary_and_region_are_accepted(tmp_path):
    """``eu-central-1`` and a hyphenated boundary id must not break the pattern."""
    report = sg.check_snapshot(
        _make_snapshot(tmp_path,
                       name="inventory-generic-env-prod-region-1-2026-09-22_1430")
    )
    assert "folder-name" not in {f.rule for f in report.errors}


# =========================================================================== #
# §4 manifest
# =========================================================================== #


def test_missing_manifest_is_an_error(tmp_path):
    report = sg.check_snapshot(_make_snapshot(tmp_path, manifest=None))
    assert "manifest-missing" in {f.rule for f in report.errors}


def test_each_missing_manifest_field_is_named(tmp_path):
    """A partial manifest names every absent key, not just "invalid"."""
    partial = "# M\n\n| Field | Value |\n| --- | --- |\n| provider | aws |\n"
    report = sg.check_snapshot(_make_snapshot(tmp_path, manifest=partial))
    details = " ".join(f.detail for f in report.errors if f.rule == "manifest-field")
    for key in ("boundary_id", "region_set", "caller_identity",
                "tool_versions", "file_count", "delta_instructions"):
        assert key in details
    assert "'provider'" not in details  # provider WAS recorded


def test_empty_manifest_value_is_an_error(tmp_path):
    blank = _MANIFEST_TABLE.replace("| aws |", "|  |")
    report = sg.check_snapshot(_make_snapshot(tmp_path, manifest=blank))
    assert any(
        f.rule == "manifest-field" and "provider" in f.detail for f in report.errors
    )


def test_bullet_list_manifest_is_accepted(tmp_path):
    """The clean-room agent wrote the fields as a bullet list, not a table. The
    contract is that the field is recorded, not how it is rendered."""
    report = sg.check_snapshot(_make_snapshot(tmp_path, manifest=_MANIFEST_BULLETS))
    assert [f.rule for f in report.errors] == []


def test_parse_manifest_fields_reads_all_three_shapes():
    table = sg.parse_manifest_fields("| provider | aws |")
    bullet = sg.parse_manifest_fields("- **provider**: azure")
    kv = sg.parse_manifest_fields("provider: gcp")
    assert table["provider"] == "aws"
    assert bullet["provider"] == "azure"
    assert kv["provider"] == "gcp"


def test_parse_manifest_fields_keeps_the_first_non_empty_value():
    text = "| provider | aws |\n- **provider**: azure\n"
    assert sg.parse_manifest_fields(text)["provider"] == "aws"


# =========================================================================== #
# §5 per-domain JSON and per-resource subfolders
# =========================================================================== #


def test_no_domain_json_is_an_error(tmp_path):
    root = tmp_path / _GOOD_NAME
    root.mkdir()
    (root / "00-MANIFEST.md").write_text(
        _MANIFEST_TABLE.format(file_count=1), encoding="utf-8"
    )
    (root / "resources").mkdir()
    report = sg.check_snapshot(root)
    assert "no-domain-json" in {f.rule for f in report.errors}


def test_missing_resources_dir_is_an_error(tmp_path):
    root = _make_snapshot(tmp_path)
    for p in sorted((root / "resources").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (root / "resources").rmdir()
    report = sg.check_snapshot(root)
    assert "resources-missing" in {f.rule for f in report.errors}


def test_empty_resources_dir_with_enumerated_resources_is_an_error(tmp_path):
    """The clean-room defect: ``resources/`` created but never populated."""
    report = sg.check_snapshot(_make_snapshot(tmp_path, resource_dirs=0))
    offending = [f for f in report.errors if f.rule == "resources-empty"]
    assert offending
    # The message must state how many items were enumerated, so the author can
    # see the folder is not merely "an empty account".
    assert "1 item" in offending[0].detail


def test_empty_resources_dir_with_nothing_enumerated_is_clean(tmp_path):
    """An account that genuinely enumerated nothing is not a defect: the domain
    files are present and empty, so there is no resource to give a subfolder."""
    report = sg.check_snapshot(
        _make_snapshot(tmp_path, domains={"storage": [], "compute": []},
                       resource_dirs=0)
    )
    assert report.findings == []


def test_count_enumerated_resources_walks_nested_lists(tmp_path):
    root = tmp_path / _GOOD_NAME
    root.mkdir()
    (root / "storage.json").write_text(
        json.dumps({"s3": {"Buckets": [1, 2, 3]}, "efs": {"FileSystems": [1]}}),
        encoding="utf-8",
    )
    assert sg.count_enumerated_resources(root) == 4


def test_count_enumerated_resources_tolerates_unreadable_json(tmp_path):
    root = tmp_path / _GOOD_NAME
    root.mkdir()
    (root / "broken.json").write_text("{not json", encoding="utf-8")
    assert sg.count_enumerated_resources(root) == 0


def test_failures_json_entries_are_not_counted_as_resources(tmp_path):
    """failures.json lists services that could NOT be enumerated (v1.6.1).

    Counting its entries turned an empty inventory with one recorded failure —
    a cost request without a declared endpoint — into a ``resources-empty``
    ERROR."""
    root = tmp_path / _GOOD_NAME
    root.mkdir()
    (root / "failures.json").write_text(
        json.dumps({"failures": [{"service": "cost", "reason": "no declared cost endpoint"}]}),
        encoding="utf-8",
    )
    (root / "storage.json").write_text(json.dumps({"service": "storage", "resources": []}), encoding="utf-8")
    assert sg.count_enumerated_resources(root) == 0


# =========================================================================== #
# §4 file_count
# =========================================================================== #


def test_stale_file_count_is_a_warning_not_an_error(tmp_path):
    """The clean-room manifest said 12 against 13 real files. A stale count is a
    documentation defect, so it reports without blocking."""
    report = sg.check_snapshot(_make_snapshot(tmp_path, file_count=99))
    assert [f.rule for f in report.errors] == []
    assert [f.rule for f in report.warnings] == ["file-count"]
    assert report.ok is True


def test_file_count_warning_reports_both_numbers(tmp_path):
    report = sg.check_snapshot(_make_snapshot(tmp_path, file_count=99))
    detail = report.warnings[0].detail
    assert "99" in detail and str(report.file_count_actual) in detail


# =========================================================================== #
# Discovery + CLI
# =========================================================================== #


def test_discover_snapshots_finds_nested_folders(tmp_path):
    _make_snapshot(tmp_path / "aws")
    _make_snapshot(tmp_path / "generic",
                   name="inventory-generic-env-prod-region-1-2026-09-22_1430")
    found = sg.discover_snapshots(tmp_path)
    assert len(found) == 2


def test_discover_snapshots_does_not_descend_into_a_snapshot(tmp_path):
    """A ``resources/`` subfolder inside a snapshot is not another snapshot."""
    _make_snapshot(tmp_path)
    assert len(sg.discover_snapshots(tmp_path)) == 1


def test_looks_like_snapshot_dir(tmp_path):
    root = _make_snapshot(tmp_path)
    assert sg.looks_like_snapshot_dir(root) is True
    assert sg.looks_like_snapshot_dir(root / "storage.json") is False


def test_cli_ok_on_a_conforming_tree(tmp_path, capsys):
    _make_snapshot(tmp_path)
    assert sg.main(["--root", str(tmp_path)]) == sg.EXIT_OK
    assert "satisfy the mandated shape" in capsys.readouterr().out


def test_cli_blocks_on_an_empty_resources_dir(tmp_path, capsys):
    _make_snapshot(tmp_path, resource_dirs=0)
    assert sg.main(["--root", str(tmp_path)]) == sg.EXIT_VIOLATION
    assert "resources-empty" in capsys.readouterr().err


def test_cli_warning_alone_does_not_fail(tmp_path, capsys):
    _make_snapshot(tmp_path, file_count=99)
    assert sg.main(["--root", str(tmp_path)]) == sg.EXIT_OK


def test_cli_strict_fails_on_a_warning(tmp_path):
    _make_snapshot(tmp_path, file_count=99)
    assert sg.main(["--root", str(tmp_path), "--strict"]) == sg.EXIT_VIOLATION


def test_cli_no_snapshots_is_ok(tmp_path, capsys):
    assert sg.main(["--root", str(tmp_path)]) == sg.EXIT_OK
    assert "no inventory-*" in capsys.readouterr().out


def test_cli_missing_root_is_a_usage_error(tmp_path):
    assert sg.main(["--root", str(tmp_path / "nope")]) == sg.EXIT_USAGE


def test_cli_explicit_snapshot_argument(tmp_path):
    root = _make_snapshot(tmp_path)
    assert sg.main(["--snapshot", str(root)]) == sg.EXIT_OK


def test_cli_explicit_missing_snapshot_is_a_usage_error(tmp_path):
    assert sg.main(["--snapshot", str(tmp_path / "nope")]) == sg.EXIT_USAGE


# =========================================================================== #
# The shipped example snapshots
# =========================================================================== #


def test_shipped_example_snapshots_conform():
    """Both golden Snapshot folders satisfy the whole §3-§5 contract.

    Before v1.6.0 they held only ``00-MANIFEST.md`` + ``10-delta-example.md``
    while their own manifests described per-domain JSON, per-resource subfolders,
    and ``file_count: 11`` — a doc/data mismatch in the reference set itself.
    """
    reports = sg.check_snapshots(_REPO_ROOT / "examples")
    assert reports, "expected the shipped example Snapshot folders"
    for report in reports:
        assert report.findings == [], f"{report.path}: {report.findings}"


def test_shipped_example_snapshots_record_an_accurate_file_count():
    for report in sg.check_snapshots(_REPO_ROOT / "examples"):
        assert report.file_count_recorded == report.file_count_actual, report.path
