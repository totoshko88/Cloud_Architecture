"""Post-layout lint-only check (FEAT-004, 1.13.0).

Why this exists
---------------
The scored solver and the repair oracle judge a candidate on the ROUTING rules
(:func:`rule_engine.geometry.rule_violations`) and the blocking geometry rules
(``repair._BLOCKING_RULES``). Several lint rules that are ERRORs are not among
them, because they need context a candidate does not carry cheaply (the
provider's container styles, the spec's roles): ``scope-placement``,
``geometric-containment``, ``container-style``, ``container-caption-overflow``
``caption-overprints-node`` and ``legend-placement`` ``overlaps-node``. A ``layout()`` result could therefore
look clean (``layout_warnings == ()``) and still be blocked by the linter.

:func:`postcheck` runs those rules ONCE on the finished diagram, so the
defect is reported where the spec author looks first. It never raises and it
does not feed the solver: scoring them per candidate would need the mapping
context in the inner loop, which is too costly (recorded as a partial in the
1.13.0 CHANGELOG).

Scope notes
-----------
* The diagram is serialized the way the repair oracle does it (stub icons,
  :func:`rule_engine.layout.repair._serialize_candidate`), with every container
  drawn in its provider's declared style (``mappings/<provider>-icons.yaml``,
  provider = the title's first token) unless the spec carries its own style,
  and nodes parented by spec membership.
* ``container-caption-overflow`` is judged only for containers whose caption
  the spec declares (``container_captions``); the stub otherwise captions a box
  with its id, which is not what the skin draws.
* The ``edge-crossing-excess`` hard cap is a landscape-only ERROR and a spec
  does not carry its diagram class, so it is not checked here.
* The numbered-marker rules (``marker-label-collision``,
  ``marker-on-container-border``) are not checked either: a marker's anchor is
  final only after ``build_diagram``'s finishing re-routes and marker hygiene,
  so judging the layout() geometry reports overprints the published document
  does not have (the kubernetes landscape golden: ``e14`` on ``ns-data``).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import PlacedDiagram

#: Rules whose findings make the result ``degraded``: each is an ERROR on the
#: classes a ``layout()`` diagram is built for (a flow, a network / landscape
#: view). ``scope-placement`` and ``geometric-containment`` are ERRORs on a
#: network diagram or a landscape, the kinds a spec with containers draws.
BLOCKING_RULES = (
    "scope-placement",
    "geometric-containment",
    "container-style",
    "container-caption-overflow",
    "legend-placement",
)


def _providers(title: str) -> List[str]:
    from ..constants import PROVIDERS

    token = ((title or "").split() or [""])[0].lower()
    return [token] if token in PROVIDERS else list(PROVIDERS)


def _container_mappings(providers: Sequence[str]) -> Dict[str, Mapping]:
    from .. import icon_resolver

    out: Dict[str, Mapping] = {}
    for provider in providers:
        try:
            out[provider] = icon_resolver.load_mapping(provider).get("containers") or {}
        except icon_resolver.IconResolverError:
            continue
    return out


#: The style a container gets when no real one is known (a multi-provider or
#: provider-less title, an unknown kind): still a Boundary to the parser
#: (``dashed=1;fillColor=none``), but its dash pattern matches no declared
#: ``containers.*.style``, so ``container-style`` and ``scope-placement`` leave
#: it unrecognised instead of judging the oracle's stub colours.
_UNKNOWN_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=2 6;"
    "strokeColor=#808080;fillColor=none;verticalAlign=top;fontColor=#333333;fontSize=12"
)


def _styled_spec(placed: PlacedDiagram, providers: Sequence[str]):
    """The spec with every container in its provider's declared style (a style
    the spec already declares wins); a container with no known style (a
    multi-provider title, an unknown kind) gets :data:`_UNKNOWN_STYLE`."""
    spec = placed.spec
    styles = dict(getattr(spec, "container_styles", ()) or ())
    for c in spec.containers:
        if c.id in styles:
            continue
        style = _UNKNOWN_STYLE
        if len(providers) == 1:
            from ..draw_cli import _container_style

            try:
                style = _container_style(c.kind, providers[0])
            except Exception:  # an unknown kind stays unrecognised
                pass
        styles[c.id] = style
    return replace(spec, container_styles=tuple(sorted(styles.items())))


def _geometry(placed: PlacedDiagram, providers: Sequence[str]):
    from ..drawio_model import parse_drawio
    from ..geometry import build_geometry
    from .pipeline import membership_of
    from .repair import _oracle_container_id, _serialize_candidate

    cand = replace(placed, spec=_styled_spec(placed, providers))
    labels = dict(getattr(placed.spec, "node_labels", ()) or ())
    try:
        # Every container is styled here, so the serializer writes it under its
        # oracle id (``boundary-<id>``); membership must name the same box.
        membership = {nid: _oracle_container_id(cid) if cid else ""
                      for nid, cid in membership_of(placed).items()}
    except (KeyError, ValueError):
        membership = None
    text = _serialize_candidate(cand, labels, membership=membership)
    return build_geometry(parse_drawio(text.encode("utf-8"), path="<postcheck>.drawio")[0])


def _scope_findings(geo, placed: PlacedDiagram, providers: Sequence[str],
                    mappings: Mapping) -> List[Tuple[str, str]]:
    from ..geometry import check_scope_placement
    from .base import effective_scope, is_vpc_edge, provider_role_scope

    nodes = {n.id: n for n in placed.spec.nodes}
    single = providers[0] if len(providers) == 1 else None

    def node(nid: str):
        return nodes.get(nid)

    def scope_of(nid: str) -> Optional[str]:
        n = node(nid)
        return effective_scope(n) if n is not None else None

    def explicit(nid: str) -> bool:
        n = node(nid)
        return bool(n is not None and getattr(n, "scope", None))

    def external(nid: str) -> bool:
        n = node(nid)
        return bool(n is not None and getattr(n, "external", False))

    def vpc_edge(nid: str) -> bool:
        n = node(nid)
        return bool(n is not None and is_vpc_edge(n.role))

    def provider_scope(nid: str) -> Optional[str]:
        n = node(nid)
        if n is None or single is None:
            return None
        return provider_role_scope(n.role, getattr(n, "provider", None) or single)

    return check_scope_placement(geo, scope_of, external, providers, mappings,
                                 scope_is_explicit=explicit, is_vpc_edge=vpc_edge,
                                 provider_scope=provider_scope)


def postcheck(placed: PlacedDiagram) -> Tuple[List[str], bool]:
    """``('<rule>: <payload>' lines, blocking)`` for the lint-only ERROR rules
    on a finished ``layout()`` result. Never raises: a diagram that cannot be
    serialized or parsed yields ``([], False)``."""
    from .. import geometry as _geo

    try:
        providers = _providers(placed.spec.title)
        mappings = _container_mappings(providers)
        geo = _geometry(placed, providers)
    except Exception:
        return [], False
    lines: List[str] = []

    def add(rule: str, findings) -> None:
        for finding in findings:
            lines.append(f"{rule}: {finding!r}")

    add("scope-placement", _scope_findings(geo, placed, providers, mappings))
    add("geometric-containment", _geo.check_geometric_containment(geo))
    add("container-style", _geo.check_container_style(geo, providers, mappings))
    declared = {cid for cid, _ in (getattr(placed.spec, "container_captions", ()) or ())}
    declared |= {f"boundary-{cid}" for cid in declared}
    add("container-caption-overflow", [
        (cid, f"caption-overprints-node:+{over}", tuple(nodes))
        for cid, over, nodes in _geo.check_container_caption_overflow(geo)
        if nodes and cid in declared])
    add("legend-placement", [
        f for f in _geo.check_legend_placement(geo)
        if str(f[1]).startswith("overlaps-node-")])
    return lines, bool(lines)


def with_postcheck(placed: PlacedDiagram) -> PlacedDiagram:
    """``placed`` with :func:`postcheck`'s lines appended to ``layout_warnings``
    (``degraded`` set when one is blocking); the same object when clean."""
    lines, blocking = postcheck(placed)
    if not lines:
        return placed
    return replace(placed, layout_warnings=tuple(placed.layout_warnings) + tuple(lines),
                   degraded=placed.degraded or blocking)


__all__ = ["BLOCKING_RULES", "postcheck", "with_postcheck"]
