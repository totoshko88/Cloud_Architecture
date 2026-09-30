#!/usr/bin/env python3
"""AWS agent-platform example (``examples/aws/01-aws-agent-platform.drawio``).

Engine-generated (D1 / D20): a coordinate-free :class:`DiagramSpec` is laid out
by ``layout()`` and serialized by ``build_diagram()`` through the shared
:mod:`engine_example_common` builder, so the geometry — node placement, edge
routing, caption-safe corridors — is the engine's output and is regenerated
whenever the layout engine changes. This file supplies only the AWS official
icons, the labels, the container captions/styles (from ``mappings/aws-icons.yaml``),
the Flow text and the title.

Topology (an agentic platform): an EKS cluster fronts an Application Load
Balancer that invokes a Lambda tool-invoker (the hub). The hub enqueues async
work on SQS, calls Bedrock for inference, reads Secrets Manager, persists to RDS
and writes artifacts to S3. EKS / ALB / RDS are **VPC-scoped** (inside the
Network Boundary); Lambda / SQS / Bedrock / Secrets / S3 are **regional** managed
services (inside the Account/Region, outside the VPC — the engine places them
there by scope).

Usage::

    python scripts/build_aws_agent_platform_example.py            # write
    python scripts/build_aws_agent_platform_example.py --check    # exit 1 stale
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rule_engine.diagram_layout import image_icon  # noqa: E402
from rule_engine.icon_resolver import resolve_container  # noqa: E402
from rule_engine.layout.model import (  # noqa: E402
    ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec,
)
from engine_example_common import ExampleSkin, run_cli  # noqa: E402

OUT = REPO_ROOT / "examples" / "aws" / "01-aws-agent-platform.drawio"

_ARCH = "assets/vendor/aws-icons/Architecture-Service-Icons_07312026"
_RES = "assets/vendor/aws-icons/Resource-Icons_07312026"
_ICONS = {
    "eks": f"{_ARCH}/Arch_Containers/48/Arch_Amazon-Elastic-Kubernetes-Service_48.svg",
    "alb": f"{_RES}/Res_Networking-Content-Delivery/Res_Elastic-Load-Balancing_Application-Load-Balancer_48.svg",
    "rds": f"{_RES}/Res_Databases/Res_Amazon-Aurora_Amazon-RDS-Instance_48.svg",
    "lambda": f"{_RES}/Res_Compute/Res_AWS-Lambda_Lambda-Function_48.svg",
    "sqs": f"{_RES}/Res_Application-Integration/Res_Amazon-Simple-Queue-Service_Queue_48.svg",
    "bedrock": f"{_ARCH}/Arch_Artificial-Intelligence/48/Arch_Amazon-Bedrock_48.svg",
    "secrets": f"{_ARCH}/Arch_Security-Identity/48/Arch_AWS-Secrets-Manager_48.svg",
    "s3": f"{_RES}/Res_Storage/Res_Amazon-Simple-Storage-Service_Bucket_48.svg",
}
LABELS = {
    "eks": "agent-eks-cluster", "alb": "agent-alb", "rds": "agent-conversation-db",
    "lambda": "agent-tool-invoker", "sqs": "agent-task-queue",
    "bedrock": "agent-bedrock-llm", "secrets": "agent-api-secrets",
    "s3": "agent-artifact-store",
}

# Coordinate-free spec. VPC-scoped roles (k8s/lb/sql) declare the vpc container;
# regional roles (fn/queue/llm_platform/sec/obj) declare the region container,
# so the engine places them outside the Network Boundary by scope (D20).
_NODES = (
    NodeSpec(id="eks", role="k8s", lane="workers", region="a", slot=0, container="vpc-a"),
    NodeSpec(id="alb", role="lb", lane="router", region="a", slot=0, container="vpc-a"),
    NodeSpec(id="rds", role="sql", lane="data", region="a", slot=0, container="vpc-a"),
    # Lambda tool-invoker is the hub. The engine caps any node face at three
    # exits (diagram-standards: "a fourth means the node is over-connected —
    # split or re-lane"), so the hub fans out to exactly THREE targets: the async
    # queue, the inference platform (bedrock), and the artifact store (s3). The
    # inference call reads the API secrets (bedrock → secrets), and the EKS app
    # tier persists conversations to RDS inside the VPC (eks → rds) — so every
    # node stays at or below three edges per face while the workload's meaning is
    # preserved.
    NodeSpec(id="lambda", role="fn", lane="workers", region="a", slot=1, container="region-a"),
    NodeSpec(id="sqs", role="queue", lane="async", region="a", slot=2, container="region-a"),
    NodeSpec(id="bedrock", role="llm_platform", lane="platform", region="a", slot=0, container="region-a"),
    NodeSpec(id="secrets", role="sec", lane="platform", region="a", slot=1, container="region-a"),
    NodeSpec(id="s3", role="obj", lane="data", region="a", slot=1, container="region-a"),
)
_EDGES = (
    EdgeSpec(id="e1", source="eks", target="alb", marker="1"),
    EdgeSpec(id="e2", source="alb", target="lambda", marker="2"),
    # Hub fan-out (exactly three): async queue, inference, artifact store.
    EdgeSpec(id="e3", source="lambda", target="sqs", marker="3", dashed=True),
    EdgeSpec(id="e4", source="lambda", target="bedrock", marker="4"),
    EdgeSpec(id="e5", source="lambda", target="s3", marker="5"),
    # Inference reads the API secrets; the EKS app tier persists to RDS.
    EdgeSpec(id="e6", source="bedrock", target="secrets", marker="6"),
    EdgeSpec(id="e7", source="eks", target="rds", marker="7"),
)
_CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
    ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
    ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
)

SPEC = DiagramSpec(
    diagram_id="aws-agent-platform", diagram_name="aws-agent-platform",
    axis="north-south", nodes=_NODES, edges=_EDGES, containers=_CONTAINERS,
    flow_lines=(), title="aws-agent-platform",
)

CONTAINER_LABELS = {
    "account": "Account 123456789012",
    "region-a": "region us-east-1",
    "vpc-a": "VPC agent-vpc",
}
FLOW_LINES = (
    "Flow",
    "1. EKS routes request to ALB",
    "2. ALB invokes Lambda function",
    "3. Lambda enqueues task to SQS (async)",
    "4. Lambda calls Bedrock for inference",
    "5. Lambda stores artifact in S3 bucket",
    "6. Bedrock reads secrets from Secrets Manager",
    "7. EKS app tier persists conversation to RDS",
)


def skin() -> ExampleSkin:
    styles = {
        "account": resolve_container("boundary", "aws")["style_string"],
        "region-a": resolve_container("region", "aws")["style_string"],
        "vpc-a": resolve_container("network_boundary", "aws")["style_string"],
    }
    return ExampleSkin(
        spec=SPEC,
        renderers={nid: image_icon(path) for nid, path in _ICONS.items()},
        labels=LABELS,
        container_labels=CONTAINER_LABELS,
        container_styles=styles,
        flow_lines=FLOW_LINES,
        title="aws agent-platform — 123456789012 / us-east-1 | 2026-09-30 | v4",
        diagram_id="aws-agent-platform",
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(skin, OUT, "build_aws_agent_platform_example"))
