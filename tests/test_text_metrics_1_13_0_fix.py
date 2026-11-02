"""1.13.0 fix (ITEM 16): one text-width estimator module.

``geometry._container_caption_width`` used its own 7.5px/char and a fixed 40px
inset, capped at the box width, while ``container-caption-overflow`` used
7.0px/char + the style's spacings: on SEP 01 the overflow rule saw +115px and the
caption-cut detector never saw the overflowing part. Both now read
``text_metrics``; the builder's caption fit no longer lets a box's own member
block its growth.
"""
from __future__ import annotations

import tokenize
from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine import text_metrics as tm

_SRC = Path(__file__).resolve().parents[1] / "src" / "rule_engine"


def test_constants():
    assert tm.CAPTION_CHAR_W == 7.0
    assert tm.FURNITURE_CHAR_W == 5.6
    assert tm.DRAWIO_LABEL_SPACING == 2.0
    assert geo._CAPTION_TEXT_CHAR_W == tm.CAPTION_CHAR_W   # deprecated alias


def test_caption_text_width_uses_longest_line():
    assert tm.caption_text_width("abc") == 21.0
    assert tm.caption_text_width("ab<br>abcd") == 28.0
    assert tm.caption_text_width("") == 0.0


def test_extent_honours_spacing_left_and_is_not_capped():
    label = "x" * 30
    style = "rounded=0;html=1;spacingLeft=110;align=left;verticalAlign=top"
    ext = tm.container_caption_extent(label, style)
    assert ext == 110 + 4 + 210
    assert ext > 178                     # wider than the SEP 01 box: no cap
    box = geo.Box("c", 0, 0, 178, 400)
    band, _extent = geo.container_caption_geom(label, style, box)
    assert band.w == ext                 # the caption-cut detector sees the overflow


def test_extent_aws_group_badge_and_unknown_style():
    aws = "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;spacingLeft=30"
    assert tm.container_caption_extent("abc", aws) == 30 + 4 + 21
    assert tm.container_caption_extent("abc", "grIcon=x;spacingLeft=5") == 25 + 4 + 21
    assert tm.container_caption_extent("abc", None) == tm.UNKNOWN_STYLE_CAPTION_INSET + 21


def test_style_token():
    assert tm.style_token("a=1;spacingLeft=30;b=2", "spacingLeft") == "30"
    assert tm.style_token("a=1", "spacingLeft", "0") == "0"


def test_no_px_per_char_literals_outside_text_metrics():
    """Only text_metrics.py carries the 7.5 / 5.6 / 7.0 px-per-char numbers as
    CODE literals (prose in comments / docstrings is fine)."""
    offenders = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.name == "text_metrics.py" or "_bootstrap" in path.parts:
            continue
        with open(path, "rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.NUMBER and tok.string in ("7.5", "5.6", "7.0"):
                    offenders.append(f"{path.name}:{tok.start[0]}: {tok.line.strip()}")
    assert offenders == []


def _sep01_like(member_label: str):
    style = ("shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;grStroke=1;"
             "fillColor=none;strokeColor=#CD2264;dashed=0;verticalAlign=top;align=left;"
             "spacingLeft=30;fontColor=#CD2264;fontSize=12;html=1")
    b = dl.Boundary(id="acct", label="SEP — AWS 870325637521 / eu-central-1",
                    x=390, y=350, w=178, h=408, style=style, kind="account")
    # A member near the right edge whose wide caption overhangs the border.
    member = dl.Node(id="sep", label=member_label, x=470, y=420)
    return b, member


def test_fit_boundary_captions_grows_over_its_own_member():
    b, member = _sep01_like("Syndicate Server (Education Extension)")
    need = geo.container_caption_need(b.label, b.style)
    assert need - b.w == 115                         # the SEP 01 lint figure
    (out,) = dl.fit_boundary_captions([b], [member], [], legend_x=1138)
    assert out.w >= need and out.w % dl.GRID == 0   # grown, not blocked by its member
    assert out.label == b.label


def test_fit_boundary_captions_still_blocked_by_a_non_member():
    b, member = _sep01_like("SEP platform")
    b = dl.replace(b, w=210)
    neighbour = dl.Node(id="ext", label="MongoDB Atlas", x=620, y=500)
    (out,) = dl.fit_boundary_captions([b], [member, neighbour], [], legend_x=1138)
    assert out.w == b.w
    # Wrapped instead, breaking after the slash (spacingLeft counted in the fit).
    assert out.label == "SEP — AWS 870325637521 /<br>eu-central-1"
    assert geo.container_caption_need(out.label, b.style) <= out.w


def test_wrap_prefers_the_slash():
    assert dl._wrap_caption_at_slash("aws account / eu-central-1") == \
        "aws account /<br>eu-central-1"
    assert dl._wrap_caption_at_slash("no slash here") is None
