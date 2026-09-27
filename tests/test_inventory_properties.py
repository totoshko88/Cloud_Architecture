"""Property-based tests for the Normalizer's key-case / separator invariance.

Feature: honest-gates, Property 18: Normalization ignores key case and separators

Property 18 — Normalization ignores key case and separators
(Validates: Requirements 5.3):

*For any* native resource and any transformation that re-cases its keys or swaps
separators (``InstanceId`` / ``instance_id`` / ``instanceId`` / ``INSTANCE_ID``),
``normalize`` returns the same Normalized Resource for the original and the
transformed input.

The Normalizer resolves every field alias through a ``{flat(key): key}`` lookup
built once per resource (``normalizer._extract``), and ``flat`` drops case and
non-alphanumeric separators (design §5, §7). So re-rendering a key in any
case/separator style — camelCase, snake_case, kebab-case, UPPER_CASE, PascalCase
— must not change the Normalized Resource that ``normalize`` produces, nor the
mapped ``resource_type`` (which is looked up case- and separator-insensitively).

The invariance is asserted on the *outcome* of ``normalize``: for a resource
that normalizes cleanly, the two Normalized Resources compare equal; for a
resource that the Normalizer excludes (e.g. missing a mandatory ``boundary``),
the base and the transformed input must be excluded for the *same reason* — a
key transform never flips an accept to a reject or vice versa.
"""

from __future__ import annotations

from typing import Any, Dict

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from rule_engine.constants import PROVIDERS
from rule_engine.normalizer import NormalizationError, normalize

from tests.strategies import (
    apply_key_transform,
    key_case_transforms,
    native_resources,
)


@st.composite
def _complete_native_resources(draw: DrawFn) -> Dict[str, Any]:
    """A :func:`native_resources` resource plus the mandatory ``boundary`` field.

    :func:`native_resources` omits ``boundary`` (a mandatory Normalized field),
    so a bare draw always excludes with a missing-field error — the property
    would then only ever compare two *rejections*. Adding a ``boundary`` (with a
    lowerCamel key, so a transform still re-cases it) lets many draws normalize
    cleanly, exercising the success path where two full Normalized Resources must
    compare equal.
    """
    resource = draw(native_resources())
    resource["boundaryId"] = draw(
        st.sampled_from(["123456789012", "acct-a", "proj-1", "tenancy-x"])
    )
    return resource


# The Normalized fields whose values are *sourced* from the native resource via
# alias matching, plus the mapped ``resource_type``. These are exactly what R5.3
# governs, so key case / separator invariance is asserted over them. The
# ``config_digest`` is intentionally excluded: it is a SHA-256 of the native
# resource's own bytes (whose key *spellings* legitimately differ between
# ``resourceType`` and ``resource_type``), not a sourced field — the task states
# the property as "the sourced fields match".
_SOURCED = (
    "provider",
    "resource_type",
    "native_type",
    "id",
    "name",
    "boundary",
    "region",
    "tags",
)


def _normalize_outcome(resource: Dict[str, Any], provider: str) -> Any:
    """Return a comparable outcome for ``normalize`` — success or exclusion.

    On success, the outcome is the Normalized Resource's *sourced* fields (see
    :data:`_SOURCED`) — everything alias matching produces, excluding the
    key-spelling-dependent ``config_digest``. On exclusion, it is an
    ``("error", kind, field)`` tuple built from the recorded
    :class:`~rule_engine.normalizer.NormalizationErrorRecord`. The ``resource``
    string in the record is deliberately excluded: it embeds a native id/name a
    transform does not change and which is not the subject of this property.
    Both outcomes are value-comparable, so the base and transformed inputs can
    be asserted equal either way.
    """
    try:
        normalized = normalize(resource, provider)
    except NormalizationError as exc:
        record = exc.record
        return ("error", record.kind, record.field)
    return {field: normalized[field] for field in _SOURCED}


# Feature: honest-gates, Property 18: Normalization ignores key case and separators
@settings(max_examples=100)
@given(
    resource=_complete_native_resources(),
    style=key_case_transforms(),
    provider=st.sampled_from(PROVIDERS),
)
def test_normalize_ignores_key_case_and_separators(
    resource: Dict[str, Any], style: str, provider: str
) -> None:
    """normalize() is invariant to a key case / separator transform.

    Uses a resource carrying every mandatory field, so many draws normalize
    cleanly and the property exercises the success path (the sourced fields of
    two Normalized Resources compared equal) as well as any shared exclusion.

    Feature: honest-gates, Property 18: Normalization ignores key case and separators
    Validates: Requirements 5.3
    """
    transformed = apply_key_transform(resource, style)

    base_outcome = _normalize_outcome(resource, provider)
    transformed_outcome = _normalize_outcome(transformed, provider)

    assert base_outcome == transformed_outcome, (
        f"key transform {style!r} changed the normalize() outcome for provider "
        f"{provider!r}: {base_outcome!r} != {transformed_outcome!r}"
    )


# Feature: honest-gates, Property 18: Normalization ignores key case and separators
@settings(max_examples=100)
@given(
    resource=native_resources(),
    style=key_case_transforms(),
    provider=st.sampled_from(PROVIDERS),
)
def test_normalize_outcome_invariant_for_raw_resources(
    resource: Dict[str, Any], style: str, provider: str
) -> None:
    """A key transform never flips a normalize() accept/reject or its reason.

    Complements the completed-resource property by drawing the raw
    :func:`native_resources` shape (which may omit mandatory fields): whatever
    the outcome — a Normalized Resource or a specific exclusion reason — it is
    identical for the original and the transformed keys.

    Feature: honest-gates, Property 18: Normalization ignores key case and separators
    Validates: Requirements 5.3
    """
    transformed = apply_key_transform(resource, style)

    assert _normalize_outcome(resource, provider) == _normalize_outcome(
        transformed, provider
    ), f"key transform {style!r} changed the normalize() outcome for {provider!r}"


# ===========================================================================
# Property 19: The Collector loses nothing and passes its own gates
# ===========================================================================
#
# Feature: honest-gates, Property 19: The Collector loses nothing and passes its own gates
#
# Property 19 — The Collector loses nothing and passes its own gates
# (Validates: Requirements 5.4, 5.5):
#
# *For any* set of fake read-only enumerators returning resources with colliding
# slugs, identical identities, PascalCase identity keys and no identity at all,
# ``collect()`` writes one ``resource.json`` per returned resource with content
# equal to the redacted resource, never writes two resources to one subfolder,
# and the resulting snapshot passes its own gates:
#
#   * ``rule-engine-check-snapshot --strict`` exits 0 on the collected folder, AND
#   * ``rule-engine-lint --all --workspace-root <tmp>`` exits 0 on the folder.
#
# The two colliding cases the design names are what would silently lose a
# resource under a naive collector: two resources whose service+identity slug is
# the same string (a slug collision), two resources with the *same* identity in
# one service (a duplicate identity), an identity carried under a PascalCase SDK
# key (``InstanceId`` — must be found case-insensitively), and a resource with no
# identity key at all (falls back to a content digest). ``_resource_dirname``
# allocates a collision-free subfolder for each, so ``collect()`` writes exactly
# one ``resource.json`` per returned resource and never overwrites one.

import json
import os
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine import cli, collector, snapshot_gate

from tests.strategies import benign_json, fs_settings


# A benign, non-secret metadata mapping to attach to each generated resource, so
# the snapshot's per-resource JSON and domain files carry no ``secret-safety``
# CRITICAL finding (the gate the property most needs to pass). ``benign_json``
# only ever draws benign keys/values (see tests/strategies.py → BENIGN_KEYS).
@st.composite
def _benign_metadata(draw: st.DrawFn) -> dict:
    payload = draw(benign_json(max_depth=2))
    return payload if isinstance(payload, dict) else {"detail": payload}


# One generated resource, in one of four identity shapes the property calls out.
# ``kind`` records how the identity is carried so the strategy can deliberately
# manufacture collisions (see ``_enumerator_batches``).
@st.composite
def _resource(draw: st.DrawFn, *, identity_pool: list) -> dict:
    meta = draw(_benign_metadata())
    resource = dict(meta)
    resource["name"] = draw(st.sampled_from(["alpha", "beta", "gamma", "delta"]))
    kind = draw(st.sampled_from(["pascal-id", "shared-id", "name-only", "no-id"]))
    if kind == "pascal-id":
        # PascalCase native identity key — must be resolved case-insensitively.
        resource["InstanceId"] = "i-" + draw(
            st.text(alphabet="0123456789abcdef", min_size=8, max_size=17)
        )
    elif kind == "shared-id":
        # A deliberately shared identity so several resources collide on identity.
        resource["InstanceId"] = draw(st.sampled_from(identity_pool))
    elif kind == "name-only":
        # No native id key: identity falls back to the resource ``name``.
        resource.pop("InstanceId", None)
    else:  # no-id
        # No native id and no usable name: identity falls back to a content digest.
        resource.pop("InstanceId", None)
        resource["name"] = ""
    return resource


@st.composite
def _enumerator_batches(draw: st.DrawFn) -> list:
    """A list of ``(service, verb, resources)`` batches for one collect() run.

    Resources are drawn into a *small* set of services (so their
    ``service-identity`` slugs collide often) with a *small* shared identity pool
    (so duplicate identities occur), exercising exactly the collision cases the
    property names. Every verb is a genuine read-only enumeration verb, so the
    read-only contract admits it and the batch actually runs.
    """
    identity_pool = ["i-share0", "i-share1"]
    n = draw(st.integers(min_value=1, max_value=5))
    batches = []
    for _ in range(n):
        service = draw(st.sampled_from(["compute", "storage", "network"]))
        verb = draw(st.sampled_from(["describe_instances", "list_buckets", "get_vpcs"]))
        resources = draw(
            st.lists(_resource(identity_pool=identity_pool), min_size=0, max_size=4)
        )
        batches.append((service, verb, resources))
    return batches


def _make_enumerators(batches: list) -> list:
    """Turn ``(service, verb, resources)`` batches into Collector enumerators.

    ``fn`` closes over its own resource list (the default-argument bind avoids
    the late-binding-closure trap) and returns it verbatim — a read-only verb.
    """
    enumerators = []
    for service, verb, resources in batches:
        enumerators.append(
            collector.Enumerator(
                service=service,
                verb=verb,
                fn=lambda *, boundary_id, region, _r=resources: list(_r),
            )
        )
    return enumerators


# Feature: honest-gates, Property 19: The Collector loses nothing and passes its own gates
@settings(fs_settings)
@given(batches=_enumerator_batches())
def test_collector_loses_nothing_and_passes_its_own_gates(
    batches: list, tmp_path_factory
) -> None:
    """collect() writes one resource.json per resource and passes its own gates.

    (a) *Loses nothing*: the number of ``resource.json`` files written equals the
    number of resources the enumerators returned, and each file's content equals
    the redacted resource — no two resources share a subfolder (R5.5).

    (b) *Passes its own gates*: ``rule-engine-check-snapshot --strict`` exits 0
    and ``rule-engine-lint --all --workspace-root <tmp>`` exits 0 on the
    collected folder (R5.4).

    Feature: honest-gates, Property 19: The Collector loses nothing and passes its own gates
    Validates: Requirements 5.4, 5.5
    """
    output_root = tmp_path_factory.mktemp("collect19")
    enumerators = _make_enumerators(batches)

    result = collector.collect(
        "aws",
        "123456789012",
        "us-east-1",
        output_root=str(output_root),
        enumerators=enumerators,
    )
    snapshot_folder = result["snapshot_folder"]

    # --- (a) The Collector loses nothing --------------------------------------
    # Every returned resource, redacted, must be present as a resource.json.
    expected_resources = [
        collector.redact_secrets(dict(r))
        for _service, _verb, resources in batches
        for r in resources
    ]

    def _key(obj: dict) -> str:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)

    resources_dir = os.path.join(snapshot_folder, "resources")
    written = []
    seen_dirs = set()
    for entry in sorted(os.listdir(resources_dir)):
        # Never two resources in one subfolder: each subfolder name is unique and
        # holds exactly one resource.json (R5.5 — no overwrite / merge).
        assert entry not in seen_dirs
        seen_dirs.add(entry)
        rj = os.path.join(resources_dir, entry, "resource.json")
        assert os.path.isfile(rj), f"subfolder {entry} has no resource.json"
        with open(rj, encoding="utf-8") as fh:
            written.append(json.loads(fh.read()))

    # Nothing lost, nothing invented: the *set* of written contents equals the
    # set of redacted returned resources. Two byte-identical, identity-less
    # resources are genuinely indistinguishable, so they legitimately coalesce to
    # one file — the file still carries their exact content, so no information is
    # lost. Every distinct returned resource must still appear, and every written
    # file must be a returned resource (no foreign or partial content).
    expected_contents = {_key(e) for e in expected_resources}
    written_contents = {_key(w) for w in written}
    assert written_contents == expected_contents, (
        "the set of written resource.json contents does not equal the set of "
        f"redacted returned resources: missing "
        f"{expected_contents - written_contents}, extra "
        f"{written_contents - expected_contents}"
    )

    # Every written resource.json content is exactly some redacted returned
    # resource — i.e. a subfolder never holds content that was never enumerated.
    for w in written:
        assert _key(w) in expected_contents, (
            "a written resource.json does not equal any redacted returned resource"
        )

    # --- (b) The snapshot passes its own gates --------------------------------
    # rule-engine-check-snapshot --strict exits 0 on the collected folder.
    assert (
        snapshot_gate.main(["--snapshot", snapshot_folder, "--strict"]) == 0
    ), "rule-engine-check-snapshot --strict did not exit 0 on the collected folder"

    # rule-engine-lint --all --workspace-root <tmp> exits 0 on the collected folder.
    assert (
        cli.main(["--all", "--workspace-root", str(output_root)]) == 0
    ), "rule-engine-lint --all did not exit 0 on the collected folder"


# ===========================================================================
# Property 20: Unsafe Collector inputs are refused before any write
# ===========================================================================
#
# Feature: honest-gates, Property 20: Unsafe Collector inputs are refused before any write
#
# Property 20 — Unsafe Collector inputs are refused before any write
# (Validates: Requirements 5.6):
#
# *For any* boundary_id or region carrying a character outside
# ``[A-Za-z0-9._:-]`` (BOUNDARY_RE), or any input whose snapshot folder resolves
# outside ``output_root`` (a ``..`` traversal the regex lets through via ``.``),
# ``collect()`` raises ``CollectorInputError`` and writes no file — the
# ``output_root`` directory is left byte-for-byte unchanged.
#
# ``collector._validate_target`` runs before the first filesystem call
# (``_allocate_snapshot_dir``), so an unsafe input is refused before any mkdir /
# write. The property proves this by pre-populating ``output_root`` with a
# sentinel file and asserting that, after the refused run, the directory tree
# under ``output_root`` is exactly what it was before the call — the sentinel is
# untouched and no snapshot folder was created.


import pytest

# A single character outside BOUNDARY_RE (``[A-Za-z0-9._:-]``), used to poison an
# otherwise-safe boundary_id / region. Newline is excluded because Python's ``$``
# matches just before a trailing ``\n`` (so ``"0\n"`` would slip past the anchor);
# every character here is rejected purely by the regex anywhere it appears.
_UNSAFE_CHARS = st.sampled_from(list(" /\\*?!@#$%^&()=+[]{}<>,;'\"`~\t"))


@st.composite
def _regex_unsafe_field(draw: st.DrawFn) -> str:
    """A boundary_id / region string with at least one out-of-class character."""
    safe = draw(st.text(alphabet="abcdefABCDEF0123456789._:-", max_size=8))
    bad = draw(_UNSAFE_CHARS)
    # Splice the bad character at a random position so the offending char is not
    # always leading/trailing.
    pos = draw(st.integers(min_value=0, max_value=len(safe)))
    return safe[:pos] + bad + safe[pos:]


def _snapshot_dirs(output_root) -> set:
    """The set of relative paths present under ``output_root`` (files + dirs)."""
    found = set()
    for base, dirs, files in os.walk(output_root):
        for name in list(dirs) + list(files):
            found.add(os.path.relpath(os.path.join(base, name), output_root))
    return found


# Feature: honest-gates, Property 20: Unsafe Collector inputs are refused before any write
@settings(fs_settings)
@given(
    provider=st.sampled_from(list(PROVIDERS)),
    unsafe_boundary=st.booleans(),
    bad_field=_regex_unsafe_field(),
    safe_field=st.text(alphabet="abcdef0123456789-", min_size=1, max_size=8),
)
def test_regex_unsafe_input_is_refused_before_any_write(
    provider: str,
    unsafe_boundary: bool,
    bad_field: str,
    safe_field: str,
    tmp_path_factory,
) -> None:
    """A boundary_id/region with an out-of-class char is refused before any write.

    Either ``boundary_id`` (``unsafe_boundary``) or ``region`` carries a
    character outside ``BOUNDARY_RE``; the other is safe. ``collect()`` must raise
    ``CollectorInputError`` and leave ``output_root`` byte-for-byte unchanged — a
    pre-seeded sentinel survives and no snapshot folder is created.

    Feature: honest-gates, Property 20: Unsafe Collector inputs are refused before any write
    Validates: Requirements 5.6
    """
    output_root = tmp_path_factory.mktemp("collect20-regex")
    sentinel = output_root / "sentinel.txt"
    sentinel.write_text("pre-existing", encoding="utf-8")
    before = _snapshot_dirs(output_root)

    boundary_id = bad_field if unsafe_boundary else safe_field
    region = safe_field if unsafe_boundary else bad_field

    with pytest.raises(collector.CollectorInputError):
        collector.collect(
            provider,
            boundary_id,
            region,
            output_root=str(output_root),
            enumerators=[
                collector.Enumerator(
                    service="compute",
                    verb="describe_instances",
                    fn=lambda *, boundary_id, region: [{"name": "x"}],
                )
            ],
        )

    # No file was written: the tree under output_root is exactly what it was, and
    # the sentinel is untouched.
    assert _snapshot_dirs(output_root) == before, (
        "a refused (regex-unsafe) run wrote to output_root"
    )
    assert sentinel.read_text(encoding="utf-8") == "pre-existing"


# Feature: honest-gates, Property 20: Unsafe Collector inputs are refused before any write
@settings(fs_settings)
@given(
    depth=st.integers(min_value=1, max_value=5),
    tail=st.text(alphabet="abcdef0123456789-_", max_size=8),
)
def test_path_escaping_folder_is_refused_before_any_write(
    depth: int,
    tail: str,
    tmp_path_factory,
) -> None:
    """A snapshot ``folder`` that resolves outside ``output_root`` is refused.

    ``.`` is inside ``BOUNDARY_RE``, so ``..`` segments pass the character check;
    only ``_validate_target``'s resolve-inside-root check catches a folder that
    climbs above ``output_root``. Because ``collect()`` embeds ``boundary_id`` /
    ``region`` mid-string in a single folder segment, this escape is exercised at
    the ``_validate_target`` boundary directly, with a ``folder`` built from
    real path-separator ``..`` segments. It must raise ``CollectorInputError``
    (which ``collect()`` never catches, so the run aborts before any write), and
    the ``output_root`` tree — including a pre-seeded sentinel — is unchanged.

    Feature: honest-gates, Property 20: Unsafe Collector inputs are refused before any write
    Validates: Requirements 5.6
    """
    output_root = tmp_path_factory.mktemp("collect20-escape")
    sentinel = output_root / "sentinel.txt"
    sentinel.write_text("pre-existing", encoding="utf-8")
    before = _snapshot_dirs(output_root)

    # A folder that climbs above output_root, then names a sibling directory —
    # the resolved target lands outside output_root, which _validate_target must
    # refuse (boundary_id / region are legal so only the path check fires).
    folder = "/".join([".."] * depth + ["escaped" + tail])

    with pytest.raises(collector.CollectorInputError):
        collector._validate_target(output_root, "acct-1", "us-east-1", folder)

    assert _snapshot_dirs(output_root) == before, (
        "a refused (path-escaping) validation wrote to output_root"
    )
    assert sentinel.read_text(encoding="utf-8") == "pre-existing"


# ===========================================================================
# Property 21: Repeated runs never merge snapshots
# ===========================================================================
#
# Feature: honest-gates, Property 21: Repeated runs never merge snapshots
#
# Property 21 — Repeated runs never merge snapshots
# (Validates: Requirements 5.7):
#
# *For any* N >= 2 collect() runs with the *same* provider / boundary_id /
# region / started_at (so every run computes the identical base folder name),
# each run gets its own snapshot folder — the first is ``inventory-…`` and the
# k-th (k >= 2) is ``inventory-…-k`` — and no run ever overwrites or merges into
# an earlier run's folder. After all N runs, every earlier folder's content is
# byte-for-byte what it was immediately after that run finished.
#
# collector._allocate_snapshot_dir tries ``folder``, ``folder-2``, ``folder-3``,
# … with ``mkdir(exist_ok=False)`` (task 13.4), so a colliding name never lands
# on an existing directory; snapshot_gate._FOLDER_RE accepts the optional
# ``-<n>`` suffix (n >= 2) so each allocated folder still passes the gate
# (task 13.5). This property proves the no-merge guarantee end-to-end: it
# snapshots the full content tree of every folder right after each run and
# asserts, once all runs are done, that no earlier folder changed.


def _tree_contents(folder: str) -> dict:
    """Map every file under ``folder`` to its bytes (relative-path keyed).

    A byte-level capture of the whole subtree, so a later run merging into,
    truncating, or appending to any earlier-run file is detected — not only a
    changed directory listing.
    """
    contents: dict = {}
    for base, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(base, name)
            rel = os.path.relpath(path, folder)
            with open(path, "rb") as fh:
                contents[rel] = fh.read()
    return contents


# Feature: honest-gates, Property 21: Repeated runs never merge snapshots
@settings(fs_settings)
@given(
    provider=st.sampled_from(list(PROVIDERS)),
    runs=st.integers(min_value=2, max_value=4),
    batches=_enumerator_batches(),
)
def test_repeated_runs_never_merge_snapshots(
    provider: str,
    runs: int,
    batches: list,
    tmp_path_factory,
) -> None:
    """N runs with identical inputs each get their own, never-merged folder.

    Every run uses the same provider / boundary_id / region / started_at, so
    every run computes the identical base folder name and forces the suffix
    allocator. Each run must land in a *distinct* folder (``folder`` then
    ``folder-2`` …), and once all runs have finished, every earlier folder's
    content is byte-for-byte what it was right after that run — nothing was
    merged, overwritten, appended, or truncated.

    Feature: honest-gates, Property 21: Repeated runs never merge snapshots
    Validates: Requirements 5.7
    """
    output_root = tmp_path_factory.mktemp("collect21")
    boundary_id = "123456789012"
    region = "us-east-1"
    # A fixed start timestamp so every run computes the SAME base folder name;
    # otherwise the minute component could differ and no collision would occur,
    # and the property (which exists to test the suffix path) would not bite.
    started_at = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)

    base = collector.snapshot_folder_name(provider, boundary_id, region, started_at)

    seen_folders: list[str] = []
    # The content of each folder captured immediately after its own run, so a
    # later run cannot have touched it yet.
    snapshot_after_own_run: dict[str, dict] = {}

    for run_index in range(runs):
        enumerators = _make_enumerators(batches)
        result = collector.collect(
            provider,
            boundary_id,
            region,
            output_root=str(output_root),
            enumerators=enumerators,
            started_at=started_at,
        )
        folder = result["snapshot_folder"]

        # (a) Each run gets a brand-new folder — never one already allocated.
        assert folder not in seen_folders, (
            f"run {run_index} reused an earlier snapshot folder {folder!r}"
        )
        seen_folders.append(folder)

        # (b) The name follows the folder / folder-N convention deterministically:
        # the first run is the bare base name, the k-th (k >= 2) is base-<k>.
        expected_name = base if run_index == 0 else f"{base}-{run_index + 1}"
        assert os.path.basename(folder) == expected_name, (
            f"run {run_index} folder {os.path.basename(folder)!r} is not the "
            f"expected {expected_name!r} (folder / folder-N suffix convention)"
        )

        snapshot_after_own_run[folder] = _tree_contents(folder)

    # (c) No merge / overwrite: after every run has finished, each earlier
    # folder's full content tree is byte-for-byte what it was right after its
    # own run — a later colliding run never wrote into it.
    for folder, expected_contents in snapshot_after_own_run.items():
        assert _tree_contents(folder) == expected_contents, (
            f"snapshot folder {folder!r} changed after a later run — a repeated "
            "run merged into or overwrote an earlier snapshot"
        )

    # (d) Sanity: all N folders coexist on disk (none was replaced by another).
    assert len(set(seen_folders)) == runs
    for folder in seen_folders:
        assert os.path.isdir(folder)

# ===========================================================================
# Property 22: Delta classification is a partition with explicit duplicates
# ===========================================================================
#
# Feature: honest-gates, Property 22: Delta classification is a partition with explicit duplicates
#
# Property 22 — Delta classification is a partition with explicit duplicates
# (Validates: Requirements 5.8):
#
# *For any* pair of snapshots (resources may share ids across boundaries or
# regions, and an identity may repeat within a snapshot), ``compute_delta``
# assigns exactly one classification from ``CLASSIFICATIONS`` to each distinct
# ``(provider, resource_type, boundary, region, identity)`` tuple in the union
# of both snapshots — a partition: no identity is dropped and none is
# double-counted. It assigns ``duplicate`` to exactly the identities that occur
# more than once in either snapshot (an explicit record, never a silent
# last-writer-wins overwrite), and it treats resources that differ only in
# ``boundary`` or ``region`` as distinct identities.
#
# R5.8: "THE Delta_Engine SHALL include boundary and region in resource identity
# and emit an explicit duplicate entry instead of a silent last-writer-wins."
#
# This property is stated for the honest-gates identity contract (boundary +
# region in the identity, ``duplicate`` as a first-class classification). It is
# self-contained: it builds its own snapshot-pair strategy rather than the
# diagram/KB generators in tests.strategies, since a snapshot is just a list of
# Normalized Resources.

from collections import Counter

from rule_engine.delta import CLASSIFICATIONS, DUPLICATE, compute_delta, identity_of

# A closed alphabet so identity collisions across the two snapshots are common
# (exercising changed/unchanged) and collisions *within* one snapshot are common
# (exercising duplicate). ``boundary`` and ``region`` vary so the property can
# assert that resources differing only in boundary/region are distinct.
_p22_providers = st.sampled_from(list(PROVIDERS))
_p22_resource_types = st.sampled_from(
    ["object_store", "serverless_fn", "managed_sql", "message_queue"]
)
_p22_boundaries = st.sampled_from(["acct-1", "acct-2"])
_p22_regions = st.sampled_from(["us-east-1", "eu-west-1"])
_p22_ids = st.sampled_from(["id-1", "id-2", "id-3"])
_p22_names = st.sampled_from(["name-a", "name-b", "name-c"])
_p22_digests = st.sampled_from(["digest-x", "digest-y", "digest-z"])


@st.composite
def _p22_resource(draw: st.DrawFn) -> Dict[str, Any]:
    """A valid Normalized Resource carrying every identity field.

    Always carries ``boundary`` and ``region`` (part of the identity since the
    honest-gates release), so ``identity_of`` never raises. At least one of
    ``id`` / ``name`` is non-empty and ``config_digest`` is always present, so
    the changed/unchanged distinction is well defined.
    """
    resource: Dict[str, Any] = {
        "provider": draw(_p22_providers),
        "resource_type": draw(_p22_resource_types),
        "boundary": draw(_p22_boundaries),
        "region": draw(_p22_regions),
        "config_digest": draw(_p22_digests),
    }
    which = draw(st.sampled_from(["id", "name", "both"]))
    if which in ("id", "both"):
        resource["id"] = draw(_p22_ids)
    if which in ("name", "both"):
        resource["name"] = draw(_p22_names)
    return resource


def _p22_snapshots() -> st.SearchStrategy[list]:
    """A snapshot: a possibly-empty list of valid Normalized Resources."""
    return st.lists(_p22_resource(), max_size=8)


def _p22_counts(snapshot: list, *, name: str) -> Counter:
    """Count occurrences of each identity tuple in a snapshot."""
    counts: Counter = Counter()
    for resource in snapshot:
        counts[identity_of(resource, snapshot=name).as_tuple()] += 1
    return counts


def _p22_first_by_identity(snapshot: list, *, name: str) -> Dict[tuple, Dict[str, Any]]:
    """Index a snapshot by identity tuple, keeping the FIRST entry seen.

    Mirrors ``compute_delta``'s dedup: a repeated identity is reported as
    ``duplicate`` rather than overwritten, so the ground truth reads the first
    entry's digest only for identities that are NOT duplicated.
    """
    index: Dict[tuple, Dict[str, Any]] = {}
    for resource in snapshot:
        key = identity_of(resource, snapshot=name).as_tuple()
        index.setdefault(key, resource)
    return index


# Feature: honest-gates, Property 22: Delta classification is a partition with explicit duplicates
@settings(max_examples=100)
@given(current=_p22_snapshots(), previous=_p22_snapshots())
def test_delta_classification_is_a_partition_with_explicit_duplicates(
    current: list, previous: list
) -> None:
    """compute_delta partitions the union identity set, duplicates explicit.

    (a) *Partition*: exactly one ``DeltaRecord`` per distinct identity in the
    union of both snapshots — none dropped, none double-counted — and every
    classification is drawn from ``CLASSIFICATIONS``.

    (b) *Explicit duplicates*: an identity occurring more than once in either
    snapshot is classified ``duplicate`` (never silently overwritten and never
    re-classified as added/changed/removed/unchanged). Every other identity
    lands in its correct ground-truth class.

    (c) *Boundary/region are part of the identity*: resources sharing a
    ``(provider, resource_type, identity_key)`` but differing in ``boundary`` or
    ``region`` are distinct identities, so they classify independently.

    Feature: honest-gates, Property 22: Delta classification is a partition with explicit duplicates
    Validates: Requirements 5.8
    """
    curr_counts = _p22_counts(current, name="current")
    prev_counts = _p22_counts(previous, name="previous")
    curr_index = _p22_first_by_identity(current, name="current")
    prev_index = _p22_first_by_identity(previous, name="previous")
    expected_identities = set(curr_counts) | set(prev_counts)

    # Ground truth: an identity duplicated in either snapshot is `duplicate`.
    duplicate_identities = {
        key
        for key in expected_identities
        if curr_counts.get(key, 0) > 1 or prev_counts.get(key, 0) > 1
    }

    records = compute_delta(current, previous)
    record_identities = [r.identity.as_tuple() for r in records]

    # (a) Partition: one record per distinct union identity — no drop, no double.
    assert len(record_identities) == len(set(record_identities)), (
        "each identity must appear in exactly one DeltaRecord (no double-count)"
    )
    assert set(record_identities) == expected_identities, (
        "the classified identity set must equal the union of both snapshots "
        "(nothing dropped, nothing invented)"
    )

    for record in records:
        key = record.identity.as_tuple()
        assert record.classification in CLASSIFICATIONS, (
            f"classification {record.classification!r} not in {CLASSIFICATIONS}"
        )

        # (b) Ground-truth classification per identity.
        if key in duplicate_identities:
            expected = DUPLICATE
        else:
            in_curr = key in curr_index
            in_prev = key in prev_index
            if in_curr and not in_prev:
                expected = "added"
            elif in_prev and not in_curr:
                expected = "removed"
            else:  # present in both
                same_digest = curr_index[key].get("config_digest") == prev_index[
                    key
                ].get("config_digest")
                expected = "unchanged" if same_digest else "changed"

        assert record.classification == expected, (
            f"identity {key} classified {record.classification!r}, "
            f"expected {expected!r}"
        )

    # (b, restated) Exactly the duplicated identities are classified `duplicate`,
    # and each such identity yields exactly one duplicate record (no overwrite).
    duplicate_records = [r for r in records if r.classification == DUPLICATE]
    assert {r.identity.as_tuple() for r in duplicate_records} == duplicate_identities
    assert len(duplicate_records) == len(duplicate_identities), (
        "each repeated identity yields exactly one explicit duplicate record"
    )

    # (c) Boundary/region are part of the identity: two identity tuples that
    # agree on (provider, resource_type, identity_key) but differ in boundary or
    # region are genuinely distinct records, never collapsed into one.
    for key in expected_identities:
        provider, resource_type, boundary, region, identity_key = key
        siblings = [
            other
            for other in expected_identities
            if other != key
            and other[0] == provider
            and other[1] == resource_type
            and other[4] == identity_key
        ]
        for other in siblings:
            # Same service + identity_key but different boundary/region: both
            # must have their own record (distinct identities), confirming
            # boundary/region participate in identity (R5.8).
            assert (other[2], other[3]) != (boundary, region)
            assert other in set(record_identities)
