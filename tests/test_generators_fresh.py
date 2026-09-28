"""Freshness test for every Generated_Example (R8.1).

Every Example_Generator has a ``--check`` mode that regenerates its output in
memory and compares it with the committed file, writing nothing. This test runs
that mode for every generator in the shared table
``scripts/regen_examples.GENERATORS`` — the same table
``python scripts/regen_examples.py`` uses to regenerate the examples, so the list
of checked generators and the list of regenerated ones cannot drift.

Coverage: nine generators, thirteen Generated_Examples. The four HA generators
each write a summary + landscape pair (8); five single-example generators write
one each (aws infra, gcp, oci, generic, cross-cloud). Before the process fix
after 1.10.1 this test hard-coded seven generators and missed the generic and
cross-cloud builders.

Each generator runs as a subprocess with ``sys.executable`` (the venv running
pytest), so its imports resolve exactly as in CI. A generator that exits 2
naming the missing OCI stencil pack is SKIPPED: the pack-less CI ``test`` job
does not fetch it, and that is a build-environment condition, not a broken
``--check``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from regen_examples import (  # noqa: E402
    EXAMPLES,
    GENERATORS,
    SCRIPTS,
    Generator,
    is_missing_pack,
    run_script,
)


def test_generator_table_is_complete():
    """Nine generators own thirteen distinct examples, one owner each."""
    assert len(GENERATORS) == 9
    owned = [ex for gen in GENERATORS for ex in gen.examples]
    assert len(owned) == 13
    assert len(set(owned)) == 13, "an example has more than one generator"


def test_every_builder_script_is_in_the_table():
    """A new ``build_*_example.py`` must be registered, or it is never checked."""
    on_disk = {p.name for p in SCRIPTS.glob("build_*_example.py")}
    in_table = {g.script for g in GENERATORS}
    assert on_disk == in_table, (
        f"unregistered generators: {sorted(on_disk - in_table)}; "
        f"registered but missing: {sorted(in_table - on_disk)}"
    )


@pytest.mark.parametrize("gen", GENERATORS, ids=lambda g: g.script)
def test_generator_script_and_examples_exist(gen: Generator):
    assert (SCRIPTS / gen.script).is_file(), f"missing generator {gen.script}"
    for ex in gen.examples:
        assert (EXAMPLES / ex).is_file(), f"missing committed example examples/{ex}"


@pytest.mark.parametrize("gen", GENERATORS, ids=lambda g: g.script)
def test_generator_output_is_fresh(gen: Generator):
    """``--check`` exits 0: the committed examples match the generator."""
    result = run_script(gen.script, "--check", *gen.extra_args)
    diagnostics = (
        f"{gen.script} --check exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    if is_missing_pack(result):
        pytest.skip(f"OCI stencil pack not fetched; run scripts/fetch_assets.py --only oci\n{diagnostics}")
    assert result.returncode in (0, 1), f"--check crashed\n{diagnostics}"
    assert result.returncode == 0, (
        f"examples/{gen.examples} is STALE; regenerate with "
        f"`python scripts/regen_examples.py`\n{diagnostics}"
    )
