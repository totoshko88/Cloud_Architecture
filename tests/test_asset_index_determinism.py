"""The icon index is a pure function of the pack contents (v1.6.1).

Before 1.6.1 ``index_provider`` kept the first file the directory walk reached
for each slug, and ``os.walk`` order is the filesystem's readdir order — APFS
hash order on macOS, a different order on Linux. Reversing the walk changed 15 of
the 32 aws/azure role references in the committed ``mappings/icon-index.json``,
so CI's staleness check could fail on an unchanged tree. These tests build a
synthetic pack (the real packs are not committed) and index it under several
enumeration orders.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from rule_engine import asset_index as ai

_AWS_FILES = [
    "Architecture-Service-Icons_07312026/Arch_Compute/16/Arch_Amazon-EC2_16.svg",
    "Architecture-Service-Icons_07312026/Arch_Compute/32/Arch_Amazon-EC2_32.svg",
    "Architecture-Service-Icons_07312026/Arch_Compute/32/Arch_Amazon-EC2_32.png",
    "Architecture-Service-Icons_07312026/Arch_Compute/48/Arch_Amazon-EC2_48.svg",
    "Architecture-Service-Icons_07312026/Arch_Compute/64/Arch_Amazon-EC2_64.svg",
    "Architecture-Group-Icons_07312026/AWS-Cloud-logo_32.svg",
    "Architecture-Group-Icons_07312026/AWS-Cloud-logo_32_Dark.svg",
    "Resource-Icons_07312026/Res_Storage/Res_Amazon-Elastic-File-System_File-System_48.png",
    "Resource-Icons_07312026/Res_Storage/Res_Amazon-Elastic-File-System_File-System_48.svg",
]

_AZURE_FILES = [
    "Azure_Public_Service_Icons/Icons/app services/00056-icon-service-CDN-Profiles.svg",
    "Azure_Public_Service_Icons/Icons/networking/00056-icon-service-CDN-Profiles.svg",
    "Azure_Public_Service_Icons/Icons/compute/10029-icon-service-Function-Apps.svg",
    "Azure_Public_Service_Icons/Icons/iot/10029-icon-service-Function-Apps.svg",
]


def _make_pack(root: Path, files) -> Path:
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>" if rel.endswith(".svg") else "png", encoding="utf-8")
    return root


def _index_with_order(monkeypatch, provider: str, root: Path, reorder) -> dict:
    original = ai._iter_files
    monkeypatch.setattr(ai, "_iter_files", lambda r: reorder(original(r)))
    try:
        index = ai.index_provider(provider, str(root))
    finally:
        monkeypatch.setattr(ai, "_iter_files", original)
    return {slug: Path(entry.path).as_posix() for slug, entry in index.items()}


_ORDERS = {
    "sorted": lambda files: list(files),
    "reversed": lambda files: list(reversed(files)),
    "shuffled-1": lambda files: random.Random(1).sample(files, len(files)),
    "shuffled-2": lambda files: random.Random(2).sample(files, len(files)),
}


@pytest.mark.parametrize("provider,files", [("aws", _AWS_FILES), ("azure", _AZURE_FILES)])
def test_index_is_independent_of_enumeration_order(monkeypatch, tmp_path, provider, files):
    root = _make_pack(tmp_path / provider, files)
    results = {
        name: _index_with_order(monkeypatch, provider, root, reorder)
        for name, reorder in _ORDERS.items()
    }
    first = results["sorted"]
    for name, result in results.items():
        assert result == first, f"{provider} index differs under {name} enumeration"


def _slug_of(provider: str, rel: str) -> str:
    return ai.normalize_slug(ai._DISPLAY_FN[provider](Path(rel)), strip_vendor=True)


def test_aws_ranking_prefers_svg_then_base_variant_then_32px(tmp_path):
    root = _make_pack(tmp_path / "aws", _AWS_FILES)
    index = {s: Path(e.path).as_posix() for s, e in ai.index_provider("aws", str(root)).items()}
    assert index["ec2"].endswith("/32/Arch_Amazon-EC2_32.svg")
    # The base icon, not its _Dark variant.
    logo = _slug_of("aws", "Architecture-Group-Icons_07312026/AWS-Cloud-logo_32.svg")
    assert index[logo].endswith("AWS-Cloud-logo_32.svg")
    # SVG over PNG at the same size.
    efs = _slug_of("aws", _AWS_FILES[-1])
    assert index[efs].endswith("_File-System_48.svg")


def test_azure_duplicate_category_tie_break_is_stable(tmp_path):
    """The same icon filed under two category folders: the greater path wins.

    This is the choice the committed index and the Azure HA landscape golden
    already embed for the CDN icon (``networking/``)."""
    root = _make_pack(tmp_path / "azure", _AZURE_FILES)
    index = {s: Path(e.path).as_posix() for s, e in ai.index_provider("azure", str(root)).items()}
    assert index["cdn-profiles"].startswith("Azure_Public_Service_Icons/Icons/networking/")
    assert index["function-apps"].startswith("Azure_Public_Service_Icons/Icons/iot/")


def test_size_and_theme_variants_are_not_reported_as_collisions(tmp_path, caplog):
    root = _make_pack(tmp_path / "aws", _AWS_FILES)
    with caplog.at_level("WARNING", logger=ai.__name__):
        ai.index_provider("aws", str(root))
    assert not [r for r in caplog.records if "slug collision" in r.getMessage()]


def test_distinct_services_on_one_slug_are_reported_once(tmp_path, caplog):
    root = _make_pack(
        tmp_path / "azure",
        [
            "Azure_Public_Service_Icons/Icons/networking/00427-icon-service-Private-Link.svg",
            "Azure_Public_Service_Icons/Icons/networking/01105-icon-service-Private-Link-Service.svg",
        ],
    )
    with caplog.at_level("WARNING", logger=ai.__name__):
        ai.index_provider("azure", str(root))
    messages = [r.getMessage() for r in caplog.records if "slug collision" in r.getMessage()]
    assert len(messages) == 1
    assert "'private-link'" in messages[0]


def test_token_match_tie_is_broken_by_slug_not_insertion_order():
    def entry(slug):
        return ai.AssetEntry(provider="aws", slug=slug, display_name=slug, path=f"{slug}.svg", ext=".svg")

    a, b = entry("alpha-queue"), entry("omega-queue")
    forward = ai._best_token_match(["queue"], {"alpha-queue": a, "omega-queue": b})
    backward = ai._best_token_match(["queue"], {"omega-queue": b, "alpha-queue": a})
    assert forward is not None and backward is not None
    assert forward.slug == backward.slug == "alpha-queue"
