"""Tests for the raw-JSON → role mapper ``reconcile.role_of`` (Part B, task 5).

Feature: placement-and-gates (release 1.9.0), Component B1 — the raw-JSON → role
mapper. Requirements 2.1 (map each enumerated Snapshot resource to a diagram
role via the ``mappings/roles.yaml`` vocabulary, reading only committed Snapshot
files) and 2.5 (a resource with no resolvable role is NOT an omission), under
Decision D5 (reconciliation reads the Snapshot, never the provider).

The mapper resolves a raw, redacted native provider metadata dict — the shape a
Snapshot's per-domain JSON records — to one of the 16 diagram roles
(``rule_engine.constants.RESOURCE_TYPES`` = the ``roles.yaml`` role set), or to
``None`` when no role resolves. These tests cover:

- example resolution of the nine neutral types and the seven presentation roles;
- an already-normalized resource carrying ``resource_type`` verbatim;
- case- / separator-insensitive native-type field aliases;
- unresolvable / typeless / bad-provider inputs → ``None`` (never an omission);
- purity: ``role_of`` returns the same answer for the same input and never
  mutates it (Decision D5 — offline);
- the offline Snapshot readers ``iter_domain_resources`` / ``iter_snapshot_roles``
  over a committed folder written by the real Collector.
"""

from __future__ import annotations

import copy
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.collector import collect
from rule_engine.constants import DIAGRAM_ROLE_TYPES, NEUTRAL_RESOURCE_TYPES, RESOURCE_TYPES
from rule_engine.normalizer import TYPE_MAPPING, resolve_resource_type
from rule_engine.reconcile import (
    SnapshotReadError,
    iter_domain_resources,
    iter_snapshot_roles,
    role_of,
)

_VALID_ROLES = frozenset(RESOURCE_TYPES)


# --------------------------------------------------------------------------- #
# Example resolution — the nine neutral types + seven presentation roles
# --------------------------------------------------------------------------- #

# (native_type, provider, expected_role). Uses native aliases straight from
# profiles/terminology.yaml so the mapper is exercised against real vendor types.
_NEUTRAL_CASES = [
    ("AWS::Lambda::Function", "aws", "serverless_fn"),
    ("aws::s3::bucket", "aws", "object_store"),
    ("aws::rds::dbinstance", "aws", "managed_sql"),
    ("aws::sqs::queue", "aws", "message_queue"),
    ("aws::secretsmanager::secret", "aws", "secrets_store"),
    ("aws::eks::cluster", "aws", "managed_k8s"),
    ("bedrock", "aws", "llm_platform"),
    ("Microsoft.Compute/virtualMachines", "azure", "compute_instance"),
    ("google_storage_bucket", "gcp", "object_store"),
    ("oci_core_vcn", "oci", "network_boundary"),
]

_PRESENTATION_CASES = [
    ("AWS::EC2::Instance", "aws", "compute_instance"),
    ("AWS::EFS::FileSystem", "aws", "file_system"),
    ("cloudfront", "aws", "cdn"),
    ("aws::route53::hostedzone", "aws", "dns"),
    ("aws::wafv2::webacl", "aws", "waf"),
    ("aws::elasticloadbalancingv2::loadbalancer", "aws", "lb"),
    ("elasticache", "aws", "cache"),
]


@pytest.mark.parametrize("native_type, provider, expected", _NEUTRAL_CASES + _PRESENTATION_CASES)
def test_role_of_maps_native_types(native_type: str, provider: str, expected: str) -> None:
    """A native type on any recognised field resolves to its diagram role (Req 2.1)."""
    assert role_of({"native_type": native_type}, provider) == expected
    # The same native type on the generic `type` field resolves identically.
    assert role_of({"type": native_type}, provider) == expected


def test_role_of_covers_every_role_via_terminology() -> None:
    """Every one of the 16 roles is reachable through role_of (Req 2.1)."""
    reached = set()
    for provider, aliases in TYPE_MAPPING.items():
        for alias, role in aliases.items():
            if role_of({"native_type": alias}, provider) == role:
                reached.add(role)
    assert reached == _VALID_ROLES == set(NEUTRAL_RESOURCE_TYPES) | set(DIAGRAM_ROLE_TYPES)


# --------------------------------------------------------------------------- #
# Already-normalized resource_type is honoured verbatim
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", sorted(_VALID_ROLES))
def test_role_of_honours_normalized_resource_type(role: str) -> None:
    """A Snapshot resource already carrying a valid resource_type maps to it."""
    # resource_type is provider-independent once normalized; any provider works.
    assert role_of({"resource_type": role}, "aws") == role
    assert role_of({"ResourceType": role}, "azure") == role


# --------------------------------------------------------------------------- #
# Field-alias tolerance (case / separators)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key",
    ["native_type", "nativeType", "NativeType", "type", "Type", "kind", "Kind"],
)
def test_role_of_field_aliases_are_case_and_separator_insensitive(key: str) -> None:
    """The type field is matched by its flattened spelling (Req 2.1)."""
    assert role_of({key: "s3"}, "aws") == "object_store"


def test_role_of_prefers_resource_type_field_when_present() -> None:
    """An already-normalized resource_type takes precedence over a native type field."""
    resource = {"resource_type": "file_system", "type": "s3"}
    assert role_of(resource, "aws") == "file_system"


# --------------------------------------------------------------------------- #
# Unresolvable / typeless / bad input → None (never an omission, Req 2.5)
# --------------------------------------------------------------------------- #


def test_role_of_unmapped_native_type_is_none() -> None:
    """A native type with no role mapping resolves to None, not an omission."""
    assert resolve_resource_type("aws::glacier::vault", "aws") is None
    assert role_of({"native_type": "aws::glacier::vault"}, "aws") is None


def test_role_of_no_type_field_is_none() -> None:
    """A resource with no type field resolves to None."""
    assert role_of({"name": "my-thing", "region": "us-east-1"}, "aws") is None


def test_role_of_empty_type_value_is_none() -> None:
    """An empty type value is treated as absent → None."""
    assert role_of({"type": ""}, "aws") is None


def test_role_of_unknown_provider_is_none() -> None:
    """An unknown provider never resolves a role."""
    assert role_of({"type": "s3"}, "not-a-provider") is None


@pytest.mark.parametrize("bad", [None, [], "s3", 42, ("type", "s3")])
def test_role_of_non_mapping_is_none(bad: object) -> None:
    """A non-mapping resource resolves to None and never raises."""
    assert role_of(bad, "aws") is None


# --------------------------------------------------------------------------- #
# Purity / offline (Decision D5)
# --------------------------------------------------------------------------- #


def test_role_of_does_not_mutate_input() -> None:
    """role_of is a pure read: the input dict is unchanged (Decision D5)."""
    resource = {"native_type": "AWS::Lambda::Function", "id": "arn:x", "tags": {"a": "b"}}
    before = copy.deepcopy(resource)
    role_of(resource, "aws")
    assert resource == before


# --------------------------------------------------------------------------- #
# Property: role_of returns a valid role or None, deterministically (Req 2.1/2.5)
# --------------------------------------------------------------------------- #

_PROVIDERS_WITH_ALIASES = ("aws", "azure", "gcp", "oci")


@st.composite
def _known_native_type(draw: st.DrawFn, provider: str) -> tuple[str, str]:
    """Draw a (native_type, expected_role) pair from the provider's alias table."""
    aliases = sorted(TYPE_MAPPING[provider].items())
    alias, role = draw(st.sampled_from(aliases))
    return alias, role


@settings(max_examples=200)
@given(data=st.data(), provider=st.sampled_from(_PROVIDERS_WITH_ALIASES))
def test_property_known_alias_maps_to_its_role(data: st.DataObject, provider: str) -> None:
    """Property: every known native alias maps to exactly its declared role.

    Validates: Requirements 2.1
    """
    alias, expected = data.draw(_known_native_type(provider))
    result = role_of({"native_type": alias}, provider)
    assert result == expected
    assert result in _VALID_ROLES
    # Deterministic: a second call on the same input gives the same answer.
    assert role_of({"native_type": alias}, provider) == result


@settings(max_examples=200)
@given(
    junk=st.text(min_size=1, max_size=24).filter(lambda s: s.strip() != ""),
    provider=st.sampled_from(_PROVIDERS_WITH_ALIASES),
)
def test_property_unresolvable_type_is_none_not_a_role(junk: str, provider: str) -> None:
    """Property: a type that does not resolve is None (never a spurious role).

    Validates: Requirements 2.5
    """
    result = role_of({"native_type": junk}, provider)
    # Either it happened to match a real alias (a valid role) or it is None —
    # never anything outside the role vocabulary, and never raised.
    assert result is None or result in _VALID_ROLES
    if resolve_resource_type(junk, provider) is None and junk not in _VALID_ROLES:
        assert result is None


# --------------------------------------------------------------------------- #
# Offline Snapshot readers over a real committed folder (Decision D5)
# --------------------------------------------------------------------------- #


def _write_snapshot(tmp_path):
    """Write a real Snapshot via the Collector; return its folder Path."""
    storage = [
        {"native_type": "aws::s3::bucket", "id": "b1", "name": "b1",
         "boundary": "111122223333", "region": "us-east-1", "tags": {}},
        {"native_type": "AWS::EFS::FileSystem", "id": "fs1", "name": "fs1",
         "boundary": "111122223333", "region": "us-east-1", "tags": {}},
    ]
    compute = [
        {"native_type": "AWS::EC2::Instance", "id": "i-1", "name": "i-1",
         "boundary": "111122223333", "region": "us-east-1", "tags": {}},
        # An unresolvable type — recorded, but must not become an omission.
        {"native_type": "AWS::Glacier::Vault", "id": "v-1", "name": "v-1",
         "boundary": "111122223333", "region": "us-east-1", "tags": {}},
    ]
    enumerators = [
        {"service": "storage", "verb": "list_buckets", "fn": lambda **_: storage},
        {"service": "compute", "verb": "describe_instances", "fn": lambda **_: compute},
    ]
    result = collect(
        "aws", "111122223333", "us-east-1",
        output_root=str(tmp_path), enumerators=enumerators,
    )
    from pathlib import Path

    return Path(result["snapshot_folder"])


def test_iter_domain_resources_reads_committed_json(tmp_path) -> None:
    """iter_domain_resources yields each raw resource from a committed domain file."""
    folder = _write_snapshot(tmp_path)
    resources = list(iter_domain_resources(folder / "storage.json"))
    assert len(resources) == 2
    assert {r["native_type"] for r in resources} == {"aws::s3::bucket", "AWS::EFS::FileSystem"}


def test_iter_snapshot_roles_yields_only_resolvable(tmp_path) -> None:
    """iter_snapshot_roles maps resolvable resources and skips the rest (Req 2.5)."""
    folder = _write_snapshot(tmp_path)
    roles = [role for _res, role in iter_snapshot_roles(folder, "aws")]
    # s3 → object_store, efs → file_system, ec2 → compute_instance; glacier skipped.
    assert sorted(roles) == ["compute_instance", "file_system", "object_store"]


def test_iter_snapshot_roles_skips_failures_file(tmp_path) -> None:
    """A failures.json artefact is not a domain file and is skipped, not errored."""
    folder = _write_snapshot(tmp_path)
    (folder / "failures.json").write_text(
        json.dumps({"failures": [{"service": "x", "reason": "y"}]}), encoding="utf-8"
    )
    # Does not raise and yields the same resolvable roles as before.
    roles = [role for _res, role in iter_snapshot_roles(folder, "aws")]
    assert sorted(roles) == ["compute_instance", "file_system", "object_store"]


def test_iter_domain_resources_bad_json_raises(tmp_path) -> None:
    """An unparsable domain file is a gate error, not a silent empty."""
    bad = tmp_path / "storage.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotReadError):
        list(iter_domain_resources(bad))


def test_iter_domain_resources_wrong_shape_raises(tmp_path) -> None:
    """A JSON file without a 'resources' list is not a domain file → error."""
    wrong = tmp_path / "storage.json"
    wrong.write_text(json.dumps({"service": "storage"}), encoding="utf-8")
    with pytest.raises(SnapshotReadError):
        list(iter_domain_resources(wrong))


def test_iter_domain_resources_missing_file_raises(tmp_path) -> None:
    """A missing file is a gate error, not a silent pass."""
    with pytest.raises(SnapshotReadError):
        list(iter_domain_resources(tmp_path / "nope.json"))
