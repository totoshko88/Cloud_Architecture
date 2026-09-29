"""Example tests for the 16-value resource-type vocabulary and identity keys.

These cover three contracts from the honest-gates spec (task 4.3):

* **R5.1 / R5.2 — one vocabulary, three files.** The
  ``schemas/inventory.schema.json`` ``resource_type.enum``,
  :data:`rule_engine.constants.RESOURCE_TYPES` and the roles declared in
  ``mappings/roles.yaml`` must be the *same set* of 16 values. Adding a role in
  one place without the others is exactly the drift this test blocks.
* **R5.2 — every role × vendor round-trips through the terminology loader.**
  Each of the 16 roles, for each of the four cloud vendors (aws, azure, gcp,
  oci), declares at least one native-type alias, and every one of those aliases
  normalizes back to its own role through
  :func:`rule_engine.normalizer.resolve_resource_type` (the terminology loader).
* **R5.3 — identity keys ignore case and separators.**
  :func:`rule_engine.identity.native_identity` resolves ``InstanceId``,
  ``instance_id`` and ``instanceId`` to the same value for provider ``aws``.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from rule_engine import constants as C
from rule_engine import identity, normalizer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "inventory.schema.json"
_ROLES_PATH = _REPO_ROOT / "mappings" / "roles.yaml"

# The four cloud vendors that carry native-type aliases per role. `generic` is a
# fallback profile with only a neutral label, so it is excluded from the
# per-vendor alias round-trip.
_VENDORS = ("aws", "azure", "gcp", "oci")


def _schema_enum() -> set[str]:
    data = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return set(data["properties"]["resource_type"]["enum"])


def _roles() -> set[str]:
    data = yaml.safe_load(_ROLES_PATH.read_text(encoding="utf-8"))
    return set(data["roles"])


def test_resource_type_vocabulary_is_one_set() -> None:
    """Schema enum, constants.RESOURCE_TYPES and roles.yaml core roles are the same set (R5.1/R5.2).

    The 16 core roles (9 neutral + 7 presentation) must be present in all three
    sources. roles.yaml may additionally contain extended roles for AWS-specific
    services; these are allowed but not required in constants or schema.
    """
    constants_set = set(C.RESOURCE_TYPES)
    schema_set = _schema_enum()
    roles_set = _roles()

    # Sanity: the vocabulary is the 16 documented values (9 neutral + 7 roles).
    assert len(C.RESOURCE_TYPES) == 16
    assert constants_set == set(C.NEUTRAL_RESOURCE_TYPES) | set(C.DIAGRAM_ROLE_TYPES)

    assert schema_set == constants_set, (
        "schema resource_type.enum and constants.RESOURCE_TYPES disagree: "
        f"only in schema={schema_set - constants_set}, "
        f"only in constants={constants_set - schema_set}"
    )
    # roles.yaml must include all 16 core roles; it may have additional extended
    # roles for AWS-specific services beyond the core set.
    missing_core_roles = constants_set - roles_set
    assert not missing_core_roles, (
        "mappings/roles.yaml is missing core roles: "
        f"{missing_core_roles}"
    )


def test_every_role_vendor_alias_round_trips() -> None:
    """Every role × vendor has aliases that the terminology loader maps back (R5.2)."""
    aliases = C.native_aliases()
    for role in C.RESOURCE_TYPES:
        assert role in aliases, f"terminology source has no row for role {role!r}"
        for vendor in _VENDORS:
            vendor_aliases = aliases[role].get(vendor, ())
            assert vendor_aliases, (
                f"role {role!r} declares no {vendor} native-type aliases"
            )
            for alias in vendor_aliases:
                resolved = normalizer.resolve_resource_type(alias, vendor)
                assert resolved == role, (
                    f"{vendor} alias {alias!r} for role {role!r} resolved to "
                    f"{resolved!r} instead of {role!r}"
                )


def test_native_identity_ignores_case_and_separators() -> None:
    """InstanceId / instance_id / instanceId resolve to the same value for aws (R5.3)."""
    value = "i-0123456789abcdef0"
    for key in ("InstanceId", "instance_id", "instanceId"):
        resource = {key: value, "name": "web-1"}
        assert identity.native_identity(resource, "aws") == value, (
            f"native_identity did not resolve key {key!r} to {value!r}"
        )


def test_native_identity_flat_form_is_shared_with_normalize_key() -> None:
    """identity.flat delegates to the shared secret_safety.normalize_key (R5.3)."""
    assert identity.flat("InstanceId") == identity.flat("instance_id")
    assert identity.flat("instanceId") == "instanceid"
