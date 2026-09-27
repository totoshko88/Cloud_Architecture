"""One resource-identity vocabulary for the Collector, Normalizer and Delta (design §7, R5).

Before 1.7.0 the "what makes two resources the same resource?" question was
answered in three subtly different places: ``collector._resource_identity`` (a
provider-specific key list with a ``"resource"`` catch-all that collided every
identity-less resource into one folder), ``normalizer._extract`` (its own
``id`` alias list) and ``delta`` (a boundary/region-blind last-writer-wins).
This module is the single home for the answer.

Two ideas, one shared with :mod:`secret_safety`:

* :func:`flat` is exactly :func:`secret_safety.normalize_key` — a key name is
  lowercased and every character outside ``[a-z0-9]`` is dropped, so
  ``InstanceId``, ``instance_id`` and ``instanceId`` all flatten to
  ``instanceid`` and compare equal (R5.3).
* :data:`IDENTITY_KEYS` maps each provider to its identity keys in priority
  order (flat spelling). :func:`native_identity` returns the value of the
  first key a resource carries, case- and separator-insensitively (R5.5).

When a resource has no native identity key, :func:`content_identity` returns a
stable ``sha256:<12 hex>`` digest of its canonical JSON, so an identity-less
resource still gets a unique, reproducible identity rather than colliding with
its siblings (R5.8).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Tuple

from . import secret_safety

__all__ = [
    "flat",
    "IDENTITY_KEYS",
    "native_identity",
    "content_identity",
]


def flat(name: str) -> str:
    """Flatten a key name for case- and separator-insensitive comparison.

    Delegates to :func:`secret_safety.normalize_key`: ``name`` is lowercased and
    every character outside ``[a-z0-9]`` is removed. ``InstanceId``,
    ``instance_id`` and ``instanceId`` all flatten to ``instanceid`` (R5.3).
    """
    return secret_safety.normalize_key(name)


#: Provider -> identity keys in priority order, each already :func:`flat`.
#: :func:`native_identity` returns the value of the first key a resource
#: carries. The aws list is the design §7 priority order: the most specific,
#: globally-unique identifiers (ARNs) first, then service-specific ids, then the
#: generic ``id`` last. azure uses the ARM ``id``; gcp prefers ``selfLink`` over
#: ``id``; oci prefers ``id`` then ``ocid``; generic (Terraform state) uses
#: ``id`` then ``address``.
IDENTITY_KEYS: Mapping[str, Tuple[str, ...]] = {
    "aws": (
        "arn",
        "functionarn",
        "loadbalancerarn",
        "topicarn",
        "clusterarn",
        "instanceid",
        "filesystemid",
        "dbinstanceidentifier",
        "dbclusteridentifier",
        "cacheclusterid",
        "replicationgroupid",
        "queueurl",
        "vpcid",
        "subnetid",
        "id",
    ),
    "azure": ("id",),
    "gcp": ("selflink", "id"),
    "oci": ("id", "ocid"),
    "generic": ("id", "address"),
}


def native_identity(resource: Mapping[str, Any], provider: str) -> Optional[str]:
    """Return the resource's native identity, or ``None`` when it has none.

    Looks up each key in ``IDENTITY_KEYS[provider]`` in priority order, matching
    the resource's own keys by their :func:`flat` spelling — so ``InstanceId``,
    ``instance_id`` and ``instanceId`` all resolve to the same value (R5.5). The
    first key whose value is a non-empty scalar (string, number or bool) wins;
    an empty string, ``None`` or a non-scalar value is skipped. An unknown
    provider (no entry in :data:`IDENTITY_KEYS`) yields ``None``.
    """
    keys = IDENTITY_KEYS.get(provider)
    if not keys or not isinstance(resource, Mapping):
        return None
    flat_map: dict[str, Any] = {}
    for key, value in resource.items():
        if isinstance(key, str):
            flat_map.setdefault(flat(key), value)
    for wanted in keys:
        if wanted not in flat_map:
            continue
        value = flat_map[wanted]
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str) and value:
            return value
    return None


def content_identity(resource: Mapping[str, Any]) -> str:
    """Return a stable ``sha256:<12 hex>`` digest of the resource's canonical JSON.

    Used as the last-resort identity for a resource with no native identity key
    (R5.8), so it stays unique and reproducible instead of colliding with its
    siblings. The canonical JSON sorts keys and drops insignificant whitespace,
    so the same resource always yields the same digest regardless of key order.
    """
    canonical = json.dumps(
        resource,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"
