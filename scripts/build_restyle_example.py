#!/usr/bin/env python3
"""Restyle the hand-authored examples from the provider mappings.

``aws/01-aws-agent-platform`` and ``azure/01-azure-openai-rag`` are hand-laid
diagrams: their geometry is authored, not computed. Their *styling* must still
follow the mappings, or a mapping change (D18/D19: AWS Account ``#CD2264``,
Azure dotted VNet with corner icon) never reaches them. This generator owns that
styling: for each listed container cell it replaces the style with
``resolve_container(kind, provider)``, and it rewrites the Legend's boundary
lines to the standard wording. Everything else in the file is left untouched.

Idempotent and deterministic, so ``--check`` (regenerate in memory, compare,
write nothing) makes the styling a gated contract like every other example.

Usage::

    python scripts/build_restyle_example.py          # rewrite in place
    python scripts/build_restyle_example.py --check  # exit 1 when stale
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rule_engine.icon_resolver import resolve_container  # noqa: E402

#: example -> (provider, {container cell id: mapping container kind},
#:             [(legend line prefix, replacement line)])
TARGETS: Dict[str, Tuple[str, Dict[str, str], List[Tuple[str, str]]]] = {
    "aws/01-aws-agent-platform.drawio": (
        "aws",
        {"boundary-account": "boundary", "boundary-vpc": "network_boundary"},
        [
            ("Dashed outer boundary", "Outer boundary = Account (captioned; provider style)"),
            ("Dashed inner boundary", "Inner boundary = VPC (captioned; provider style)"),
        ],
    ),
    "azure/01-azure-openai-rag.drawio": (
        "azure",
        {"boundary": "boundary", "vnet": "network_boundary"},
        [
            ("Dashed outer boundary", "Outer boundary = Subscription (captioned; provider style)"),
            ("Dashed inner boundary", "Inner boundary = VNet (captioned; provider style)"),
        ],
    ),
}


def _cell_re(cell_id: str) -> "re.Pattern[str]":
    return re.compile(r'(<mxCell\b[^>]*\bid="' + re.escape(cell_id) + r'"[^>]*>)')


def restyle(text: str, provider: str, cells: Dict[str, str],
            legend: List[Tuple[str, str]]) -> str:
    for cell_id, kind in cells.items():
        style = html.escape(resolve_container(kind, provider)["style_string"], quote=True)
        rx = _cell_re(cell_id)
        m = rx.search(text)
        if m is None:
            raise SystemExit(f"{provider}: container cell {cell_id!r} not found")
        tag = re.sub(r'\bstyle="[^"]*"', f'style="{style}"', m.group(1), count=1)
        text = text[:m.start()] + tag + text[m.end():]

    def _legend(m: "re.Match[str]") -> str:
        lines = m.group(2).split("&#xa;")
        for i, line in enumerate(lines):
            for prefix, repl in legend:
                if line.startswith(prefix):
                    lines[i] = repl
        return m.group(1) + "&#xa;".join(lines) + m.group(3)

    return re.sub(r'(<mxCell\b[^>]*\bid="legend"[^>]*\bvalue=")([^"]*)(")', _legend, text, count=1)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_restyle_example")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    stale = False
    for rel, (provider, cells, legend) in TARGETS.items():
        path = REPO / "examples" / rel
        current = path.read_text(encoding="utf-8")
        wanted = restyle(current, provider, cells, legend)
        if args.check:
            if wanted != current:
                print(f"build_restyle_example: STALE: regenerate {path}", file=sys.stderr)
                stale = True
        elif wanted != current:
            path.write_text(wanted, encoding="utf-8")
            print(f"build_restyle_example: wrote {path}")
    if args.check and not stale:
        print("build_restyle_example: OK — hand-authored examples follow the mappings")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
