# Feature: placement-and-gates, Property 5: dead-space rule has no corpus false-positive
"""Property test for the ``container-dead-space`` lint rule (Part C).

Placement-and-gates release 1.9.0, Part C (tasks 8, 9, 9.2). Task 8 calibrated
:data:`rule_engine.geometry.DEAD_SPACE_RATIO` to 5.0 (the 57 shipped containers'
sparsest legitimate tier packs at ~4.536, so 5.0 sits above it with headroom);
task 9 implemented :func:`rule_engine.geometry.check_container_dead_space` and
wired the advisory ``container-dead-space`` WARNING rule.

This module holds **Property 5**:

* *Dead-space rule has no corpus false-positive.* Every Shipped_Diagram is clean
  under ``container-dead-space`` at the calibrated threshold — parametrised over
  the shipped corpus (``examples/**/*.drawio``), so a diagram whose containers
  are sized close to their children never flags.

Per the design testing strategy ("a synthetic over-sized container proves the
rule fires"), the module also exercises the fire path: a synthetic container
sized far larger than its lone child is flagged, a packed container is not, a
childless container is skipped rather than divided by zero, and the rule surfaces
as an advisory WARNING through the linter without blocking publication.

Conventions mirror the existing geometry tests (``test_geometry_hard_rules.py``,
``test_golden_examples.py``): the corpus is discovered exactly as the CLI would
(:func:`rule_engine.cli.discover_artifacts` + :func:`rule_engine.cli.parse_artifact`),
synthetic geometry is built directly from :class:`~rule_engine.geometry.Box`
inputs, and the Hypothesis profile lives in ``tests/conftest.py`` (loaded
automatically, ``max_examples=100``).

**Validates: Requirements 3.3**
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rule_engine import cli
from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, DEAD_SPACE_RATIO
from rule_engine.linter import Artifact, Severity, lint

# tests/ -> workspace root -> examples/.
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_ROOT = WORKSPACE_ROOT / "examples"


def _discover_example_drawios() -> List[str]:
    """Every committed ``.drawio`` source under ``examples/`` (CLI discovery).

    Uses the same discovery the ``rule-engine-lint --all`` CLI uses, then
    restricts to the ``.drawio`` sources under ``examples/`` — the Shipped_Diagram
    corpus Property 5 is parametrised over.
    """
    all_artifacts = cli.discover_artifacts(str(WORKSPACE_ROOT))
    examples_prefix = str(EXAMPLES_ROOT) + os.sep
    return sorted(
        a
        for a in all_artifacts
        if a.startswith(examples_prefix) and a.lower().endswith(".drawio")
    )


_EXAMPLE_DRAWIOS = _discover_example_drawios()


def _artifact_id(path: str) -> str:
    """Compact, stable test id: the artifact path relative to examples/."""
    return os.path.relpath(path, str(EXAMPLES_ROOT))


def _sev(result, rule):
    return next(
        (f["severity"] for f in result["findings"] if f["rule"] == rule), None
    )


# =========================================================================== #
# Property 5 — no corpus false-positive at the calibrated threshold
# =========================================================================== #


def test_discovery_found_drawios():
    """Discovery yielded at least one committed ``.drawio`` example source."""
    assert _EXAMPLE_DRAWIOS, f"no .drawio sources discovered under {EXAMPLES_ROOT}"


# Feature: placement-and-gates, Property 5: dead-space rule has no corpus false-positive
@pytest.mark.parametrize("drawio_path", _EXAMPLE_DRAWIOS, ids=_artifact_id)
def test_shipped_diagram_clean_under_dead_space(drawio_path):
    """Every Shipped_Diagram is clean under ``container-dead-space`` (R3.3, Property 5).

    Parse the diagram exactly as the CLI does and run
    :func:`geometry.check_container_dead_space` at the calibrated
    :data:`DEAD_SPACE_RATIO`. No shipped container may exceed the threshold — the
    threshold was set above the sparsest legitimate corpus tier precisely so no
    Shipped_Diagram false-positives.
    """
    art = cli.parse_artifact(drawio_path)
    g = art.geometry
    if g is None:
        pytest.skip(f"no parsed geometry for {drawio_path}")
    findings = geo.check_container_dead_space(g)
    assert findings == [], (
        f"container-dead-space false-positive in {drawio_path} at "
        f"threshold {DEAD_SPACE_RATIO}: "
        + ", ".join(f"{cid} (ratio {ratio:.3f})" for cid, ratio in findings)
    )


def test_whole_corpus_clean_as_one_gate():
    """The whole corpus is clean under the rule as one aggregate gate (Property 5).

    A single false-positive is reported alongside the corpus-wide list, mirroring
    the per-file parametrisation above but failing once for the whole corpus.
    """
    offenders = []
    for path in _EXAMPLE_DRAWIOS:
        g = cli.parse_artifact(path).geometry
        if g is None:
            continue
        for cid, ratio in geo.check_container_dead_space(g):
            offenders.append(f"{_artifact_id(path)}: {cid} (ratio {ratio:.3f})")
    assert not offenders, (
        "container-dead-space flagged shipped containers at threshold "
        f"{DEAD_SPACE_RATIO}:\n" + "\n".join(offenders)
    )


def test_calibrated_threshold_has_headroom_over_sparsest_corpus_tier():
    """The sparsest shipped container's ratio sits below the calibrated threshold.

    Property 5 is "no false-positive"; this pins *why* — the maximum ratio any
    shipped container reaches is strictly below :data:`DEAD_SPACE_RATIO`, so the
    corpus has headroom rather than passing by a hair.
    """
    max_ratio = 0.0
    saw_container = False
    for path in _EXAMPLE_DRAWIOS:
        g = cli.parse_artifact(path).geometry
        if g is None:
            continue
        # Re-measure every container's ratio at an effectively infinite threshold
        # so check_container_dead_space returns the raw ratio for all of them.
        raw = geo.check_container_dead_space(g, threshold=-1.0)
        for _cid, ratio in raw:
            saw_container = True
            max_ratio = max(max_ratio, ratio)
    assert saw_container, "expected the shipped corpus to contain containers"
    assert max_ratio < DEAD_SPACE_RATIO, (
        f"sparsest shipped container ratio {max_ratio:.3f} is not below the "
        f"calibrated threshold {DEAD_SPACE_RATIO} — no headroom"
    )


# =========================================================================== #
# The fire path — a synthetic over-sized container proves the rule DOES fire
# (design Testing Strategy, Part C)
# =========================================================================== #


def test_synthetic_oversized_container_fires():
    """A container sized far larger than its lone child is flagged.

    A single 78x78 node inside a 2000x2000 container: the child's
    footprint+padding demand is tiny relative to the container area, so the ratio
    is well above the threshold and the rule fires, naming the container.
    """
    g = DiagramGeometry(
        nodes={"n": Box("n", 100, 100, 78, 78)},
        containers={"huge": Box("huge", 0, 0, 2000, 2000)},
    )
    findings = geo.check_container_dead_space(g)
    assert any(cid == "huge" for cid, _ratio in findings), findings
    # And the reported ratio genuinely exceeds the threshold.
    ratio = next(r for cid, r in findings if cid == "huge")
    assert ratio > DEAD_SPACE_RATIO


def test_synthetic_packed_container_is_clean():
    """A container sized close to its child's footprint+padding is not flagged.

    The mirror of the fire test: a 78x78 node in a container just large enough to
    give it one grid-step of padding on every side packs near ratio ~1.0, well
    under the threshold, so the rule stays silent.
    """
    pad = geo.CONTAINER_PAD
    # Child footprint is 78 wide, (78 + LABEL_BAND) tall; grow by pad on all sides.
    fw = 78 + 2 * pad
    fh = 78 + geo.LABEL_BAND + 2 * pad
    g = DiagramGeometry(
        nodes={"n": Box("n", pad, pad, 78, 78)},
        containers={"snug": Box("snug", 0, 0, fw, fh)},
    )
    assert geo.check_container_dead_space(g) == []


def test_childless_container_is_skipped():
    """A container with no direct children is skipped, never divided by zero.

    Design Error Handling: "a container with no children is skipped rather than
    divided by zero."
    """
    g = DiagramGeometry(containers={"empty": Box("empty", 0, 0, 5000, 5000)})
    assert geo.check_container_dead_space(g) == []


# =========================================================================== #
# Hypothesis property — the rule fires above and stays clean below the threshold
# for a single-child container (the ratio is monotone in container area)
# =========================================================================== #


# Feature: placement-and-gates, Property 5: dead-space rule has no corpus false-positive
@given(
    scale=st.floats(min_value=1.05, max_value=8.0, allow_nan=False, allow_infinity=False),
)
def test_single_child_container_fires_iff_above_threshold(scale):
    """For a single-child container, the rule fires exactly when area/demand > threshold.

    Build a container whose area is ``scale`` times the child's single-source
    footprint+padding demand, then confirm the rule fires iff ``scale`` exceeds
    the calibrated ratio. This exercises both sides of the threshold with one
    generator (the demand is one child, so ``ratio == scale`` by construction).
    """
    pad = geo.CONTAINER_PAD
    demand = (78 + 2 * pad) * (78 + geo.LABEL_BAND + 2 * pad)
    area = scale * demand
    # A square container of the target area, child centred inside it.
    side = area ** 0.5
    g = DiagramGeometry(
        nodes={"n": Box("n", side / 2 - 39, side / 2 - 39, 78, 78)},
        containers={"c": Box("c", 0, 0, side, side)},
    )
    findings = geo.check_container_dead_space(g)
    fired = any(cid == "c" for cid, _ in findings)
    assert fired == (scale > DEAD_SPACE_RATIO), (scale, findings)


# =========================================================================== #
# Linter integration — advisory WARNING, never blocks (R3.2, R3.4)
# =========================================================================== #


def _oversized_geo():
    return DiagramGeometry(
        nodes={"n": Box("n", 100, 100, 78, 78)},
        containers={"huge": Box("huge", 0, 0, 2000, 2000)},
    )


def test_dead_space_is_warning_on_flow():
    art = Artifact(kind="diagram", node_names=["n"], geometry=_oversized_geo())
    assert _sev(lint(art), "container-dead-space") == Severity.WARNING.value


def test_dead_space_is_warning_on_landscape_not_escalated():
    """Unlike the routing-family rules, dead-space is advisory on BOTH classes —
    it is not escalated to ERROR for landscape (design Component C1, R3.4)."""
    art = Artifact(
        kind="diagram",
        diagram_class="landscape",
        node_names=["n"],
        summary_of="01-x-summary",
        geometry=_oversized_geo(),
    )
    assert _sev(lint(art), "container-dead-space") == Severity.WARNING.value


def test_dead_space_warning_does_not_block_publication():
    """The advisory WARNING never blocks on its own (R3.4): an artifact whose only
    finding is container-dead-space is still eligible for publication."""
    art = Artifact(kind="diagram", node_names=["n"], geometry=_oversized_geo())
    result = lint(art)
    assert _sev(result, "container-dead-space") == Severity.WARNING.value
    assert result["eligible_for_publication"] is True, result["findings"]
