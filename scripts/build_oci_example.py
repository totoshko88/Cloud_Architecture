#!/usr/bin/env python3
"""OCI GenAI stack example (``examples/oci/01-oci-genai-stack.drawio``).

A thin skin over :mod:`genai_pipeline_common`: the geometry comes from the shared
coordinate-free spec via ``layout()`` (byte-identical to ``gcp/01``), and this
file supplies only the embedded OCI stencils, the labels and the Flow text.
Container styles (Compartment ⊃ Region ⊃ VCN, Style Guide v24.2) come from
``mappings/oci-icons.yaml``. Exits 2 when the stencil pack is not fetched.

Usage::

    python scripts/build_oci_example.py            # write the .drawio
    python scripts/build_oci_example.py --check    # exit 1 when stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rule_engine.diagram_layout import OciStencilIcon  # noqa: E402
from genai_pipeline_common import GenaiSkin, run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
STENCILS = REPO_ROOT / "assets" / "vendor" / "oci-stencils" / "stencils.json"
OUT = REPO_ROOT / "examples" / "oci" / "01-oci-genai-stack.drawio"
OCI_BRAND = "#F80000"

_SLUGS = {
    "api": "functions", "lb": "load-balancer", "queue": "streaming",
    "sec": "vault", "ingest": "functions",
    # No dedicated Generative AI stencil in the pack: Analytics and AI category.
    "hub": "analytics-and-ai",
    "train": "container-engine-for-kubernetes", "sql": "autonomous-db",
    "obj": "object-storage",
}
LABELS = {
    "api": "api-function", "lb": "load-balancer", "queue": "streaming-events",
    "sec": "vault-secrets", "ingest": "ingest-function", "hub": "generative-ai",
    "train": "training-oke", "sql": "autonomous-db", "obj": "model-storage",
}
FLOW_LINES = (
    "Flow",
    "1. api-function forwards request to load-balancer",
    "2. load-balancer routes inference to Generative AI",
    "3. api-function publishes event to Streaming (async)",
    "4. Streaming delivers event to ingest-function (async)",
    "5. ingest-function submits training job to OKE",
    "6. OKE registers trained model with Generative AI",
    "7. Generative AI reads metadata from Autonomous DB",
    "8. Generative AI stores artifacts in Object Storage",
    "9. Generative AI fetches credentials from Vault",
)


def skin() -> GenaiSkin:
    stencils = json.loads(STENCILS.read_text(encoding="utf-8"))
    return GenaiSkin(
        provider="oci",
        renderers={nid: OciStencilIcon(stencils, slug, brand_hex=OCI_BRAND)
                   for nid, slug in _SLUGS.items()},
        labels=LABELS, account_label="compartment-acme-prod", region="us-ashburn-1",
        network_name="prod", flow_lines=FLOW_LINES,
        title="oci genai-stack — acme-prod / us-ashburn-1 | 2026-09-30 | v2",
        diagram_id="oci-genai-stack",
    )


def main() -> int:
    if not STENCILS.is_file():
        print(f"build_oci_example: error: extracted stencils not found at {STENCILS}. "
              "Run: python scripts/fetch_assets.py --only oci", file=sys.stderr)
        return 2
    try:
        return run_cli(skin, OUT, "build_oci_example")
    except KeyError as exc:
        print(f"build_oci_example: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
