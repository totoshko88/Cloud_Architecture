"""Example tests for the ``layout/`` package public import surface and the
unwired scored-router seam (scored-router release 1.8.0, Phase A, task 1.6).

These are **example** tests (not property-based). They pin the three things the
behavior-preserving split promises about its interface, independently of the
byte-identity property test (task 1.5 / Property 1):

* **R1.1 — one public import surface.** Both
  ``from rule_engine.layout_engine import layout`` and
  ``from rule_engine.layout import layout`` must resolve to the *same* function
  object, and the same must hold for a sampling of the previously-public symbols
  (``DiagramSpec``, ``PlacedDiagram``, ``CorridorAllocator``, ``classify_edge``)
  — the shim re-exports, it does not re-define.
* **R1.6 — the scored-router seam exists but is unwired.**
  :mod:`rule_engine.layout.variants` and :mod:`rule_engine.layout.solver` import
  cleanly and expose their stub symbols (``RouteVariant`` / ``RoutePlan`` /
  ``generate`` / ``solve`` / ``RoutedEdges``), yet nothing on the default
  :func:`layout` path references them — proven behaviorally by a normal
  ``layout(spec)`` call succeeding without tripping the ``NotImplementedError``
  the unwired ``generate``/``solve`` stubs raise.
* **R1.4 — no test change forced by the relocation.** Proven by the whole suite
  passing unchanged; this file adds tests, it does not edit existing ones.

The behavioral R1.6 check reuses the committed ``SUMMARY_SPEC`` from
``rule_engine.ha_multiregion_spec`` — the same known-good spec
``tests/test_layout_engine.py`` runs through ``layout()`` — so it exercises the
real default pipeline end-to-end rather than a hand-built spec.

Requirements: R1.1, R1.4, R1.6
"""

from __future__ import annotations

import importlib

from rule_engine import layout as layout_pkg
from rule_engine import layout_engine as le
from rule_engine.layout import DiagramSpec, layout

# A committed, known-good spec the engine places and routes cleanly end-to-end
# (``tests/test_layout_engine.py`` runs it through ``le.layout()``). Reusing it
# keeps the behavioral R1.6 check off a hand-built spec that the repair loop
# might legitimately reject.
from rule_engine.ha_multiregion_spec import SUMMARY_SPEC


# --------------------------------------------------------------------------- #
# R1.1 — the two import paths resolve to the same objects (shim re-exports).
# --------------------------------------------------------------------------- #

def test_layout_resolves_to_the_same_function_object_from_both_paths():
    # from rule_engine.layout_engine import layout
    # from rule_engine.layout import layout
    # must be the SAME function object — the shim re-exports, never re-defines.
    assert le.layout is layout
    assert layout_pkg.layout is layout
    assert le.layout is layout_pkg.layout


def test_previously_public_symbols_resolve_identically_from_both_paths():
    # A sampling across the model, corridors and routers submodules: each
    # previously-public symbol is one object, exposed under both import paths.
    assert le.DiagramSpec is layout_pkg.DiagramSpec
    assert le.PlacedDiagram is layout_pkg.PlacedDiagram

    # CorridorAllocator and classify_edge live in submodules but are re-exposed
    # on the shim; import them from the package's submodules and confirm identity.
    from rule_engine.layout.corridors import CorridorAllocator as pkg_allocator
    from rule_engine.layout.routers import classify_edge as pkg_classify

    assert le.CorridorAllocator is pkg_allocator
    assert le.classify_edge is pkg_classify

    # The package __init__ re-exports the two headline model types; the shim's
    # DiagramSpec/PlacedDiagram are those very objects (not copies). The
    # module-level ``DiagramSpec`` imported from ``rule_engine.layout`` is the
    # same object the shim exposes.
    assert DiagramSpec is layout_pkg.DiagramSpec
    assert le.DiagramSpec is DiagramSpec


# --------------------------------------------------------------------------- #
# R1.6 — the scored-router seam imports cleanly and exposes its stub symbols.
# --------------------------------------------------------------------------- #

def test_variants_module_imports_cleanly_and_exposes_its_symbols():
    variants = importlib.import_module("rule_engine.layout.variants")

    # The stub's frozen interface is present and type-complete.
    assert hasattr(variants, "RouteVariant")
    assert hasattr(variants, "RoutePlan")
    assert hasattr(variants, "generate")
    assert callable(variants.generate)

    # RoutePlan always carries the rule-based route as one sanctioned shape.
    assert variants.RoutePlan.RULE_BASED.value == "rule-based"

    # RouteVariant is the frozen (id, exit, entry, plan, rank) dataclass.
    import dataclasses

    assert dataclasses.is_dataclass(variants.RouteVariant)
    field_names = {f.name for f in dataclasses.fields(variants.RouteVariant)}
    assert field_names == {"id", "exit", "entry", "plan", "rank"}


def test_solver_module_imports_cleanly_and_exposes_its_symbols():
    solver = importlib.import_module("rule_engine.layout.solver")

    assert hasattr(solver, "solve")
    assert callable(solver.solve)
    # RoutedEdges alias is present (the routed edge set the solver will commit).
    assert hasattr(solver, "RoutedEdges")


def test_solver_solve_is_implemented_but_still_unwired():
    # ``solver.solve`` is NO LONGER a bodyless stub: task 7.1 implemented the
    # real order-score-commit loop. It remains **unwired** on the default path
    # (nothing in the pipeline imports or calls it — proven by the two R1.6
    # tests below), but calling it directly now routes a placed spec instead of
    # raising ``NotImplementedError``.
    #
    # This mirrors ``variants.generate`` (task 6.1): both are implemented,
    # exercised by their own property tests, and still not on the default path.
    # The R1.6 guarantee is enforced by the behavioral + static tests below, not
    # by the solver raising when touched.
    solver = importlib.import_module("rule_engine.layout.solver")
    from rule_engine.layout.corridors import CorridorAllocator
    from rule_engine.layout.place import (
        centre_block_in_vpc,
        place_nodes,
        size_containers,
    )

    # Place the summary spec through the real place → size → centre stages, then
    # route it with the scored solver directly.
    placed = place_nodes(SUMMARY_SPEC)
    containers = size_containers(placed, SUMMARY_SPEC)
    placed = centre_block_in_vpc(placed, containers, SUMMARY_SPEC)

    routed = solver.solve(placed, containers, SUMMARY_SPEC, CorridorAllocator())

    # One committed edge per declared edge, in declared order (R3.7, R4.1).
    assert [pe.spec.id for pe in routed] == [e.id for e in SUMMARY_SPEC.edges]
    # Deterministic: a second run on a fresh allocator is identical (R3.9).
    routed2 = solver.solve(placed, containers, SUMMARY_SPEC, CorridorAllocator())
    assert [(pe.exit, pe.entry, tuple(pe.points)) for pe in routed] == [
        (pe.exit, pe.entry, tuple(pe.points)) for pe in routed2
    ]


def test_variants_generate_is_implemented_but_still_unwired():
    # Task 6.1: ``variants.generate`` is now a real, pure generator — it returns
    # a non-empty, rank-ordered, contract-legal list with the rule-based route
    # first (rank 0). It remains unwired on the default path (the two R1.6 tests
    # below prove the pipeline never calls it).
    variants = importlib.import_module("rule_engine.layout.variants")
    from rule_engine.geometry import Box
    from rule_engine.layout.model import EdgeSpec

    # A minimal same-column spine: source over a directly-below target.
    placed = {
        "s": Box(id="s", x=100, y=100, w=78, h=78),
        "t": Box(id="t", x=100, y=100 + 160, w=78, h=78),
    }
    edge = EdgeSpec(id="e1", source="s", target="t", marker="1")
    result = variants.generate(edge, placed, containers={}, kind="spine")

    assert result, "generate must never be empty (R3.3)"
    assert result[0].plan is variants.RoutePlan.RULE_BASED
    assert result[0].rank == 0
    ranks = [v.rank for v in result]
    assert ranks == sorted(ranks), "variants must be rank-ordered"
    for v in result:  # every variant contract-legal (R3.4)
        ex_ok = (v.exit[0] is not None and v.exit[0] >= 1.0) or (
            v.exit[1] is not None and v.exit[1] >= 1.0
        )
        en_ok = (v.entry[0] is not None and v.entry[0] <= 0.0) or (
            v.entry[1] is not None and v.entry[1] <= 0.0
        )
        assert ex_ok, f"illegal exit {v.exit} in {v.id}"
        assert en_ok, f"illegal entry {v.entry} in {v.id}"


# --------------------------------------------------------------------------- #
# R1.6 — the default layout() path does NOT reference the unwired seam.
# --------------------------------------------------------------------------- #

def test_default_layout_runs_without_touching_the_unwired_seam():
    # If the default pipeline referenced variants.generate / solver.solve, this
    # normal layout() call would raise NotImplementedError from the stubs. It
    # succeeds instead — behavioral evidence that nothing on the default path
    # imports or calls the scored-router seam (R1.6).
    placed = layout(SUMMARY_SPEC)

    # Sanity: we got a placed diagram back with the spec's nodes laid out.
    assert placed is not None
    assert isinstance(placed, layout_pkg.PlacedDiagram)
    assert placed.nodes  # non-empty placement


def test_pipeline_imports_the_solver_as_the_default_route():
    # Task 7.3 wires the scored solver in as the DEFAULT routing stage, so the
    # Phase-A "unwired" invariant no longer holds: pipeline now imports
    # ``solver.solve`` and calls it on the non-``--legacy`` path. The variant
    # generator stays one level down — the pipeline reaches it through the
    # solver, never directly — so ``variants.generate`` is still not referenced
    # in the pipeline source.
    import inspect

    from rule_engine.layout import pipeline

    src = inspect.getsource(pipeline)
    assert "from .solver import solve" in src or "solver import solve" in src
    # The pipeline drives the solver, not the variant generator directly.
    assert "variants.generate" not in src
