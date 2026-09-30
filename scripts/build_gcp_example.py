#!/usr/bin/env python3
"""GCP GenAI pipeline example (``examples/gcp/01-gcp-vertex-pipeline.drawio``).

A thin skin over :mod:`genai_pipeline_common`: the geometry comes from the shared
coordinate-free spec via ``layout()`` (byte-identical to ``oci/01``), and this
file supplies only the official Google Cloud 2025 icons (Core Product first,
Product Category fallback; Apigee for the API front door; the LLM hub uses the Agents category icon since
Vertex AI became the Gemini Enterprise Agent Platform), the labels and the
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
    # Vertex AI was renamed Gemini Enterprise Agent Platform (Cloud Next 2026);
    # Google ships no dedicated product icon yet, so use the official Agents
    # category icon (product-first, category-fallback — Google's own convention).
    "hub": f"{_CAT}/Agents/SVG/Agents-512-color.svg",
    "train": f"{_CORE}/GKE/SVG/GKE-512-color.svg",
    "sql": f"{_CORE}/Cloud SQL/SVG/CloudSQL-512-color.svg",
    "obj": f"{_CORE}/Cloud Storage/SVG/Cloud_Storage-512-color.svg",
}
LABELS = {
    "api": "api-gateway", "lb": "load-balancer", "queue": "pubsub-events",
    "sec": "secret-manager", "ingest": "ingest-function",
    "hub": "gemini-agent-platform",
    "train": "training-gke", "sql": "cloud-sql", "obj": "model-storage",
}
FLOW_LINES = (
    "Flow",
    "1. api-gateway forwards request to load-balancer",
    "2. load-balancer routes inference to Gemini Agent Platform",
    "3. api-gateway publishes event to Pub/Sub (async)",
    "4. Pub/Sub delivers event to ingest-function (async)",
    "5. ingest-function submits training job to GKE",
    "6. GKE registers trained model with Gemini Agent Platform",
    "7. Gemini Agent Platform reads metadata from Cloud SQL",
    "8. Gemini Agent Platform stores artifacts in Cloud Storage",
    "9. Gemini Agent Platform fetches credentials from Secret Manager",
)


def skin() -> GenaiSkin:
    return GenaiSkin(
        provider="gcp",
        renderers={nid: image_icon(path) for nid, path in _ICONS.items()},
        labels=LABELS, account_label="project-acme-prod", region="us-central1",
        network_name="prod", flow_lines=FLOW_LINES,
        title="gcp vertex-pipeline — acme-prod / us-central1 | 2026-09-30 | v2",
        diagram_id="gcp-vertex-pipeline",
        # Apigee is a REGIONAL product, so the API front door sits inside the
        # region (unlike OCI API Gateway, which is global).
        api_global=False,
        # Hand-verified routes (1.10.5) that take this diagram from 6 crossings
        # to 1. Three edges — e1 (api->lb), e4 (queue->ingest), e6 (train->hub) —
        # use a bottom-exit + wide free-corridor detour the greedy scored router
        # cannot reach without tripping an unrepairable corridor-sharing finding.
        # Injected as a per-edge geometry override after layout(); a pure constant
        # so the diagram stays deterministic and --check stays fresh. Node
        # positions are the engine's, so the absolute waypoints align.
        edge_overrides={
            # x=80 corridor sits between region-a.left (60) and vpc-a.left (90),
            # clear of both borders (x=100 rode the vpc-a left border —
            # edge-on-container-border).
            "e1": {"exit": (0.511, 0.979), "entry": (0.055, 0.499),
                   "points": ((440, 350), (80, 350), (80, 280))},
            "e4": {"exit": (0.493, 1.0), "entry": (0.0, 0.5128),
                   "points": ((658, 840), (330, 840), (330, 600))},
            # e6 loops in the x=70 corridor — one grid step left of e1's x=80 —
            # so the two long verticals do not share a trunk (parallel-trunk).
            "e6": {"exit": (0.508, 0.957), "entry": (0.506, 0.02),
                   "points": ((160, 720), (70, 720), (70, 160), (660, 160))},
        },
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(skin, OUT, "build_gcp_example"))
