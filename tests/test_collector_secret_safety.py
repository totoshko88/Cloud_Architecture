"""Regression tests for the 1.6.1 collector secret-safety hotfix.

Every case here was a confirmed defect in 1.6.0:

* the read-only allow-list admitted operations that return a secret value or
  mint a credential (``get_secret_value``, ``get_session_token``,
  ``az keyvault secret show`` …), because they create, update and delete nothing;
* ``re.IGNORECASE`` made the camelCase boundary ``[_A-Z]`` match any letter, so
  ``listen`` and ``getanddeletebucket`` counted as read-only verbs;
* redaction erased the *name* of every ``{Key, Value}`` tag and kept its value,
  and kept the ``Value`` of an SSM ``SecureString`` parameter;
* ``failures.json`` was written verbatim, and the "no declared cost endpoint"
  failure was appended after it had already been written.

(inventory-standards §1, §2, §7, §8, §9.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rule_engine.collector import (
    REDACTED,
    Enumerator,
    collect,
    has_shell_metacharacters,
    is_read_only_verb,
    is_secret_verb,
    redact_secrets,
    rejection_reason,
)

FIXED_START = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Verb boundary (the IGNORECASE defect)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb",
    ["listen", "getaway", "getanddeletebucket", "describeanddestroyall", "Listen"],
)
def test_aws_prefix_must_end_at_a_word_boundary(verb: str) -> None:
    assert is_read_only_verb("aws", verb) is False


@pytest.mark.parametrize(
    "verb",
    [
        "list",
        "list_buckets",
        "ListBuckets",
        "listBuckets",
        "describe_instances",
        "DescribeInstances",
        "describe-instances",  # kebab case, as the inventory-standards §6 table writes it
        "get_bucket_policy",
        "GetBucketPolicy",
        "get_caller_identity",
    ],
)
def test_aws_read_only_spellings_still_allowed(verb: str) -> None:
    assert is_read_only_verb("aws", verb) is True


# ---------------------------------------------------------------------------
# Secret-returning / credential-minting operations
# ---------------------------------------------------------------------------

_SECRET_VERBS = [
    ("aws", "get_secret_value"),
    ("aws", "GetSecretValue"),
    ("aws", "get-secret-value"),
    ("aws", "batch_get_secret_value"),
    ("aws", "get_session_token"),
    ("aws", "GetFederationToken"),
    ("aws", "get_authorization_token"),
    ("aws", "get_login_password"),
    ("aws", "get_password_data"),
    ("aws", "get_random_password"),
    ("aws", "get_parameter"),
    ("aws", "GetParameters"),
    ("aws", "get_parameters_by_path"),
    ("aws", "get_parameter_history"),
    ("aws", "get_object"),
    ("aws", "get_cluster_credentials"),
    ("aws", "get_role_credentials"),
    ("aws", "get_credentials_for_identity"),
    ("aws", "get_open_id_token"),
    ("aws", "GetRelationalDatabaseMasterUserPassword"),
    ("aws", "get_instance_access_details"),
    ("azure", "az keyvault secret show"),
    ("azure", "az storage account keys list"),
    ("azure", "az cosmosdb keys list"),
    ("azure", "az search admin-key show"),
    ("azure", "az acr credential show"),
    ("azure", "az webapp config appsettings list"),
    ("oci", "oci secrets secret-bundle get"),
    ("oci", "oci os object get"),
]


@pytest.mark.parametrize("provider,verb", _SECRET_VERBS)
def test_secret_returning_verbs_are_rejected(provider: str, verb: str) -> None:
    assert is_secret_verb(verb, provider) is True
    assert is_read_only_verb(provider, verb) is False
    assert "secret-safety" in (rejection_reason(provider, verb) or "")


@pytest.mark.parametrize(
    "verb",
    ["gcloud secrets versions access", "gcloud auth print-access-token", "az account get-access-token"],
)
def test_cli_secret_verbs_are_named_even_when_patterns_already_reject_them(verb: str) -> None:
    """Defence in depth: these fail the provider patterns anyway, but the
    secret classifier recognises them too."""
    assert is_secret_verb(verb) is True


_METADATA_VERBS = [
    ("aws", "list_secrets"),
    ("aws", "describe_secret"),
    ("aws", "describe_parameters"),
    ("aws", "get_account_password_policy"),
    ("aws", "get_credential_report"),
    ("aws", "get_caller_identity"),
    ("aws", "get_object_tagging"),
    ("aws", "list_access_keys"),
    ("aws", "get_access_key_last_used"),
    ("aws", "get_key_policy"),
    ("aws", "list_keys"),
    ("azure", "az keyvault list"),
    ("azure", "az keyvault secret list"),
    ("azure", "az keyvault key list"),
    ("azure", "az keyvault key show"),
    ("azure", "az storage account list"),
    ("azure", "az account show"),
    ("gcp", "gcloud secrets list"),
    ("gcp", "gcloud secrets describe"),
    ("gcp", "gcloud secrets versions list"),
    ("oci", "oci vault secret list"),
    ("oci", "oci os object list"),
    # Key-management listings: the GCP / OCI counterparts of ``kms list-keys``,
    # which inventory-standards §6 puts in the secrets.json floor. An Azure
    # ``keys list`` returns account keys; these return key metadata only.
    ("gcp", "gcloud kms keys list"),
    ("gcp", "gcloud iam service-accounts keys list"),
    ("gcp", "gcloud services api-keys list"),
    ("gcp", "gcloud compute os-login ssh-keys list"),
    ("oci", "oci kms management key list"),
    ("oci", "oci iam api-key list"),
    ("oci", "oci iam customer-secret-key list"),
    ("oci", "oci iam smtp-credential list"),
    ("azure", "az ad sp credential list"),
    ("azure", "az ad app credential list"),
    ("aws", "list_service_specific_credentials"),
]


@pytest.mark.parametrize("provider,verb", _METADATA_VERBS)
def test_metadata_verbs_on_secret_services_stay_allowed(provider: str, verb: str) -> None:
    assert is_secret_verb(verb, provider) is False
    assert is_read_only_verb(provider, verb) is True


def test_azure_shaped_patterns_still_apply_when_no_provider_is_given() -> None:
    """Without a provider the classifier stays conservative (every pattern)."""
    assert is_secret_verb("gcloud kms keys list") is True
    assert is_secret_verb("gcloud kms keys list", "gcp") is False
    assert is_secret_verb("gcloud kms keys list", "generic") is True


# ---------------------------------------------------------------------------
# Shell metacharacters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider,verb",
    [
        ("aws", "list_buckets; rm -rf /"),
        ("aws", "describe_instances > out.json"),
        ("aws", "get_bucket_policy`id`"),
        ("azure", "az vm list && curl https://example.invalid"),
        ("azure", "az vm list | tee out"),
        ("gcp", "gcloud compute instances list $(id)"),
        ("generic", "terraform state list; terraform apply"),
    ],
)
def test_shell_metacharacters_reject_the_verb(provider: str, verb: str) -> None:
    assert has_shell_metacharacters(verb) is True
    assert is_read_only_verb(provider, verb) is False
    assert rejection_reason(provider, verb) == "shell metacharacter in verb rejected"


def test_secret_verb_is_never_called_by_collect(tmp_path: Path) -> None:
    called = {"value": False}

    def _get_secret_value(**_kwargs):  # pragma: no cover - must never run
        called["value"] = True
        return [{"SecretString": "hunter2"}]

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=[
            Enumerator("secrets", "list_secrets", lambda **_: [{"Name": "app/db"}]),
            Enumerator("secrets", "get_secret_value", _get_secret_value),
        ],
        started_at=FIXED_START,
    )
    assert called["value"] is False
    rejected = {r["verb"]: r["reason"] for r in result["manifest"]["rejected_verbs"]}
    assert "secret-safety" in rejected["get_secret_value"]
    assert "list_secrets" not in rejected


def test_manifest_lists_rejected_verbs_so_a_skipped_domain_is_visible(tmp_path: Path) -> None:
    """A rejected verb writes no domain file; the manifest must say so."""
    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=[Enumerator("secrets", "get_secret_value", lambda **_: [])],
        started_at=FIXED_START,
    )
    manifest_md = (Path(result["snapshot_folder"]) / "00-MANIFEST.md").read_text(encoding="utf-8")
    assert "## Rejected verbs (not executed)" in manifest_md
    assert "| secrets | get_secret_value |" in manifest_md


# ---------------------------------------------------------------------------
# Redaction of name/value pairs
# ---------------------------------------------------------------------------


def test_benign_tag_keeps_its_name_and_value() -> None:
    out = redact_secrets({"Tags": [{"Key": "Environment", "Value": "prod"}]})
    assert out["Tags"] == [{"Key": "Environment", "Value": "prod"}]


def test_secret_tag_redacts_its_value_and_its_name() -> None:
    out = redact_secrets({"Tags": [{"Key": "DB_PASSWORD", "Value": "hunter2"}]})
    assert out["Tags"] == [{"Key": REDACTED, "Value": REDACTED}]
    assert "hunter2" not in json.dumps(out)


def test_container_environment_pair_is_judged_by_name() -> None:
    out = redact_secrets(
        {
            "environment": [
                {"name": "LOG_LEVEL", "value": "debug"},
                {"name": "API_TOKEN", "value": "tok-abc123"},
            ]
        }
    )
    assert out["environment"][0] == {"name": "LOG_LEVEL", "value": "debug"}
    assert out["environment"][1] == {"name": REDACTED, "value": REDACTED}


def test_cloudformation_parameter_pair_is_judged_by_name() -> None:
    out = redact_secrets({"ParameterKey": "DBPassword", "ParameterValue": "hunter2"})
    assert out["ParameterValue"] == REDACTED
    assert "hunter2" not in json.dumps(out)


def test_securestring_parameter_value_is_redacted() -> None:
    out = redact_secrets(
        {"Parameter": {"Name": "/app/flag", "Type": "SecureString", "Value": "s3cr3t"}}
    )
    assert out["Parameter"]["Value"] == REDACTED
    assert out["Parameter"]["Name"] == "/app/flag"
    assert "s3cr3t" not in json.dumps(out)


def test_azure_keys_list_record_value_is_redacted() -> None:
    out = redact_secrets([{"keyName": "key1", "permissions": "FULL", "value": "base64key=="}])
    assert out[0]["value"] == REDACTED
    assert out[0]["keyName"] == "key1"


def test_metric_dimension_pair_is_left_alone() -> None:
    record = {"Name": "InstanceId", "Value": "i-0123456789abcdef0"}
    assert redact_secrets(record) == record


def test_non_pair_bare_key_is_still_key_material() -> None:
    """The pre-1.6.1 rule for a bare ``key`` outside a {Key, Value} pair stands."""
    assert redact_secrets({"key": "AKIAEXAMPLE", "region": "us-east-1"})["key"] == REDACTED


@pytest.mark.parametrize(
    "field",
    [
        "primaryKey",
        "secondaryKey",
        "primaryMasterKey",
        "primaryConnectionString",
        "connectionString",
        "AccountKey",
        "sharedAccessKey",
        "adminKey",
    ],
)
def test_azure_key_field_names_are_redacted(field: str) -> None:
    out = redact_secrets({field: "c2VjcmV0LWtleS1tYXRlcmlhbA==", "name": "acct"})
    assert out[field] == REDACTED
    assert out["name"] == "acct"


def test_kms_key_spec_metadata_is_not_mistaken_for_a_master_key() -> None:
    record = {"KeyId": "1234abcd", "CustomerMasterKeySpec": "SYMMETRIC_DEFAULT"}
    assert redact_secrets(record) == record


# ---------------------------------------------------------------------------
# Redaction of secret content in values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIexample",
        "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=abc123==;EndpointSuffix=core.windows.net",
        "Endpoint=sb://ns.servicebus.windows.net/;SharedAccessKeyName=root;SharedAccessKey=abc=",
        "postgres://app:hunter2@db.internal:5432/app",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOYBF...\n-----END PGP PRIVATE KEY BLOCK-----",
    ],
)
def test_secret_content_is_redacted(value: str) -> None:
    assert redact_secrets({"note": value})["note"] == REDACTED


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/path?x=1",
        "ssh://git@github.com/org/repo.git",
        "arn:aws:iam::123456789012:role/app",
        "max connections: 100",
    ],
)
def test_ordinary_values_are_not_redacted(value: str) -> None:
    assert redact_secrets({"note": value})["note"] == value


# ---------------------------------------------------------------------------
# failures.json and the cost failure
# ---------------------------------------------------------------------------


def _snapshot_dir(result) -> Path:
    return Path(result["snapshot_folder"])


def test_failure_reasons_are_redacted_in_every_snapshot_file(tmp_path: Path) -> None:
    def _boom(**_kwargs):
        raise RuntimeError("auth failed for connection password=hunter2")

    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=[
            Enumerator("storage", "list_buckets", lambda **_: [{"Name": "b1"}]),
            Enumerator("database", "describe_db_instances", _boom),
        ],
        started_at=FIXED_START,
    )
    snapshot = _snapshot_dir(result)
    failures = json.loads((snapshot / "failures.json").read_text(encoding="utf-8"))
    assert failures["failures"][0]["service"] == "database"
    for path in snapshot.rglob("*"):
        if path.is_file():
            assert "hunter2" not in path.read_text(encoding="utf-8"), path


def test_missing_cost_endpoint_is_recorded_in_failures_json(tmp_path: Path) -> None:
    result = collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=tmp_path,
        enumerators=[Enumerator("storage", "list_buckets", lambda **_: [{"Name": "b1"}])],
        collect_cost=True,
        started_at=FIXED_START,
    )
    snapshot = _snapshot_dir(result)
    failures = json.loads((snapshot / "failures.json").read_text(encoding="utf-8"))
    assert [f["service"] for f in failures["failures"]] == ["cost"]
    # file_count still matches what is on disk (failures.json is now written).
    on_disk = sum(1 for p in snapshot.rglob("*") if p.is_file())
    assert result["manifest"]["file_count"] == on_disk
