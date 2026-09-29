#!/usr/bin/env python3
"""GCP GenAI pipeline example (``examples/gcp/01-gcp-vertex-pipeline.drawio``).

A thin skin over :mod:`genai_pipeline_common`: the geometry comes from the shared
coordinate-free spec via ``layout()`` (byte-identical to ``oci/01``), and this
file supplies only the official Google Cloud 2025 icons (Core Product first,
Product Category fallback; Apigee for the API front door), the labels and the
Flow text. Container styles come from ``mappings/gcp-icons.yaml``.

Usage::

    python scripts/build_gcp_example.py            # write the .drawio
    python scripts/build_gcp_example.py --check    # exit 1 when stale
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rule_engine.diagram_layout import image_icon  # noqa: E402
from genai_pipeline_common import GenaiSkin, run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "examples" / "gcp" / "01-gcp-vertex-pipeline.drawio"

_CORE = "assets/vendor/gcp-core/Unique Icons"
_CAT = "assets/vendor/gcp-category/Category Icons"
_ICONS = {
    "api": f"{_CORE}/Apigee/SVG/Apigee-512-color-rgb.svg",
    "lb": f"{_CAT}/Networking/SVG/Networking-512-color-rgb.svg",
    "queue": f"{_CAT}/Integration Services/SVG/IntegrationServices-512-color.svg",
    "sec": f"{_CAT}/Security Identity/SVG/SecurityIdentity-512-color.svg",
    "ingest": f"{_CAT}/Serverless Computing/SVG/ServerlessComputing-512-color.svg",
    "hub": f"{_CORE}/Vertex AI/SVG/VertexAI-512-color.svg",
    "train": f"{_CORE}/GKE/SVG/GKE-512-color.svg",
    "sql": f"{_CORE}/Cloud SQL/SVG/CloudSQL-512-color.svg",
    "obj": f"{_CORE}/Cloud Storage/SVG/Cloud_Storage-512-color.svg",
}
LABELS = {
    "api": "api-gateway", "lb": "load-balancer", "queue": "pubsub-events",
    "sec": "secret-manager", "ingest": "ingest-function", "hub": "vertex-ai",
    "train": "training-gke", "sql": "cloud-sql", "obj": "model-storage",
}
FLOW_LINES = (
    "Flow",
    "1. api-gateway forwards request to load-balancer",
    "2. load-balancer routes inference to Vertex AI",
    "3. api-gateway publishes event to Pub/Sub (async)",
    "4. Pub/Sub delivers event to ingest-function (async)",
    "5. ingest-function submits training job to GKE",
    "6. GKE registers trained model with Vertex AI",
    "7. Vertex AI reads metadata from Cloud SQL",
    "8. Vertex AI stores artifacts in Cloud Storage",
    "9. Vertex AI fetches credentials from Secret Manager",
)


def skin() -> GenaiSkin:
    return GenaiSkin(
        provider="gcp",
        renderers={nid: image_icon(path) for nid, path in _ICONS.items()},
        labels=LABELS, account_label="project-acme-prod", region="us-central1",
        network_name="prod", flow_lines=FLOW_LINES,
        title="gcp vertex-pipeline — acme-prod / us-central1 | 2026-09-30 | v2",
        diagram_id="gcp-vertex-pipeline",
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(skin, OUT, "build_gcp_example"))
