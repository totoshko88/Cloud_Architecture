#!/usr/bin/env python3
"""Azure OpenAI RAG example (``examples/azure/01-azure-openai-rag.drawio``).

Engine-generated (D1 / D20): a coordinate-free :class:`DiagramSpec` is laid out
by ``layout()`` and serialized by ``build_diagram()`` through the shared
:mod:`engine_example_common` builder, so the geometry is the engine's output and
regenerates whenever the layout engine changes. This file supplies only the
Azure official icons (``img/lib/azure2/...``), the labels, the container
captions/styles (from ``mappings/azure-icons.yaml``), the Flow text and the title.

Topology (a retrieval-augmented-generation API): an external User calls an
Application Gateway (VNet-scoped) that routes to the ApiFunction. ApiFunction
publishes an async ingest job to Service Bus, embeds via Azure OpenAI and reads
its API key from Key Vault. Service Bus delivers to the IngestFunction, which
loads documents from Blob Storage and upserts vectors into Azure SQL DB; Azure
OpenAI queries those vectors. The Application Gateway is VNet-scoped; every other
Azure service is a regional managed service (outside the VNet — the engine
places them there by scope). The User actor sits outside all boundaries.

Usage::

    python scripts/build_azure_openai_rag_example.py            # write
    python scripts/build_azure_openai_rag_example.py --check    # exit 1 stale
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

OUT = REPO_ROOT / "examples" / "azure" / "01-azure-openai-rag.drawio"

_AZ = "img/lib/azure2"
_ICONS = {
    "user": f"{_AZ}/identity/Users.svg",
    "appgw": f"{_AZ}/networking/Application_Gateways.svg",
    "api": f"{_AZ}/compute/Function_Apps.svg",
    "bus": f"{_AZ}/general/Service_Bus.svg",
    "ingest": f"{_AZ}/compute/Function_Apps.svg",
    "openai": f"{_AZ}/ai_machine_learning/Azure_OpenAI.svg",
    "vault": f"{_AZ}/security/Key_Vaults.svg",
    "blob": f"{_AZ}/storage/Storage_Accounts.svg",
    "sql": f"{_AZ}/databases/SQL_Database.svg",
}
LABELS = {
    "user": "User", "appgw": "AppGateway", "api": "ApiFunction",
    "bus": "ServiceBus", "ingest": "IngestFunction", "openai": "AzureOpenAI",
    "vault": "KeyVault", "blob": "BlobStorage", "sql": "AzureSqlDB",
}

# Coordinate-free spec. AppGateway is VNet-scoped (declares the vnet container);
# every other Azure service is regional (declares the region container, so the
# engine places it outside the Network Boundary). The User actor sits outside
# all boundaries (lane "actors", no container). Each hub keeps <= 3 fan-out
# edges (the engine caps a node face at three exits).
_NODES = (
    NodeSpec(id="user", role="user", lane="actors", region="", slot=0),
    NodeSpec(id="appgw", role="lb", lane="router", region="a", slot=0, container="vnet-a"),
    NodeSpec(id="api", role="fn", lane="workers", region="a", slot=0, container="region-a"),
    # 1.10.6: the queue sits on its consumer's row (slot 2, the ingest
    # function's), so the delivery is one level hop; Azure SQL DB moves up
    # between Azure OpenAI and Blob Storage, so its two writers arrive from
    # above and below instead of crossing. Measured: 2 crossings -> 0, every
    # route rule-clean, with no hand-pinned edge geometry.
    NodeSpec(id="bus", role="queue", lane="async", region="a", slot=2, container="region-a"),
    NodeSpec(id="ingest", role="fn", lane="workers", region="a", slot=2, container="region-a"),
    NodeSpec(id="openai", role="llm_platform", lane="platform", region="a", slot=0, container="region-a"),
    NodeSpec(id="vault", role="sec", lane="platform", region="a", slot=1, container="region-a"),
    NodeSpec(id="blob", role="obj", lane="data", region="a", slot=2, container="region-a"),
    NodeSpec(id="sql", role="sql", lane="data", region="a", slot=1, container="region-a"),
)
_EDGES = (
    EdgeSpec(id="e1", source="user", target="appgw", marker="1"),
    EdgeSpec(id="e2", source="appgw", target="api", marker="2"),
    # ApiFunction hub fan-out (exactly three): async ingest job, embeddings, key.
    EdgeSpec(id="e3", source="api", target="bus", marker="3", dashed=True),
    EdgeSpec(id="e5", source="api", target="openai", marker="5"),
    EdgeSpec(id="e6", source="api", target="vault", marker="6"),
    # Async delivery, then the ingest path loads docs and upserts vectors.
    EdgeSpec(id="e4", source="bus", target="ingest", marker="4", dashed=True),
    EdgeSpec(id="e7", source="ingest", target="blob", marker="7"),
    EdgeSpec(id="e8", source="ingest", target="sql", marker="8"),
    # Azure OpenAI queries the vectors it upserted.
    EdgeSpec(id="e9", source="openai", target="sql", marker="9"),
)
_CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
    ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
    ContainerSpec(id="vnet-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
)

SPEC = DiagramSpec(
    diagram_id="azure-openai-rag", diagram_name="azure-openai-rag",
    axis="left-right", nodes=_NODES, edges=_EDGES, containers=_CONTAINERS,
    flow_lines=(), title="azure-openai-rag", compact=True,
)

CONTAINER_LABELS = {
    "account": "Subscription sub-9f3c1a",
    "region-a": "region eastus",
    "vnet-a": "VNet vnet-core",
}
FLOW_LINES = (
    "Flow",
    "1. User sends HTTPS request to Application Gateway",
    "2. App Gateway routes /chat to the API Function",
    "3. API Function publishes ingest job to Service Bus (async)",
    "4. Service Bus delivers message to Ingest Function (async)",
    "5. API Function embeds and completes via Azure OpenAI",
    "6. API Function reads API key from Key Vault",
    "7. Ingest Function loads documents from Blob Storage",
    "8. Ingest Function upserts vectors into Azure SQL DB",
    "9. Azure OpenAI queries vectors from Azure SQL DB",
)


def skin() -> ExampleSkin:
    styles = {
        "account": resolve_container("boundary", "azure")["style_string"],
        "region-a": resolve_container("region", "azure")["style_string"],
        "vnet-a": resolve_container("network_boundary", "azure")["style_string"],
    }
    return ExampleSkin(
        spec=SPEC,
        renderers={nid: image_icon(path) for nid, path in _ICONS.items()},
        labels=LABELS,
        container_labels=CONTAINER_LABELS,
        container_styles=styles,
        flow_lines=FLOW_LINES,
        title="azure openai-rag — sub-9f3c1a / eastus | 2026-09-30 | v2",
        diagram_id="azure-openai-rag",
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(skin, OUT, "build_azure_openai_rag_example"))
