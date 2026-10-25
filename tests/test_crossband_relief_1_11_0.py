"""FEAT-002 / FEAT-001 engine fixes (1.11.0): G33 / G34 / G35.

G34 — dense-external crossing-hard-cap relief. A landscape that draws many
genuine cross-band edges (the account reaching several disjoint external
sibling bands) gets the ``edge-crossing-excess`` hard cap extra headroom equal
to the number of crossing pairs that involve a cross-band edge
(``geometry.cross_band_crossing_count``). A diagram with no external sibling
bands — the collapsed-routing case the cap exists to catch — gets zero headroom
and still trips the ERROR.

G33 — dense-landscape finishing gate. ``build_diagram`` skips the greedy
Variant A finishing (caption-safe + crossing-repair + collinear) at or above
``_FINISH_NODE_GATE`` nodes, keeping the crossing-minimised ``layout()``
geometry (faster, and never worse on a dense cross-band landscape).

G35 — export-overshoot correction (FEAT-001). The exporter re-exports once when
the actual PNG width exceeds the class budget by a few px of wrapped-text render
overshoot; it fires only for an over-budget raster, so a within-budget golden is
untouched.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    EdgeGeom,
    cross_band_crossing_count,
    cross_band_edge_ids,
    edge_crossing_stats,
)
from rule_engine import geometry as _geo
from rule_engine import diagram_layout as _dl
from rule_engine.linter import Artifact, lint

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True))


# --------------------------------------------------------------------------- #
# G34 — cross-band identification
# --------------------------------------------------------------------------- #

def _two_band_geo() -> DiagramGeometry:
    """An account box and a disjoint external sibling band, with one edge
    crossing between them and one edge internal to the account."""
    return DiagramGeometry(
        nodes={
            "app": Box("app", 100, 100, 78, 78),
            "db": Box("db", 100, 300, 78, 78),       # same (account) band
            "ext": Box("ext", 700, 100, 78, 78),     # external band
        },
        containers={
            "boundary-account": Box("boundary-account", 60, 60, 300, 400),
            "ext-datastore": Box("ext-datastore", 640, 60, 200, 200),
        },
        edges=[
            # internal: app -> db (both in the account band)
            EdgeGeom(id="e_int", source="app", target="db", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5),
                     points=[(178, 139), (700, 139)]),
            # cross-band: app -> ext (account -> external band)
            EdgeGeom(id="e_cb", source="app", target="ext", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5),
                     points=[(178, 139), (700, 139)]),
        ],
    )


def test_cross_band_edge_is_identified():
    g = _two_band_geo()
    ids = cross_band_edge_ids(g)
    assert "e_cb" in ids
    assert "e_int" not in ids


def test_single_container_has_no_cross_band_edges():
    """A diagram with one container (the collapsed-routing quick landscape
    shape: one account box, loose external actors) has NO cross-band edge — a
    bare node in no container never qualifies, so the hard cap is unrelieved."""
    g = DiagramGeometry(
        nodes={
            "app": Box("app", 100, 100, 78, 78),
            "actor": Box("actor", 700, 100, 78, 78),  # loose, no container
        },
        containers={"boundary-account": Box("boundary-account", 60, 60, 300, 400)},
        edges=[
            EdgeGeom(id="e", source="app", target="actor", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5),
                     points=[(178, 139), (700, 139)]),
        ],
    )
    assert cross_band_edge_ids(g) == frozenset()
    assert cross_band_crossing_count(g) == 0


# --------------------------------------------------------------------------- #
# G34 — the shipped quick-1.10.0 landscape (collapsed routing) STILL errors
# --------------------------------------------------------------------------- #

QUICK_LANDSCAPE = (
    REPO_ROOT / "tests" / "fixtures" / "drawio" / "quick-1.10.0"
    / "02-quick-partner-data-landscape.drawio"
)


def _lint_file(path: Path):
    from rule_engine.cli import parse_artifacts
    out = []
    for art in parse_artifacts(str(path)):
        out += lint(art)["findings"]
    return out


@pytest.mark.skipif(not QUICK_LANDSCAPE.is_file(), reason="fixture absent")
def test_collapsed_landscape_still_hard_cap_error():
    """The quick landscape crosses 28/28 with ONE container and no external
    band, so the relief grants zero headroom and the hard cap stays an ERROR."""
    findings = _lint_file(QUICK_LANDSCAPE)
    hits = [f for f in findings if f["rule"] == "edge-crossing-excess"]
    assert hits, "expected an edge-crossing-excess finding"
    assert hits[0]["severity"] == "ERROR"
    assert hits[0]["reason"].startswith("crossings-over-hard-cap")


# --------------------------------------------------------------------------- #
# G34 — corpus is unaffected (no golden gains a cross-band relief or loses one)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("src", CORPUS)
def test_corpus_hard_cap_unaffected(src):
    """No shipped golden trips the landscape hard cap (relief or not): the relief
    only adds headroom, never removes it, and every golden is well under the cap.
    """
    findings = _lint_file(Path(src))
    hard = [f for f in findings if f["rule"] == "edge-crossing-excess"
            and str(f.get("reason", "")).startswith("crossings-over-hard-cap")]
    assert hard == []


# --------------------------------------------------------------------------- #
# G33 — the dense-landscape finishing gate
# --------------------------------------------------------------------------- #

def test_finish_node_gate_value():
    """The gate mirrors ordering.FINISH_NODE_BUDGET (20): dense landscapes only."""
    from rule_engine.layout import ordering
    assert _dl._FINISH_NODE_GATE == ordering.FINISH_NODE_BUDGET == 20


def test_finish_gate_skips_caption_plan_for_dense(monkeypatch):
    """At >= the gate, build_diagram does NOT invoke the auto caption-safe plan
    (the 260s pass); below it, it does."""
    calls = {"n": 0}
    import rule_engine.diagram_layout as dl

    def _fake_plan(text):
        calls["n"] += 1
        return None  # empty plan -> no geometry change

    monkeypatch.setattr(dl, "_plan_from_text", _fake_plan)

    def _mk_nodes(n):
        return [
            dl.Node(id=f"n{i}", label=f"n{i}", x=100 + 220 * (i % 5),
                    y=100 + 160 * (i // 5),
                    render=lambda node, pid: (
                        f'<mxCell id="{node.id}" value="{node.label}" '
                        f'style="rounded=0" vertex="1" parent="{pid}">'
                        f'<mxGeometry x="{node.x}" y="{node.y}" width="78" '
                        f'height="78" as="geometry"/></mxCell>'))
            for i in range(n)
        ]

    common = dict(
        diagram_id="t", diagram_name="t", title="t v1 | 2026-10-23 | v1",
        boundaries=[], edges=[], flow_lines=("Flow",),
        legend_x=2000, legend_lines=("Legend",), page_w=3000, page_h=2000,
    )
    # Below the gate (3 nodes): the auto plan IS computed.
    calls["n"] = 0
    dl.build_diagram(nodes=_mk_nodes(3), **common)
    assert calls["n"] == 1
    # At/above the gate (20 nodes): the auto plan is SKIPPED.
    calls["n"] = 0
    dl.build_diagram(nodes=_mk_nodes(20), **common)
    assert calls["n"] == 0


# --------------------------------------------------------------------------- #
# G35 — export-overshoot correction helper
# --------------------------------------------------------------------------- #

def test_png_width_reads_ihdr(tmp_path):
    from rule_engine.export_raster import _png_width
    # Minimal PNG header: signature + IHDR length/type + width=1599, height=1
    import struct
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">II", 1599, 1) + b"\x08\x06\x00\x00\x00"
    data = sig + struct.pack(">I", 13) + b"IHDR" + ihdr
    p = tmp_path / "x.png"
    p.write_bytes(data)
    assert _png_width(p) == 1599


def test_png_width_rejects_non_png(tmp_path):
    from rule_engine.export_raster import _png_width
    p = tmp_path / "x.png"
    p.write_bytes(b"not a png at all, really")
    assert _png_width(p) == 0
