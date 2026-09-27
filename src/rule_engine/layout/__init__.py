"""The ``layout/`` package (scored-router release 1.8.0, Phase A).

The layout engine is split from the single ``layout_engine.py`` module into
this package behind a stable seam (design.md §``layout/`` package seam). As of
task 1.4 the split is complete: the model types live in
:mod:`rule_engine.layout.model`, the placement base kernel in
:mod:`rule_engine.layout.base`, placement / contacts / corridors / routers in
their own submodules, the oracle-and-repair finishing stage in
:mod:`rule_engine.layout.repair`, and the entry point plus the retained ten-pass
``Legacy_Path`` in :mod:`rule_engine.layout.pipeline`. The two scored-router
seams, :mod:`rule_engine.layout.variants` and :mod:`rule_engine.layout.solver`,
are present but **unwired** — nothing on the default :func:`layout` path imports
them (R1.6).

This package is now the *source* of the public surface: :func:`layout`,
:class:`DiagramSpec` and :class:`PlacedDiagram` are re-exported here, and
``layout_engine`` is a thin re-export shim over the package. Both
``from rule_engine.layout import layout`` and
``from rule_engine.layout_engine import layout`` therefore resolve to the **same**
function object (R1.1).

The relocation is **behavior-preserving**: :func:`layout` runs the exact
pre-split pipeline (scored solver off), so every shipped ``.drawio`` stays
byte-identical (R1.2, Property 1).

Because the whole dependency graph is now one-directional
(``model``/``base`` → ``place``/``routers``/``repair`` → ``pipeline``), the
package no longer needs the lazy ``layout_engine`` re-export it used before the
split — :func:`layout` is imported directly from :mod:`rule_engine.layout.pipeline`.
"""

from __future__ import annotations

from .model import DiagramSpec, PlacedDiagram

try:  # package-relative import when used as ``rule_engine.layout``
    from .pipeline import layout
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from layout.pipeline import layout  # type: ignore[no-redef]

__all__ = ["layout", "DiagramSpec", "PlacedDiagram"]
