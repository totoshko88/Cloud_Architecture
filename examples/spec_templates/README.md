# DiagramSpec templates (E-06, engine 1.11.0 ITEM D)

Runnable, commented starting points for authoring a diagram **from a
coordinate-free `DiagramSpec`** rather than by hand-placing cells. Each template
declares its nodes, edges and containers with `(lane, region, slot)` keys only —
**no `x`/`y`** — hands the spec to the public `layout()` + `build_diagram()`
pipeline, and writes a publication-eligible triple (`.drawio` + companion
`.diagram.md`). The engine derives every coordinate, sizes every boundary, picks
contact points and routes every edge, so you never author geometry.

These templates are the documented answer to "how do I drive the engine
directly?" The raw-provider-JSON → normalised-snapshot adapter is **deferred**
(see the design decision); for a snapshot-driven diagram use `rule-engine-draw`,
and for re-flowing an engine-emitted `.drawio` use `rule-engine-relayout`.

## One template per `diagram_type`

| `diagram_type`  | Template                 | Lint class  | What it shows                                              |
| --------------- | ------------------------ | ----------- | --------------------------------------------------------- |
| `context`       | `build_context.py`       | `flow`      | C4 Context — who uses the system, and the external systems it talks to |
| `c4_container`  | `build_c4_container.py`  | `flow`      | C4 Container — the deployable units of one system and how a request moves |
| `network`       | `build_network.py`       | `flow`¹     | A cloud network topology with real provider icons and `account → region → VPC` boundaries |
| `component`     | `build_component.py`     | `flow`      | C4 Component — one container decomposed into its internal components |

¹ `network` is a *Network_Diagram* for the `ip-range` rule regardless of class;
these templates declare `diagram_class: flow` so they stand alone. A full
network **as-built** is usually `diagram_class: landscape` and must cross-link a
`flow` summary via `summary_of` (the sanctioned pair — see the HA golden pair).

## Run a template

```bash
# Writes a temp triple ( .drawio + .diagram.md ) and prints where it went:
python examples/spec_templates/build_context.py

# Choose the output path explicitly:
python examples/spec_templates/build_network.py --out /tmp/net.drawio

# Or stream the .drawio to stdout (no files written):
python examples/spec_templates/build_component.py --stdout
```

Every template needs only the installed `rule_engine` package on the path. The
Context / C4 Container / Component templates draw **neutral C4 boxes** (no
provider icon), so they render with no fetched asset pack. The **network**
template resolves **official AWS glyphs** from the committed icon mappings via
`icon_resolver.resolve_icon`; to export its raster you must fetch the AWS asset
pack first (`rule-engine-fetch-assets`), but the `.drawio` source lints clean
without it.

## How a template is built

1. **Declare** `NodeSpec` / `EdgeSpec` / `ContainerSpec` with lane, region, slot
   and (for a boundary diagram) a `container` membership — never a coordinate.
2. **`layout(spec, strict=True)`** places every node, sizes every container, and
   routes every edge. The returned `PlacedDiagram` carries the geometry.
3. **`build_diagram(...)`** serializes the placed geometry plus the per-node icon
   renderer, the container labels/styles, the Flow legend and the title into a
   `.drawio`.
4. The shared helper `_common.py` wires steps 2–3 and also writes a conforming
   companion `.diagram.md` (the twelve `kb-frontmatter.md` keys + the four
   100–200-word sections), so the emitted triple is publication-eligible.

## Relevant steering

- **Lane order, orientation, the twelve-node cap, the numbered flow legend** —
  `diagram-standards.md` (*Lane Order*, *Diagram Orientation*, *Node Limit*,
  *Numbered Flow Legend*).
- **C4 layering / progressive disclosure, the diagram-type taxonomy** —
  `diagram-standards.md` (*C4 layering & progressive disclosure*,
  *Diagram-type taxonomy*).
- **Service scope placement** (why a regional service sits outside the VPC) —
  `provider-profiles.md` (*Service Scope Classification*) and
  `diagram-standards.md` (*Service Scope Placement*). The `network` template
  demonstrates it.
- **The lint rules and class-aware severities** that judge the output —
  `diagram-lint.md`.
- **The companion frontmatter contract** every template satisfies —
  `kb-frontmatter.md`.

## Not first-class

A **hand-authored** `.drawio` (hand-placed, hand-pinned geometry) is not the
engine's input model — coordinates are its *output*. Author from a `DiagramSpec`
as these templates do. `rule-engine-relayout` can re-flow an engine-emitted
`.drawio`, but it fails honestly on a hand-pinned source it cannot reconstruct.
