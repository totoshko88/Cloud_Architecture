#!/usr/bin/env python3
"""Generate the GCP HA multi-region golden pair (summary + landscape) — v1.3.0.

Thin per-provider wrapper over ``scripts/ha_multiregion_common.py``: it supplies
only the GCP icon renderer per neutral role and the GCP container styles
and region/account labels. The verified layout geometry (node coordinates, nested
container boxes, edge waypoint corridors) lives in the shared module, so this
provider's pair is byte-identical in layout to the other three.

Usage::

    python scripts/build_gcp_ha_example.py                 # write both .drawio files
    python scripts/build_gcp_ha_example.py --stdout-summary
    python scripts/build_gcp_ha_example.py --stdout-landscape
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import image_icon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_multiregion_common import ProviderSkin, run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

RENDERERS = {
    "dns": image_icon("assets/vendor/gcp-category/Category Icons/Networking/SVG/Networking-512-color-rgb.svg"),
    "lb": image_icon("assets/vendor/gcp-category/Category Icons/Networking/SVG/Networking-512-color-rgb.svg"),
    "k8s": image_icon("assets/vendor/gcp-core/Unique Icons/GKE/SVG/GKE-512-color.svg"),
    "sql": image_icon("assets/vendor/gcp-core/Unique Icons/Cloud SQL/SVG/CloudSQL-512-color.svg"),
    "obj": image_icon("assets/vendor/gcp-core/Unique Icons/Cloud Storage/SVG/Cloud_Storage-512-color.svg"),
    "fn": image_icon("assets/vendor/gcp-category/Category Icons/Serverless Computing/SVG/ServerlessComputing-512-color.svg"),
    "queue": image_icon("assets/vendor/gcp-category/Category Icons/Integration Services/SVG/IntegrationServices-512-color.svg"),
    "sec": image_icon("assets/vendor/gcp-category/Category Icons/Security Identity/SVG/SecurityIdentity-512-color.svg"),
    "cache": image_icon("assets/vendor/gcp-category/Category Icons/Databases/SVG/Databases-512-color.svg"),
    # Cloud CDN has no dedicated 2025 product icon: Google's docs represent it with
    # the Networking *category* icon (product-first, category-fallback). WAF (Cloud
    # Armor) uses the Security-Identity category. Both match the committed index.
    "cdn": image_icon("assets/vendor/gcp-category/Category Icons/Networking/SVG/Networking-512-color-rgb.svg"),
    "waf": image_icon("assets/vendor/gcp-category/Category Icons/Security Identity/SVG/SecurityIdentity-512-color.svg"),
}
CONTAINER_STYLES = {
    "account": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#4285F4;fillColor=none;verticalAlign=top;fontColor=#4285F4;fontSize=12",
    "vpc": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#34A853;fillColor=none;verticalAlign=top;fontColor=#34A853;fontSize=12",
    "az": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#FBBC04;fillColor=none;verticalAlign=top;fontColor=#EA4335;fontSize=12",
}
SKIN = ProviderSkin("gcp", RENDERERS, CONTAINER_STYLES,
                    "Project acme-prod", "us-central1", "us-west1")
STEM = "02-gcp-ha-multiregion"
OUT_DIR = REPO_ROOT / "examples" / "gcp"


def main(argv=None) -> int:
    return run_cli(SKIN, OUT_DIR, STEM, prog="build_gcp_ha_example", argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
