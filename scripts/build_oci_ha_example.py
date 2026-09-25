#!/usr/bin/env python3
"""Generate the OCI HA multi-region golden pair (summary + landscape) — v1.3.0.

Thin per-provider wrapper over ``scripts/ha_multiregion_common.py``: it supplies
only the OCI icon renderer per neutral role and the OCI container styles
and region/account labels. The verified layout geometry (node coordinates, nested
container boxes, edge waypoint corridors) lives in the shared module, so this
provider's pair is byte-identical in layout to the other three.

Usage::

    python scripts/build_oci_ha_example.py                 # write both .drawio files
    python scripts/build_oci_ha_example.py --stdout-summary
    python scripts/build_oci_ha_example.py --stdout-landscape
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import OciStencilIcon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_multiregion_common import ProviderSkin, run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

# OCI ships no built-in draw.io library; its shapes are embedded stencils decoded
# from OCI Library.xml into assets/vendor/oci-stencils/stencils.json by
# scripts/fetch_assets.py. Render each role via OciStencilIcon (the same
# mechanism as the shipped 01-oci-genai-stack golden example) so real glyphs
# render — NOT the bare red labelled-box fallback (which left every node empty).
import json as _json  # noqa: E402

_STENCILS_PATH = REPO_ROOT / "assets" / "vendor" / "oci-stencils" / "stencils.json"
_STENCILS = _json.loads(_STENCILS_PATH.read_text(encoding="utf-8"))

# role -> OCI library slug (verified present in stencils.json). `cache` has no
# dedicated OCI glyph; it falls back to the Autonomous DB family (documented gap).
_OCI_SLUGS = {
    "dns": "dns",
    "cdn": "cdn",
    "waf": "waf",
    "lb": "load-balancer",
    "k8s": "container-engine-for-kubernetes",
    "sql": "autonomous-db",
    "obj": "object-storage",
    "fn": "functions",
    "queue": "streaming",
    "sec": "vault",
    "cache": "autonomous-db",
}
RENDERERS = {
    role: OciStencilIcon(_STENCILS, slug, "#F80000")
    for role, slug in _OCI_SLUGS.items()
}
CONTAINER_STYLES = {
    "account": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#F80000;fillColor=none;verticalAlign=top;fontColor=#F80000;fontSize=12",
    "vpc": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#C74634;fillColor=none;verticalAlign=top;fontColor=#C74634;fontSize=12",
    "az": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#312D2A;fillColor=none;verticalAlign=top;fontColor=#312D2A;fontSize=12",
}
SKIN = ProviderSkin("oci", RENDERERS, CONTAINER_STYLES,
                    "Compartment acme-prod", "us-ashburn-1", "us-phoenix-1")
STEM = "02-oci-ha-multiregion"
OUT_DIR = REPO_ROOT / "examples" / "oci"


def main(argv=None) -> int:
    return run_cli(SKIN, OUT_DIR, STEM, prog="build_oci_ha_example", argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
