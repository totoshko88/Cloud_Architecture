"""Clarify gate (1.11.0 WS5) — surface spec assumptions BEFORE generation.

Today a diagram is partly built on silent assumptions: a node with no declared
container falls back to a geometric tier-band, an edge with no ``kind_hint`` is
classified from lane/region geometry, and a role the provider mapping cannot
resolve is (in the contract path) quietly replaced by the boundary icon. None of
these are recorded, so a reader cannot tell a stated fact from a guess (the SEP
09 legend literally hand-types ``draft-assumption`` lines).

The clarify gate scans a :class:`~rule_engine.layout.model.DiagramSpec` for these
uncertainties and returns a list of typed :class:`Assumption` records. A caller
then applies a policy:

- ``ask``   — raise :class:`ClarifyRequired` carrying the list, draw nothing;
- ``auto``  — apply each assumption's default, draw, and RECORD every applied
              assumption in the companion document (structured, not free text);
- ``error`` — fail the build if any assumption exists (CI strict mode).

The gate is a **read-only pre-pass**: it never mutates the spec or the geometry,
so a fully-specified spec scans empty and the drawn ``.drawio`` is byte-identical
to the no-gate result. It runs OUTSIDE ``layout()`` (the caller invokes it before
building), keeping the deterministic layout hot-path untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Sequence, Tuple

from .model import DiagramSpec


class UncertaintyKind(str, Enum):
    """The kinds of uncertainty the gate detects."""

    UNRESOLVED_ROLE = "unresolved_role"
    MISSING_MEMBERSHIP = "missing_membership"
    AMBIGUOUS_EDGE_KIND = "ambiguous_edge_kind"
    GUESSED_DIRECTION = "guessed_direction"


class ClarifyPolicy(str, Enum):
    ASK = "ask"
    AUTO = "auto"
    ERROR = "error"


@dataclass(frozen=True)
class Assumption:
    """One uncertainty the engine would resolve by a default."""

    kind: UncertaintyKind
    target_id: str          # node id or edge id the assumption is about
    question: str           # owner-facing question
    default: str            # what `auto` picks
    rationale: str          # why that default is reasonable


class ClarifyRequired(Exception):
    """Raised under the ``ask`` policy when at least one assumption exists."""

    def __init__(self, assumptions: Sequence[Assumption]):
        self.assumptions: Tuple[Assumption, ...] = tuple(assumptions)
        super().__init__(
            f"{len(self.assumptions)} assumption(s) need owner input before drawing"
        )


#: A role resolver predicate: ``(role) -> bool`` is True when the role resolves
#: to an icon. Optional — when None the UNRESOLVED_ROLE scan is skipped (the
#: module stays self-contained and testable without the icon index).
RoleResolver = Callable[[str], bool]


def _region_has_leaf_container(spec: DiagramSpec, region: str) -> bool:
    """True when ``region`` has a vpc/az leaf a node could be a member of."""
    return any(
        c.region == region and c.kind in ("vpc", "az")
        for c in spec.containers
    )


def scan_uncertainties(
    spec: DiagramSpec, *, role_resolves: Optional[RoleResolver] = None,
) -> Tuple[Assumption, ...]:
    """Return the assumptions ``spec`` would be built on, in deterministic order.

    Detectors (each mirrors the engine's real silent-default site):

    * **unresolved_role** — a node whose ``role`` does not resolve to an icon
      (only when ``role_resolves`` is supplied). Default: the boundary icon
      fallback, the same choice ``contract._resolve_nodes`` makes today.
    * **missing_membership** — a node with ``container is None`` whose region
      holds a vpc/az leaf it could belong to (the ``base.py`` membership
      condition). Default: the geometric tier-band partition.
    * **ambiguous_edge_kind** — an edge with no ``kind_hint`` AND no derivable
      region relationship (both endpoints account-level). Default: the geometric
      classifier's choice.
    """
    out: List[Assumption] = []
    node_by_id = {n.id: n for n in spec.nodes}

    for n in sorted(spec.nodes, key=lambda x: x.id):
        if role_resolves is not None and not role_resolves(n.role):
            out.append(Assumption(
                kind=UncertaintyKind.UNRESOLVED_ROLE,
                target_id=n.id,
                question=f"Node {n.id!r} role {n.role!r} has no provider icon. "
                         f"Which service icon should it use?",
                default="boundary icon fallback",
                rationale="the contract falls back to the enclosing boundary "
                          "icon when a role does not resolve",
            ))
        if n.container is None and n.region and _region_has_leaf_container(spec, n.region):
            out.append(Assumption(
                kind=UncertaintyKind.MISSING_MEMBERSHIP,
                target_id=n.id,
                question=f"Node {n.id!r} declares no container but region "
                         f"{n.region!r} has a VPC/AZ. Which does it belong to?",
                default="geometric tier-band partition",
                rationale="the engine assigns the node to the tier band its "
                          "lane lands in when no container is declared",
            ))

    for e in sorted(spec.edges, key=lambda x: x.id):
        s, t = node_by_id.get(e.source), node_by_id.get(e.target)
        if e.kind_hint is None and s is not None and t is not None:
            # ambiguous only when neither endpoint carries a region, so the
            # geometric classifier cannot tell same-region from cross-region.
            if not s.region and not t.region:
                out.append(Assumption(
                    kind=UncertaintyKind.AMBIGUOUS_EDGE_KIND,
                    target_id=e.id,
                    question=f"Edge {e.id!r} ({e.source}->{e.target}) has no "
                             f"kind_hint and neither endpoint names a region. "
                             f"Is it a straight / spine / cross-region hop?",
                    default="geometric classifier",
                    rationale="classify_edge derives the class from lane/region; "
                              "with no region it defaults to the in-band class",
                ))

    return tuple(out)


def clarify_gate(
    spec: DiagramSpec,
    policy: ClarifyPolicy | str = ClarifyPolicy.AUTO,
    *,
    role_resolves: Optional[RoleResolver] = None,
    sink: Optional[List[Assumption]] = None,
) -> Tuple[Assumption, ...]:
    """Run the gate under ``policy`` and return the assumptions found.

    * ``ask``   — raise :class:`ClarifyRequired` if any assumption exists.
    * ``auto``  — append every assumption to ``sink`` (for the companion
                  recorder) and return them; the caller proceeds to build.
    * ``error`` — raise :class:`ClarifyRequired` if any assumption exists
                  (same halt as ask, used as a CI strict gate).

    A fully-specified spec returns the empty tuple under every policy and the
    gate is a no-op.
    """
    policy = ClarifyPolicy(policy)
    found = scan_uncertainties(spec, role_resolves=role_resolves)
    if not found:
        return found
    if policy in (ClarifyPolicy.ASK, ClarifyPolicy.ERROR):
        raise ClarifyRequired(found)
    # AUTO: record and proceed.
    if sink is not None:
        sink.extend(found)
    return found


def format_assumptions_markdown(assumptions: Sequence[Assumption]) -> str:
    """Render recorded assumptions as a companion ``## Assumptions`` section.

    The structured replacement for hand-typed ``draft-assumption`` legend lines:
    one bullet per assumption naming the target, the default applied, and why.
    Returns '' when there are none (the section is omitted entirely).
    """
    if not assumptions:
        return ""
    lines = ["## Assumptions", ""]
    for a in assumptions:
        lines.append(
            f"- **{a.kind.value}** on `{a.target_id}`: applied default "
            f"*{a.default}* — {a.rationale}."
        )
    lines.append("")
    return "\n".join(lines)
