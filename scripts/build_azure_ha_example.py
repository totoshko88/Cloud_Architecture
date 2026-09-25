#!/usr/bin/env python3
"""Generate the Azure HA multi-region golden pair (summary + landscape) — v1.3.0.

Thin per-provider wrapper over ``scripts/ha_multiregion_common.py``: it supplies
only the Azure icon renderer per neutral role and the Azure container styles
and region/account labels. The verified layout geometry (node coordinates, nested
container boxes, edge waypoint corridors) lives in the shared module, so this
provider's pair is byte-identical in layout to the other three.

Usage::

    python scripts/build_azure_ha_example.py                 # write both .drawio files
    python scripts/build_azure_ha_example.py --stdout-summary
    python scripts/build_azure_ha_example.py --stdout-landscape
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import image_icon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_multiregion_common import (  # noqa: E402
    ProviderSkin, run_cli, index_renderer,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

RENDERERS = {
    "dns": image_icon("img/lib/azure2/networking/Traffic_Manager_Profiles.svg"),
    "lb": image_icon("img/lib/azure2/networking/Load_Balancers.svg"),
    "k8s": image_icon("img/lib/azure2/compute/Kubernetes_Services.svg"),
    "sql": image_icon("img/lib/azure2/databases/SQL_Database.svg"),
    "obj": image_icon("img/lib/azure2/storage/Storage_Accounts.svg"),
    "fn": image_icon("img/lib/azure2/compute/Function_Apps.svg"),
    "queue": image_icon("img/lib/azure2/general/Service_Bus.svg"),
    "sec": image_icon("img/lib/azure2/security/Key_Vaults.svg"),
    "cache": image_icon("img/lib/azure2/databases/Cache_Redis.svg"),
    # Distinct edge-row services resolve their correct icon through the committed
    # icon index (official Azure pack file paths, inlined at raster export).
    "cdn": index_renderer("cdn", "azure"),
    "waf": index_renderer("waf", "azure"),
}
CONTAINER_STYLES = {
    "account": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#0078D4;fillColor=none;verticalAlign=top;fontColor=#0078D4;fontSize=12",
    "vpc": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#0062AD;fillColor=none;verticalAlign=top;fontColor=#0062AD;fontSize=12",
    "az": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#50E6FF;fillColor=none;verticalAlign=top;fontColor=#0078D4;fontSize=12",
}
SKIN = ProviderSkin("azure", RENDERERS, CONTAINER_STYLES,
                    "Subscription contoso-prod", "eastus", "westus2")
STEM = "02-azure-ha-multiregion"
OUT_DIR = REPO_ROOT / "examples" / "azure"


def main(argv=None) -> int:
    return run_cli(SKIN, OUT_DIR, STEM, prog="build_azure_ha_example", argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
