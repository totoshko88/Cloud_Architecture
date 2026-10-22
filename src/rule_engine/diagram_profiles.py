"""Data-defined diagram-type profiles (1.11.0 WS6, Requirement 6).

A ``TypeProfile`` is the engine's view of one user-facing ``diagram_type`` from
``mappings/diagram-types.yaml``: the lint ``base_class`` it belongs to plus the
type-scoped knobs the generator and linter read (``node_cap``, ``axis``,
``allowed_roles``, ``special_containers``, ``lint_profile``). Reading a profile
is DESCRIPTIVE and side-effect-free: a diagram that declares no ``diagram_type``
(or an unknown one) resolves to ``None`` and the engine behaves exactly as in
1.10.12 — so the profiles file is byte-inert until a diagram opts in.

The file is optional: a workspace without ``diagram-types.yaml`` simply has no
profiles (``load_type_profile`` returns ``None`` for every type), never an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Optional, Tuple

import yaml

from rule_engine.asset_index import resolve_bundled_dir

_PROFILES_FILE = "diagram-types.yaml"


@dataclass(frozen=True)
class TypeProfile:
    """One diagram-type profile (Req 6 AC1), coordinate-free."""

    name: str
    base_class: str
    node_cap: Optional[int] = None
    axis: Optional[str] = None
    allowed_roles: Tuple[str, ...] = ()
    special_containers: Tuple[str, ...] = ()
    lint_profile: Optional[str] = None
    #: 1.11.0 WS7 (access type, Req 7 AC1): the role dimension the type
    #: aggregates on before the node cap applies — e.g. ``principal`` for an
    #: access diagram, so a 40-role account collapses to a small
    #: principal→policy→resource graph. ``None`` for types that do not aggregate.
    aggregation_key: Optional[str] = None


@lru_cache(maxsize=1)
def _load_profiles() -> Dict[str, TypeProfile]:
    """Parse ``diagram-types.yaml`` into ``{type_name: TypeProfile}``.

    Returns ``{}`` when the file is absent or declares no profiles. Malformed
    entries are skipped rather than raising, so one bad profile never breaks
    resolution of the others (and never breaks a diagram that uses none)."""
    path = resolve_bundled_dir("mappings") / _PROFILES_FILE
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    raw = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, TypeProfile] = {}
    for name, body in raw.items():
        if not isinstance(body, dict) or not body.get("base_class"):
            continue
        node_cap = body.get("node_cap")
        out[str(name)] = TypeProfile(
            name=str(name),
            base_class=str(body["base_class"]),
            node_cap=int(node_cap) if isinstance(node_cap, int) else None,
            axis=(str(body["axis"]) if body.get("axis") else None),
            allowed_roles=tuple(str(r) for r in (body.get("allowed_roles") or ())),
            special_containers=tuple(
                str(c) for c in (body.get("special_containers") or ())
            ),
            lint_profile=(
                str(body["lint_profile"]) if body.get("lint_profile") else None
            ),
            aggregation_key=(
                str(body["aggregation_key"]) if body.get("aggregation_key") else None
            ),
        )
    return out


def load_type_profile(diagram_type: Optional[str]) -> Optional[TypeProfile]:
    """The :class:`TypeProfile` for ``diagram_type``, or ``None`` when the type
    is empty, unknown, or no profiles file is present (byte-inert default)."""
    if not diagram_type:
        return None
    return _load_profiles().get(str(diagram_type).strip())
