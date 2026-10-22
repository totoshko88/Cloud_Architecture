"""``rule-engine-advise`` — report what automatic ordering changes, and why
(1.10.12 WS4).

Usage::

    rule-engine-advise SPEC [SPEC ...] [--json]

``SPEC`` is one of:

* a ``.json`` / ``.yaml`` / ``.yml`` file holding a coordinate-free
  :class:`~rule_engine.layout.model.DiagramSpec` as a mapping (``nodes``,
  ``edges``, ``containers`` as lists of field mappings; every other key a
  ``DiagramSpec`` field);
* ``path/to/module.py:NAME`` — ``NAME`` is a ``DiagramSpec`` or a zero-argument
  callable returning one;
* ``path/to/build_script.py`` — a builder that calls ``layout(spec)``: its
  ``build()`` / ``main()`` is run with ``layout`` intercepted, so the spec is
  captured before anything is laid out or written.

For each spec the tool runs :func:`~rule_engine.layout.layout` (the default
path, so the decision-3 guard applies exactly as in a build) and prints the
``order_report``: each slot / lane / ``vpc_side`` change, and the verdict with
the finished back-edge and crossing counts before and after. Nothing is
written. A spec with ``order: manual`` reports that it opted out.

Exit status: 0 on success, 2 when a spec cannot be loaded.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

_TUPLE_FIELDS = ("container_captions", "container_styles", "node_labels")


class SpecLoadError(Exception):
    """A SPEC argument could not be turned into a DiagramSpec."""


def spec_from_mapping(data: Mapping[str, Any]) -> DiagramSpec:
    """Build a :class:`DiagramSpec` from a plain mapping (JSON / YAML form)."""
    try:
        fields = dict(data)
        fields["nodes"] = tuple(NodeSpec(**n) for n in fields.get("nodes", ()))
        fields["edges"] = tuple(EdgeSpec(**e) for e in fields.get("edges", ()))
        fields["containers"] = tuple(ContainerSpec(**c) for c in fields.get("containers", ()))
        fields["flow_lines"] = tuple(fields.get("flow_lines", ()))
        for key in _TUPLE_FIELDS:
            value = fields.get(key, ())
            if isinstance(value, Mapping):
                value = value.items()
            fields[key] = tuple(tuple(pair) for pair in value)
        return DiagramSpec(**fields)
    except TypeError as exc:
        raise SpecLoadError(f"not a DiagramSpec mapping: {exc}") from exc


def spec_to_mapping(spec: DiagramSpec) -> dict:
    """The inverse of :func:`spec_from_mapping` (JSON-serialisable)."""
    out = dataclasses.asdict(spec)
    for key in _TUPLE_FIELDS:
        out[key] = [list(pair) for pair in out[key]]
    return out


def _import(path: Path):
    mod_spec = importlib.util.spec_from_file_location(f"_advise_{path.stem}", path)
    if mod_spec is None or mod_spec.loader is None:
        raise SpecLoadError(f"cannot import {path}")
    module = importlib.util.module_from_spec(mod_spec)
    sys.modules[mod_spec.name] = module
    mod_spec.loader.exec_module(module)
    return module


class _Captured(Exception):
    def __init__(self, spec: DiagramSpec):
        super().__init__(spec.diagram_id)
        self.spec = spec


def _capture_from_builder(module) -> List[DiagramSpec]:
    """Run a builder's entry point with ``layout`` intercepted."""
    import rule_engine.layout as layout_pkg
    import rule_engine.layout.pipeline as pipeline

    real = pipeline.layout

    def intercept(spec, *args, **kwargs):
        raise _Captured(spec)

    entry = getattr(module, "build", None) or getattr(module, "main", None)
    if not callable(entry):
        raise SpecLoadError("builder has no build() / main() and no DiagramSpec")
    patched = [(module, name) for name, value in vars(module).items() if value is real]
    for mod, name in patched:
        setattr(mod, name, intercept)
    layout_pkg.layout = intercept
    try:
        entry()
    except _Captured as cap:
        return [cap.spec]
    except SystemExit:
        pass
    finally:
        for mod, name in patched:
            setattr(mod, name, real)
        layout_pkg.layout = real
    raise SpecLoadError("builder finished without calling layout()")


def load_specs(arg: str) -> List[DiagramSpec]:
    """Resolve one SPEC argument (see the module docstring)."""
    target, _, attr = arg.partition(":") if not os.path.exists(arg) else (arg, "", "")
    path = Path(target)
    if not path.is_file():
        raise SpecLoadError(f"no such file: {target}")
    suffix = path.suffix.lower()
    if suffix in (".json", ".yaml", ".yml"):
        text = path.read_text(encoding="utf-8")
        if suffix == ".json":
            data = json.loads(text)
        else:
            import yaml
            data = yaml.safe_load(text)
        items = data if isinstance(data, list) else [data]
        return [spec_from_mapping(d) for d in items]
    if suffix != ".py":
        raise SpecLoadError(f"unsupported spec file type: {path.name}")
    path = path.resolve()
    cwd = os.getcwd()
    os.chdir(path.parent)
    try:
        module = _import(path)
        if attr:
            obj = getattr(module, attr, None)
            if obj is None:
                raise SpecLoadError(f"{path.name} has no attribute {attr!r}")
            obj = obj() if callable(obj) and not isinstance(obj, DiagramSpec) else obj
            if not isinstance(obj, DiagramSpec):
                raise SpecLoadError(f"{path.name}:{attr} is not a DiagramSpec")
            return [obj]
        for name in ("SPEC", "spec", "build_spec"):
            obj = getattr(module, name, None)
            if isinstance(obj, DiagramSpec):
                return [obj]
            if callable(obj) and name != "SPEC":
                try:
                    got = obj()
                except TypeError:
                    continue
                if isinstance(got, DiagramSpec):
                    return [got]
        return _capture_from_builder(module)
    finally:
        os.chdir(cwd)


def propose_flow_groups(spec: DiagramSpec, max_size: int = 4) -> List[dict]:
    """Propose a DRAFT flow_groups list (1.11.0 WS2) for the owner to confirm.

    Heuristic: cluster nodes that share a lane into runs of CONSECUTIVE slots,
    capped at ``max_size`` (a larger run is a subsystem — advise splitting the
    diagram instead). The engine never auto-applies groups; this only prints a
    draft the owner edits and pastes into ``DiagramSpec.flow_groups``. A cluster
    of a single node is dropped (a group of one is noise).
    """
    by_lane: dict = {}
    for n in spec.nodes:
        by_lane.setdefault((n.lane, n.region), []).append(n)
    proposals: List[dict] = []
    for (lane, region), group in sorted(by_lane.items()):
        members = sorted(group, key=lambda n: n.slot)
        run: List[str] = []
        prev_slot: Optional[int] = None
        def _flush():
            if len(run) >= 2:
                label = f"{lane.replace('_', ' ').title()} group"
                proposals.append({"label": label, "members": list(run)})
        for n in members:
            if prev_slot is not None and (n.slot != prev_slot + 1 or len(run) >= max_size):
                _flush()
                run = []
            run.append(n.id)
            prev_slot = n.slot
        _flush()
    return proposals


def advise(spec: DiagramSpec) -> dict:
    """Lay ``spec`` out and return the advice record."""
    from rule_engine.layout import layout

    if spec.order == "manual":
        return {"diagram_id": spec.diagram_id, "order": "manual",
                "report": ["auto-order: skipped (order: manual)"]}
    placed = layout(spec)
    return {"diagram_id": spec.diagram_id, "order": spec.order,
            "report": list(placed.order_report)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rule-engine-advise",
        description="Report what automatic flow-aware ordering changes in a "
                    "DiagramSpec, and why (back-edges / crossings before and after).",
    )
    ap.add_argument("specs", nargs="+", metavar="SPEC",
                    help="a .json/.yaml spec, module.py:NAME, or a builder script")
    ap.add_argument("--json", action="store_true", help="emit JSON records")
    ap.add_argument("--flow-groups", action="store_true",
                    help="propose a DRAFT flow_groups list (1.11.0 WS2) to "
                    "confirm and paste into DiagramSpec.flow_groups, instead of "
                    "the ordering report")
    args = ap.parse_args(argv)

    records = []
    for arg in args.specs:
        try:
            specs = load_specs(arg)
        except (SpecLoadError, OSError, ValueError) as exc:
            print(f"error: {arg}: {exc}", file=sys.stderr)
            return 2
        for spec in specs:
            if args.flow_groups:
                rec = {"diagram_id": spec.diagram_id,
                       "flow_groups": propose_flow_groups(spec)}
            else:
                rec = advise(spec)
            rec["source"] = arg
            records.append(rec)
    if args.json:
        print(json.dumps(records, indent=2))
    elif args.flow_groups:
        for rec in records:
            print(f"{rec['source']} [{rec['diagram_id']}] — draft flow_groups:")
            if not rec["flow_groups"]:
                print("  (no adjacent same-lane runs to group)")
            for g in rec["flow_groups"]:
                members = ", ".join(repr(m) for m in g["members"])
                print(f"  ({g['label']!r}, ({members}))")
    else:
        for rec in records:
            print(f"{rec['source']} [{rec['diagram_id']}]")
            for line in rec["report"]:
                print(f"  {line}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
