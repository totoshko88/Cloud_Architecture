"""Freshness smoke test for every Generated_Example (R8.1).

Feature: honest-gates (release 1.7.0), task 18.3.

Requirement 8.1 says: *every* Example_Generator provides a ``--check`` mode that
compares its output with the committed file without writing, and CI runs that
mode for **all eleven** Generated_Examples. This test is the local, per-example
counterpart to that CI step: it enumerates every generator in ``scripts/`` and
runs its ``--check`` mode, asserting the committed ``examples/**/*.drawio`` are
up to date.

There are **seven** Example_Generators producing **eleven** Generated_Examples:

* Four HA generators (``build_<prov>_ha_example.py``) — each writes a *pair*
  (``…-summary.drawio`` + ``…-landscape.drawio``), so 4 × 2 = 8 examples. Their
  shared ``--check`` lives in ``scripts/ha_multiregion_common.run_cli``.
* Three single-example generators (``build_aws_infra_example.py``,
  ``build_gcp_example.py``, ``build_oci_example.py``) — 3 examples. Each has its
  own ``--check`` (added in task 18.2).

8 + 3 = 11, matching "all eleven Generated_Examples" in R8.1.

Invocation model
----------------
The generators import :mod:`rule_engine` and read ``mappings/*.yaml`` /
``assets/vendor/oci-stencils/stencils.json``, so they need the project venv
(PyYAML, the installed package). We invoke each generator as a **subprocess**
using ``sys.executable`` — under pytest that is the venv interpreter running the
suite, which is exactly the environment CI uses — and assert on the process exit
code. ``--check`` writes nothing, so this test never mutates ``examples/``.

Known-stale examples (pending task 22)
--------------------------------------
Task 5.2 made :class:`~rule_engine.diagram_layout.OciStencilIcon` emit an
``ociSlug=<slug>`` marker in each OCI node's group style (so the Icon_Verifier
can bind an embedded OCI glyph to its slug — R4.1). The committed OCI examples
predate that marker, so every OCI generator now reports STALE until the examples
are regenerated in **task 22.7**. Those generators are marked ``xfail`` on the
*strict-freshness* assertion here (``strict=False`` so they flip to XPASS — and
this test flips to strict — the moment task 22 regenerates them). For those
generators we still assert the ``--check`` **machinery** works: it exits cleanly
with 0 (fresh) or 1 (stale), never crashing (a non-``{0, 1}`` exit would signal
a broken ``--check``, e.g. a missing asset → exit 2, or a traceback).

When task 22/23 regenerates the OCI examples, delete the ``stale_task`` markers
below (and the ``xfail`` wiring keys off them), turning every generator strict.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "scripts"
_EXAMPLES = _REPO / "examples"


@dataclass(frozen=True)
class Generator:
    """One Example_Generator: its script, the committed examples it owns, and
    (optionally) the task that will make it fresh again."""

    script: str
    #: Committed ``.drawio`` paths (relative to ``examples/``) this script writes.
    examples: tuple[str, ...]
    #: When set, the generator is known-stale pending this task; its strict
    #: freshness assertion is xfailed until then.
    stale_task: str = ""
    #: Extra argv passed alongside ``--check`` (none of the generators need any).
    extra_args: tuple[str, ...] = field(default_factory=tuple)


# The seven generators and the eleven Generated_Examples they own (R8.1).
GENERATORS: tuple[Generator, ...] = (
    # --- four HA generators: each writes a summary + landscape pair (8) --------
    Generator(
        "build_aws_ha_example.py",
        ("aws/02-aws-ha-multiregion-summary.drawio",
         "aws/02-aws-ha-multiregion-landscape.drawio"),
    ),
    Generator(
        "build_azure_ha_example.py",
        ("azure/02-azure-ha-multiregion-summary.drawio",
         "azure/02-azure-ha-multiregion-landscape.drawio"),
    ),
    Generator(
        "build_gcp_ha_example.py",
        ("gcp/02-gcp-ha-multiregion-summary.drawio",
         "gcp/02-gcp-ha-multiregion-landscape.drawio"),
    ),
    Generator(
        "build_oci_ha_example.py",
        ("oci/02-oci-ha-multiregion-summary.drawio",
         "oci/02-oci-ha-multiregion-landscape.drawio"),
        # Regenerated in task 22.7/22.8 with the ociSlug= marker; now FRESH (exit
        # 0) whenever the OCI stencil pack is present. In a pack-less environment
        # its --check exits 2 (input asset missing), which the runner SKIPs.
    ),
    # --- three single-example generators (3) -----------------------------------
    Generator(
        "build_aws_infra_example.py",
        ("aws/03-aws-hybrid-infrastructure.drawio",),
    ),
    Generator(
        "build_gcp_example.py",
        ("gcp/01-gcp-vertex-pipeline.drawio",),
    ),
    Generator(
        "build_oci_example.py",
        ("oci/01-oci-genai-stack.drawio",),
        # Regenerated in task 22.7/22.8; now FRESH (exit 0) with the stencil pack
        # present, and SKIPped (exit 2, input asset missing) without it.
    ),
)


#: A generator whose ``--check`` returns exit 2 (a missing input asset, not a
#: broken check) with a message naming the missing stencil pack is SKIPped, not
#: failed — the pack-less CI ``test`` job does not fetch it. Recognised from the
#: generator's own message ("stencils not found" / "fetch_assets").
_MISSING_PACK_MARKERS = ("stencils not found", "fetch_assets")


def _run_check(gen: Generator) -> subprocess.CompletedProcess:
    """Run ``python <script> --check`` as a subprocess and return the result.

    ``sys.executable`` is the interpreter running pytest — under the project venv
    it carries PyYAML and the installed ``rule_engine`` package, so the generator
    imports resolve exactly as they do in CI. ``--check`` writes nothing."""
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / gen.script), "--check", *gen.extra_args],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_eleven_generated_examples_are_enumerated():
    """The table names all seven generators and exactly eleven examples (R8.1)."""
    assert len(GENERATORS) == 7
    all_examples = [ex for gen in GENERATORS for ex in gen.examples]
    assert len(all_examples) == 11, "R8.1 says eleven Generated_Examples"
    # No duplicate ownership: each committed example has exactly one generator.
    assert len(set(all_examples)) == 11


@pytest.mark.parametrize("gen", GENERATORS, ids=lambda g: g.script)
def test_generator_script_and_examples_exist(gen: Generator):
    """Every generator script and every committed example it owns is on disk."""
    assert (_SCRIPTS / gen.script).is_file(), f"missing generator {gen.script}"
    for ex in gen.examples:
        assert (_EXAMPLES / ex).is_file(), f"missing committed example examples/{ex}"


@pytest.mark.parametrize("gen", GENERATORS, ids=lambda g: g.script)
def test_generator_check_mode_runs(gen: Generator):
    """``--check`` runs and reports a *clean* freshness verdict.

    Exit 0 = fresh, exit 1 = stale. A generator known-stale pending task 22 is
    allowed to report 1 (the ``--check`` machinery is what matters here); every
    other generator must be fresh. Any exit code outside ``{0, 1}`` means
    ``--check`` itself is broken (a missing asset exits 2, a traceback exits
    non-zero-and-uncontrolled) and always fails.
    """
    result = _run_check(gen)
    diagnostics = (
        f"{gen.script} --check exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Exit 2 with a message naming the missing stencil pack is the generator's
    # CORRECT "input asset missing" signal — a build-environment condition, not a
    # broken --check. The pack-less CI ``test`` job does not fetch the OCI stencil
    # pack, so SKIP (with the fetch instruction) rather than fail. This keeps the
    # {0, 1} contract for every non-pack generator: a real crash (exit 2 with no
    # pack message, or any other non-zero) still fails below.
    message = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 2 and any(m in message for m in _MISSING_PACK_MARKERS):
        pytest.skip(
            f"{gen.script}: OCI stencil pack not fetched in this environment; "
            f"run scripts/fetch_assets.py --only oci to fetch it.\n{diagnostics}"
        )

    # The --check machinery must never crash: a controlled verdict is 0 or 1.
    assert result.returncode in (0, 1), diagnostics

    if gen.stale_task:
        # Known-stale pending task 22: assert only that the machinery works, and
        # xfail the strict-freshness expectation so it flips to XPASS (and this
        # test to strict) once the example is regenerated.
        if result.returncode != 0:
            pytest.xfail(
                f"examples/{gen.examples[0]} (+ pair) is STALE pending "
                f"{gen.stale_task} — OCI ociSlug= marker (task 5.2); "
                f"drop stale_task to make strict.\n{diagnostics}"
            )
        # It regenerated fresh already (task 22 done): fall through to strict.

    assert result.returncode == 0, (
        f"examples/{gen.examples} is STALE — regenerate with "
        f"`python scripts/{gen.script}`.\n{diagnostics}"
    )
