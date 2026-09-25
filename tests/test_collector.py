"""Unit / integration tests for the Inventory Collector (task 7.11).

These tests exercise ``rule_engine.collector.collect`` against injected fake
Enumerators and a ``tmp_path`` output root, validating the read-only /
secret-safe / non-fatal-failure contract of the Inventory Collector.

Validates:
- Requirement 3.1 — only the profile's read-only verbs execute; a
  state-mutating verb is rejected and never called.
- Requirement 3.3 — the count of executed state-mutating verbs is zero.
- Requirement 3.6 — all seven manifest fields are present and non-empty.
- Requirement 3.8 — no snapshot file contains a secret value (redaction).
- Requirement 3.9 — a single-service failure is recorded (service + reason)
  and collection continues with the remaining services.

The tests never touch a live cloud: every Enumerator ``fn`` is a local Python
callable, and mutating verbs are wired to a callable that flips a flag so the
test can assert it was never invoked.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rule_engine.collector import (
    REDACTED,
    Enumerator,
    collect,
    is_mutating_verb,
    is_read_only_verb,
    redact_secrets,
    snapshot_folder_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# inventory-<provider>-<boundary>-<region>-<YYYY-MM-DD_HHMM>
SNAPSHOT_NAME_RE = re.compile(
    r"^inventory-(?P<provider>[^-]+)-(?P<boundary>.+)-(?P<region>[^-]+)-"
    r"(?P<ts>\d{4}-\d{2}-\d{2}_\d{4})$"
)

FIXED_START = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)


def _read_only_fn(resources):
    """Return an enumerator fn that yields the given resource metadata."""

    def _fn(**_kwargs):
        return list(resources)

    return _fn


def _walk_files(root: Path):
    """Yield every file under ``root`` (recursively)."""
    return [p for p in Path(root).rglob("*") if p.is_file()]


# ---------------------------------------------------------------------------
# 3.1 / 3.3 — state-mutating verbs are rejected and never executed
# ---------------------------------------------------------------------------


def test_state_mutating_verbs_are_rejected_and_never_called(tmp_path) -> None:
    """A mutating verb is rejected, its fn is never invoked, and the manifest
    records zero executed mutating verbs (Requirements 3.1, 3.3)."""
    called = {"create_bucket": False, "delete_queue": False}

    def _create_bucket(**_kwargs):  # pragma: no cover - must never run
        called["create_bucket"] = True
        return [{"id": "should-not-exist"}]

    def _delete_queue(**_kwargs):  # pragma: no cover - must never run
        called["delete_queue"] = True
        return [{"id": "should-not-exist"}]

    enumerators = [
        Enumerator(service="storage", verb="list_buckets", fn=_read_only_fn([{"id": "b1"}])),
        Enumerator(service="storage", verb="create_bucket", fn=_create_bucket),
        Enumerator(service="messaging", verb="delete_queue", fn=_delete_queue),
    ]

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=enumerators,
        started_at=FIXED_START,
    )

    manifest = result["manifest"]

    # The mutating fns must never have been invoked.
    assert called["create_bucket"] is False
    assert called["delete_queue"] is False

    # The invariant: zero mutating verbs executed.
    assert manifest["mutating_verbs_executed"] == 0

    # The mutating verbs were recorded as rejected, not executed.
    rejected_verbs = {r["verb"] for r in manifest["rejected_verbs"]}
    assert "create_bucket" in rejected_verbs
    assert "delete_queue" in rejected_verbs

    # The legitimate read-only verb still produced output.
    snapshot_dir = Path(result["snapshot_folder"])
    assert (snapshot_dir / "storage.json").exists()


def test_verb_classification_helpers() -> None:
    """The verb classifiers agree with the read-only / mutating contract."""
    assert is_mutating_verb("create_bucket") is True
    assert is_mutating_verb("delete_queue") is True
    assert is_mutating_verb("put_object") is True
    assert is_mutating_verb("list_buckets") is False
    assert is_mutating_verb("describe_vpcs") is False

    assert is_read_only_verb("aws", "list_buckets") is True
    assert is_read_only_verb("aws", "describe_instances") is True
    assert is_read_only_verb("aws", "get_bucket_policy") is True
    assert is_read_only_verb("aws", "create_bucket") is False
    assert is_read_only_verb("aws", "delete_queue") is False


# ---------------------------------------------------------------------------
# 3.6 — all seven manifest fields present and non-empty
# ---------------------------------------------------------------------------


def _assert_non_empty(value) -> None:
    assert value is not None
    if isinstance(value, str):
        assert value.strip() != ""
    elif isinstance(value, (list, tuple, dict)):
        assert len(value) > 0
    else:
        assert bool(value) or value == 0  # file_count may legitimately be int


def test_manifest_has_all_seven_non_empty_fields(tmp_path) -> None:
    """All seven required manifest fields are present and non-empty
    (Requirement 3.6), and 00-MANIFEST.md is written at the snapshot root."""
    enumerators = [
        Enumerator(service="compute", verb="describe_instances", fn=_read_only_fn([{"id": "i-1"}])),
    ]

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=enumerators,
        region_set=["us-east-1", "us-west-2"],
        tool_versions={"aws-cli": "2.15.0"},
        caller_identity="arn:aws:iam::123456789012:role/reader",
        started_at=FIXED_START,
    )

    manifest = result["manifest"]

    required_fields = (
        "provider",
        "boundary_id",
        "region_set",
        "caller_identity",
        "tool_versions",
        "file_count",
        "delta_instructions",
    )
    for field_name in required_fields:
        assert field_name in manifest, f"missing manifest field: {field_name}"
        _assert_non_empty(manifest[field_name])

    # file_count must be a positive integer.
    assert isinstance(manifest["file_count"], int)
    assert manifest["file_count"] > 0

    # 00-MANIFEST.md exists at the snapshot root and lists the fields.
    snapshot_dir = Path(result["snapshot_folder"])
    manifest_md = snapshot_dir / "00-MANIFEST.md"
    assert manifest_md.exists()
    md_text = manifest_md.read_text(encoding="utf-8")
    for field_name in required_fields:
        assert field_name in md_text


# ---------------------------------------------------------------------------
# 3.9 — single-service failure recorded and collection continues
# ---------------------------------------------------------------------------


def test_single_service_failure_recorded_and_collection_continues(tmp_path) -> None:
    """A single failing service is recorded with its service + reason, and the
    remaining services are still collected (Requirement 3.9)."""

    def _boom(**_kwargs):
        raise RuntimeError("throttled: rate exceeded")

    enumerators = [
        Enumerator(service="compute", verb="describe_instances", fn=_read_only_fn([{"id": "i-1"}])),
        Enumerator(service="network", verb="describe_vpcs", fn=_boom),
        Enumerator(service="storage", verb="list_buckets", fn=_read_only_fn([{"id": "b-1"}])),
    ]

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=enumerators,
        started_at=FIXED_START,
    )

    manifest = result["manifest"]
    failures = manifest["failures"]

    # The failure is recorded with the failing service and a non-empty reason.
    assert len(failures) == 1
    failure = failures[0]
    assert failure["service"] == "network"
    assert "throttled" in failure["reason"] or failure["reason"]

    # Collection continued: the other services' resources were still written.
    snapshot_dir = Path(result["snapshot_folder"])
    assert (snapshot_dir / "compute.json").exists()
    assert (snapshot_dir / "storage.json").exists()

    # A snapshot + manifest were still produced despite the failure.
    assert (snapshot_dir / "00-MANIFEST.md").exists()
    assert (snapshot_dir / "failures.json").exists()

    failures_file = json.loads((snapshot_dir / "failures.json").read_text(encoding="utf-8"))
    assert failures_file["failures"][0]["service"] == "network"


# ---------------------------------------------------------------------------
# 3.8 — no snapshot file contains a secret value
# ---------------------------------------------------------------------------


def test_no_snapshot_file_contains_a_secret_value(tmp_path) -> None:
    """Injected secret values are redacted; the raw secret string appears in no
    snapshot file (Requirement 3.8)."""
    secret_password = "sup3r-s3cret-passw0rd"
    secret_access_key = "AKIAIOSFODNN7EXAMPLE"
    secret_token = "session-token-xyz-123"

    resource = {
        "id": "db-1",
        "name": "prod-db",
        "engine": "postgres",
        "password": secret_password,
        "access_key": secret_access_key,
        "credentials": {
            "session_token": secret_token,
            "nested": {"secret": "another-secret-value"},
        },
    }

    enumerators = [
        Enumerator(service="database", verb="describe_db_instances", fn=_read_only_fn([resource])),
    ]

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=enumerators,
        started_at=FIXED_START,
    )

    snapshot_dir = Path(result["snapshot_folder"])
    secret_values = [secret_password, secret_access_key, secret_token, "another-secret-value"]

    files = _walk_files(snapshot_dir)
    assert files, "expected snapshot files to have been written"

    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        for secret in secret_values:
            assert secret not in content, f"secret leaked into {path}: {secret!r}"

    # The redaction placeholder is present in the domain file (non-secret metadata
    # such as id/name/engine is retained).
    domain_text = (snapshot_dir / "database.json").read_text(encoding="utf-8")
    assert REDACTED in domain_text
    assert "prod-db" in domain_text
    assert "postgres" in domain_text


# ---------------------------------------------------------------------------
# 3.4 / 3.7 — snapshot folder naming + one JSON per service + one subfolder per resource
# ---------------------------------------------------------------------------


def test_snapshot_folder_name_and_content_layout(tmp_path) -> None:
    """The snapshot folder name matches the mandated pattern, and the content
    layout has one JSON per service and one subfolder per resource
    (Requirements 3.4, 3.7)."""
    enumerators = [
        Enumerator(
            service="compute",
            verb="describe_instances",
            fn=_read_only_fn([{"id": "i-1"}, {"id": "i-2"}]),
        ),
        Enumerator(service="storage", verb="list_buckets", fn=_read_only_fn([{"name": "my-bucket"}])),
    ]

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=enumerators,
        started_at=FIXED_START,
    )

    snapshot_dir = Path(result["snapshot_folder"])

    # Folder name matches the mandated pattern and equals the helper output.
    match = SNAPSHOT_NAME_RE.match(snapshot_dir.name)
    assert match is not None, f"bad snapshot folder name: {snapshot_dir.name}"
    assert match.group("provider") == "aws"
    assert match.group("ts") == "2025-01-15_1430"
    assert snapshot_dir.name == snapshot_folder_name(
        "aws", "123456789012", "us-east-1", FIXED_START
    )

    # One JSON file per service domain at the snapshot root.
    assert (snapshot_dir / "compute.json").exists()
    assert (snapshot_dir / "storage.json").exists()

    # One subfolder per enumerated resource under resources/.
    resources_dir = snapshot_dir / "resources"
    assert resources_dir.is_dir()
    subfolders = sorted(p.name for p in resources_dir.iterdir() if p.is_dir())
    # 2 compute instances + 1 storage bucket == 3 resource subfolders.
    assert len(subfolders) == 3
    for sub in subfolders:
        assert (resources_dir / sub / "resource.json").exists()


# ---------------------------------------------------------------------------
# 3.8 — value-level secret redaction (secret under a benign key name)
# ---------------------------------------------------------------------------


def test_redact_secrets_strips_pem_private_key_under_benign_key() -> None:
    """A PEM private-key block hidden under a non-secret key ("note") is
    redacted by value-content scanning, not just by key name."""
    pem = "-----BEGIN PRIVATE KEY-----\nMIIBVwIBADANBg...\n-----END PRIVATE KEY-----"
    out = redact_secrets({"note": pem, "region": "us-east-1"})
    assert out["note"] == REDACTED
    assert out["region"] == "us-east-1"  # ordinary metadata untouched


def test_redact_secrets_strips_inline_assignment_and_securestring() -> None:
    out = redact_secrets(
        {
            "description": "connect with password=hunter2 then retry",
            "payload": "SecureString:AQICAHhwm...",
            "arn": "arn:aws:iam::123456789012:role/app",
        }
    )
    assert out["description"] == REDACTED
    assert out["payload"] == REDACTED
    # An ARN is not a secret and must survive.
    assert out["arn"].startswith("arn:aws:iam::")


def test_redact_secrets_does_not_over_redact_ordinary_values() -> None:
    out = redact_secrets(
        {"name": "prod-bucket", "note": "the primary region", "count": 3}
    )
    assert out == {"name": "prod-bucket", "note": "the primary region", "count": 3}


def test_redact_secrets_recurses_into_nested_values() -> None:
    out = redact_secrets(
        {"config": {"items": [{"note": "token=abc123def"}]}, "ok": "value"}
    )
    assert out["config"]["items"][0]["note"] == REDACTED
    assert out["ok"] == "value"


def test_key_is_secret_boundary_words_not_redacted_by_bare_key() -> None:
    """A benign compound word ending in "key" (monkey/sortkey) is not redacted
    by the bare-key rule; genuine key names still are."""
    out = redact_secrets(
        {"monkey": "george", "sortkey": "z", "key": "AKIA...", "api_key": "x"}
    )
    assert out["monkey"] == "george"
    assert out["sortkey"] == "z"
    assert out["key"] == REDACTED
    assert out["api_key"] == REDACTED


def test_redact_secrets_strips_pem_under_benign_key_delivered_as_bytes() -> None:
    """A PEM block delivered as *bytes* under a benign key is content-scanned
    and redacted (a str-only scan would let it through)."""
    pem = b"-----BEGIN PRIVATE KEY-----\nMIIBVwIBADANBg...\n-----END PRIVATE KEY-----"
    out = redact_secrets({"blob": pem, "region": "us-east-1"})
    assert out["blob"] == REDACTED
    assert out["region"] == "us-east-1"


def test_manifest_redacts_a_credentialed_caller_identity(tmp_path) -> None:
    """00-MANIFEST.md is a snapshot file, so a caller_identity carrying an inline
    token must be redacted there too (inventory-standards §6)."""
    result = collect(
        provider="aws",
        boundary_id="123456789012",
        region="us-east-1",
        enumerators=[],
        output_root=tmp_path,
        caller_identity="reader token=supersecret123",
        tool_versions={"aws-cli": "2.15.0"},
        started_at=FIXED_START,
    )
    manifest_md = (
        tmp_path / result["snapshot_folder"].split("/")[-1] / "00-MANIFEST.md"
    ).read_text(encoding="utf-8")
    assert "supersecret123" not in manifest_md
    assert REDACTED in manifest_md
