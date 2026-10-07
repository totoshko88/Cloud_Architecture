"""Declarative lane-grid layout engine — re-export shim over ``layout/``.

Historically this module *was* the layout engine (≈3,960 lines). As of
scored-router release 1.8.0 Phase A the engine lives in the
:mod:`rule_engine.layout` package (design.md §``layout/`` package seam), and
this module is a **pure re-export shim**: it imports the package's public and
previously-public symbols and re-exposes them under their original names, so
every existing caller keeps working with no edit.

Both ``from rule_engine.layout_engine import layout`` and
``from rule_engine.layout import layout`` resolve to the **same** function
object (R1.1), and ``rule_engine.layout_engine.<name>`` still resolves for every
symbol the pre-split module exposed — the public surface (``layout``,
``DiagramSpec``, ``PlacedDiagram``, the routers, the constants) **and** the
private helpers tests import directly (``_detour_clockwise_if_blocked``,
``MERGE_THRESHOLD``, ``CorridorAllocator``, ``_place_base``, ``_run_oracle``, …).

The engine's code now lives in these package modules, imported below:

* :mod:`rule_engine.layout.model`     — the declaration + placed-geometry model
* :mod:`rule_engine.layout.base`      — lane table, ``SpecError`` /
  ``_validate_spec``, region/title constants, ``_snap`` and the placement kernel
* :mod:`rule_engine.layout.place`     — ``place_nodes`` / ``size_containers`` /
  ``centre_block_in_vpc``
* :mod:`rule_engine.layout.contacts`  — ``select_contacts`` + the contact ladder
* :mod:`rule_engine.layout.corridors` — ``CorridorAllocator``
* :mod:`rule_engine.layout.routers`   — ``classify_edge`` + the ``route_*``
  routers + routing helpers
* :mod:`rule_engine.layout.repair`    — ``place_legend``, the oracle adapter, the
  repair loop, ``orthogonalise_candidate`` and their constants
* :mod:`rule_engine.layout.pipeline`  — ``layout`` and the retained ten-pass
  ``Legacy_Path`` (``_place_and_route`` / ``_normalise_origin``)

The scored-router seams :mod:`rule_engine.layout.variants` and
:mod:`rule_engine.layout.solver` exist but are **unwired** — this shim does not
import them into the default surface, and nothing on the default ``layout``
path references them (R1.6).

Design references: ``.kiro/specs/scored-router/design.md`` (§``layout/`` package
seam, Component 5) and ``.kiro/specs/lane-grid-layout-engine`` (the original
engine spec).
"""

from __future__ import annotations

# Incidental module-level names the pre-split module exposed (typing aliases,
# ``math``, ``dataclass``). Re-exported so any caller that reached them through
# ``rule_engine.layout_engine`` keeps resolving.
import math  # noqa: F401
from dataclasses import dataclass  # noqa: F401
from typing import Dict, List, Optional, Tuple  # noqa: F401

try:  # package-relative import when used as ``rule_engine.layout_engine``
    # Canonical layout constants (never redefined — sourced from diagram_layout).
    from .diagram_layout import (  # noqa: F401
        ICON_SIZE,
        GRID,
        COL_STEP,
        ROW_STEP,
        CONTAINER_PAD,
        STAIR_STEP,
    )
    # Geometry helpers the pre-split module re-exposed.
    from .geometry import (  # noqa: F401
        Box,
        LABEL_BAND,
        CONTAINER_LABEL_BAND,
        contact_faces,
        leg_axis as _leg_axis,
        orthogonalise_route,
        segment_crosses_box,
    )
    # Declaration + placed-geometry model.
    from .layout.model import (  # noqa: F401
        Contact,
        Point,
        NodeSpec,
        EdgeSpec,
        ContainerSpec,
        DiagramSpec,
        PlacedEdge,
        PlacedDiagram,
    )
    # Placement base kernel — lane table, validation, constants, helpers.
    from .layout.base import (  # noqa: F401
        LANES,
        LANE_INDEX,
        SpecError,
        _validate_spec,
        REGION_GAP,
        REGION_STEP,
        SUB_STEP,
        _ORIGIN,
        TITLE_BAND,
        _snap,
        _secondary_axis,
        _az_ordinals,
        _vpcs_with_service_row,
        _node_az_band,
        _band_within,
        _band_packing,
        _place_base,
        _region_secondary_offset,
        _container_axes,
        _children_of,
        _leaf_region_containers,
        _assign_nodes_to_leaves,
        _bbox,
        _extent,
        _with_extent,
        _stack_peer_azs_in_vpc,
        _equalize_peer_widths,
        _size_account,
    )
    # Corridors.
    from .layout.corridors import (  # noqa: F401
        CorridorAllocator,
        CorridorExhaustedError,
    )
    # Contacts — ladder helpers, constants, spreads.
    from .layout.contacts import (  # noqa: F401
        MERGE_THRESHOLD,
        MAX_SIDE_EXITS,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
        OverConnectedError,
        _boxes_adjacent,
        _box_directly_below,
        select_contacts,
        _exit_side,
        _band_coord,
        _with_band,
        _entry_face,
        _entry_band,
        _with_entry_band,
        spread_entries,
        spread_contacts,
    )
    # Placement.
    from .layout.place import (  # noqa: F401
        place_nodes,
        size_containers,
        centre_block_in_vpc,
    )
    # Routers + routing helpers.
    from .layout.routers import (  # noqa: F401
        EDGE_KINDS,
        CROSS_REGION_SPAN,
        UnclassifiableEdgeError,
        _same_row,
        classify_edge,
        _contact_point,
        _grid_contact,
        _obstacles_between,
        _relevant_obstacles,
        route_straight,
        _stair_first_waypoint,
        _gap_column_x,
        _enclosing_container,
        _free_left_corridor_x,
        _fanout_above_row,
        route_spine,
        route_fan_out_row,
        _hcorridor_below,
        _exit_band_rank,
        decide_lane_sides,
        _assign_exit_bands,
        _has_free_left_approach,
        _target_container_top,
        _box_contains,
        _caption_free_band,
        _column_is_clear,
        _free_drop_column,
        _hcorridor_band,
        route_cross_region,
        route_back_edge,
        ROUTERS,
        route_edge,
        obstacle_box,
        _allocate_or_first,
        _dedupe_axis_collapse,
        _corner_detour,
        _detour_clockwise_if_blocked,
        _interior_waypoints,
    )
    # Oracle adapter, repair loop, and right-margin Flow/Legend placement.
    from .layout.repair import (  # noqa: F401
        LEGEND_W,
        place_legend,
        place_legend_for,
        legend_clear_right,
        MAX_REPAIR_ITERS,
        LayoutError,
        OracleFindings,
        _STUB_ICON_STYLE,
        _stub_boundary_style,
        _serialize_candidate,
        _collect_findings,
        _BLOCKING_RULES,
        _FIXABLE_RULES,
        _run_oracle,
        _grow_container,
        _bump_edge_corridor,
        orthogonalise_candidate,
        _repair,
        _dl,
        _geo,
    )
    # Pipeline entry point + retained ten-pass Legacy_Path.
    from .layout.pipeline import (  # noqa: F401
        layout,
        _place_and_route,
        _normalise_origin,
    )
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import (  # type: ignore[no-redef]  # noqa: F401
        ICON_SIZE,
        GRID,
        COL_STEP,
        ROW_STEP,
        CONTAINER_PAD,
        STAIR_STEP,
    )
    from geometry import (  # type: ignore[no-redef]  # noqa: F401
        Box,
        LABEL_BAND,
        CONTAINER_LABEL_BAND,
        contact_faces,
        leg_axis as _leg_axis,
        orthogonalise_route,
        segment_crosses_box,
    )
    from layout.model import (  # type: ignore[no-redef]  # noqa: F401
        Contact,
        Point,
        NodeSpec,
        EdgeSpec,
        ContainerSpec,
        DiagramSpec,
        PlacedEdge,
        PlacedDiagram,
    )
    from layout.base import (  # type: ignore[no-redef]  # noqa: F401
        LANES,
        LANE_INDEX,
        SpecError,
        _validate_spec,
        REGION_GAP,
        REGION_STEP,
        SUB_STEP,
        _ORIGIN,
        TITLE_BAND,
        _snap,
        _secondary_axis,
        _az_ordinals,
        _vpcs_with_service_row,
        _node_az_band,
        _band_within,
        _band_packing,
        _place_base,
        _region_secondary_offset,
        _container_axes,
        _children_of,
        _leaf_region_containers,
        _assign_nodes_to_leaves,
        _bbox,
        _extent,
        _with_extent,
        _stack_peer_azs_in_vpc,
        _equalize_peer_widths,
        _size_account,
    )
    from layout.corridors import (  # type: ignore[no-redef]  # noqa: F401
        CorridorAllocator,
        CorridorExhaustedError,
    )
    from layout.contacts import (  # type: ignore[no-redef]  # noqa: F401
        MERGE_THRESHOLD,
        MAX_SIDE_EXITS,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
        OverConnectedError,
        _boxes_adjacent,
        _box_directly_below,
        select_contacts,
        _exit_side,
        _band_coord,
        _with_band,
        _entry_face,
        _entry_band,
        _with_entry_band,
        spread_entries,
        spread_contacts,
    )
    from layout.place import (  # type: ignore[no-redef]  # noqa: F401
        place_nodes,
        size_containers,
        centre_block_in_vpc,
    )
    from layout.routers import (  # type: ignore[no-redef]  # noqa: F401
        EDGE_KINDS,
        CROSS_REGION_SPAN,
        UnclassifiableEdgeError,
        _same_row,
        classify_edge,
        _contact_point,
        _grid_contact,
        _obstacles_between,
        _relevant_obstacles,
        route_straight,
        _stair_first_waypoint,
        _gap_column_x,
        _enclosing_container,
        _free_left_corridor_x,
        _fanout_above_row,
        route_spine,
        route_fan_out_row,
        _hcorridor_below,
        _exit_band_rank,
        decide_lane_sides,
        _assign_exit_bands,
        _has_free_left_approach,
        _target_container_top,
        _box_contains,
        _caption_free_band,
        _column_is_clear,
        _free_drop_column,
        _hcorridor_band,
        route_cross_region,
        route_back_edge,
        ROUTERS,
        route_edge,
        obstacle_box,
        _allocate_or_first,
        _dedupe_axis_collapse,
        _corner_detour,
        _detour_clockwise_if_blocked,
        _interior_waypoints,
    )
    from layout.repair import (  # type: ignore[no-redef]  # noqa: F401
        LEGEND_W,
        place_legend,
        place_legend_for,
        legend_clear_right,
        MAX_REPAIR_ITERS,
        LayoutError,
        OracleFindings,
        _STUB_ICON_STYLE,
        _stub_boundary_style,
        _serialize_candidate,
        _collect_findings,
        _BLOCKING_RULES,
        _FIXABLE_RULES,
        _run_oracle,
        _grow_container,
        _bump_edge_corridor,
        orthogonalise_candidate,
        _repair,
        _dl,
        _geo,
    )
    from layout.pipeline import (  # type: ignore[no-redef]  # noqa: F401
        layout,
        _place_and_route,
        _normalise_origin,
    )


__all__ = [
    "ICON_SIZE",
    "GRID",
    "COL_STEP",
    "ROW_STEP",
    "CONTAINER_PAD",
    "TITLE_BAND",
    "REGION_STEP",
    "REGION_GAP",
    "SUB_STEP",
    "MERGE_THRESHOLD",
    "MAX_SIDE_EXITS",
    "CROSS_REGION_SPAN",
    "STAIR_STEP",
    "LEGEND_W",
    "LABEL_BAND",
    "Box",
    "Contact",
    "Point",
    "LANES",
    "LANE_INDEX",
    "EDGE_KINDS",
    "NodeSpec",
    "EdgeSpec",
    "ContainerSpec",
    "DiagramSpec",
    "SpecError",
    "OverConnectedError",
    "UnclassifiableEdgeError",
    "_validate_spec",
    "place_nodes",
    "size_containers",
    "centre_block_in_vpc",
    "select_contacts",
    "spread_contacts",
    "CorridorAllocator",
    "CorridorExhaustedError",
    "classify_edge",
    "place_legend",
    "place_legend_for",
    "legend_clear_right",
    "route_straight",
    "route_spine",
    "route_fan_out_row",
    "route_cross_region",
    "route_back_edge",
    "route_edge",
    "ROUTERS",
    "MAX_REPAIR_ITERS",
    "LayoutError",
    "PlacedEdge",
    "PlacedDiagram",
    "OracleFindings",
    "layout",
    "_run_oracle",
    "_repair",
    "_place_and_route",
    "_normalise_origin",
]
