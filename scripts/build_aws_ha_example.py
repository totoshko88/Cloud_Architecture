#!/usr/bin/env python3
"""Generate the AWS HA multi-region golden pair (summary + landscape) — v1.3.0.

Thin per-provider wrapper over ``scripts/ha_multiregion_common.py``: it supplies
only the AWS icon renderer per neutral role and the AWS container styles
and region/account labels. The verified layout geometry (node coordinates, nested
container boxes, edge waypoint corridors) lives in the shared module, so this
provider's pair is byte-identical in layout to the other three.

**Migration 1.10.2:** Icons now resolve via ``mappings/aws-icons.yaml`` using
official AWS SVG file paths (like Azure/GCP), not hardcoded mxgraph.aws4 stencils.
This provides exact AWS brand colors and consistent icon handling across providers.

Usage::

    python scripts/build_aws_ha_example.py                 # write both .drawio files
    python scripts/build_aws_ha_example.py --stdout-summary
    python scripts/build_aws_ha_example.py --stdout-landscape
    python scripts/build_aws_ha_example.py --check          # compare with committed, write nothing
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import builtin_icon  # noqa: E402
from rule_engine.icon_resolver import resolve_icon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_multiregion_common import mapping_container_styles, ProviderSkin, run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def _icon(role: str):
    """Resolve an icon from mappings/aws-icons.yaml."""
    result = resolve_icon(role, "aws")
    return builtin_icon(result["style_string"])


# Role -> yaml key mapping (the HA example uses short role names)
_ROLE_MAP = {
    "dns": "dns",
    "cdn": "cdn",
    "waf": "waf",
    "lb": "lb",
    "k8s": "managed_k8s",
    "sql": "managed_sql",
    "obj": "object_store",
    "fn": "serverless_fn",
    "queue": "message_queue",
    "sec": "secrets_store",
    "cache": "cache",
}

RENDERERS = {role: _icon(yaml_key) for role, yaml_key in _ROLE_MAP.items()}

# Container styles: still use mxgraph.aws4.group for proper draw.io group behavior
# (only structural elements, not service icons)
CONTAINER_STYLES = mapping_container_styles("aws")
SKIN = ProviderSkin("aws", RENDERERS, CONTAINER_STYLES,
                    "Account 111122223333", "us-east-1", "us-west-2")
STEM = "02-aws-ha-multiregion"
OUT_DIR = REPO_ROOT / "examples" / "aws"


def main(argv=None) -> int:
    return run_cli(SKIN, OUT_DIR, STEM, prog="build_aws_ha_example", argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
