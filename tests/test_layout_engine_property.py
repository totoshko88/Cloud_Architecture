"""Feature: lane-grid-layout-engine, Property: layout output passes the geometry oracle.

Property (Validates: Requirements 9.3, 10.3):
For a generated family of small, valid ``DiagramSpec``s, WHEN ``layout(spec)``
succeeds THEN its placed output passes every geometry ``check_*`` validator with
zero blocking (ERROR/CRITICAL) findings — the oracle *is* the invariant
(design.md → "Testing strategy / Property-based"). The engine does not
re-implement the constraints; it produces a candidate and the ``check_*``
functions judge it, so "the output is publication-eligible" is exactly
"``_run_oracle`` reports no blocking findings".

The generator builds *layout-able* specs by construction, mirroring the shape the
HA landscape uses: a nested ``account ⊃ vpc ⊃ az`` container tree, two
mirror-symmetric regions ``a``/``b`` with a small number of workers/data slots
each, and edges that reference declared nodes and classify into the five
supported edge kinds. A spec that legitimately cannot be laid out (an
over-connected node, or a candidate the bounded repair loop cannot clear) raises
``LayoutError``/``OverConnectedError``; per the design the invariant is
conditional on layout *succeeding*, so such a spec is excluded with
``hypothesis.assume`` rather than counted as a counterexample.

Serialization is reused from the engine (``_run_oracle`` →
``_serialize_candidate`` → ``build_geometry`` → the geometry ``check_*`` set), so
the property judges exactly what the linter would parse rather than
re-implementing serialization.
"""

from __future__ import annotations

from typing import List

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rule_engine.geometry import build_geometry as _build_geometry
from rule_engine.geometry import check_grid_alignment
from rule_engine.layout_engine import (
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    GRID,
    LayoutError,
    NodeSpec,
    OverConnectedError,
    _run_oracle,
    _serialize_candidate,
    _validate_spec,
    layout,
)


@st.composite
def _small_valid_spec(draw: st.DrawFn) -> DiagramSpec:
    """Generate a small, valid, layout-able ``DiagramSpec``.

    Structure (matching the HA landscape shape so the engine can place it):

    * a single ``account`` container wrapping two peer ``vpc`` bands (region
      ``a`` / region ``b``), each vpc wrapping one or two ``az`` boxes;
    * for each region, ``workers`` and ``data`` lanes with a Hypothesis-chosen
      slot count (unique ``(lane, region, slot)`` keys by construction);
    * a handful of edges that always reference declared nodes and classify into
      the five supported kinds — kept to at most three per source side so the
      generator never *forces* an over-connected node.

    ``axis`` is drawn from both supported values so the invariant is exercised on
    each layout axis.
    """
    axis = draw(st.sampled_from(("north-south", "left-right")))
    workers_per_region = draw(st.integers(min_value=1, max_value=3))
    data_per_region = draw(st.integers(min_value=1, max_value=2))
    az_per_region = draw(st.integers(min_value=1, max_value=2))

    nodes: List[NodeSpec] = []
    for region in ("a", "b"):
        for slot in range(workers_per_region):
            nodes.append(
                NodeSpec(
                    id=f"w{region}{slot}",
                    role="serverless_fn",
                    lane="workers",
                    region=region,
                    slot=slot,
                )
            )
        for slot in range(data_per_region):
            nodes.append(
                NodeSpec(
                    id=f"d{region}{slot}",
                    role="managed_sql",
                    lane="data",
                    region=region,
                    slot=slot,
                )
            )

    containers = [
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ContainerSpec(id="vpc-b", kind="vpc", region="b", parent="acct", label_key="vpc"),
    ]
    for region in ("a", "b"):
        for i in range(1, az_per_region + 1):
            containers.append(
                ContainerSpec(
                    id=f"az-{region}{i}",
                    kind="az",
                    region=region,
                    parent=f"vpc-{region}",
                    label_key="az",
                )
            )

    # Candidate edges, each referencing declared nodes. Every pair below sits at
    # distinct grid positions, so classify_edge always resolves them to one of
    # the five kinds (a same-region worker→data tier hop is a spine; the
    # region-a→region-b worker link is a cross-region hop).
    candidate_edges: List[EdgeSpec] = []
    for region in ("a", "b"):
        # worker slot 0 → data slot 0 within the region (spine)
        candidate_edges.append(
            EdgeSpec(id=f"e-{region}-wd", source=f"w{region}0", target=f"d{region}0", marker="1")
        )
    # a cross-region worker link (region a → region b)
    candidate_edges.append(EdgeSpec(id="e-xr", source="wa0", target="wb0", marker="2"))

    # Choose a subset of the candidate edges to include (possibly none), so the
    # family covers edge-free and multi-edge diagrams alike. Selecting a subset
    # (rather than adding arbitrary edges) keeps every source side well under the
    # three-exit cap, so the generator never deliberately over-connects a node.
    include = draw(
        st.lists(
            st.booleans(),
            min_size=len(candidate_edges),
            max_size=len(candidate_edges),
        )
    )
    edges = tuple(e for e, keep in zip(candidate_edges, include) if keep)

    spec = DiagramSpec(
        diagram_id="prop",
        diagram_name="property",
        axis=axis,
        nodes=tuple(nodes),
        edges=edges,
        containers=tuple(containers),
        flow_lines=("Flow", "1. worker to data", "2. region a to region b"),
        title="prop workload — acct / region | 2025-01-15 | v1",
    )
    # The generator is valid by construction; this asserts the contract loudly if
    # a future edit to the strategy breaks it.
    _validate_spec(spec)
    return spec


@settings(max_examples=150)
@given(spec=_small_valid_spec())
def test_layout_output_passes_every_geometry_check(spec: DiagramSpec) -> None:
    """WHEN ``layout(spec)`` succeeds, its output has zero blocking geometry findings.

    Reuses the engine's own oracle (``_run_oracle`` → ``_serialize_candidate`` →
    ``build_geometry`` → the geometry ``check_*`` set) so the property judges
    exactly the parsed geometry the linter sees. A spec the engine legitimately
    cannot lay out (over-connected node, or unrepairable within the bound) raises
    and is excluded — the invariant is conditional on layout succeeding
    (Req 9.3, 10.3)."""
    try:
        placed = layout(spec)
    except (LayoutError, OverConnectedError):
        # A spec the engine refuses (fail-honest) is not a counterexample: the
        # invariant is "WHEN layout succeeds, the output passes every check_*".
        assume(False)
        return

    findings = _run_oracle(placed)
    assert findings.clean, (
        "layout output has blocking geometry findings: "
        f"{findings.blocking!r}"
    )

    # Also exercise grid-alignment on the same serialized geometry the oracle
    # parsed: every emitted node origin is a whole GRID multiple (Req 11.4).
    geo = _build_geometry(_serialize_candidate(placed))
    assert check_grid_alignment(geo) == [], "layout output has off-grid nodes"
    for box in list(placed.nodes.values()) + list(placed.containers.values()):
        assert box.x % GRID == 0 and box.y % GRID == 0
