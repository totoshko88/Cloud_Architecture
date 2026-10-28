"""ITEM D ergonomics (1.11.0, FEAT-004): E-04 small-flow export upscale bound
and E-06 DiagramSpec spec-template presence.

E-04
----
A very small flow canvas (``W <= FLOW_SMALL_WIDTH``) may upscale up to
``FLOW_SMALL_MAX_SCALE`` (2.5) instead of the default 1.5, so a tiny single-path
diagram is not a postage stamp — WITHOUT busting the flow raster budget (the
budget fit term still binds) and WITHOUT regressing the G35 export-overshoot fix
(``_canvas_width`` / ``_WRAPPED_TEXT_RENDER_OVERSHOOT`` are untouched). A
landscape and a flow wider than ``FLOW_SMALL_WIDTH`` keep the 1.5 cap.

E-06
----
``examples/spec_templates/`` ships one runnable, commented template per
``diagram_type`` the authoring audience needs (context / c4_container / network
/ component) plus a README.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from rule_engine import export_raster as er  # noqa: E402

_SPEC_TEMPLATES = _REPO_ROOT / "examples" / "spec_templates"


# --------------------------------------------------------------------------- #
# Helpers: a .drawio whose natural canvas width is EXACTLY ``w`` px.
# --------------------------------------------------------------------------- #

def _drawio_of_width(w: int) -> str:
    """A minimal .drawio with one plain box at x=0 of width ``w``.

    A plain ``rounded`` box (no ``verticalLabelPosition=bottom`` caption, no
    text) spans exactly ``x .. x+w`` in ``_canvas_width``'s model, so the natural
    canvas width is ``w``."""
    return (
        '<mxfile host="app.diagrams.net">\n'
        '  <diagram id="d" name="w">\n'
        '    <mxGraphModel gridSize="10">\n'
        "      <root>\n"
        '        <mxCell id="0" />\n'
        '        <mxCell id="1" parent="0" />\n'
        f'        <mxCell id="n" value="" style="rounded=1;html=1" vertex="1" parent="1">\n'
        f'          <mxGeometry x="0" y="0" width="{w}" height="78" as="geometry" />\n'
        "        </mxCell>\n"
        "      </root>\n"
        "    </mxGraphModel>\n"
        "  </diagram>\n"
        "</mxfile>\n"
    )


def _write_drawio(tmp_path: Path, w: int, diagram_class: str) -> Path:
    src = tmp_path / f"d-{w}-{diagram_class}.drawio"
    src.write_text(_drawio_of_width(w), encoding="utf-8")
    companion = tmp_path / f"d-{w}-{diagram_class}.diagram.md"
    companion.write_text(f"---\ndiagram_class: {diagram_class}\n---\n", encoding="utf-8")
    return src


# --------------------------------------------------------------------------- #
# E-04 — small-flow upscale bound
# --------------------------------------------------------------------------- #

def test_small_flow_upscale_bound(tmp_path):
    """A 600px flow scales to 2.5 and the exported width stays under budget."""
    src = _write_drawio(tmp_path, 600, "flow")
    scale, width = er.compute_scale(src)
    assert width == 600.0
    # fit = (1600 - 16) / 600 ~= 2.64 > 2.5, so the small-flow cap binds.
    assert scale == er.FLOW_SMALL_MAX_SCALE == 2.5
    # ... and even at 2.5 the raster stays within the 1600px flow budget.
    assert width * scale <= er.FLOW_MAX_WIDTH


def test_small_flow_cap_never_busts_budget(tmp_path):
    """A flow at the small-width boundary never exceeds the flow budget.

    The budget fit term dominates the 2.5 cap for every width, so
    ``W * scale <= budget`` holds across the whole small-flow range (the E-04
    AC: no budget bust)."""
    for w in (100, 300, 600, 900, 1000):
        src = _write_drawio(tmp_path, w, "flow")
        scale, width = er.compute_scale(src)
        assert width * scale <= er.FLOW_MAX_WIDTH, (w, scale, width)


def test_landscape_keeps_default_cap(tmp_path):
    """A small LANDSCAPE keeps the 1.5 cap (the small-flow cap is flow-only)."""
    src = _write_drawio(tmp_path, 600, "landscape")
    scale, width = er.compute_scale(src)
    assert scale == er.MAX_EXPORT_SCALE == 1.5


def test_near_budget_flow_keeps_default_cap(tmp_path):
    """A flow WIDER than FLOW_SMALL_WIDTH keeps the 1.5 cap, not 2.5.

    At W=1040 (> 1000) the cap is 1.5; fit = (1600-16)/1040 ~= 1.523 > 1.5, so
    the cap binds and the scale is exactly 1.5 — a >1000px flow is byte-stable."""
    src = _write_drawio(tmp_path, 1040, "flow")
    scale, width = er.compute_scale(src)
    assert width == 1040.0
    assert scale == er.MAX_EXPORT_SCALE == 1.5


def test_g35_canvas_width_untouched(tmp_path):
    """E-04 touches only the SCALE ceiling, never the G35 width model.

    The wrapped-text render overshoot constant (the G35 fix) is unchanged, and
    ``_canvas_width`` is a pure function of geometry with no cap logic — so a
    flow and a landscape of the same source measure the same natural width."""
    assert er._WRAPPED_TEXT_RENDER_OVERSHOOT == 15.0
    src_flow = _write_drawio(tmp_path, 600, "flow")
    src_land = _write_drawio(tmp_path, 600, "landscape")
    assert er._canvas_width(src_flow) == er._canvas_width(src_land) == 600.0


def test_small_flow_cap_constants():
    """The E-04 constants exist with the documented values."""
    assert er.FLOW_SMALL_WIDTH == 1000
    assert er.FLOW_SMALL_MAX_SCALE == 2.5


# --------------------------------------------------------------------------- #
# E-06 — spec-template presence
# --------------------------------------------------------------------------- #

_TEMPLATE_TYPES = ("context", "c4_container", "network", "component")


def test_spec_templates_dir_exists():
    assert _SPEC_TEMPLATES.is_dir(), f"missing {_SPEC_TEMPLATES}"


@pytest.mark.parametrize("dtype", _TEMPLATE_TYPES)
def test_one_template_per_diagram_type(dtype):
    """One runnable build_<type>.py template per diagram_type, plus a README."""
    template = _SPEC_TEMPLATES / f"build_{dtype}.py"
    assert template.is_file(), f"missing template {template}"
    text = template.read_text(encoding="utf-8")
    # Each template drives the public pipeline coordinate-free.
    assert "DiagramSpec" in text
    assert "def main" in text


def test_spec_templates_readme_present():
    readme = _SPEC_TEMPLATES / "README.md"
    assert readme.is_file(), f"missing {readme}"
    text = readme.read_text(encoding="utf-8")
    # The README maps every diagram_type to its template.
    for dtype in _TEMPLATE_TYPES:
        assert f"build_{dtype}.py" in text, f"README omits build_{dtype}.py"
