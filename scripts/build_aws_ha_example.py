#!/usr/bin/env python3
"""Generate the AWS HA multi-region golden pair (summary + landscape) — v1.3.0.

Thin per-provider wrapper over ``scripts/ha_multiregion_common.py``: it supplies
only the AWS icon renderer per neutral role and the AWS container styles
and region/account labels. The verified layout geometry (node coordinates, nested
container boxes, edge waypoint corridors) lives in the shared module, so this
provider's pair is byte-identical in layout to the other three.

Usage::

    python scripts/build_aws_ha_example.py                 # write both .drawio files
    python scripts/build_aws_ha_example.py --stdout-summary
    python scripts/build_aws_ha_example.py --stdout-landscape
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import builtin_icon, image_icon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_multiregion_common import ProviderSkin, build_summary, build_landscape, write_pair  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

def _res(name: str, color: str):
    return builtin_icon(
        f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{name};"
        f"fillColor={color};strokeColor=#ffffff;aspect=fixed;html=1"
    )

RENDERERS = {
    "dns": _res("route_53", "#8C4FFF"),
    "cdn": _res("cloudfront", "#8C4FFF"),
    "waf": _res("waf", "#DD344C"),
    "lb": _res("elastic_load_balancing", "#8C4FFF"),
    "k8s": _res("eks", "#ED7100"),
    "sql": _res("rds", "#527FFF"),
    "obj": _res("s3", "#7AA116"),
    "fn": _res("lambda", "#ED7100"),
    "queue": _res("sqs", "#E7157B"),
    "sec": _res("secrets_manager", "#DD344C"),
    "cache": _res("elasticache", "#527FFF"),
}
CONTAINER_STYLES = {
    "account": "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;grStroke=1;fillColor=none;strokeColor=#232F3E;dashed=0;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;fontSize=12;html=1",
    "vpc": "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;grStroke=1;fillColor=none;strokeColor=#8C4FFF;dashed=0;verticalAlign=top;align=left;spacingLeft=30;fontColor=#8C4FFF;fontSize=12;html=1",
    "az": "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;fontColor=#00A4A6;fontSize=12",
}
SKIN = ProviderSkin("aws", RENDERERS, CONTAINER_STYLES,
                    "Account 111122223333", "us-east-1", "us-west-2")
STEM = "02-aws-ha-multiregion"
OUT_DIR = REPO_ROOT / "examples" / "aws"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build_aws_ha_example")
    ap.add_argument("--stdout-summary", action="store_true")
    ap.add_argument("--stdout-landscape", action="store_true")
    args = ap.parse_args(argv)
    if args.stdout_summary:
        sys.stdout.write(build_summary(SKIN)); return 0
    if args.stdout_landscape:
        sys.stdout.write(build_landscape(SKIN)); return 0
    paths = write_pair(SKIN, OUT_DIR, STEM)
    for p in paths:
        print("build_aws_ha_example: wrote " + str(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
