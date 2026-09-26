#!/usr/bin/env python3
"""Generate the per-domain JSON and per-resource subfolders of the example Snapshots.

Why this exists
---------------
Two Snapshot folders ship as golden examples — one ``aws``, one ``generic`` — and
until v1.6.0 each held only two Markdown documents: ``00-MANIFEST.md`` and
``10-delta-example.md``. Their own manifests, however, state that "each service
domain is written to exactly one JSON file at the Snapshot root
(``compute.json``, ``storage.json``, ``network.json``), and each enumerated
resource gets one subfolder under ``resources/``", and record ``file_count: 11``
against the two files actually present.

So the reference Snapshots described a shape they did not have — the same class of
doc/data mismatch the re-connected HA landscapes fixed for diagrams. The new
snapshot gate (``rule-engine-check-snapshot``) surfaces it as
``no-domain-json`` / ``resources-missing`` / ``file-count``. This script closes
the gap by materialising the missing files, so the examples teach the whole
``inventory-standards.md`` §3–§5 contract rather than only the manifest.

The per-resource documents are **Normalized Resources** conforming to
``schemas/inventory.schema.json`` (so the CI schema gate validates them), and the
domain files use the collector's own envelope ``{"service", "resources"}`` (an
object with no top-level ``provider``, which the schema gate correctly skips).
``config_digest`` is the SHA-256 of the resource identity, so re-running this
script is byte-stable.

Resource metadata only — no secret values, key material, or SecureString
contents, per §7 (the linter's ``secret-safety`` CRITICAL gate covers every file
written here).

Usage::

    python scripts/build_example_snapshots.py          # write both snapshots
    python scripts/build_example_snapshots.py --check   # verify, write nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

AWS_SNAPSHOT = (
    REPO_ROOT / "examples" / "aws"
    / "inventory-aws-123456789012-us-east-1-2026-09-22_1430"
)
GENERIC_SNAPSHOT = (
    REPO_ROOT / "examples" / "generic"
    / "inventory-generic-env-prod-region-1-2026-09-22_1430"
)


def _digest(identity: str) -> str:
    """Deterministic 64-hex ``config_digest`` for a resource identity."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    """Filesystem-safe slug, matching ``collector._slug``."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")
    return slug or "resource"


def _resource(
    provider: str,
    resource_type: str,
    native_type: str,
    rid: str,
    name: str,
    boundary: str,
    region: str,
    tags: Dict[str, str],
) -> Dict[str, object]:
    """Build one Normalized Resource (schemas/inventory.schema.json)."""
    return {
        "provider": provider,
        "resource_type": resource_type,
        "native_type": native_type,
        "id": rid,
        "name": name,
        "boundary": boundary,
        "region": region,
        "tags": dict(tags),
        "config_digest": _digest(rid),
    }


# ---------------------------------------------------------------------------
# AWS example — the agent platform of examples/aws/01-aws-agent-platform.drawio.
# Six resources across the three domains the manifest names, so the snapshot
# holds 2 Markdown + 3 domain JSON + 6 resource.json = 11 files, exactly the
# ``file_count: 11`` the manifest records.
# ---------------------------------------------------------------------------

_AWS_BOUNDARY = "123456789012"
_AWS_REGION = "us-east-1"
_AWS_TAGS = {"env": "prod", "team": "platform", "workload": "agent-platform"}

AWS_DOMAINS: Dict[str, List[Dict[str, object]]] = {
    "network": [
        _resource("aws", "network_boundary", "AWS::EC2::VPC",
                  "vpc-0a1b2c3d4e5f60718", "agent-platform-vpc",
                  _AWS_BOUNDARY, _AWS_REGION, _AWS_TAGS),
    ],
    "compute": [
        _resource("aws", "serverless_fn", "AWS::Lambda::Function",
                  "arn:aws:lambda:us-east-1:123456789012:function:agent-tool-invoker",
                  "agent-tool-invoker", _AWS_BOUNDARY, _AWS_REGION, _AWS_TAGS),
        _resource("aws", "managed_k8s", "AWS::EKS::Cluster",
                  "arn:aws:eks:us-east-1:123456789012:cluster/agent-runtime",
                  "agent-runtime", _AWS_BOUNDARY, _AWS_REGION, _AWS_TAGS),
        _resource("aws", "llm_platform", "AWS::Bedrock::FoundationModel",
                  "arn:aws:bedrock:us-east-1::foundation-model/agent-reasoning",
                  "agent-reasoning", _AWS_BOUNDARY, _AWS_REGION, _AWS_TAGS),
    ],
    "storage": [
        _resource("aws", "object_store", "AWS::S3::Bucket",
                  "arn:aws:s3:::agent-artifact-store", "agent-artifact-store",
                  _AWS_BOUNDARY, _AWS_REGION, _AWS_TAGS),
        _resource("aws", "object_store", "AWS::S3::Bucket",
                  "arn:aws:s3:::agent-transcripts", "agent-transcripts",
                  _AWS_BOUNDARY, _AWS_REGION, _AWS_TAGS),
    ],
}

# ---------------------------------------------------------------------------
# Generic example — the vendor-neutral profile: no vendor service names, so the
# native types are the profile's own neutral labels and the identities are
# Terraform addresses (the profile's declared collection method is manual entry /
# Terraform-state import).
# ---------------------------------------------------------------------------

_GEN_BOUNDARY = "env-prod"
_GEN_REGION = "region-1"
_GEN_TAGS = {"env": "prod", "team": "platform", "source": "terraform-state"}

GENERIC_DOMAINS: Dict[str, List[Dict[str, object]]] = {
    "network": [
        _resource("generic", "network_boundary", "Network",
                  "module.network.network.prod", "prod-network",
                  _GEN_BOUNDARY, _GEN_REGION, _GEN_TAGS),
    ],
    "compute": [
        _resource("generic", "serverless_fn", "Function",
                  "module.compute.function.ingest", "ingest-function",
                  _GEN_BOUNDARY, _GEN_REGION, _GEN_TAGS),
        _resource("generic", "managed_k8s", "Managed Kubernetes",
                  "module.compute.managed_kubernetes.workload", "workload-cluster",
                  _GEN_BOUNDARY, _GEN_REGION, _GEN_TAGS),
        _resource("generic", "managed_sql", "Managed SQL",
                  "module.data.managed_sql.primary", "primary-sql",
                  _GEN_BOUNDARY, _GEN_REGION, _GEN_TAGS),
    ],
    "storage": [
        _resource("generic", "object_store", "Object Store",
                  "module.data.object_store.artifacts", "artifact-store",
                  _GEN_BOUNDARY, _GEN_REGION, _GEN_TAGS),
        _resource("generic", "secrets_store", "Secrets Store",
                  "module.security.secrets_store.app", "app-secrets",
                  _GEN_BOUNDARY, _GEN_REGION, _GEN_TAGS),
    ],
}


def _render(domains: Dict[str, List[Dict[str, object]]]) -> Dict[str, str]:
    """Return ``{relative path -> JSON text}`` for one snapshot's data files.

    Mirrors ``collector.collect`` exactly: one ``<domain>.json`` at the root with
    the ``{"service", "resources"}`` envelope, and one
    ``resources/<domain>-<identity>/resource.json`` per enumerated resource.
    """
    out: Dict[str, str] = {}
    for domain, resources in domains.items():
        out[f"{domain}.json"] = json.dumps(
            {"service": domain, "resources": resources}, indent=2, sort_keys=True
        ) + "\n"
        for resource in resources:
            sub = f"{_slug(domain)}-{_slug(str(resource['id']))}"
            out[f"resources/{sub}/resource.json"] = json.dumps(
                resource, indent=2, sort_keys=True
            ) + "\n"
    return out


def build(check: bool = False) -> int:
    """Write (or, with ``check``, verify) both example snapshots' data files."""
    stale: List[str] = []
    for snapshot, domains in ((AWS_SNAPSHOT, AWS_DOMAINS),
                              (GENERIC_SNAPSHOT, GENERIC_DOMAINS)):
        if not snapshot.is_dir():
            print(f"error: missing snapshot folder {snapshot}", file=sys.stderr)
            return 2
        files = _render(domains)
        for rel, text in sorted(files.items()):
            target = snapshot / rel
            if check:
                current = target.read_text(encoding="utf-8") if target.is_file() else None
                if current != text:
                    stale.append(str(target.relative_to(REPO_ROOT)))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        if not check:
            total = sum(1 for p in snapshot.rglob("*") if p.is_file())
            print(
                f"build_example_snapshots: {snapshot.relative_to(REPO_ROOT)} "
                f"-> {len(files)} data file(s), {total} file(s) total"
            )
    if check:
        if stale:
            print("BLOCKING: example snapshot data files are stale or missing:",
                  file=sys.stderr)
            for s in stale:
                print(f"    - {s}", file=sys.stderr)
            print("Re-run: python scripts/build_example_snapshots.py",
                  file=sys.stderr)
            return 1
        print("OK: example snapshot data files are current.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build_example_snapshots")
    parser.add_argument(
        "--check", action="store_true",
        help="verify the generated files are current; write nothing",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return build(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
