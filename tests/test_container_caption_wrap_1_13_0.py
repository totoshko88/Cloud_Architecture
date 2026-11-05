"""L5 (1.13.0): generalized N-line container-caption wrap.

A draw.io container draws its caption inside its own top edge. When a top-entry
edge leg drops through the caption band on the column where the text sits, the
line slices the words (``edge-crosses-container-label``). The existing
:func:`rule_engine.diagram_layout._clear_container_captions` pass SHIFTS the
left-anchored caption to a clear grid slot — but when cutting legs BRACKET the
text, no single-line shift of the full-width line clears them (SEP 08
``peer-ext``). L5 adds an N-line WRAP fallback behind the default-off
``container_caption_wrap`` build-diagram option: wrap onto the smallest ``N`` in
``2..max_wrap`` whose longest line can be placed clear.

Proven here on synthetic fixtures:
* ``_wrap_caption_n_lines`` balances a label onto exactly N lines;
* ``geometry.caption_text_extent`` measures a wrapped caption by its LONGEST
  line, so a wrapped caption reports its true shorter horizontal extent;
* ``_clear_container_captions`` with ``max_wrap`` clears a mid-text cut a
  single-line shift cannot, picking the smallest N;
* ``max_wrap=0`` (the default) leaves every caption byte-identical;
* a caption not cut by any leg is never wrapped (byte-inert).
"""

from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.geometry import Box

# A long, left-aligned caption that nearly fills a 560px-wide boundary.
_LONG = "External peers OUTSIDE SEP -- partner-vpc eu-central-1 audit log-archive"
_STYLE = ("rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;"
          "verticalAlign=top;align=left;spacingLeft=4;fontSize=12")


def _boundary(label=_LONG):
    return dl.Boundary("peer-ext", label, 30, 840, 560, 300,
                       "#5A6B7B", None, _STYLE, "network_boundary")


def _two_legs(x_left, x_right):
    """A one-edge polyline with two vertical legs bracketing the caption."""
    n1 = dl.Node("a", "", 100, 600, None, None, None, None, False)
    n2 = dl.Node("c", "", 490, 980, None, None, None, None, False)
    e = dl.Edge("e", "a", "c", "classic", dashed=False, exit=(0.5, 0.5),
                entry=(0.5, 0.5),
                points=((x_left, 940), (x_left, 760),
                        (x_right, 760), (x_right, 940)))
    return [n1, n2], [e]


# --------------------------------------------------------------------------- #
# _wrap_caption_n_lines
# --------------------------------------------------------------------------- #

def test_wrap_n_lines_balances_onto_exactly_n_lines():
    w = dl._wrap_caption_n_lines(_LONG, 3)
    assert w is not None
    lines = w.split("<br>")
    assert len(lines) == 3
    # balanced: the longest line is shorter than the whole label split 1-way.
    assert max(len(l) for l in lines) < len(_LONG)


def test_wrap_n_lines_refuses_unsplittable():
    assert dl._wrap_caption_n_lines("single", 2) is None          # no space
    assert dl._wrap_caption_n_lines("a<br>b c", 2) is None        # already wrapped
    assert dl._wrap_caption_n_lines("a b", 2) is not None         # 2 words -> 2 lines ok
    assert dl._wrap_caption_n_lines("a b", 3) is None             # fewer words than lines
    assert dl._wrap_caption_n_lines(_LONG, 1) is None             # n<2


def test_wrap_n_lines_minimises_longest_line():
    # A larger N never increases the longest line.
    longest = []
    for n in (2, 3, 4):
        w = dl._wrap_caption_n_lines(_LONG, n)
        longest.append(max(len(l) for l in w.split("<br>")))
    assert longest[0] >= longest[1] >= longest[2]


# --------------------------------------------------------------------------- #
# geometry: caption_text_extent measures the longest <br> line
# --------------------------------------------------------------------------- #

def test_caption_text_extent_measures_longest_wrapped_line():
    box = Box("c", 30, 840, 560, 300)
    one = geo.caption_text_extent(_LONG, _STYLE, box)
    wrapped = dl._wrap_caption_n_lines(_LONG, 3)
    two = geo.caption_text_extent(wrapped, _STYLE, box)
    # the wrapped caption's text extent is strictly narrower.
    assert (two[1] - two[0]) < (one[1] - one[0])


def test_container_caption_geom_band_grows_per_line():
    box = Box("c", 30, 840, 560, 300)
    b1, _ = geo.container_caption_geom(_LONG, _STYLE, box)
    wrapped = dl._wrap_caption_n_lines(_LONG, 3)
    b3, _ = geo.container_caption_geom(wrapped, _STYLE, box)
    assert b3.h > b1.h  # three lines occupy a taller band


# --------------------------------------------------------------------------- #
# _clear_container_captions: N-line wrap fallback
# --------------------------------------------------------------------------- #

def _still_cut(b, legs):
    box = Box(b.id, b.x, b.y, b.w, b.h)
    tx0, tx1 = geo.caption_text_extent(b.label, b.style, box)
    cuts = [cx for leg in legs for cx in geo.vertical_caption_cuts([leg], box)]
    return any(tx0 - geo._CAPTION_CLEARANCE < cx < tx1 + geo._CAPTION_CLEARANCE
               for cx in cuts)


def test_wrap_clears_a_cut_no_single_line_shift_can():
    nodes, edges = _two_legs(120, 520)
    legs = [[(120, 600), (120, 940)], [(520, 600), (520, 940)]]
    # The one-line caption is cut and no single-line shift clears it.
    assert geo.free_caption_x0(
        _LONG, _STYLE, Box("peer-ext", 30, 840, 560, 300),
        [120.0, 520.0]) is None
    out = dl._clear_container_captions([_boundary()], nodes, edges, max_wrap=3)
    nb = out[0]
    assert "<br>" in nb.label                 # the caption was wrapped
    assert not _still_cut(nb, legs)           # and now clears both legs


def test_wrap_picks_smallest_n():
    nodes, edges = _two_legs(120, 520)
    out = dl._clear_container_captions([_boundary()], nodes, edges, max_wrap=4)
    nb = out[0]
    # two lines are enough to clear this fixture -> smallest N is 2.
    assert nb.label.count("<br>") == 1


def test_default_off_is_byte_inert():
    nodes, edges = _two_legs(120, 520)
    b = _boundary()
    out = dl._clear_container_captions([b], nodes, edges)  # max_wrap default 0
    nb = out[0]
    # No shift was possible and no wrap allowed: the boundary is returned as-is.
    assert nb.label == b.label
    assert nb.style == b.style


def test_uncut_caption_is_never_wrapped():
    # Legs far to the right of the text: the caption is already clear.
    nodes, edges = _two_legs(1500, 1520)
    out = dl._clear_container_captions([_boundary()], nodes, edges, max_wrap=3)
    nb = out[0]
    assert "<br>" not in nb.label  # untouched — nothing cut it
