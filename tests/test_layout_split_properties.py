# Feature: scored-router, Property 1: the split is behavior-preserving
"""Property 1 — the ``layout/`` package split is behavior-preserving.

**Validates: Requirements 1.2, 1.3, 1.4, 1.5** (scored-router release 1.8.0,
tasks 1.5 and 8.1).

Phase A relocated ``layout_engine.py`` into the ``layout/`` package behind stable
names, added ``variants.py`` / ``solver.py`` **unwired**, and kept the
``--legacy`` ten-pass path. When this module was first written (task 1.5) the
scored solver was absent, so the default path and the ``--legacy`` path were the
*same* code and every assertion here could compare "default vs legacy".

**Re-baseline (task 8.1).** The scored solver is now the DEFAULT routing stage
(task 7.3), so "default == legacy byte-for-byte" is no longer true in general —
on a small generated spec the scored router legitimately picks a lower-cost route
than the ten-pass path. That Phase A invariant has been retired here **without
weakening the intent**: Property 1 still guarantees the split changed no
published output, split cleanly into the two claims the split actually makes:

* **(a) the ``--legacy`` path is byte-identical to the pre-split / committed
  output** — the ten-pass path is the untouched code, so it must still reproduce
  every committed shipped ``.drawio`` exactly (R1.5), and it must be
  deterministic run-to-run;
* **(b) the default (scored) path is deterministic and produces the committed
  shipped diagrams** — the scored router is the published default, so it must
  reproduce every committed shipped ``.drawio`` byte for byte and ``generator
  --check`` must report no difference (R1.2, R1.3).

This module proves both, in three parts mirroring the design's *Correctness
Property 1*:

1. **Default (scored) byte-identical to the committed file.** For every shipped
   diagram driven by ``layout()`` — the four HA providers' ``summary`` +
   ``landscape`` pair — the freshly built ``.drawio`` equals the committed file
   byte for byte, and ``generator --check`` reports no difference (R1.2, R1.3,
   claim (b)).
2. **``--legacy`` reproduces the committed (pre-split) output.** The ``--legacy``
   ten-pass path is byte-identical to the committed shipped ``.drawio`` — proven
   at the ``layout()`` level (``layout(spec, legacy=True)`` is deterministic and
   reproduces the committed geometry) and at the generator level
   (``build_summary(skin, legacy=True)`` equals the committed file). This is the
   R1.5 guarantee that the legacy path reproduces the pre-split output, and it no
   longer leans on the scored default happening to match.
3. **Hypothesis over the corpus + generated small specs.** A Hypothesis strategy
   generates small ``DiagramSpec``s (reusing the established ``_small_valid_spec``
   generator from ``tests/test_layout_engine_property.py``) and also samples the
   two shipped-corpus specs, asserting for every one that (a) the ``--legacy``
   path is deterministic (byte-identical run twice, the behavior-preserving
   guarantee for the untouched ten-pass code) and (b) the default scored path is
   deterministic, at ``max_examples >= 100``. It no longer asserts
   ``default == legacy``, which the scored router legitimately breaks; scored
   determinism as a pure function of the spec is separately and exhaustively
   proven by *Property 3* (``tests/test_solver_properties.py``).

The single-example generators (``build_gcp_example.py``,
``build_aws_infra_example.py``, ``build_oci_example.py``) hand-place their
geometry and never call ``layout()``, so the ``layout()`` behavior-preserving
contract does not touch them; the byte-identity checks here cover exactly the
diagrams ``layout()`` drives (the four HA pairs), plus ``generator --check`` for
those generators.

Conventions (established by honest-gates, extended here): shared strategies live
in ``tests/strategies.py`` and the Hypothesis profile in ``tests/conftest.py``
(loaded automatically, ``max_examples=100``). The shipped-spec enumeration and
the ``generator --check`` subprocess invocation follow ``tests/test_ha_generator
_parity.py`` and ``tests/test_generators_fresh.py`` respectively.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "scripts"
_EXAMPLES = _REPO / "examples"

# Make the ``src`` package and the ``scripts`` generators importable, mirroring
# tests/test_ha_generator_parity.py so the shipped builders resolve.
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_SCRIPTS))

from ha_multiregion_common import build_landscape, build_summary  # noqa: E402
from rule_engine.ha_multiregion_spec import LANDSCAPE_SPEC, SUMMARY_SPEC  # noqa: E402
from rule_engine.layout_engine import (  # noqa: E402
    DiagramSpec,
    LayoutError,
    OverConnectedError,
    _serialize_candidate,
    layout,
)

# Reuse the established small-valid-spec generator so this property exercises the
# same layout-able family as the geometry-oracle property, rather than
# re-deriving one (tasks.md: "Reuse existing strategies where possible").
from tests.test_layout_engine_property import _small_valid_spec  # noqa: E402


# --------------------------------------------------------------------------- #
# Shipped corpus enumeration.
#
# The two specs that flow through ``layout()`` are SUMMARY_SPEC and
# LANDSCAPE_SPEC; each is skinned by the four HA providers into a committed
# ``.drawio``. OCI renders via embedded stencils decoded into
# assets/vendor/oci-stencils/stencils.json, which is git-ignored and fetched on
# demand — present on a dev machine, ABSENT in a bare CI checkout — so building
# the OCI skin raises there. Skip OCI when the stencils file is missing (an
# environment prerequisite, not a code defect); the geometry byte-identity
# contract is skin-independent, so aws/azure/gcp still exercise the shared engine.
# --------------------------------------------------------------------------- #
_OCI_STENCILS = _REPO / "assets" / "vendor" / "oci-stencils" / "stencils.json"
_OCI_ASSETS_PRESENT = _OCI_STENCILS.is_file()

_HA_PROVIDERS = ("aws", "azure", "gcp", "oci")


def _ha_skin(provider: str):
    """Load the per-provider ``SKIN`` from its HA generator script.

    The per-provider ``build_<prov>_ha_example.py`` wrapper supplies only the
    ``ProviderSkin``; the ``build_summary`` / ``build_landscape`` builders live in
    the shared ``ha_multiregion_common`` module and take the skin + ``legacy``."""
    return importlib.import_module(f"build_{provider}_ha_example").SKIN


# The four HA generators and the committed pair each one writes (8 diagrams).
_HA_EXAMPLES: tuple[tuple[str, str, str], ...] = tuple(
    item
    for provider in _HA_PROVIDERS
    for item in (
        (provider, "summary",
         f"{provider}/02-{provider}-ha-multiregion-summary.drawio"),
        (provider, "landscape",
         f"{provider}/02-{provider}-ha-multiregion-landscape.drawio"),
    )
)

# The seven Example_Generators (four HA + three single) for the ``--check``
# freshness gate (R1.3). ``--check`` writes nothing.
_ALL_GENERATORS: tuple[str, ...] = (
    "build_aws_ha_example.py",
    "build_azure_ha_example.py",
    "build_gcp_ha_example.py",
    "build_oci_ha_example.py",
    "build_aws_infra_example.py",
    "build_gcp_example.py",
    "build_oci_example.py",
)

# A generator whose ``--check`` exits 2 because an input asset (the OCI stencil
# pack) is missing is SKIPped, not failed — the pack-less environment simply has
# not fetched it. Recognised from the generator's own message.
_MISSING_PACK_MARKERS = ("stencils not found", "fetch_assets")


def _build_ha(provider: str, kind: str, *, legacy: bool = False) -> str:
    """Build one HA ``.drawio`` (``kind`` is ``summary`` or ``landscape``)."""
    builder = build_summary if kind == "summary" else build_landscape
    return builder(_ha_skin(provider), legacy=legacy)


def _serialise(spec: DiagramSpec, *, legacy: bool) -> str:
    """Serialise ``layout(spec, legacy=…)`` to ``.drawio`` text (stub icons).

    Reuses the engine's own ``_serialize_candidate`` (``build_diagram`` with stub
    icons) so the comparison is over exactly the geometry ``layout`` produced,
    independent of any provider skin — the cleanest possible view of "did the
    split change the layout output".
    """
    return _serialize_candidate(layout(spec, legacy=legacy))


# =========================================================================== #
# Part 1 — every shipped diagram is byte-identical to the committed file (R1.2)
#          and ``generator --check`` reports no difference (R1.3).
# =========================================================================== #


@pytest.mark.parametrize(
    "provider,kind,rel_path",
    _HA_EXAMPLES,
    ids=[f"{p}-{k}" for p, k, _ in _HA_EXAMPLES],
)
def test_layout_output_is_byte_identical_to_committed(provider, kind, rel_path):
    """``layout()`` (solver off) reproduces every committed HA ``.drawio`` byte
    for byte — the core of Property 1 (R1.2)."""
    if provider == "oci" and not _OCI_ASSETS_PRESENT:
        pytest.skip(
            "OCI stencil pack not fetched in this environment; run "
            "scripts/fetch_assets.py --only oci to fetch it."
        )
    committed_path = _EXAMPLES / rel_path
    assert committed_path.is_file(), f"missing committed example examples/{rel_path}"
    committed = committed_path.read_text(encoding="utf-8")

    regenerated = _build_ha(provider, kind)
    assert regenerated == committed, (
        f"examples/{rel_path} is NOT byte-identical after the layout/ split — "
        f"the relocation changed the layout output (Property 1 / R1.2). "
        f"Regenerate with scripts/build_{provider}_ha_example.py to inspect."
    )


def _run_check(script: str) -> subprocess.CompletedProcess:
    """Run ``python <script> --check`` as a subprocess (writes nothing).

    ``sys.executable`` is the venv interpreter running pytest, exactly the
    environment CI uses, so the generator's ``rule_engine`` / ``mappings`` imports
    resolve identically."""
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / script), "--check"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("script", _ALL_GENERATORS, ids=lambda s: s)
def test_generator_check_reports_no_difference(script):
    """``generator --check`` reports no difference for every Shipped_Diagram with
    the solver off (R1.3). Exit 0 = fresh (no diff). A generator whose ``--check``
    exits 2 for a missing OCI stencil pack is skipped (an environment condition,
    not a difference)."""
    result = _run_check(script)
    diagnostics = (
        f"{script} --check exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    message = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 2 and any(m in message for m in _MISSING_PACK_MARKERS):
        pytest.skip(
            f"{script}: OCI stencil pack not fetched; run "
            f"scripts/fetch_assets.py --only oci.\n{diagnostics}"
        )
    assert result.returncode == 0, (
        f"generator --check reports a DIFFERENCE after the layout/ split — the "
        f"split was not behavior-preserving (Property 1 / R1.3).\n{diagnostics}"
    )


# =========================================================================== #
# Part 2 — the ``--legacy`` path reproduces the committed (pre-split) output
#          (R1.5). The ten-pass path is the untouched code; it must still
#          produce every committed shipped ``.drawio`` byte for byte and be
#          deterministic run-to-run. Re-baselined at task 8.1: this no longer
#          asserts legacy == the scored DEFAULT (which the scored router
#          legitimately breaks on generated specs), but legacy == COMMITTED,
#          which is the honest R1.5 guarantee and is independent of the default.
# =========================================================================== #


@pytest.mark.parametrize(
    "spec_name,spec",
    [("summary", SUMMARY_SPEC), ("landscape", LANDSCAPE_SPEC)],
    ids=["summary-spec", "landscape-spec"],
)
def test_legacy_layout_is_deterministic(spec_name, spec):
    """At the ``layout()`` seam, ``layout(spec, legacy=True)`` serialises byte-for-
    byte identically on two runs — the retained ten-pass path is a deterministic,
    pure function of the spec, which is the run-to-run half of the R1.5
    behavior-preserving guarantee for the untouched legacy code.

    (That the legacy path reproduces the committed *skinned* output end to end is
    asserted at the generator seam by
    :func:`test_legacy_generator_output_matches_committed`; here we prove the
    legacy geometry itself is stable, independent of any provider skin.)"""
    assert _serialise(spec, legacy=True) == _serialise(spec, legacy=True), (
        f"the --legacy path is non-deterministic for {spec_name}; the retained "
        f"ten-pass path must be a pure function of the spec (R1.5)."
    )


@pytest.mark.parametrize(
    "provider,kind,rel_path",
    _HA_EXAMPLES,
    ids=[f"{p}-{k}" for p, k, _ in _HA_EXAMPLES],
)
def test_legacy_generator_output_matches_committed(provider, kind, rel_path):
    """At the generator seam, ``build_*(skin, legacy=True)`` is byte-identical to
    the COMMITTED shipped ``.drawio`` for every HA diagram — the ``--legacy`` flag
    reproduces the pre-split output end to end (R1.5).

    This is the honest R1.5 check after the scored router became the default: the
    untouched ten-pass path must still reproduce every committed file exactly, on
    its own merits — not merely match whatever the scored default now emits. (On
    the shipped corpus the scored default *also* matches the committed file, which
    Part 1 asserts; the two claims are now proven independently.)"""
    if provider == "oci" and not _OCI_ASSETS_PRESENT:
        pytest.skip("OCI stencil pack not fetched in this environment.")
    committed_path = _EXAMPLES / rel_path
    assert committed_path.is_file(), f"missing committed example examples/{rel_path}"
    committed = committed_path.read_text(encoding="utf-8")
    legacy = _build_ha(provider, kind, legacy=True)
    assert legacy == committed, (
        f"{provider} {kind}: --legacy output diverged from the committed file; "
        f"the retained ten-pass path must reproduce the pre-split output (R1.5)."
    )


# =========================================================================== #
# Part 3 — Hypothesis over generated small specs PLUS the shipped-spec corpus:
#          BOTH paths are deterministic (byte-identical run twice) for every spec
#          (R1.2, R1.4). max_examples >= 100 (conftest profile = 100).
#
# Re-baselined at task 8.1: the pre-8.1 test asserted the default (scored) path
# and the ``--legacy`` path serialised byte-identically. That was true only while
# the scored solver was unwired (Phase A); now that scored is the default it
# legitimately picks a lower-cost route than the ten-pass path on a generated
# spec, so ``default == legacy`` is no longer a valid invariant. The
# behavior-preserving guarantee is instead held as two determinism claims — the
# untouched ``--legacy`` path is a pure function of the spec (its run-to-run
# stability is the "the split changed nothing" guarantee for the legacy code),
# and the scored default is a pure function of the spec (so ``generator --check``
# never flaps). Scored-vs-legacy cost ordering (scored is never worse) is
# Property 4; full scored determinism is Property 3 — both in
# tests/test_solver_properties.py.
# =========================================================================== #

#: Generated small specs interleaved with the two shipped-corpus specs, so the
#: property is exercised on the real diagrams and on a broad generated family.
_split_specs = st.one_of(
    st.sampled_from([SUMMARY_SPEC, LANDSCAPE_SPEC]),
    _small_valid_spec(),
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(spec=_split_specs)
def test_split_is_behavior_preserving(spec: DiagramSpec) -> None:
    """For every spec (generated small specs + the shipped corpus), BOTH the
    default (scored) path and the retained ``--legacy`` ten-pass path serialise to
    a byte-identical ``.drawio`` when run twice — each is a deterministic, pure
    function of the spec (Property 1, R1.2/R1.4).

    This is the re-baselined behavior-preserving guarantee (task 8.1): the split
    left the ``--legacy`` code untouched, so its output must be stable run-to-run;
    and the scored default must be equally stable so ``generator --check`` cannot
    flap. The two paths need NOT produce the same bytes — the scored router
    legitimately routes some generated specs better than the ten-pass path (that
    it is never *worse* is Property 4). A spec the engine legitimately refuses to
    lay out raises the SAME error on both paths (they share ``place → size →
    centre`` and the repair loop), which is itself behavior-preserving, so it is
    asserted rather than treated as a counterexample.
    """
    # The retained legacy ten-pass path — the untouched code — must be a pure
    # function of the spec: same bytes on two runs.
    try:
        legacy_a = _serialise(spec, legacy=True)
    except (LayoutError, OverConnectedError) as exc:
        # The legacy path refuses this spec; a second legacy run must refuse it
        # identically, and the scored default must refuse it too (both share the
        # place/size/centre stages and the bounded repair loop).
        with pytest.raises(type(exc)):
            _serialise(spec, legacy=True)
        with pytest.raises((LayoutError, OverConnectedError)):
            _serialise(spec, legacy=False)
        return

    legacy_b = _serialise(spec, legacy=True)
    assert legacy_a == legacy_b, (
        "the retained --legacy ten-pass path produced different bytes on two "
        "runs; the untouched legacy code must be a deterministic pure function "
        "of the spec (Property 1 — the split is behavior-preserving)."
    )

    # The scored default must be equally deterministic, so the generator --check
    # freshness gate holds (R4.1). Both paths agree on layout-ability, so if
    # legacy succeeded the default must also succeed.
    default_a = _serialise(spec, legacy=False)
    default_b = _serialise(spec, legacy=False)
    assert default_a == default_b, (
        "the default (scored) path produced different bytes on two runs; the "
        "scored router must be a deterministic pure function of the spec so the "
        "generator --check freshness gate cannot flap (Property 1 / R4.1)."
    )
