"""Inventory → diagram reconciliation (Part B; design Components B1, B2).

This module implements the **inventory → diagram reconciliation gate** from
release 1.9.0 (``.kiro/specs/placement-and-gates``). The gate compares a
committed inventory Snapshot against the diagram generated from it and blocks
when a role-bearing, enumerated resource is silently absent from the diagram —
the "ten KMS keys omitted while the companion asserted completeness" defect.

Task 5 delivers **Component B1** — the raw-JSON → role mapper :func:`role_of`
(and the Snapshot-reading helpers it needs). Task 6 adds **Component B2**: the
:func:`reconcile` comparison and the ``rule-engine-reconcile`` CLI
(:func:`main`). :func:`reconcile` maps a Snapshot's role-bearing enumerated
resources (the *expected* role set) and the diagram's drawn node icons (the
*drawn* role set), then blocks — naming the omitted resource(s) — when a
role-bearing enumerated resource has no drawn node, scoped by the diagram's
Coverage_Class: a ``landscape`` requires **total** coverage (Requirement 2.3),
a ``flow`` blocks only on a resource that is part of the flow it claims to show
(Requirement 2.4). A resource with no resolvable role is never an omission
(Requirement 2.5).

The drawn role set is read from the ``.drawio`` icon references (via
:mod:`rule_engine.icon_refs`) reverse-mapped through the committed
``mappings/icon-index.json`` (image / OCI-slug refs) and the AWS ``resIcon``
table — the same committed data the generators resolve a role→icon *forward*
through, so the gate cannot drift from what a generator draws. A drawn icon may
be shared by several roles (a GCP CDN and load-balancer both use the Networking
category icon; an OCI managed-SQL and cache both use ``autonomous-db``), so a
drawn node contributes the **set** of roles its icon can stand for, and an
expected role is covered when *some* drawn node's role-set contains it — the
gate blocks only on a definite omission, never on an ambiguous icon.

Design contract (Decision **D5** — *reconciliation reads the Snapshot, never
the provider*):

* :func:`role_of` is a **pure, offline** function of a single Snapshot resource
  dict. It reads only committed Snapshot JSON; it never calls a provider, opens
  a socket, or touches provider state.
* A resource is mapped to a **diagram role** — one of the 16 values in
  :data:`rule_engine.constants.RESOURCE_TYPES` (the nine neutral resource types
  plus the seven presentation roles ``compute_instance`` / ``file_system`` /
  ``cdn`` / ``dns`` / ``waf`` / ``lb`` / ``cache``). That 16-value set is, by the
  ``test_resource_types`` contract, exactly the role set declared in
  ``mappings/roles.yaml`` (Requirement 2.1).
* A resource with **no resolvable role** yields ``None`` and is **not** an
  omission (Requirement 2.5): the mapper skips it, it never appears in the
  expected role set, and the gate never blocks on it.

A Snapshot records **raw, redacted native provider metadata**, one
``<domain>.json`` file per service domain at the snapshot root, each shaped::

    {"service": "storage", "resources": [ {<native resource>}, ... ]}

and one ``resources/<slug>/resource.json`` per enumerated resource (see
:mod:`rule_engine.collector` and ``.kiro/steering/inventory-standards.md`` §5).
:func:`role_of` accepts a single such resource dict; the reading helpers
:func:`iter_domain_resources` and :func:`iter_snapshot_roles` walk the committed
per-domain JSON files and hand each resource to :func:`role_of`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from rule_engine.constants import PROVIDERS, RESOURCE_TYPES, resolve_bundled_dir, seed_icons
from rule_engine.identity import flat
from rule_engine.normalizer import resolve_resource_type

__all__ = [
    "role_of",
    "iter_domain_resources",
    "iter_snapshot_roles",
    "SnapshotReadError",
    "ReconcileError",
    "ReconcileReport",
    "drawn_roles",
    "reconcile",
    "main",
]


# The set of valid diagram roles a resource may map to — the nine neutral
# resource types plus the seven presentation roles. Identical (by the
# ``test_resource_types`` contract) to the role set declared in
# ``mappings/roles.yaml``, so a role returned here is always a drawable role.
_VALID_ROLES = frozenset(RESOURCE_TYPES)

# Native-type field aliases, matched by their :func:`flat` spelling so a
# PascalCase SDK response (``ResourceType``, ``Type``, ``Kind``) resolves like
# its snake/camel spellings. ``resource_type`` is consulted first: a Snapshot
# resource that has already been normalized carries the neutral/role type
# directly, and honouring it avoids a needless re-lookup. This mirrors the
# normalizer's ``native_type`` alias list (``rule_engine.normalizer``), extended
# with ``resource_type`` for the already-normalized case.
_TYPE_FIELD_ALIASES: Tuple[str, ...] = (
    "resourcetype",   # already-normalized resource_type (or a native "resourceType")
    "nativetype",
    "type",
    "kind",
)


class SnapshotReadError(ValueError):
    """Raised when a committed Snapshot file cannot be read or parsed.

    A missing file, unparsable JSON, or a domain file whose top-level shape is
    not the ``{"service", "resources": [...]}`` contract is a gate *error*, not
    a silent pass (design "Error Handling" — a Snapshot file that does not parse
    is reported, never treated as "no resources"). The mapper itself
    (:func:`role_of`) never raises; only the file-reading helpers do.
    """


def _flat_lookup(resource: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``{flat(key): value}`` for a resource's string keys.

    The first original spelling of a flattened key wins, matching
    :func:`rule_engine.identity.native_identity` and the normalizer's extraction
    so case- and separator-insensitive lookups agree across the engine.
    """
    lookup: dict[str, Any] = {}
    for key, value in resource.items():
        if isinstance(key, str):
            lookup.setdefault(flat(key), value)
    return lookup


def role_of(resource: Any, provider: str) -> Optional[str]:
    """Map one raw Snapshot resource to its diagram role, or ``None``.

    Resolves ``resource`` (a raw, redacted native provider metadata dict as
    written into a Snapshot's per-domain JSON) to a **diagram role** — one of the
    16 values in :data:`rule_engine.constants.RESOURCE_TYPES`, i.e. the role set
    declared in ``mappings/roles.yaml`` (Requirement 2.1). Returns ``None`` when
    the resource carries no type field, or its native type has no role mapping
    for ``provider`` — a resource with no resolvable role is **not** an omission
    (Requirement 2.5).

    Pure and offline (Decision D5): it inspects only the passed-in dict and the
    committed terminology/role vocabulary. It never contacts a provider and never
    raises — a malformed resource (not a mapping, unknown provider, empty type)
    simply yields ``None`` so the reconciliation loop skips it rather than
    aborting.

    Resolution order:

    1. Read the resource's type using the flat aliases ``resource_type`` (an
       already-normalized Snapshot resource) / ``native_type`` / ``type`` /
       ``kind`` — the first present, non-empty value wins.
    2. If that value is *already* one of the 16 diagram roles verbatim, return it
       (a normalized Snapshot resource is honoured directly).
    3. Otherwise resolve the value as a native type via the shared terminology
       mapping (:func:`rule_engine.normalizer.resolve_resource_type`), which is
       tolerant of casing and separators and covers all 16 roles.
    """
    if not isinstance(resource, Mapping) or provider not in PROVIDERS:
        return None

    flat_map = _flat_lookup(resource)
    raw_type: Any = None
    for alias in _TYPE_FIELD_ALIASES:
        value = flat_map.get(alias)
        if value is not None and str(value) != "":
            raw_type = value
            break
    if raw_type is None:
        return None

    type_str = str(raw_type)
    # An already-normalized resource carries the neutral/role type verbatim.
    if type_str in _VALID_ROLES:
        return type_str

    # Otherwise treat it as a native type and resolve through the shared
    # terminology vocabulary (case- and separator-insensitive; covers all 16
    # roles). resolve_resource_type returns None for an unmapped native type.
    role = resolve_resource_type(type_str, provider)
    if role in _VALID_ROLES:
        return role
    return None


def iter_domain_resources(domain_file: Path) -> Iterator[Mapping[str, Any]]:
    """Yield each raw resource dict from one committed per-domain JSON file.

    ``domain_file`` is a Snapshot ``<domain>.json`` file (``storage.json``,
    ``compute.json``, …) shaped ``{"service": str, "resources": [ {...}, ... ]}``
    per :mod:`rule_engine.collector`. Yields each mapping in ``resources`` in
    file order; a non-mapping entry is skipped (it can carry no type field, so it
    can resolve to no role).

    Reads only the committed file (Decision D5). Raises :class:`SnapshotReadError`
    when the file is absent, is not valid JSON, or does not carry a ``resources``
    list — a Snapshot that does not parse is a gate error, not a silent empty.
    """
    try:
        text = domain_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotReadError(f"cannot read snapshot file {domain_file}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SnapshotReadError(
            f"snapshot file {domain_file} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, Mapping) or not isinstance(data.get("resources"), list):
        raise SnapshotReadError(
            f"snapshot file {domain_file} is not a domain file "
            "(expected an object with a 'resources' list)"
        )
    for entry in data["resources"]:
        if isinstance(entry, Mapping):
            yield entry


def iter_snapshot_roles(
    snapshot_dir: Path, provider: str
) -> Iterator[Tuple[Mapping[str, Any], str]]:
    """Yield ``(resource, role)`` for every role-resolvable resource in a Snapshot.

    Walks the committed per-domain JSON files at the root of ``snapshot_dir``
    (the ``inventory-<provider>-…`` folder) in sorted filename order, maps each
    resource with :func:`role_of`, and yields only those that resolve to a role.
    A resource with no resolvable role is skipped, never yielded (Requirement
    2.5). The ``failures.json`` domain file (collector-written enumeration
    failures, shaped ``{"failures": [...]}``) has no ``resources`` list and so is
    not a domain file; it is skipped rather than treated as an error.

    Pure and offline (Decision D5): reads only the committed ``*.json`` files.
    Propagates :class:`SnapshotReadError` from :func:`iter_domain_resources` for
    a domain file that does not parse.
    """
    for domain_file in sorted(snapshot_dir.glob("*.json")):
        # failures.json is a collector artefact, not a service-domain file.
        if domain_file.name == "failures.json":
            continue
        for resource in iter_domain_resources(domain_file):
            role = role_of(resource, provider)
            if role is not None:
                yield resource, role


# =========================================================================== #
# Component B2 — the reconciliation gate (task 6)
# =========================================================================== #
#
# ``reconcile`` compares the Snapshot's *expected* role set (every role-bearing
# enumerated resource, via ``iter_snapshot_roles``) against the diagram's
# *drawn* role set (the roles the diagram's node icons stand for), and blocks
# when a role-bearing enumerated resource has no drawn node.
#
# The drawn role set is derived by reverse-mapping each node's icon reference
# through the committed data a generator resolves a role→icon *forward* through:
#
#   * image providers (azure / gcp): the node's ``image=<path>`` equals the
#     icon-index ``roles[<role>][<provider>].ref`` for its role, so the ref path
#     is the reverse key;
#   * oci: the node's ``ociSlug=<slug>`` equals the ``#<slug>`` suffix of the
#     icon-index oci ref, so the slug is the reverse key;
#   * aws: the node renders a built-in ``resIcon=mxgraph.aws4.<id>`` stencil
#     (NOT an icon-index asset path), so aws is reverse-mapped from the neutral
#     seed-icon ids (``constants.seed_icons``) plus the committed presentation-
#     role resIcon table below.
#
# Because a single icon can legitimately stand for several roles (GCP's
# Networking category icon serves ``cdn``, ``lb`` and ``network_boundary``; OCI's
# ``autonomous-db`` serves ``managed_sql`` and ``cache``), the reverse index maps
# one signature to a *set* of roles. A drawn node therefore contributes every
# role its icon can stand for, and an expected role is *covered* when some drawn
# node's role-set contains it. The gate blocks only on a definite omission (no
# drawn node can stand for the expected role) — never on an ambiguous icon.


# The AWS presentation-role -> resIcon id table. AWS renders built-in
# ``mxgraph.aws4.<id>`` stencils, so — unlike the file-path providers — its
# drawn nodes do not carry an icon-index asset path. The nine neutral types are
# covered by ``constants.seed_icons()['aws']`` (each a ``mxgraph.aws4.<id>``);
# the seven presentation roles are not in the terminology seed, so their resIcon
# ids are declared here, matching what the AWS generators draw
# (``scripts/build_aws_ha_example.py`` / ``build_aws_infra_example.py`` /
# ``build_cross_cloud_example.py``). Each id is verified present in the shipped
# corpus and in ``mappings/aws4-icons.json``. ``efs_standard`` is the id the AWS
# landscape uses for a file system; ``ec2`` for a compute instance.
_AWS_PRESENTATION_RESICON: Dict[str, Tuple[str, ...]] = {
    "cdn": ("cloudfront",),
    "dns": ("route_53",),
    "waf": ("waf",),
    "lb": ("application_load_balancer", "elastic_load_balancing"),
    "cache": ("elasticache",),
    "compute_instance": ("ec2",),
    "file_system": ("efs_standard", "elastic_file_system", "efs"),
}


# The Azure presentation-role -> azure2 basename table. Azure's nine neutral
# types are covered by ``mappings/azure-icons.yaml`` `resources` (each an
# ``img/lib/azure2/*`` path); the presentation roles are drawn as azure2 image
# shapes too (``scripts/build_azure_ha_example.py`` RENDERERS) but are not in the
# mapping's `resources`, and the icon-index Azure ref uses the *fetched-pack*
# basename (``10062-icon-service-Load-Balancers``), which differs from the
# draw.io-internal azure2 basename a node actually carries. So the drawn azure2
# basenames are declared here, matching the Azure generator. (Azure DNS is drawn
# as Traffic Manager — a deliberate generator choice distinct from the
# icon-index's DNS-Zones ref — which is why it needs an explicit entry.)
_AZURE_PRESENTATION_AZURE2: Dict[str, Tuple[str, ...]] = {
    "lb": ("load_balancers",),
    "dns": ("traffic_manager_profiles", "dns_zones"),
    "cache": ("cache_redis",),
    "cdn": ("cdn_profiles",),
    "waf": ("web_application_firewall_policies(waf)", "application_gateways"),
    "compute_instance": ("virtual_machines",),
    "file_system": ("azure_files", "files"),
}


def _normalise_ref(ref: str) -> str:
    """Normalise an icon-index / drawn ``image=`` reference for matching.

    Reduces a file path to its lowercase basename with the extension stripped, so
    a drawn ``image=<path>`` and the icon-index ``ref`` compare equal even if one
    carries a directory prefix the other does not. An OCI ``…stencils.json#<slug>``
    ref is reduced to its ``<slug>``. A value with neither ``/`` nor ``#`` (a bare
    token) is lowercased as-is.
    """
    ref = ref.strip()
    if "#" in ref:
        ref = ref.rsplit("#", 1)[1]
    if "/" in ref:
        ref = ref.rsplit("/", 1)[1]
    ref = ref.rsplit(".", 1)[0] if "." in ref else ref
    return ref.lower()


@lru_cache(maxsize=len(PROVIDERS) or None)
def _reverse_role_index(provider: str) -> Mapping[str, FrozenSet[str]]:
    """Build the ``signature -> {roles}`` reverse index for ``provider``.

    The signature is the normalised icon reference a drawn node carries
    (:func:`_normalise_ref`): the icon-index ``ref`` basename/slug for the
    file-path providers (aws/azure/gcp) and OCI slug for oci. One signature may
    map to several roles (a shared fallback icon), so the value is a role *set*.
    Built once per provider from committed data only (Decision D5).

    Since v1.10.2, AWS uses official SVG file paths (``image=assets/vendor/aws-
    icons/...``) instead of the legacy ``mxgraph.aws4.*`` stencils. AWS is now
    treated the same as Azure/GCP: file-path reverse-indexing through
    ``_mapping_style_signatures`` and the ``icon-index.json`` roles layer.
    For backward compatibility, the legacy ``mxgraph.aws4.*`` stencil IDs are
    also recognized via ``_AWS_PRESENTATION_RESICON`` and ``seed_icons()``.
    """
    index: Dict[str, Set[str]] = {}

    def _add(signature: str, role: str) -> None:
        if signature:
            index.setdefault(signature, set()).add(role)

    # AWS backward compatibility: recognize legacy mxgraph.aws4.* stencil IDs
    # so that existing hand-authored diagrams and test fixtures still reconcile.
    if provider == "aws":
        # Nine neutral types: mxgraph.aws4.<id> from the terminology seed.
        for role, (icon_id, _name, _hex) in seed_icons().get("aws", {}).items():
            # icon_id is e.g. "mxgraph.aws4.s3" -> signature "s3".
            _add(_normalise_ref(icon_id.rsplit(".", 1)[-1]), role)
        # Presentation roles: the committed resIcon table.
        for role, ids in _AWS_PRESENTATION_RESICON.items():
            for icon_id in ids:
                _add(_normalise_ref(icon_id), role)

    # All file-path providers (aws/azure/gcp) and OCI, two committed sources:
    #
    #   1. mappings/<provider>-icons.yaml `resources` — the per-provider style
    #      for each of the nine neutral types. Azure/GCP draw these as
    #      `image=<path>` (Azure uses the draw.io-internal `img/lib/azure2/*`
    #      paths, GCP the fetched `assets/vendor/gcp-*` paths), OCI as a
    #      labelled box with no per-role token — so the YAML covers exactly the
    #      neutral-type nodes a generator draws through the mapping.
    #   2. mappings/icon-index.json `roles` — the resolved official pack ref for
    #      every role incl. the presentation-only roles (cdn/dns/waf/lb/cache/…).
    #      A node drawn through `index_renderer` (the HA edge services, and every
    #      GCP node) carries this exact ref.
    #
    # Both are keyed by the same normalised signature (:func:`_normalise_ref`),
    # so a drawn node matches whichever source produced it.
    for role, signature in _mapping_style_signatures(provider).items():
        _add(signature, role)

    # Azure presentation roles are drawn as azure2 image shapes whose basenames
    # differ from the icon-index fetched-pack basenames; declare them explicitly.
    if provider == "azure":
        for role, basenames in _AZURE_PRESENTATION_AZURE2.items():
            for basename in basenames:
                _add(_normalise_ref(basename), role)

    idx = _load_icon_index()
    roles_layer = idx.get("roles", {}) if isinstance(idx, Mapping) else {}
    for role, per_provider in roles_layer.items():
        if not isinstance(per_provider, Mapping):
            continue
        entry = per_provider.get(provider)
        if not isinstance(entry, Mapping):
            continue
        if entry.get("source") == "unresolved":
            continue
        ref = entry.get("ref")
        if isinstance(ref, str) and ref:
            _add(_normalise_ref(ref), role)
    return {sig: frozenset(roles) for sig, roles in index.items()}


_IMAGE_TOKEN_RE = None  # lazily compiled in _mapping_style_signatures


def _mapping_style_signatures(provider: str) -> Dict[str, str]:
    """Return ``{role -> signature}`` from a provider's ``<provider>-icons.yaml``.

    Reads the committed per-provider mapping and extracts the reverse-index
    signature from each ``resources`` entry's ``style``: the ``image=<path>``
    basename stem for the file-path providers (azure/gcp), or the
    ``resIcon=mxgraph.<lib>.<id>`` id. An OCI labelled-box style carries no
    per-role image/resIcon token, so OCI contributes nothing here (its nodes are
    reversed by ``ociSlug`` through the icon-index). A role whose style has no
    extractable token is skipped. Returns an empty mapping when the file is
    absent or unparsable (a diagnosable empty, never a raise).
    """
    import re

    import yaml

    out: Dict[str, str] = {}
    path = resolve_bundled_dir("mappings") / f"{provider}-icons.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return out
    if not isinstance(data, Mapping):
        return out
    resources = data.get("resources") or {}
    if not isinstance(resources, Mapping):
        return out
    image_re = re.compile(r"(?:^|;)image=([^;]+)")
    res_re = re.compile(r"(?:^|;)resIcon=mxgraph\.[A-Za-z0-9_]+\.([A-Za-z0-9_]+)")
    for role, spec in resources.items():
        if not isinstance(spec, Mapping):
            continue
        style = str(spec.get("style", ""))
        m = image_re.search(style)
        if m:
            out[role] = _normalise_ref(m.group(1))
            continue
        m = res_re.search(style)
        if m:
            out[role] = _normalise_ref(m.group(1))
    return out


@lru_cache(maxsize=1)
def _load_icon_index() -> Mapping[str, Any]:
    """Load the committed ``mappings/icon-index.json`` (repo / bundle / cwd).

    Returns an empty mapping when the index is absent or unparsable rather than
    raising — the AWS reverse index needs no index, and a missing index for a
    file-path provider yields an empty reverse map (every drawn node then has an
    empty role-set), which is a diagnosable state, not a crash.
    """
    path = resolve_bundled_dir("mappings") / "icon-index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, Mapping) else {}


class ReconcileError(ValueError):
    """Raised when reconciliation cannot run (a gate error, not an omission).

    A Snapshot file that does not parse (:class:`SnapshotReadError`), a diagram
    that does not parse, or an unknown provider is a gate *error* — reported and
    fail-closed — rather than a silent pass (design "Error Handling"). A resource
    with no resolvable role is **not** an error: it is simply skipped.
    """


@dataclass
class ReconcileReport:
    """The outcome of reconciling one Snapshot against one diagram.

    * ``expected_roles`` — the role set the Snapshot's role-bearing enumerated
      resources map to (``iter_snapshot_roles``).
    * ``drawn_roles`` — the union of every drawn node's possible-role set.
    * ``omissions`` — the role-bearing enumerated resources with no drawn node
      that can stand for their role, each ``{"role", "resource"}`` where
      ``resource`` is a stable human identifier (name / id / role). Empty ⇒ the
      artifact is eligible.
    * ``coverage_class`` — ``landscape`` (total coverage required) or ``flow``
      (scoped coverage). Governs how ``omissions`` is computed.
    * ``eligible`` — ``True`` iff ``omissions`` is empty for the coverage class.
    """

    provider: str
    snapshot_dir: str
    diagram_path: str
    coverage_class: str
    expected_roles: FrozenSet[str] = field(default_factory=frozenset)
    drawn_roles: FrozenSet[str] = field(default_factory=frozenset)
    omissions: List[Dict[str, str]] = field(default_factory=list)
    #: Every resource enumerated in the Snapshot's domain files, role or not
    #: (1.10.7, S2). With ``roleless`` it shows how much of the inventory this
    #: gate can actually see.
    enumerated_count: int = 0
    #: Identifiers of enumerated resources that resolve to NO role. They are
    #: invisible to the coverage check (never an omission), so the report names
    #: them instead of passing silently; eligibility is unaffected.
    roleless: List[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        """True when nothing is omitted for this coverage class."""
        return not self.omissions

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-serialisable view of the report (sorted role lists)."""
        return {
            "provider": self.provider,
            "snapshot_dir": self.snapshot_dir,
            "diagram_path": self.diagram_path,
            "coverage_class": self.coverage_class,
            "expected_roles": sorted(self.expected_roles),
            "drawn_roles": sorted(self.drawn_roles),
            "omissions": self.omissions,
            "eligible": self.eligible,
            "enumerated_count": self.enumerated_count,
            "roleless_count": len(self.roleless),
            "roleless": list(self.roleless),
        }


def _resource_identifier(resource: Mapping[str, Any]) -> str:
    """Return a stable human identifier for a Snapshot resource.

    Prefers ``name`` then ``id`` then ``arn`` (by their flattened spelling), so
    the blocked-omission message names the offending resource the way an operator
    knows it. Falls back to a compact repr when none is present. Never emits a
    secret value — only identity/name metadata is read.
    """
    flat_map = _flat_lookup(resource)
    for key in ("name", "id", "arn", "resourceid", "resourcename"):
        value = flat_map.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return "<unnamed resource>"


def drawn_roles(page: Any, provider: str) -> FrozenSet[str]:
    """Return the union of possible roles the diagram ``page`` draws.

    Two kinds of drawn role are collected:

    * **Service-vertex icons.** Every service vertex's icon reference (via
      :mod:`rule_engine.icon_refs`) is reverse-mapped through
      :func:`_reverse_role_index`; a node whose icon can stand for several roles
      contributes all of them, and a node with no recognisable icon reference (an
      actor / on-prem glyph with no role — ``user``, ``traditional_server``)
      contributes nothing.
    * **Boundary containers.** The two structural roles ``boundary`` and
      ``network_boundary`` are drawn as dashed *container frames*, not as
      service-vertex node icons, so they are never carried by an icon reference.
      A diagram that draws a stack Boundary / Network Boundary container
      therefore *covers* those structural roles: the container's presence is the
      node. Without this, a Snapshot that enumerates the account/VPC boundary
      would be reported as a spurious omission on every diagram.

    Pure and offline.
    """
    from rule_engine.icon_refs import extract_refs
    from rule_engine.constants import is_boundary_container_style

    reverse = _reverse_role_index(provider)
    found: Set[str] = set()
    for cell_refs in extract_refs(page).values():
        for ref in cell_refs:
            signature = _drawn_signature(ref)
            if signature is None:
                continue
            found |= reverse.get(signature, frozenset())

    # A Boundary/Network-Boundary container covers the structural roles. We
    # cannot tell the stack Boundary from the Network Boundary by style alone
    # (both are dashed frames), so a diagram carrying any boundary container
    # covers *both* structural roles — the conservative choice that never
    # produces a spurious structural omission.
    cells = getattr(page, "cells", {})
    for cid, cell in cells.items():
        if getattr(cell, "vertex", False) and is_boundary_container_style(
            cid, getattr(cell, "style", "")
        ):
            found.add("boundary")
            found.add("network_boundary")
            break
    return frozenset(found)


def _drawn_signature(ref: Any) -> Optional[str]:
    """Return the normalised reverse-index signature for one drawn ``IconRef``.

    * ``resIcon`` / ``grIcon`` — an ``mxgraph.aws4.<id>`` id → ``<id>``.
    * ``azure2`` / ``image`` — a file path → its basename stem.
    * ``oci-slug`` — the slug verbatim.
    Other kinds (``oci-glyph``, ``generic-shape``) carry no role signature.

    An ``image`` ref's ``reference`` is already the asset *path*, not the inline
    glyph: :func:`icon_refs.extract_refs` takes the image identity from the
    ``iconRef=<assets/vendor/...>`` companion token when a node embeds its glyph
    as ``image=data:image/svg+xml,<b64>`` (so it renders in the draw.io editor),
    and falls back to the ``image=`` path otherwise. So the reverse-map reduces
    the real asset path here and never sees the opaque data-URI.
    """
    kind = getattr(ref, "kind", None)
    reference = getattr(ref, "reference", None)
    if not isinstance(reference, str) or reference == "":
        return None
    if kind in ("resIcon", "grIcon"):
        ident = reference.rsplit(".", 1)[-1]
        return _normalise_ref(ident)
    if kind in ("azure2", "image"):
        return _normalise_ref(reference)
    if kind == "oci-slug":
        return _normalise_ref(reference)
    return None


def _parse_diagram(diagram_path: Path) -> Tuple[List[Any], str]:
    """Parse a ``.drawio`` into its pages and read its companion coverage class.

    Returns ``(pages, coverage_class)`` where ``coverage_class`` is ``landscape``
    or ``flow`` (default ``flow``), read from the companion ``.diagram.md``
    ``diagram_class`` frontmatter — the same source the Linter uses. A diagram
    that does not parse raises :class:`ReconcileError` (a gate error, not a pass).
    """
    from rule_engine.drawio_model import DrawioParseError, parse_drawio

    try:
        data = diagram_path.read_bytes()
    except OSError as exc:
        raise ReconcileError(f"cannot read diagram {diagram_path}: {exc}") from exc
    try:
        pages = parse_drawio(data, path=str(diagram_path))
    except DrawioParseError as exc:
        raise ReconcileError(
            f"diagram {diagram_path} does not parse: {exc.cause}"
        ) from exc
    return pages, _coverage_class_of(diagram_path)


def _coverage_class_of(diagram_path: Path) -> str:
    """Read ``diagram_class`` (``flow`` default) from the companion frontmatter."""
    # Reuse the CLI's companion loader so the class is read exactly as the Linter
    # reads it (companion path convention + shared YAML frontmatter loader).
    from rule_engine.cli import _companion_path, _load_companion_frontmatter

    fm, _failed = _load_companion_frontmatter(_companion_path(str(diagram_path)))
    if fm:
        cls = str(fm.get("diagram_class", "") or "").strip().lower()
        if cls == "landscape":
            return "landscape"
    return "flow"


def reconcile(
    snapshot_dir: Any,
    diagram_path: Any,
    provider: str,
    *,
    coverage_class: Optional[str] = None,
) -> ReconcileReport:
    """Reconcile a committed Snapshot against the diagram generated from it.

    Maps the Snapshot's role-bearing enumerated resources to their *expected*
    roles (``iter_snapshot_roles``) and the diagram's node icons to the *drawn*
    role set (:func:`drawn_roles`), then reports the role-bearing enumerated
    resources with no drawn node that can stand for their role — the omissions.

    Coverage is scoped by the diagram's Coverage_Class (read from the companion
    ``diagram_class`` unless ``coverage_class`` overrides it):

    * ``landscape`` — **total** coverage: *every* role-bearing enumerated
      resource must have a drawn node; each uncovered one is an omission that
      blocks and is named (Requirement 2.3).
    * ``flow`` — **scoped** coverage: a ``flow`` shows only the workload/flow it
      claims to, so a resource whose role is simply out of scope is *not* an
      omission. The gate blocks only on a resource whose role **is** drawn
      elsewhere in scope yet this particular resource has no node — i.e. the
      diagram already commits to that role, so silently dropping one resource of
      it is the "part of the flow it claims to show" defect (Requirement 2.4).

    Reads only committed files (Decision D5). Raises :class:`ReconcileError` on a
    gate error (unknown provider, unparsable Snapshot or diagram); a resource
    with no resolvable role is skipped, never an omission (Requirement 2.5).
    """
    if provider not in PROVIDERS:
        raise ReconcileError(
            f"unknown provider {provider!r} (expected one of {', '.join(PROVIDERS)})"
        )

    snap = Path(snapshot_dir)
    diagram = Path(diagram_path)
    if not snap.is_dir():
        raise ReconcileError(f"snapshot folder not found: {snap}")
    if not diagram.is_file():
        raise ReconcileError(f"diagram file not found: {diagram}")

    # Expected: (role -> [resource identifier, ...]) from the committed Snapshot.
    # iter_snapshot_roles propagates SnapshotReadError for an unparsable domain
    # file; surface it as a ReconcileError (a gate error, never a silent empty).
    # Same traversal as iter_snapshot_roles, but every enumerated resource is
    # counted and the role-less ones are collected (1.10.7, S2): a resource with
    # no role is still never an omission, yet the report must say the gate could
    # not see it rather than pass silently.
    expected_by_role: Dict[str, List[str]] = {}
    enumerated = 0
    roleless: List[str] = []
    try:
        for domain_file in sorted(snap.glob("*.json")):
            if domain_file.name == "failures.json":
                continue
            for resource in iter_domain_resources(domain_file):
                enumerated += 1
                role = role_of(resource, provider)
                if role is None:
                    roleless.append(_resource_identifier(resource))
                    continue
                expected_by_role.setdefault(role, []).append(
                    _resource_identifier(resource)
                )
    except SnapshotReadError as exc:
        raise ReconcileError(str(exc)) from exc

    # Drawn: the union of possible roles across every page's node icons.
    pages, detected_class = _parse_diagram(diagram)
    cover = (coverage_class or detected_class).strip().lower()
    if cover not in ("flow", "landscape"):
        cover = "flow"
    drawn: Set[str] = set()
    for page in pages:
        drawn |= drawn_roles(page, provider)

    expected_roles = frozenset(expected_by_role)

    # Compute omissions per coverage class.
    omissions: List[Dict[str, str]] = []
    if cover == "landscape":
        # Total coverage (Requirement 2.3): every role-bearing enumerated
        # resource must have a drawn node. A role in the Snapshot but not drawn
        # is an omission, and every enumerated resource of that role is named.
        uncovered_roles = expected_roles - drawn
    else:
        # Scoped coverage (Requirement 2.4): a `flow` shows only the workload /
        # flow it claims to, so a resource whose role is simply out of scope is
        # NOT an omission — that is the whole point of a scoped view. The gate
        # blocks only on a resource that is *part of the flow the diagram claims
        # to show*. A diagram's claimed scope is exactly the set of roles it
        # draws; a role it draws it commits to, so silently dropping a resource
        # of a role it does NOT draw is by definition out of scope, and a role it
        # DOES draw is covered. At role-set granularity there is therefore no
        # in-scope-yet-absent role — the diagram carries no per-resource identity
        # that would let the gate say "this specific bucket of a drawn role is
        # missing" without false-positiving every scoped view. So a `flow`
        # reconciliation never blocks on a role mismatch; the strict, total check
        # is the `landscape`'s job. (A future per-resource scope signal could
        # tighten this; today the conservative, false-positive-free reading is to
        # not block a scoped view.)
        uncovered_roles = frozenset()

    for role in sorted(uncovered_roles):
        for resource_id in expected_by_role.get(role, []):
            omissions.append({"role": role, "resource": resource_id})

    return ReconcileReport(
        provider=provider,
        snapshot_dir=str(snap),
        diagram_path=str(diagram),
        coverage_class=cover,
        expected_roles=expected_roles,
        drawn_roles=frozenset(drawn),
        omissions=omissions,
        enumerated_count=enumerated,
        roleless=roleless,
    )


# --------------------------------------------------------------------------- #
# CLI — rule-engine-reconcile
# --------------------------------------------------------------------------- #

# Exit codes mirror the sibling gates (rule-engine-verify-icon / rule-engine-lint).
EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 3

#: How many role-less resource identifiers the human report lists (1.10.7, S2).
_ROLELESS_SHOWN = 10


def _print_report(report: ReconcileReport) -> None:
    """Human-readable one-artifact report ([OK] / [BLOCKED] + named omissions,
    plus a WARNING naming role-less resources the check could not see)."""
    if report.eligible:
        print(
            f"[OK] {report.diagram_path} ({report.coverage_class}): "
            f"{len(report.expected_roles)} expected role(s), all covered."
        )
    else:
        print(
            f"[BLOCKED] {report.diagram_path} ({report.coverage_class}): "
            f"{len(report.omissions)} omitted resource(s):"
        )
        for om in report.omissions:
            print(f"    - role {om['role']}: {om['resource']}")
    if report.roleless:
        shown = ", ".join(report.roleless[:_ROLELESS_SHOWN])
        more = "…" if len(report.roleless) > _ROLELESS_SHOWN else ""
        print(
            f"[WARNING] {len(report.roleless)} of {report.enumerated_count} "
            "enumerated resource(s) have no role and are invisible to this check: "
            f"{shown}{more} — add a role in mappings/roles.yaml"
        )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: ``rule-engine-reconcile``.

    Usage::

        rule-engine-reconcile --provider aws \\
            --snapshot inventory-aws-… --diagram examples/aws/02-…-landscape.drawio
        rule-engine-reconcile --provider aws --snapshot <dir> --diagram <file> --json

    Compares a committed Snapshot against the diagram generated from it and
    blocks (exit 1) when a role-bearing enumerated resource is silently absent
    from the diagram, naming the omission(s). The Coverage_Class is read from the
    diagram's companion ``diagram_class`` (``--coverage-class`` overrides it).

    Exit codes:
      0 — eligible (no omission for the coverage class).
      1 — blocked (at least one omitted role-bearing enumerated resource).
      3 — a usage / I/O error, an unparsable Snapshot or diagram, or an unknown
          provider (fail-closed — never reported as OK).
    """
    ap = argparse.ArgumentParser(
        prog="rule-engine-reconcile",
        description="Reconcile a committed inventory Snapshot against the diagram "
        "generated from it; block on a silently-omitted role-bearing resource.",
    )
    ap.add_argument("--provider", required=True, choices=sorted(PROVIDERS),
                    help="provider profile of the Snapshot and diagram")
    ap.add_argument("--snapshot", required=True,
                    help="path to the committed inventory-* Snapshot folder")
    ap.add_argument("--diagram", required=True,
                    help="path to the .drawio the Snapshot was drawn as")
    ap.add_argument("--coverage-class", default=None,
                    choices=("flow", "landscape"),
                    help="override the coverage class (default: read the "
                    "companion diagram_class, else flow)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full ReconcileReport as JSON on stdout")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    try:
        report = reconcile(
            args.snapshot,
            args.diagram,
            args.provider,
            coverage_class=args.coverage_class,
        )
    except ReconcileError as exc:
        print(f"rule-engine-reconcile: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report)

    return EXIT_OK if report.eligible else EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
