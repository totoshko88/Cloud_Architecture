"""Theme 25: canvas-quality gate — aspect-ratio and the largest empty rectangle
(1.10.12 WS6, which replaced the canvas-utilization coverage test).

Calibrated against the shipped corpus (0 golden false-positives); these unit
tests pin the two advisory findings on synthetic geometry.
"""

from __future__ import annotations

from rule_engine.geometry import Box, DiagramGeometry, check_canvas_quality


def _geo(nodes=(), containers=()):
    g = DiagramGeometry()
    for b in nodes:
        g.nodes[b.id] = b
    for b in containers:
        g.containers[b.id] = b
    return g


def test_well_used_square_canvas_is_clean():
    # One account box filling most of a near-square canvas.
    acct = Box("acct", 0, 0, 1000, 800)
    g = _geo(containers=[acct])
    assert check_canvas_quality(g) == []


def test_wild_aspect_is_flagged():
    acct = Box("acct", 0, 0, 3000, 400)  # 7.5:1
    g = _geo(containers=[acct])
    reasons = [r for _s, r in check_canvas_quality(g)]
    assert any(r.startswith("aspect-ratio:") for r in reasons)


def test_mostly_dead_canvas_is_flagged():
    # A small subject boundary parked in the corner of a huge canvas: a far node
    # stretches the bbox and leaves one large void (largest empty rectangle).
    acct = Box("acct", 0, 0, 400, 300)          # 120k area
    far = Box("x", 1800, 1400, 78, 78)           # pushes bbox to ~1878x1478
    g = _geo(nodes=[far], containers=[acct])
    reasons = [r for _s, r in check_canvas_quality(g)]
    assert any(r.startswith("empty-rectangle:") for r in reasons)


def test_empty_geometry_is_noop():
    assert check_canvas_quality(_geo()) == []
