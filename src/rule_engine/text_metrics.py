"""Shared text-width estimators (1.13.0, review §2.2).

Before 1.13.0 the engine carried several independent per-character estimates of
the same 12px text: ``geometry._CONTAINER_LABEL_CHAR_W = 7.5`` plus a fixed
40px inset, capped at the box width (``edge-crosses-container-label``);
``geometry._CAPTION_TEXT_CHAR_W = 7.0`` (node captions and
``container-caption-overflow``); and bare ``5.6`` literals in the Flow/Legend
box sizing. Two models of one caption disagreed: on SEP 01 the overflow rule saw
a caption 115px wider than its box (``spacingLeft=110``) while the caption-cut
detector capped the same caption at the box width and never saw the overflow.

This module is the one place those numbers live. Every obstacle / lint estimator
uses :data:`CAPTION_CHAR_W`; only the Flow/Legend furniture sizing uses
:data:`FURNITURE_CHAR_W`. The two are kept apart on purpose: the furniture width
sizes a box for appearance (tight to its content), whereas an obstacle estimate
must over-estimate so a line never strikes text the estimator thought was
shorter. Changing :data:`FURNITURE_CHAR_W` would resize every golden legend.

All helpers are pure.
"""
from __future__ import annotations

import html as _html
import re
from typing import List, Optional

#: Conservative per-character advance of 12px caption text (Helvetica averages
#: ~6.3px, bold ~6.9px). Used by every lint / obstacle estimator: node captions,
#: container captions, band-group captions, the raster width estimate.
CAPTION_CHAR_W = 7.0
#: Per-character advance used to size the Flow / Legend text boxes (measured
#: against the reference renders). Appearance only — never an obstacle estimate.
FURNITURE_CHAR_W = 5.6
#: draw.io's default ``spacing`` around a label (added to ``spacingLeft`` /
#: ``spacingRight``).
DRAWIO_LABEL_SPACING = 2.0
#: Width of the group badge an AWS ``mxgraph.aws4.group`` draws in its top-left
#: corner (``grIcon=``). The shipped AWS group styles set ``spacingLeft=30`` so
#: the caption already clears it; the badge only widens the left inset of a
#: group whose ``spacingLeft`` is smaller than the badge.
AWS_GROUP_BADGE_W = 25.0
#: The pre-1.13.0 caption-band model, FROZEN for the layout solver's scored
#: objective only (``geometry.rule_violations``): per-character advance and fixed
#: left inset, capped at the box width. Lint judges captions with
#: :func:`container_caption_extent`; the solver keeps this model because moving
#: its objective re-routed shipped goldens into measurably worse routes (the
#: OCI GenAI hub->obj hook, +1 crossing) through the greedy finishing passes.
SOLVER_CONTAINER_CAPTION_CHAR_W = 7.5
SOLVER_CONTAINER_CAPTION_INSET = 40.0
#: Left inset assumed for a container caption whose style is unknown (a
#: programmatic geometry, or a layout spec with no skin): a group badge plus a
#: ``spacingLeft`` — the conservative pre-1.13.0 ``_CONTAINER_LABEL_INSET``.
UNKNOWN_STYLE_CAPTION_INSET = 40.0

_HTML_BR_RE = re.compile(r"<br\s*/?>", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def text_lines(label: str) -> List[str]:
    """The non-empty rendered lines of a label.

    ``<br>`` / ``<br/>`` and newlines are line breaks, every other tag is removed
    and HTML entities are unescaped."""
    text = _HTML_BR_RE.sub("\n", label or "")
    text = _html.unescape(_HTML_TAG_RE.sub("", text))
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def style_token(style: Optional[str], key: str, default: Optional[str] = None) -> Optional[str]:
    """The value of ``key`` in a draw.io ``style`` string, else ``default``."""
    m = re.search(rf"(?:^|;){re.escape(key)}=([^;]*)", style or "")
    return m.group(1) if m else default


def _style_float(style: Optional[str], key: str, default: float) -> float:
    raw = style_token(style, key)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def caption_text_width(label: str, style: str = "") -> float:
    """Width of a label's longest rendered line at :data:`CAPTION_CHAR_W`.

    ``style`` is accepted for a future font-aware estimate and is ignored today:
    every caption the engine draws is 12px."""
    lines = text_lines(label)
    return max((len(ln) for ln in lines), default=0) * CAPTION_CHAR_W


def container_caption_extent(label: str, style: Optional[str]) -> float:
    """Horizontal extent of a left-aligned container caption, from the box's left.

    ``spacingLeft`` (draw.io default 0) + ``2 x spacing`` + the longest line at
    :data:`CAPTION_CHAR_W`. An AWS group (``grIcon=`` in the style) never starts
    its text before the end of its :data:`AWS_GROUP_BADGE_W` badge. When the style
    is unknown (``None``) the left inset is :data:`UNKNOWN_STYLE_CAPTION_INSET`.

    NOT capped at the box width: a caption wider than its box runs past the
    border, and a caller that judges what the caption covers must see that part
    (``edge-crosses-container-label``). A caller that needs the in-box part clips
    it itself."""
    text_w = caption_text_width(label)
    if style is None:
        return UNKNOWN_STYLE_CAPTION_INSET + text_w
    spacing = _style_float(style, "spacing", DRAWIO_LABEL_SPACING)
    left = _style_float(style, "spacingLeft", 0.0)
    if style_token(style, "grIcon") is not None:
        left = max(left, AWS_GROUP_BADGE_W)
    return left + 2 * spacing + text_w


def solver_container_caption_extent(label: str, box_w: float) -> float:
    """The frozen pre-1.13.0 caption extent the solver scores with: fixed inset +
    longest line x :data:`SOLVER_CONTAINER_CAPTION_CHAR_W`, capped at ``box_w``."""
    lines = text_lines(label) or [""]
    longest = max(len(ln) for ln in lines)
    return min(box_w, SOLVER_CONTAINER_CAPTION_INSET + longest * SOLVER_CONTAINER_CAPTION_CHAR_W)


__all__ = [
    "SOLVER_CONTAINER_CAPTION_CHAR_W",
    "SOLVER_CONTAINER_CAPTION_INSET",
    "solver_container_caption_extent",
    "AWS_GROUP_BADGE_W",
    "CAPTION_CHAR_W",
    "DRAWIO_LABEL_SPACING",
    "FURNITURE_CHAR_W",
    "UNKNOWN_STYLE_CAPTION_INSET",
    "caption_text_width",
    "container_caption_extent",
    "style_token",
    "text_lines",
]
