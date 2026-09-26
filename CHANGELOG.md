# Changelog

All notable changes to the Rule Engine are recorded here, per released version, in reverse chronological order.

## [1.6.1] - 2026-09-26

**Theme: a hotfix in the safe direction only.** It closes secret leaks and permission holes, makes the CI and release gates actually able to fail, pins what the Power installs, and fixes steering and documentation that said one thing while the code did another. It adds no lint rule, makes no existing rule stricter, and regenerates no example: every change either removes a leak or a false finding, or makes a gate enforce what it already claimed to enforce. The stricter gates found in the same review (a real `.drawio` XML parser, a full frontmatter validator, a parsed-JSON `secret-safety` scan, pinned pack digests) are 1.7.0 work, because they will fail artifacts that pass today.

### Security

- **The collector no longer runs verbs that return secrets or mint credentials** (`collector.is_secret_verb`, `rejection_reason`). They are read-only in the provider's sense, so the allow-list admitted them: `get_secret_value`, `get_session_token`, `get_parameter(s)`, `get_login_password`, `get_password_data`, `get_object`, `az keyvault secret show`, `az storage account keys list`, `oci secrets secret-bundle get`, and more. They are now rejected before execution with a named reason, while the metadata verbs on the same services (`list_secrets`, `describe_secret`, `describe_parameters`, `az keyvault secret list`, `gcloud secrets list`) stay allowed. A shape that means "secret" in one CLI and "metadata" in another is scoped to its provider: `az storage account keys list` returns account keys, while `gcloud kms keys list` and `oci kms management key list` list key metadata and stay allowed. A rejected verb is now listed in `00-MANIFEST.md`, so a skipped domain is visible rather than silently absent.
- **The AWS verb boundary is case-sensitive again.** `re.IGNORECASE` made the camelCase boundary `[_A-Z]` match any letter, so `listen` and `getanddeletebucket` counted as read-only verbs. The kebab-case operation name (`describe-instances`) is now accepted as well.
- **A verb carrying a shell metacharacter is rejected** (`;`, `&`, `|`, redirects, expansions).
- **Redaction judges name/value pairs by their name.** For `{"Key": "DB_PASSWORD", "Value": "hunter2"}` the bare-`key` rule erased the tag's *name* and kept the password; an SSM `SecureString` parameter kept its `Value`. Tags, container environment, CloudFormation parameters, SSM `SecureString` parameters and Azure `keys list` records are now redacted by what they are. Azure's camelCase key fields (`primaryKey`, `primaryConnectionString`, …) and five value patterns (`AWS_SECRET_ACCESS_KEY=`, `AccountKey=`, `SharedAccessKey=`, a password in URL userinfo, PGP private-key blocks) are covered too. (`Type: SecureString` itself is still redacted: the linter's `secret-safety` scan flags that marker, and relaxing it is 1.7.0 work.)
- **`failures.json` is redacted** — failure reasons are exception text, which often echoes request parameters — and the "no declared cost endpoint" failure, appended after the file had been written, now reaches it.
- **Agent permissions match the prose** (`.kiro/agents/*.md`). `inventory-collector` denies the secret-returning and credential-minting commands and the executing verbs that its argument-spanning `aws * get*` style allowed (`run-*`, `invoke`, `cp`, `presign`, `decrypt`, …), and loses `cat *` (which read `~/.aws/credentials` and, through a redirect, wrote files past the `fs_write` deny) and `python scripts/*`. The two read-only agents deny redirects, command substitution, backticks and multi-line commands outright; `diagram-author` asks first. `terraform show -json`, which prints sensitive state values, needs confirmation, and `terraform state pull` is denied. `diagram-author`'s `git *` becomes read-only git allowed, history and remote changes on `ask`, destructive operations denied. `rule-engine-reviewer` loses `cat *`. All three deny reading local credential stores (`~/.aws/credentials` and its CLI/SSO caches, `~/.azure`, `~/.config/gcloud`, `~/.oci`, `~/.kube/config`, `~/.docker/config.json`, `~/.ssh`, `.env*`, `~/.git-credentials`, `~/.netrc`, the GitHub CLI token file, `*.pem`).

### Fixed

- **`related_docs: []` no longer fails `frontmatter` as CRITICAL.** kb-frontmatter allows 0–20 entries; the generic empty-collection check treated an empty list as a missing key. `tags` still needs at least one entry.
- **The icon index is a pure function of the pack contents** (`asset_index`). The indexer kept whichever file the directory walk reached first, and walk order differs between filesystems: reversing it changed 15 of the 32 aws/azure role references. Candidates are now ranked explicitly (SVG over PNG, base icon over a Dark/Light variant, then size) with a path tie-break, and the token-match fallback has a total order. The ranking reproduces every reference the goldens embed; the one committed change is Azure `managed_k8s`, which now points at the byte-identical copy under `containers/`. Collision warnings drop from 133 lines to 14, one per genuinely distinct pair of services.
- **The snapshot gate no longer counts `failures.json` entries as enumerated resources.** Once the cost failure reached that file, an empty inventory with a cost request failed `resources-empty`.
- **A download that is not a zip no longer leaves an empty pack directory** (`fetch_assets._unpack` opens the archive before creating it), and `--allow-missing` treats an empty pack directory as missing rather than stale.
- **`diagram-standards.md` has valid frontmatter again.** Since 2026-09-22 it began with `---`, a blank line and `## inclusion: always`: a Markdown formatter had read the key plus the closing fence as a setext heading. It kept working only because `always` is Kiro's default. `asset-packs.md` now declares its mode explicitly.
- **Documentation drift:** the raster budget in `SKILL.md` (both copies) and `ARCHITECTURE.md` said "≤ 1200px"; the GitLab CI header stated Requirements 10.6 and 10.7 backwards; `docs/REVIEW.md` listed layout passes that do not exist; `ARCHITECTURE.md` never mentioned the layout engine; and the 1.6.0 notes said CI ran `version_guard --triple`, which no pipeline did until this release.

### Changed

- **A release runs the same gate as a pull request.** The GitHub release workflow calls the CI workflow and needs it to pass. Before, it re-ran only lint and schema validation, with no tests and no icon, raster or snapshot gates. It also runs `version_guard --triple` after writing `VERSION` from the tag, so a tag that disagrees with `pyproject.toml` or the newest CHANGELOG heading fails closed. Tokens are least-privilege, and only the release job can write.
- **GitLab runs the tests.** A new `test` stage gates `version-guard` and `build`, and `build` runs `--triple` too.
- **The icon-index staleness check is blocking** in both pipelines. It was `|| echo WARNING`, so it could never fail. The new `--allow-missing` flag skips the check, with a warning, only when a pack failed to download. If a vendor republishes a pack, CI now fails until the index is rebuilt; pinning pack digests to make that an explicit step is planned for 1.7.0.
- **Hooks say what they skip.** `validate-on-task` no longer swallows schema failures with `|| true`, and runs schema validation even when lint fails. All three hooks now print a notice when the CLI is not installed instead of exiting silently.
- **What the Power installs is pinned.** The MCP server moves from `@latest` to `awslabs.aws-documentation-mcp-server@1.2.1`. `bootstrap.sh` installs the engine release it ships with (the `v1.6.1` tag) instead of the default branch, and prefers `uv tool install`, which avoids an unsupported system Python and PEP 668 refusals on a fresh macOS.

### Tests

- New: `test_collector_secret_safety.py`, `test_agent_permissions.py` (evaluates the permission rules with Kiro's documented matching semantics), `test_asset_index_determinism.py`, `test_hooks_and_ci_gates.py` (executes each hook under `/bin/sh` with stub CLIs and pins the pipeline wiring), `test_version_pins.py`, and `test_steering_frontmatter.py`. `test_linter.py` gains the `related_docs` cases.
- Suite: **675 → 1051 tests**.

## [1.6.0] - 2026-09-25

**Theme: the gate now catches what the eye catches.** A from-scratch install in a clean workspace (a fresh AWS `eu-central-1` account, collected and drawn with nothing but the Power) linted **completely clean** while shipping a diagram whose edge left a node through the top of its own icon, whose Flow/Legend blocks sat in the left margin instead of the right, and whose inventory snapshot carried an empty `resources/` folder and a wrong `file_count`. Separately, the 2026-09-25 audit's headline finding was still true: 20 of the 34 nodes on every HA landscape were drawn with **no edges at all**. This release closes those enforcement gaps, lands `node-connectivity` with re-connected examples, and adds the missing North–South golden.

Net effect on the reference set: **all 13 shipped `.drawio` goldens are now clean under every geometry check**, and the only lint finding anywhere in `examples/` is the sanctioned `node-count` WARNING the standard grants a `landscape` (34 > 30). Before this release 10 of 12 carried a finding.

### Fixed

- **`edge-direction` now classifies the contact FACE, not the half-plane** (`geometry.contact_faces`, `geometry.check_edge_direction`). The old test asked `exitX >= 0.5` in order to admit the right edge *and* the top-right / bottom-right corners — but that predicate is also true of `(0.5, 0)`, the **top-centre** point, so a pinned top exit rescued itself by its own x. An edge leaving straight out of the top of its glyph therefore linted clean, which is exactly what the clean-room install shipped (`EC2 → S3`, `exit=(0.5, 0)`, visibly rising out of the EC2 icon). The entry side had the mirror hole: a bottom-centre arrival `(0.5, 1)` was rescued by `entryX <= 0.5`. A contact point that lies on a face is now judged by that face — a valid exit is on the **right** (`exitX >= 1`) or **bottom** (`exitY >= 1`) face, a valid entry on the **left** or **top** — so the corners the rule existed to admit stay legal while the centre-of-the-wrong-face points are caught. A *band* pin naming no face (`exitX=0.75`, no `exitY`) keeps the pre-1.6.0 lean test, so every prior judgement on a single-axis pin is preserved. Reasons now name the offending face (`exit-top-not-right-or-bottom`, `enter-bottom-not-left-or-top`, …). This exposed six pre-existing defects in the `01-*` goldens, all fixed below.
- **A transparent node group is no longer mistaken for a Boundary** (`constants.is_boundary_container_style`). The dashed-borderless test (`dashed=1` + `fillColor=none`) was applied to *every* cell, but an OCI node is a transparent `group` hosting its embedded stencil — so the moment the new `standby` overlay added `dashed=1` to one, the node was reclassified as a **container**, its glyph sub-cells were promoted to top-level nodes, and an otherwise valid diagram collapsed into `node-quote` and `container-padding` ERRORs. A `group` is now a boundary only when it names a `group_` / `grIcon=` container icon, which is what the function's own docstring always said.
- **A container's top padding reserves its caption strip** (`layout_engine.size_containers`, `layout_engine._band_packing`). A draw.io group draws its caption *inside* its top edge, so a uniform 30px pad made the caption band and the padding the same strip: the first content row began where the caption ended, leaving **no corridor lane inside the container above its first row**. Every edge descending into a container had to run through the caption. Top padding is now `CONTAINER_PAD + CONTAINER_LABEL_BAND` (30 + 30), and the banded region is anchored low enough that the container cannot grow upward into the tier above it.
- **Corridor routing avoids every container caption in the band, not just the target's** (`layout_engine._caption_free_band`, applied in `route_cross_region`, `route_back_edge`, and `route_fan_out_row`). The pre-1.6.0 guard capped a corridor above the **target's innermost** enclosing container, in two routers only. That left three real gaps, all of which the re-connected landscape hit: a run into an AZ still crossed the enclosing VPC's caption; a run between two nodes *both outside* the container it passed had no cap at all; and a run *inside* a container cannot be fixed by capping above that container — it has to sit **below** the caption. Each intersecting caption now narrows the corridor to whichever side keeps the run on the correct side of that container, falling back to the other side when the preferred one collapses. Side effect: the four HA **summaries** are now fully clean — the `edge-crosses-container-label` WARNING they had carried since 1.5.1 is resolved.
- **A three-way downward fan-out no longer merges two bottom exits** (`layout_engine`, step 2b3). The bottom-left band bias ran *after* the contact spread and moved **every** left-entry bottom branch to the one left band, so a source with two such branches had both land on `0.25` (`exit-thirds` `bottom-exits-merge`). It now applies only when a source has exactly one left-entry bottom branch; otherwise the spread's already-distinct bands stand, since keeping two stubs apart matters more than which band each takes.
- **`build_diagram` no longer lets the Legend box overlap the Flow box** (`diagram_layout.build_diagram`). A caller's `legend_y_legend` was taken literally, so a long Flow list — or a pinned narrow width, which makes it wrap taller — grew past it and the two boxes overlapped silently (neither is a node, so no geometry rule would have caught it). The Legend is now pushed down to clear the Flow box by one grid step.

- **An exit band is now chosen from the lane the edge will actually run in, and the corridor side is decided per row rather than per edge** (`layout_engine.decide_lane_sides`, `_exit_band_rank`, `_assign_exit_bands`, `_fanout_above_row`, `_hcorridor_below`, `_hcorridor_band`; pipeline steps 1c2, 2b4, 2b5). This is the single change behind the **landscape reaching the reviewer's hand-routed quality** — 3 crossings / 2 rails against 7 / 4, with 42 turns against the hand-route's 45. Four coupled defects, all of them the same mistake in different places: a decision that needed to see the whole row was being taken locally. (1) The old Rule H pinned *every* off-centre long-haul exit to the **upper** quarter no matter which side its corridor ran on, so a descending branch left from above the level run it then had to cross — the `l19`/`l20` tangle where one fan-out crossed a sibling twice and a level run once, plus `l14`/`l15` and `s1`/`s5` in every summary. Rank is now read off the route: above-going branches leave high, level runs keep the centre, below-going branches leave low, and a **back-runner** — whose turn column is necessarily the nearest lane to the face — goes outermost so no sibling crosses it at the glyph. (2) A fan-out always ran **below** its row, though the band above a container's first row is empty by construction; it now runs above when it is in that row *and* no inbound top-entry approach column falls inside the run (an approach crossing the band is what made the below lane correct for the AZ-2 fan-out, and what leaves it free for the account tier's and the AZ-1 tier's). (3) Two long runs leaving one row took the same side and crossed each other's turn legs whatever lane each got, because distinct lanes do not help when the extents overlap; they now claim extents per (row, side) and take the first side that is free. (4) A `back-edge` chose its side on canvas room alone, sending a hop whose target was two rows *below* it up over the tier above and back down the diagram. Side effects: the overflow valve now stands down when a face has an above-lane-capable branch (a three-way fan-out is served from one face, one branch per band, instead of spilling the farthest onto the bottom), and the straight-drop spine is no longer gated on `spec.compact` — the hooked alternative descends through the very row gaps every corridor uses, so it cost four crossings and nine turns to avoid a caption graze.
- **A back-edge's drop column must be free** (`layout_engine._free_drop_column`, `_column_is_clear`). A top entry dropped at the target's own centre x, which is right only when nothing else stands in that column. On a stacked column — load balancer over application tier over API tier, all at one x — the drop ran through every icon above the target and the clockwise detour then shoved it **two pixels** off their right border: a 370px vertical beside two glyphs, the second-rail defect the standard forbids outright, and the one a reviewer singled out. The drop now takes the target's own column when clear, else the centred lane in the gap beside it, then steps across in the lane just above the target. On the AWS landscape it lands in the same left-gap column the reviewer chose by hand.
- **The spine and back-edge approach lanes are allocated, not hard-coded** (`layout_engine.route_spine`, `route_back_edge`). Both stepped across at `entry_y - GRID`, which is the *first* line of the band above the target — so any cross-region or fan-out run that legitimately allocated that same line shared a corridor with it. Every long horizontal now draws from one `hcorr-<side>:<row>` namespace over one shared band definition (`_hcorridor_band`, which also removes three copies of the two caption clamps), so runs in the same physical band are distinct by construction.
- **`_allocate_or_first` no longer merges corridors when a gap is full** (`CorridorAllocator.allocate_dense`). Lanes are handed out two grid steps apart so parallel runs read separately, which leaves a 30px band — a row gap trimmed by a container caption strip — holding exactly one lane. The third run asking for that band fell straight through to the gap **midpoint**, as did the fourth, so two runs shared a lane *and were unfixable by the repair loop*: neither was allocated anywhere, so bumping one moved it onto the other. There is now a step in between — allocate at one grid step instead of two, still distinct and still grid-aligned — before the midpoint is used at all.
- **A tier-skip corridor no longer lands on a container border** (`layout_engine._free_left_corridor_x`). Centring the lane in a VPC's left gap put it exactly on the nested AZ box's left edge, because both derive from the same column, and a long vertical that coincides with a box edge reads as part of that edge. It now steps to the nearest grid line in the gap that clears every container border, preferring the smallest move so the lane stays as centred as it can be.
- **Every edge leg is now explicitly axis-aligned; draw.io no longer picks any corner** (`geometry.orthogonalise_route` + the `edge-approach` rule; applied by `layout_engine` after every repair pass and by `diagram_layout.build_diagram` at render time). An `orthogonalEdgeStyle` edge never draws a diagonal — when two consecutive points are not aligned, draw.io **inserts its own corner and chooses which way it turns**, and the two possible shapes can differ by a whole icon: one clears a glyph, the other cuts through it. So an unaligned waypoint was never a diagonal on screen, it was a corner the source did not specify, invisible to every other geometry rule because they all read the points as given. **30 of the shipped routed edges had one**: each router computed its corridor correctly but emitted the waypoint next to a contact from the *corridor's* coordinates rather than the *contact's*. The rewrite inserts the implied corners, collapses overshoot-and-return runs into one, and forces both contact legs to meet their face head-on from a lane one grid step off the glyph — so a horizontal leg that used to slide along a node's top border into a top-centre entry now drops into it from above. Contacts are grid-resolved **along the face only**: snapping the face coordinate as well would pull the contact inside the glyph on a non-78px icon (azure/01's 64px icons have a right edge at 604, and rounding it to 600 moves the contact off its own face). Two side effects worth noting: the alignment exposed two genuinely under-specified routes, which are now fully pinned in their generators, and it removes the sub-pixel contact kink that made arrowheads look bent. **All 13 goldens are clean under the new rule.**

### Added

- **`edge-approach` lint rule** (WARNING — `geometry.check_edge_approach`, `linter`, `diagram-lint.md`). Reports `diagonal-leg` (two consecutive points not axis-aligned), `exit-leg-…` and `entry-leg-…` (a contact leg that does not meet its face head-on). Generated diagrams satisfy it by construction, so it exists for hand-authored and hand-dragged sources — the case it was written from.
- **`scripts/orthogonalise_drawio.py`** — applies the same rewrite to a hand-authored `.drawio` in place, with a `--check` mode that reports defects without writing. This is the operation a reviewer performed by hand on the AWS landscape; making it a tool means a hand-edit converges on the generators' geometry instead of drifting from it.
- **Route-quality objective, measurement, and a regression ratchet** (`geometry.route_cost`, `scripts/route_quality.py`, `tests/test_route_quality.py`). Routing is chosen by rule — ~25 named patterns, each distilled from a hand-edit — with no view of the diagram as a whole, and two reviewer hand-edits of the AWS HA landscape showed what that costs. The first removed 2 **parallel rails** (a long vertical alongside a column of icons, which the standard forbids) while *adding* a crossing, so rails are weighted above turns and ink; the second improved every axis at once (**3 crossings / 2 rails / 45 turns / 10.0k ink** against the generated 7 / 4 / 50 / 11.0k). `route_cost` is that objective; the ratchet pins each shipped diagram's crossing and rail ceiling so routing cannot silently regress.

  Measuring it first was what made the routing fixes above possible, and it corrected the measurement itself. The metric originally exempted any two edges sharing an endpoint, on the reasoning that diagram-standards sanctions a *shared trunk* — but the same sentence requires that "the branches never overlap", and sharing a trunk makes two branches **touch**, which `segments_cross` already excludes by testing the strict interior. The exemption was therefore protecting nothing and hiding four crossings per landscape, one per summary and two per `01-*` example. With it lifted, the reviewer's hand-route still measured **zero** co-sourced crossings, which is what identified the exit-band ordering as the real defect. The score now drives four rules (above), and the corpus reaches the hand-route's 3 / 2 with fewer turns. A **scored** router — per-edge candidate variants evaluated against what is already placed, most-constrained-first ordering, allocator snapshotting — is still future work, because `_place_and_route` decides contacts in sequential global passes before routing and so has no per-edge decision point; it is written up in `docs/REVIEW.md` → Open gaps and sequenced with the `layout/` package split.
- **Tier-skip corridors are centred in their gap** (`layout_engine._free_left_corridor_x`). The docstring has always said the left corridor is "placed midway in the left gap", but the code took `src.x - GRID` — the lane **nearest the column**. On the HA landscape that put a 540px vertical 10px from `app_a1`'s left border, reading as a second rail beside the icons; centring gives 30px clearance on both sides. A reviewer corrected the same route by hand to 20/40px, so the principled rule lands better balanced than the nudge. (The corridor is additionally stepped off any container border it would coincide with — see *Fixed*.)
- **`node-connectivity` lint rule** (WARNING, both classes — `geometry.check_node_connectivity`, `linter`, `diagram-lint.md`). A role-bearing node with **zero incident edges** is a finding unless it carries an overlay marker declaring why. This was the 2026-09-25 audit's headline finding and it could not ship as a rule until the examples it judges were connected: each of the four HA landscapes drew 34 nodes joined by 12 edges, leaving the same 20 ids unconnected on all four providers (they share one spec). Boundary containers and text cells are not nodes and are exempt; an `overlay=<term>` node is exempt by declaration. Pure topology, so it is independent of layout.
- **`legend-placement` lint rule** (WARNING — `geometry.check_legend_placement`, `linter`, `diagram-lint.md`). The `Flow` / `Legend` blocks must sit in the right margin, at least one grid step past the outermost container and clear of every boundary. Reports `left-of-diagram-body` and `overlaps-<container-id>`. The clean-room install stacked both blocks in the **left** margin under the external user; every shipped golden puts them on the right, because the shared builder does — this rule is the difference between a convention the builder follows and one a hand-authoring agent must follow too. It fires on **zero** goldens, so it shipped without example churn.
- **`flow-legend` lint rule is now implemented** (`linter._check_flow_legend`, `cli._parse_flow_legend_lines`). It was specified in `diagram-lint.md` from the first ruleset but had no code behind it: the generator always emitted the Flow cell, so every generated diagram happened to comply and only a hand-authored one could hit the gap. Numeric edge markers now require a `Flow` cell covering every marker (`N.` or `N)`); an artifact whose Flow cell was not parsed is skipped, not assumed to fail. This was the last documented-but-unimplemented rule — the ruleset and the code now match exactly.
- **`standby` overlay marker** (`diagram-standards.md` → Overlay Vocabulary; `layout_engine.NodeSpec.overlay`, `diagram_layout.overlay_suffix`). An active-passive architecture draws every passive peer, but drawing its full edge set duplicates the active topology for no new information. A peer marked `standby` states "mirrors the active one; edges omitted for clarity" — the sanctioned alternative to real edges under `node-connectivity` — triple-encoded as a dashed node outline, a `-standby` label suffix (inside the `node-quote` safe set), and a Legend entry. It deliberately declares no colour, because *Icon Fidelity* forbids recolouring a pack glyph. `build_diagram` gained a `legend_lines` parameter so a diagram using an overlay can extend the standard Legend to document it.
- **`rule-engine-check-snapshot` gate** (new `snapshot_gate.py`, entry point, both CI pipelines). The linter checks snapshot file *content* — every Markdown document through the `frontmatter` CRITICAL gate, every JSON through `secret-safety` — but nothing checked the **shape of the folder**. The clean-room snapshot proved why that matters: it had collected 400-plus items yet left `resources/` **empty** (§5 requires one subfolder per enumerated resource) and recorded `file_count: 12` against 13 real files, and it linted clean. The gate checks the folder name (§3), the seven non-empty manifest fields (§4), one JSON per service domain, non-empty per-resource subfolders, and `file_count` accuracy (§5) — reading the manifest in any of the three shapes a snapshot is written in (table row, bullet list, `key: value`), because the contract is that the field is *recorded*, not how it is rendered. `resources-empty` fires only when resources were actually enumerated, so an empty account is not a false positive. Verified against the clean-room snapshot: it reports exactly the two real defects.
- **North–South infrastructure golden example** (`examples/aws/03-aws-hybrid-infrastructure.*`, `scripts/build_aws_infra_example.py`) — the first Open gap in `docs/REVIEW.md`, closed. `diagram-standards.md` specifies a North–South axis for infrastructure / network / deployment diagrams, but no shipped golden exercised it, so that render path had never been through the publication gate. Eleven nodes descending five tiers: a corporate user **outside** the Account, Route 53 → CloudFront in the edge tier, an ALB inside the VPC fanning out to two **peer AZ containers** (side by side, sharing one top edge and height) each holding an EC2 node above its RDS node, two regional services in their own column outside the VPC, and an on-premises Oracle database in its **own** boundary — a disjoint sibling of the Account, so the hybrid replication edge visibly crosses out of the VPC, out of the Account, and into the datacenter. It is the only golden that exercises the N–S axis, an external actor outside the cloud boundaries, an on-premises boundary, and peer AZ bands.
- **Version-triple guard** (`version_guard.assert_version_triple_consistent`, `--triple` CLI mode, `tests/test_version_triple.py`). The released version lives in `VERSION`, `pyproject.toml`, and the newest `CHANGELOG.md` heading, and at 1.5.4 all three disagreed. CI rewrites `VERSION` at tag time, so the stale file never broke a release — which is precisely why nothing surfaced the drift. It is now a checked contract that names the offending source, and a missing source counts as a disagreement (fail-closed). The three tests that read the **real** repository are conditional on `VERSION` existing, because it is git-ignored and written by CI at tag time — a bare checkout legitimately has none, and asserting its presence unconditionally would redden every non-tag pipeline. A fourth, unconditional test covers the half a fresh clone *can* check: `pyproject.toml` and the newest CHANGELOG heading are both committed, so they must always agree. `plugin.json` is likewise compared against `pyproject.toml` rather than `VERSION`.

### Changed

- **The four HA landscape examples are re-connected: 21 edges, zero unconnected nodes** (`ha_multiregion_spec.py`). Nine edges were added for the account edge tier and the primary region — WAF → CDN, CDN → audit bucket (async) and → primary LB, worker → API tier and → secrets store, API tier → observability (async), and the AZ-2 application's own cache / object-store / API fan-out — all relationships the companion documents already described in prose, so this also closes a doc/diagram mismatch. The passive region's eleven mirror peers carry the `standby` overlay instead of duplicated edges. The API-tier edge is sourced from the worker rather than the load balancer: hanging a third downward branch off the LB put three exits on one bottom face, which the contact spread cannot keep distinct, and `diagram-standards` is explicit that an over-connected side means "split or re-lane" rather than bending the spread.
- **The GCP and OCI `01-*` hub descent moved out of the hub's shadow** (`scripts/build_gcp_example.py`, `scripts/build_oci_example.py`). The `ingest → training` corridor ran at `x=860`, twenty pixels from the hub's left border for four hundred pixels — the same second-rail defect, in a hand-authored generator rather than the engine. At `x=800` it clears that border by eighty pixels and crosses nothing extra, so both examples lose their rail. The hub's own back-edge (`training → hub`) is left where it is, with the measurement written into the source: it crosses the hub's two fan-out stubs, and every alternative was tried and measured worse or equal — a riser right of the fan-out meets the approach legs into the data column, a left-side riser meets the descent and the secrets lane, a bottom exit into the hub's left face trades two crossings for two others. Fixing it needs the hub's neighbours moved, which is a placement change, recorded in `docs/REVIEW.md` rather than papered over in a comment.
- **Rerouted six edges in the `01-*` goldens** that the face-classified `edge-direction` exposed (`scripts/build_gcp_example.py`, `scripts/build_oci_example.py`, `examples/azure/01-azure-openai-rag.drawio`). GCP and OCI each had an `api → topic` edge leaving the **top** face, a `training → hub` edge leaving the top *and* entering the **bottom**, and a `hub → secrets` edge leaving the **left**; Azure had the same top-face exit. Each is re-routed onto a contract-legal pair — a right exit into a gap column for the upward hops, the sanctioned back-edge loop (right exit, free riser, left lane, top entry) for the training edge, and a bottom exit into a below-row lane for the secrets edge.
- **The two example inventory Snapshots are now genuinely conforming** (`scripts/build_example_snapshots.py`). Both held only `00-MANIFEST.md` and `10-delta-example.md` while their own manifests described `compute.json` / `storage.json` / `network.json`, per-resource subfolders under `resources/`, and `file_count: 11` — the reference set describing a shape it did not have. The generator materialises three domain files and six per-resource documents per snapshot, so each folder now holds the 11 files its manifest claims. The per-resource documents are Normalized Resources validated by the CI schema gate; `config_digest` is the SHA-256 of the resource identity, so the output is byte-stable and `--check` catches a hand-edit.
- **`.kiro/agents` ships in the bootstrap payload** (`build_backend._PAYLOAD`, `init_workspace`). A clean-room install received the always-on steering rules and the icon mappings but **none** of the three agents that apply them — diagram-author, inventory-collector, rule-engine-reviewer — so a fresh workspace had the standard without the roles. They are small configuration files, like steering.
- **The two `SKILL.md` copies are back in sync, and guarded.** The workspace skill and the Power's copy had drifted across four wording hunks with nothing enforcing the sync (unlike the bootstrap payload, which has a test). Drift here is worse than in prose: the skill is the agent's instruction sheet, so two versions mean two behaviours depending on how the engine was installed. `.kiro/skills/…/SKILL.md` is now canonical, the Power copy is byte-identical, and a test asserts it. `powers/…/plugin.json` also moves from `1.0.0` — where it sat through nine engine releases — to the engine version, likewise guarded.
- **Resolved the Flow/Legend wrapping contradiction in `diagram-standards.md`.** The standard said both "each box fits its text without wrapping" and "pin the blocks narrow and let them wrap taller", and the shipped landscapes do the latter. No-wrap is now stated as the **default** (size to the longest line) and a deliberately pinned narrower width as the **sanctioned exception** for a wide diagram, with the note that wrapping *at the default width* is the actual defect.

### Tests

- New `tests/test_new_rules_1_6_0.py` (33 tests) covers `legend-placement`, `flow-legend`, and `node-connectivity` — including the overlay exemption end-to-end from real `.drawio` XML, and that a text cell is captured for placement checks while never counting as a node.
- New `tests/test_snapshot_gate.py` (36 tests) covers every finding, all three manifest shapes, the "empty account is not a defect" case, and asserts the shipped example Snapshots conform with an accurate `file_count`.
- New `tests/test_version_triple.py` (20 tests) including the exact 1.5.4 drift and the `--triple` CLI mode CI runs.
- `tests/test_geometry_hard_rules.py` gains 11 face-classification tests: the top-centre exit and bottom-centre entry are flagged, the top-right and bottom-left corners stay legal, the builder's perimeter overshoot still reads as the right face, and an interior band keeps the pre-1.6.0 lean test.
- `tests/test_bootstrap_payload_sync.py` gains four: the agents are in both payload maps, every `.kiro/*` tree is remapped dot-free (setuptools drops dot-directories), the two `SKILL.md` copies are identical, and the Power plugin version matches the engine.
- `tests/test_layout_engine.py` pins the new landscape topology (`l1..l21`, every node connected or overlay-marked, the exact `standby` set) and the container caption strip.
- `tests/test_route_quality.py`'s ratchet is tightened to the new floors: **(3, 2)** for every landscape — the hand-route's own numbers — and **(4, 0)** for `gcp/01` / `oci/01`, whose rail is gone. Its shared-trunk test is split in two, so the distinction the metric now draws is pinned from both sides: two branches meeting at a trunk corner are **not** a crossing, and the same two with their bands ordered against their directions of travel **are**.
- `tests/test_geometry_hard_rules.py`'s overflow-valve test becomes `test_three_fanout_targets_split_across_the_two_row_bands`: the same three-target fan-out is now served from one face with one branch per band (above / level / below), which is what the valve existed to approximate.
- Suite: **502 → 674 tests**.

## [1.5.4] - 2026-09-25

**Theme: the linter now catches a waypointed edge whose real orthogonal path cuts an unrelated icon.** A from-scratch test install (a fresh AWS `eu-central-1` diagram) surfaced a routing defect the gate waved through: edge 8 (EC2→S3) carried explicit waypoints, and `check_edge_routing` trusted any waypointed edge entirely on the icon-crossing criterion — so a diagram that visibly ran flow marker 8 straight through the RDS glyph, and along the VPC top border, linted clean. This release closes that gap and reroutes the test artifact.

### Fixed

- **`edge-routing` now samples a waypointed edge's real orthogonal *knee* path, not its raw diagonal** (`geometry.check_edge_routing`, new `geometry._orthogonal_knee`). An `orthogonalEdgeStyle` edge never draws a diagonal between two points: it renders an L — **horizontal first**, then vertical. The pre-1.5.4 check sampled the straight diagonal between contact points and waypoints, which (a) correctly avoided false-flagging a validly routed edge that draw.io steps around a node, but (b) also stepped cleanly *over* an icon that the real L-shaped leg slices through. The devoxx `e8` edge exited EC2 on the right face at y≈216 and its first waypoint sat up-and-right, so draw.io drew a horizontal leg at y≈216 straight through the RDS icon before turning up — a crossing the diagonal sample missed. The fix expands every diagonal leg to its horizontal-first axis-aligned segments and samples those with the same `segment_crosses_box` predicate, emitting `knee-through-<node>`. That reason matches the existing `*-through-*` escalation in `linter._check_edge_routing`, so an orthogonal-knee icon crossing is an **ERROR** on any class (it blocks publication), exactly like a waypoint-free `straight-through-<node>`. The H-first knee model was calibrated against the exported golden PNGs — `e5` on the GCP/OCI goldens routes horizontal-to-waypoint-x then vertical, clear of `vertex-ai`/`generative-ai`; `e8` routes horizontal-at-exit-y, into `rds` — so all twelve golden `.drawio` examples stay clean while the genuine crossing trips. The `edge-routing` rule detail in both steering copies (`diagram-lint.md`) documents the new knee case (d) so the rule and its description no longer drift.

### Changed

- **Rebuilt the test AWS `eu-central-1` diagram (test artifact).** Edge 8 (EC2→S3) is rerouted: it rises in the narrow gap immediately right of the EC2 node (clear of the RDS icon), runs across an over-the-top corridor that sits *above* the VPC boundary and inside the Account (so it never rides the VPC caption band), and drops into S3's top. The old routing — verified by reconstructing it against the fixed linter — now yields a `knee-through-rds` ERROR.

### Tests

- Regression tests (`tests/test_geometry_hard_rules.py`): a waypointed edge whose H-first orthogonal knee cuts an unrelated icon is flagged `knee-through-<node>`; the same crossing escalates `edge-routing` to ERROR in the linter; the same edge rerouted to clear the icon is clean; a waypointed edge whose legs are already axis-aligned and clear is clean.
- **Corrected `tests/test_review_fixes.py::test_geometry_edge_with_waypoints_not_flagged`.** Its old geometry stacked the intervening node directly in the source→target column and asserted the waypointed edge was clean — but draw.io would have drawn the knee straight through that node, so the premise was the very false-negative 1.5.4 closes. The node is moved out of the column so the route is *genuinely* clear, preserving the test's intent (a deliberately routed waypointed edge that truly clears an obstacle is not flagged).

## [1.5.3] - 2026-09-25

**Theme: a Power install stops erroring on hooks, and the linter now catches a node that spilled out the bottom of its container.** Test-installing the Power from git and generating an AWS `eu-central-1` diagram surfaced three problems: (1) installing the hooks failed with **"Hook has invalid data structure"**; (2) an inventory-driven diagram shipped with a node drawn *below* its VPC border that the gate reported clean; (3) the diagram omitted the instance type on the EC2 nodes and the auto scaling group, and drew S3 (a regional service) inside the VPC. This release fixes the hook packaging and the linter gap, and rebuilds the example.

### Fixed

- **Hook files no longer use the legacy `.kiro.hook` extension** (`.kiro/hooks/*`, `src/rule_engine/_bootstrap/kiro/hooks/*`). The bundled hooks carried the current `{"version":"v1","hooks":[…]}` schema but were named `*.kiro.hook`, and Kiro validates that extension against the *legacy* `when`/`then` schema — so the install rejected them with "Hook has invalid data structure". All six sources are renamed to `.json`; `init_workspace` and `build_backend` copy whole directories, so no code change was needed. Docs updated (`INSTALL.md`, `docs/ARCHITECTURE.md`, `docs/KIRO-UNIVERSITY-COMPLIANCE.md`), including a note on why the `.kiro.hook` extension must not be paired with the `version`/`hooks` body.
- **`container-padding` now flags a node spilled past a container's top/bottom border** (`geometry.check_container_padding`, new `geometry._SPILL_REACH`). The check previously recognised only *inside* (pad measured) or a *straddle* overlapping on **both** axes. A node in the container's x-band but sitting entirely *below* its bottom edge (the EC2-az-c / S3 defect in the inventory-driven AWS diagram) overlapped on one axis only, so it was neither inside nor a straddle and the diagram linted clean. Spill detection is deliberately narrow to avoid false positives: it fires only for an **orphaned** node (housed by no container), whose projection is **fully within** the container's x-band, that has slid at most one row-step (`160`) past the top/bottom border. **Horizontal** spill is intentionally not flagged — an external actor sits to the left of the boundary by design — so all twelve golden examples stay clean. The `container-padding` rule detail in both steering copies (`diagram-lint.md`, `diagram-standards.md`) documents the spill case so the rule and its steering description no longer drift.

### Changed

- **Rebuilt `examples`-style AWS `eu-central-1` diagram (test artifact).** EC2 nodes now carry the instance type in the label, the `devoxx-green-asg` auto scaling group is drawn as a dashed group boundary around the two EC2 instances, and S3 (a regional service) was moved out of the VPC's column into its own Account-level column outside the VPC. Node labels are slugged into the `node-quote`-clean set.

### Tests

- Regression tests (`tests/test_geometry_hard_rules.py`): a node spilled below its container is flagged; the mirror spill above the top edge is flagged; a node housed by a sibling container sharing this one's x-band is **not** flagged; an external actor to the left of a boundary is **not** flagged; a node more than one row-step below the border is **not** flagged.

## [1.5.2] - 2026-09-25

**Theme: `container-padding` now measures a nested boundary against its parent, not just a node against its boundary.** A VPC boundary sharing an edge with its Account boundary (zero padding) linted clean because the check only ever iterated nodes-in-containers — the nested-container case was claimed in diagram-standards and the docstring but never implemented.

### Fixed

- **Nested container-in-container padding is enforced** (`geometry.check_container_padding`, new `geometry._tightest_enclosing`). Each container is measured against its **tightest** enclosing parent; a four-side gap below one grid step is a finding. Sides are measured symmetrically against the same pad floor a node gets, so the check agrees with `size_containers`. The `inside` predicate uses `<=` on the far edges, so a child sharing an edge exactly with its parent (`right == right`) reads as inside-with-zero-padding (a finding), not a disjoint sibling. Severity unchanged: WARNING for `flow`, ERROR for `landscape`.
- All twelve shipped `.drawio` examples stay clean — including the multi-region landscapes with `Account ⊃ VPC ⊃ AZ` nesting (triple nests measure against the immediate parent). No false positives.

### Changed

- **Golden companions declare `diagram_class` explicitly** (audit D3). The six that relied on the implicit `flow` default — `aws/01`, `azure/01`, `gcp/01`, `oci/01`, `cross-cloud`, `generic` — now set `diagram_class: flow`. Behavior is unchanged (the linter already reads the class from the companion when linting the `.drawio`); the reference set now teaches the class instead of leaning on the default.

### Housekeeping

- **Removed git-ignored cruft** (audit G1/G2): five draw.io autosave backups (`.$….drawio.bkp`, incl. the hand-duplicated "копія") and three `.DS_Store`. All already `.gitignore`d — a local-tree tidy, no repository or behavior impact.

### Tests

- Regression tests (`tests/test_geometry_hard_rules.py`): shared-edge child flagged; well-padded child clean; top-flush child flagged; triple nest measured against its immediate parent.

> **Deferred (see `~/Downloads/rule-engine-followups.md`).** The audit's headline finding — `node-connectivity` (D1: ~20 edge-less nodes per HA landscape) — is out of scope for a hotfix: it needs the golden landscapes re-connected first. Tracked with D2/D4 and the A/P refactors in the follow-up plan.

## [1.5.1] - 2026-09-25

**Theme: a git/Power install uses the packaged resources, and the linter blocks
the routing defects it used to wave through.** Test-installing the Power from git
surfaced three problems: (1) the engine resolved its scripts and asset resources
from whatever happened to be on the local machine instead of the packaged
payload; (2) an inventory-driven AWS diagram shipped with routing defects the
gate did not catch — an edge entering a node through its icon, and two edges
stacked on one contact point; (3) an EFS filesystem that existed in the account
was missing from the diagram. This release fixes the resolution drift, closes the
linter gaps, broadens inventory coverage, and makes the diagram-type choice
explicit.

### Fixed

- **Packaged resources resolve from the install, not the local machine**
  (`asset_index.py`, `build_icon_sets_cli.py`, `azure2_shapes.py`,
  `asset_index_cli.py`, `asset_paths_guard.py`, `raster_gate.py`, `linter.py`).
  Several modules resolved data files via a bare
  `Path(__file__).resolve().parents[2]`, which is **not** the repo root in a
  pip/Power install, so they fell through to CWD-relative defaults and picked up
  whatever was on the machine. `roles.yaml`, the committed `icon-index.json`, and
  the `aws4`/`azure2` manifests now resolve through the shared
  `constants.resolve_bundled_dir()` (repo → bundled `_bootstrap` payload → CWD);
  `rule-engine-index-assets` no longer defaults `--root` to `.` (it is now
  explicit); `asset-paths-guard` / `raster-gate` default to the current workspace
  when it looks like one; and `find_ruleset` gains a bundled-payload fallback so a
  correctly-installed package can lint without a prior `rule-engine-init`.
- **The linter now blocks an edge that enters a node through its icon**
  (`geometry.py`, `linter.py`). `edge-routing` previously skipped every
  waypointed edge, so a corridor that ran a final leg up through the target's own
  glyph to reach a top entry (the ALB→S3 defect) was invisible. A new self-pierce
  check flags an edge whose final approach reaches its pinned entry contact from
  the wrong side (`pierces-target-<node>`); an icon crossing — that or a
  waypoint-free `straight-through-<node>` — is now an **ERROR** on any class, so
  it blocks publication instead of merely warning.

### Added

- **Fan-out crossing fixes: overflow valve + bottom-left left-corridor branch**
  (`layout_engine.py`, `diagram-standards.md`). Two crossings remained on the
  dense landscape after adaptive routing: (a) a fan-out source's left-corridor
  branch left the bottom-*right* band and its leftward step crossed the
  centre straight-down branch (edge 4 × edge 3); (b) a source with three
  right-going fan-out edges (`app → cache / db / obj`) had its below-row
  corridors tangle (edge 5 × edge 6, edge 5 × edge 8). Fix (a): the
  left-corridor branch now exits **bottom-left** while the straight branch keeps
  **bottom-centre**, so the two diverge from the glyph. Fix (b): an **overflow
  valve** spills the surplus beyond two right fan-out edges onto the **bottom**
  face (farthest target first) into its own below-row corridor — `route_fan_out_row`
  now honours a bottom exit (drops straight down into its lane rather than a
  right-side stair), and the exit-spread keeps an adjacent straight edge on the
  centre band. Both deterministic and scoped, so a node with ≤ 2 right fan-out
  edges is byte-unchanged. All four provider HA landscapes regenerate with zero
  crossings among the fan-out edges and every geometry check clean.
- **`edge-crosses-container-label` lint rule + adaptive corridor routing**
  (`geometry.py`, `layout_engine.py`, `linter.py`, `diagram-standards.md`). A new
  check flags a routed edge whose polyline runs along a Boundary container's top
  caption (the cross-region corridor that sliced the `vpc-passive` / `az-b1`
  labels); the caption band is sized from the real caption text, so a corridor
  clearing a short caption ("az-a1") is not false-flagged. The router now chooses
  the **nearest free corridor** and enters the face it reaches, generalising a
  reviewer's hand-route: a same-column tier-skip past an intermediate node drops
  in the column's **left** gap and enters the target's **left** face (removing
  the load-balancer→lower-AZ-app back-loop), and a cross-region hop to a
  left-clear target routes in the **inter-row gap** with a **left** entry
  (removing the caption slice and the top-entry pierce). Both faces are
  contract-legal, so `edge-direction` is unchanged. All four provider HA
  landscapes regenerated; the parity guard now accepts a top **or** left
  cross-region entry.
- **`entry-thirds` lint rule** (`geometry.py`, `linter.py`, `diagram-lint.md`).
  The entry-side mirror of `exit-thirds`: several edges arriving on one target
  face at the same/merged contact point (the two `EC2 → RDS` edges both pinned at
  `entryX=0, entryY=0.5`) now trip a finding. WARNING for `flow`, ERROR for
  `landscape`, matching the other routing-family escalations. +8 regression tests.
- **Broad inventory service domains** (`inventory-standards.md` §6). A new
  "Service Domains to Enumerate" table lists the diagram-complete set — identity,
  network, edge (CDN/DNS/WAF), load balancing, compute, containers, serverless,
  messaging, storage (**object stores AND file systems — EFS / Azure Files /
  Filestore / OCI File Storage**), database (SQL + cache), secrets, AI — so a
  diagram formed for the whole inventory no longer silently drops a resource (the
  missing-EFS defect). A domain with no resources is an empty file, never a silent
  skip.
- **Explicit diagram-type selection after inventory** (`diagram-standards.md`,
  both `SKILL.md` copies). After a snapshot, the agent offers **simple** /
  **summary** / **landscape** rather than silently picking one; simple and
  summary are the `flow` lint class, landscape is the `landscape` class.
- **Inventory-completeness → diagram rule** (`diagram-standards.md`). Every
  enumerated resource that resolves to a role must appear on the landscape (and on
  a simple/summary when it is in scope); a resource with no role gets a role added
  and the icon set rebuilt — never a dropped node or a look-alike icon. Codifies
  that `object_store` (bucket) and `file_system` (EFS) are distinct roles.

### Changed

- **A fan-out source may leave from two faces (right + bottom)** (`layout_engine.py`,
  `diagram-standards.md`). A node that starts several downward flows — a load
  balancer or DNS branching to two app tiers / AZs — now routes its
  *directly-below* branch out the **bottom** (a clean vertical drop, like the
  compact summary) while the sibling branches keep the **right** face, instead of
  cramming every branch onto the right and looping the vertical one. Both faces
  are already contract-legal (`edge-direction` admits `exitX>=0.5` OR `exitY==1`),
  so the linter is unchanged; the generator only widens which allowed face it
  picks. Scoped to a source with ≥ 2 downward edges and exactly one directly-below
  branch, so every other layout is byte-unchanged. All four provider HA landscapes
  regenerated; the parity shape-guard now accepts a bottom exit as well as a right
  exit (rejecting only a left or top exit).
- **Version bumped to 1.5.1** (`VERSION`, `pyproject.toml`); `inventory-standards.md`
  sections renumbered (secret-safety → §7, non-fatal failure → §8, cost → §9) with
  code/test references updated.

## [1.5.0] - 2026-09-25

**Theme: a fresh workspace produces correct output.** A Kiro Power carries only
the skill + MCP — not the always-on steering, the icon/role mappings, or the
icon binaries. So in an empty directory the linter never ran and the agent
guessed (EFS drawn Compute-orange instead of Storage-green, external users drawn
inside the VPC). This release makes the engine self-bootstrapping in every
install shape (repo, pip, Power) and closes a batch of correctness, security,
and layout gaps found in the pre-release review (see `docs/REVIEW.md`).

### Added

- **`rule-engine-init` — workspace bootstrap.** Copies the always-on
  `.kiro/steering/`, `.kiro/hooks/`, the `mappings/` tree (roles, per-provider
  icon maps, committed `icon-index.json`), `schemas/`, and `profiles/` into a
  target workspace, idempotently. `--check` reports what is missing (exit 1)
  without writing; `--force` overwrites; `--with-assets` also downloads the
  official icon packs and rebuilds that workspace's `icon-index.json` (needed for
  GCP/OCI, whose icons resolve to on-disk files). The skill's new **STEP 0** runs
  it before generating anything. (`init_workspace.py`, `fetch_assets.py`, console
  scripts `rule-engine-init` / `rule-engine-fetch-assets`.)
- **Bundled bootstrap payload — a power-only install self-configures.** Installing
  a Power does not run pip, and the Power directory carries neither the CLI nor
  the rule/mapping trees. An in-tree PEP 517 backend (`build_backend.py`) now
  copies `.kiro/steering/`, `.kiro/hooks/`, `mappings/`, `schemas/`, and
  `profiles/` into `src/rule_engine/_bootstrap/` at build time, so they ship as
  package data in every wheel/sdist (top level stays the single source of truth;
  `_bootstrap/` is git-ignored). Because setuptools drops dot-directories, the
  `.kiro` trees are stored dot-free (`kiro/steering`) and reconstructed on copy
  (`_BUNDLE_MAP`). The Power's skill ships `scripts/bootstrap.sh`, which
  `pip install`s the package when the CLI is missing, then runs `rule-engine-init`.
- **`compute_instance` and `file_system` presentation roles** (`roles.yaml`,
  `aws-icons.yaml` `presentation:` section, rebuilt `icon-index.json` — 16 roles).
  EC2 and EFS had no mapping, so a generator guessed. They now resolve like every
  other node with the correct AWS service-family color — EC2 Compute orange
  `#ED7100`, **EFS Storage green `#7AA116`**, LB/CDN/DNS Networking purple
  `#8C4FFF` — for all four providers.
- **`docs/REVIEW.md` — the architecture-review findings register.** The stable
  finding codes (`C*`/`D*`/`U*`/`G*`) cited throughout the code, CI, and steering
  now have their authoritative home: each finding, its status, and where it lives.
  Previously those ~20 citations pointed at a document that did not exist.

### Changed

- **Skill: mandatory STEP 0 bootstrap + hardened anti-patterns** (both `SKILL.md`
  copies): run `rule-engine-init` first in any workspace; take the whole `style:`
  string from `mappings/<provider>-icons.yaml` and never hand-write a `fillColor`
  or guess an id; add a role + re-run `rule-engine-build-icon-sets` when a service
  has none (never a look-alike); keep external actors and on-premises nodes
  OUTSIDE the cloud boundaries.
- **Power activation via `dev.kiro/` steering** (`rule-engine-setup.md`,
  `INSTALL.md`, power `README.md`): a Power cannot ship hooks, so an always-on
  `dev.kiro/` steering file is the activation surface that points the agent at
  `bootstrap.sh` first. The workspace-local `check-workspace-init` `SessionStart`
  hook (guarded by `command -v rule-engine-init`) stays for repo/pip installs.
- **Version bumped to 1.5.0** (`VERSION`, `pyproject.toml`).

### Fixed

- **Every CLI imports on a repo-less machine** (`constants.py`, `build_backend.py`).
  `profiles/terminology.yaml` — loaded at import time to build the brand palette —
  was absent from the payload, so 4 of the 8 console scripts crashed with
  `FileNotFoundError` on a power-only install. `profiles/` is now bundled, and
  `constants._resolve_terminology_path()` resolves it from the repo root, the
  bundled payload, then the CWD.
- **Icons and schema resolve in a repo-less workspace too** (`icon_resolver.py`,
  `schema.py`, `constants.py`). Both still hard-coded the repo-root path
  (`parents[2]`), so a pip/Power-only install silently degraded every icon to a
  generic box. A shared `constants.resolve_bundled_dir()` now gives `mappings/`
  and `schemas/` the same repo → bundled-payload → CWD resolution the terminology
  path already had.
- **Snapshot secret-safety redacts secret *values*, not only key names**
  (`collector.py`). A secret under a benign key (a PEM block, a `SecureString`
  payload, an inline `password=…`) was written verbatim. A conservative anchored
  content scan now redacts by value regardless of key name — including a value
  delivered as `bytes` — and the manifest (`00-MANIFEST.md`) is run through the
  same redaction, since it is a snapshot file too.
- **Generation gate fail-closes when the ruleset is missing** (`contract.py`).
  The publication gate called the unguarded `lint(...)`, so an artifact generated
  with `diagram-lint.md` absent was judged eligible — contradicting Req 7 AC14. It
  now routes through `lint_with_ruleset(...)`, so a missing ruleset blocks
  generation.
- **Router obstacle-avoidance is now applied** (`layout_engine.py`). The four
  per-class routers computed a clockwise detour into a local `route` and then
  returned the *un-detoured* interior — so the detour was discarded and an edge
  could cut an unrelated icon (Req 7.7 was a no-op). They now read the detoured
  interior back. The detour also handles a **two-point route** (a blocked
  straight run with no interior waypoint) by inserting an orthogonal staple around
  the obstacle rather than silently emitting the crossing. The shipped HA examples
  regenerate byte-identical (no current edge was blocked).
- **`check_edge_direction` no longer false-flags a single-axis contact pin**
  (`geometry.py`). An edge pinning one axis on the correct side (`exitX=1.0`,
  `exitY` unset) was wrongly flagged; it now flags only a pinned wrong-side axis
  that no correct-side pin rescues. `check_grid_alignment` compares after
  `round()` so sub-pixel float drift is not a false misalignment.
- **Obstacle sampling density is constant on wide diagrams** (`geometry.py`).
  `segment_crosses_box` sampled a fixed count, so on a multi-thousand-pixel run a
  thin obstacle between two samples was missed. It now samples at a fixed spatial
  step with a 61-sample floor.
- **`_unpack` rejects zip-slip** (`fetch_assets.py`). ZIP entries are now checked
  to stay within the asset root before extraction, so a tampered pack cannot write
  outside it.
- **Linter no longer false-positives on steering docs / build output** (`cli.py`).
  The KB `frontmatter` CRITICAL rule was applied to the Power's `dev.kiro/steering`
  file (a steering doc, not a generated KB doc), blocking the `--all` gate.
  `_is_generated_markdown` now exempts any `*.kiro/steering/` file, and discovery
  prunes `build/`, `dist/`, and `_bootstrap/`.
- **Silent collisions are surfaced** (`asset_index.py`, `delta.py`). Two services
  whose names normalize to one slug, and two resources sharing one
  `(provider, resource_type, identity)` tuple, were overwritten with no trace.
  Both now emit a WARNING (last-writer-wins retained for compatibility).

### Maintenance

- **AWS HA generator uses the mapped LB icon** (`build_aws_ha_example.py`). It
  hand-wrote `resIcon=elastic_load_balancing` where the `lb` role maps to
  `application_load_balancer`; aligned to the mapping and regenerated the AWS HA
  triple.
- **Repeated disk reads cached** (`schema.py`, `icon_resolver.py`). The schema +
  its `Draft202012Validator` and each provider's icon mapping were re-parsed on
  every validated resource / resolved node; both are now `lru_cache`d behind a
  deep-copy-returning API.
- **HA generator wrappers de-duplicated** (`ha_multiregion_common.py` +
  the four `build_*_ha_example.py`). The near-identical `main()`/argparse blocks
  collapse into one shared `run_cli(...)`; regeneration stays byte-identical.
- **Raster-budget docs reconciled with the enforced value** (`raster_gate.py`,
  `export_raster.py`, CI). Stale "≤ 1200px" prose now matches the enforced
  class-aware budget (flow ≤ 1600px / < 500KB, landscape ≤ 3600px / < 2MB).
- **CI exercises the console scripts and the bootstrap** (`.gitlab-ci.yml`,
  `.github/workflows/ci.yml`). The validate stage calls the packaged
  `rule-engine-check-asset-paths` / `rule-engine-check-rasters` entry points, uses
  `find` instead of a non-recursive glob, and adds a `rule-engine-init` smoke test.

## [1.4.1] - 2026-09-24

Refines the layout engine's **edge routing and contact-point selection** so the generated HA diagrams match the hand-routed reference, then **retires the `-reference` snapshots** now that the engine reproduces them. The routing rules were distilled from reviewer hand-edits and are enforced by the existing geometry oracle plus one new advisory lint rule; all four clouds still share one generated geometry (byte-parity preserved), and every example was regenerated from scratch to exercise the logic end-to-end.

### Added
- **GitHub community health files** (`CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, README **Community** section): the recommended open-source repository set per [opensource.guide](https://opensource.guide/) — a Contributor Covenant 2.1 code of conduct, a security policy pointing at private GitHub Security Advisories, structured issue forms (bug report / feature request) with a config that disables blank issues and links security + discussions, and a pull-request template wired to the project's gate commands.
- **`edge-crosses-label` lint rule** (WARNING) (`src/rule_engine/geometry.py` `check_edge_crosses_label`, `src/rule_engine/linter.py`, `.kiro/steering/diagram-lint.md`, `.kiro/steering/diagram-standards.md`): flags an edge whose routed polyline (its pinned contact points plus every waypoint) crosses an **unrelated node's label band** — the caption strip drawn beneath the icon. The icon-box geometry rules measure the bare icon, so a corridor one grid step under a glyph could run straight through a service name undetected; this closes that gap using the same `segment_crosses_box` predicate the routers and `edge-routing` use. Advisory for both classes.
- **Routing-rule guards** in the parity structural predicate (`tests/test_ha_generator_parity.py`): every generated landscape is asserted to have no edge crossing an unrelated icon, no edge crossing a label band, a ≥ 1-grid-step step-out before the first turn, first-exit-centred / cross-region-top-entry contacts, and within-band horizontal ordering — so the routing regressions cannot silently return.

### Changed
- **Contact-point model: first exit centred, spread only for the 2nd/3rd** (`select_contacts`, `spread_contacts`, new `spread_entries`, `_place_and_route`): `select_contacts` now always returns the right-**centre** exit and a centred entry; the off-centre quarters (0.25 / 0.75) are applied only when 2+ edges share a face, in **edge-marker order** (the first/lowest marker keeps the centre — "перший по центру"). A shared target entry face is spread the same way. This removes the systematic off-centre exits that crossed captions and made stubs look scattered.
- **Axis-clean, grid-resolving contacts (no skewed arrowheads)** (`_stair_first_waypoint`, `_grid_contact`): the step-out leaves the exit **purely horizontally** (only x moves) before the vertical turn, and every contact **fraction** is snapped so its absolute point lands on the grid — the 78 px icon centre (x0+39) is off the 10-grid, so a grid-snapped waypoint used to meet the arrow with a 1 px kink that skewed every arrowhead. Waypoints stay on the grid; the arrow now lands exactly on the final waypoint.
- **Corridors clear the label band (Rule F)** (`route_fan_out_row`, `route_cross_region`, `route_back_edge`): every horizontal corridor — below-row, over-row, and back-edge loop — now insets past the relevant row's caption band (`icon_bottom + LABEL_BAND`), so a fan-out or cross-region run never passes through a service name.
- **Left-entry step-in / top-entry for edge-of-canvas targets (Rule G)**: a back-edge whose target has no left gap (against the canvas edge) enters the target's **top** instead of running down its column edge with no offset.
- **Parallel long runs get distinct lanes (Rule H)**: cross-region and back-edge runs share one physical-corridor namespace (`hcorr-<side>:<row>`) so two runs in the same band never collapse onto one line, and a shifted (non-first) long-haul exit leaves the **upper** quarter so its stub clears the centred first edge; corridor lanes are spaced 2 grid steps apart so parallel lines stay visibly separate.
- **Straight same-column drops + top-entry for below targets**: in a `compact` flow (the summary), a spine to a target directly below in the same column drops **straight** (bottom→top) instead of an exit-right / step-back-left hook; and any edge whose target sits **below** the source enters the target's **top** rather than running along its row's centre line — removing the excessive summary crossings (e.g. `app→objstore` vs the `db→db` replication run).
- **Horizontal within-band placement + `DiagramSpec.compact`** (`layout_engine.place_nodes`/`_band_within`/`_band_packing`, `ha_multiregion_spec.py`): a north-south landscape band reads **across** (one column per lane, `sub` → sub-row) instead of stacking same-slot nodes in one column; the summary is a `compact` north-south flow (regions side-by-side, DNS centred above, flow reading down each region column) matching the hand-drawn composition. A reserved `TITLE_BAND` lifts the outermost container clear of the title.
- **Version bumped to 1.4.1** (`pyproject.toml`).

## [1.4.0] - 2026-09-24

Introduces a **declarative lane-grid layout engine** that generates the HA multi-region diagrams' geometry from a coordinate-free declaration, replacing the hand-authored coordinate tables. Node placement, container sizing, contact-point selection, corridor allocation, and orthogonal per-class routing are all derived from a `DiagramSpec` (roles + lanes + regions + slots + edge types, no `x`/`y`/waypoints); the engine reuses the existing `geometry.check_*` validators as its acceptance oracle and repairs a candidate against them rather than duplicating any constraint. The four provider skins now supply only icons and labels, so all four clouds share one geometry. The hand-authored diagrams are preserved as `-reference` snapshots for side-by-side comparison. Encodes Requirements 1–11 of the `lane-grid-layout-engine` spec.

### Added

- **Declarative layout engine** (`src/rule_engine/layout_engine.py`): a deterministic, coordinate-free lane-grid engine. Input is a `DiagramSpec` (`NodeSpec` role/lane/region/slot/sub/container, `EdgeSpec` source/target/marker/dashed, `ContainerSpec` kind/region/parent) with **no coordinates** — a declaration cannot express one, so `_validate_spec` rejects unknown lanes, duplicate `(lane, region, slot)`, and dangling edge endpoints by name (R1, R2). The pipeline: `place_nodes` (lane→primary axis, slot→secondary; region B offset along the **secondary** axis by a content-derived, grid-aligned step; mirror-symmetric — R3) → `size_containers` (bottom-up footprint bbox + `CONTAINER_PAD`, equal-width peer bands, declared `NodeSpec.container` membership with a geometric fallback — R4) → `centre_block_in_vpc` → `select_contacts`/`spread_contacts` (exit/entry priority ladder, distinct same-side exits, `OverConnectedError` on a 4th — R5) → `CorridorAllocator` (one grid-step corridor line per gap, widen-on-exhaust — R6) → `classify_edge` + per-class routers (`straight`/`spine`/`fan-out-row`/`cross-region`/`back-edge`, stair step, clockwise obstacle detour reusing the `geometry.segment_crosses_box` predicate; an unclassifiable edge raises — R7) → `place_legend` (R8) → a bounded, deterministic repair loop (`_run_oracle` serializes via `build_diagram` + `build_geometry` then runs the geometry `check_*` set; `_repair` widens corridors / grows containers / re-centres; over-connected raises `LayoutError` — R9, R11). Entry point `layout(spec) -> PlacedDiagram`. The engine produces a candidate and asks the validators — it does not re-implement the constraints. Tests in `tests/test_layout_engine.py` incl. a property-based invariant (every small valid spec's output passes every `check_*`).
- **HA diagram declarations** (`src/rule_engine/ha_multiregion_spec.py`): the two coordinate-free `DiagramSpec`s — `SUMMARY_SPEC` (left-right / `flow`) and `LANDSCAPE_SPEC` (north-south / `landscape`) — encoding the same topology the old tables expressed, with no geometry (R1.5, R2.5).

### Changed

- **`ha_multiregion_common.py` migrated off coordinate tables to the engine** (`scripts/ha_multiregion_common.py`): the `SUMMARY_*` / `LANDSCAPE_*` coordinate tables and the `_compact_landscape` / `_centre_regions_in_vpc` hand transforms were **removed**. `build_summary` / `build_landscape` now call `layout(spec)` and map the placed geometry onto the `ProviderSkin` (icons + labels + container styles, unchanged) before `build_diagram(...)`. The four `build_{aws,azure,gcp,oci}_ha_example.py` wrappers are unchanged — they still supply only the skin (R1.5, R11.2, R11.3).
- **Provider geometry is now identical across all four clouds** (`tests/test_ha_generator_parity.py`): because geometry is generated from one shared declaration, AWS/Azure/GCP/OCI summary+landscape pairs differ only in icons and labels; a parity test pins this. Regeneration is byte-stable (R11.1).
- **`NodeSpec.container` membership field**: AZ membership is **declared** on the node rather than guessed from tier geometry (guessing produced overlapping AZ boxes); `size_containers` uses it with a geometric fallback when a node declares none.
- **Hand-authored diagrams preserved as `-reference` snapshots** (`examples/{aws,azure,gcp,oci}/02-*-ha-multiregion-{summary,landscape}-reference.{drawio,drawio.png,diagram.md}`, `src/rule_engine/cli.py`): each committed HA `.drawio` (+ `.drawio.png`, `.diagram.md`) was copied to a `-reference` sibling and excluded from lint/discovery/regeneration via `_is_reference_artifact`, so the engine's output can be compared side by side against the hand-tuned original (R10.1, R10.6). The full gate (`pytest`, `rule-engine-lint --all`, `rule-engine-check-rasters`, `rule-engine-check-asset-paths`) stays green; all eight generated diagrams are publication-eligible with zero WARNING delta vs the references (R10.2–R10.5).
- **Diagram design notes** (`docs/DIAGRAM-DESIGN-NOTES.md`): a new "The layout is generated, not hand-authored" section documents the placement model (lane→primary, slot→secondary, content-derived secondary-axis region offset, declared container membership), the routing model (contact-point ladder, corridor allocation, per-class routers as the executable form of the prose routing rules), the validators-as-oracle repair loop, and the two migration lessons.
- **Version bumped to 1.4.0** (`VERSION`, `pyproject.toml`).

## [1.3.0] - 2026-09-23

Introduces a first-class **diagram class** (`flow` vs `landscape`) so the engine is first-class at both summary and comprehensive as-built diagrams. Complex diagrams (> 12 nodes) are no longer forced to split: a `landscape` as-built relaxes the node cap while other rules tighten to keep it legible, and the "summary + detailed" pairing becomes a checked contract. Ships a cross-linked golden summary+landscape pair per cloud (HA multi-region active-passive), **icon standardisation on the official vendor bundles** via a committed index built at install time (with `cdn`/`dns`/`waf` roles and an icon-reference verifier that catches broken/non-existent glyphs), a set of **geometry-enforced routing rules** distilled from hand-review (directional contract, spine/stair/fan-out corridors, no line crossings, container-overlap, label-aware padding), and a **class-aware raster budget** so a wide as-built stays legible.

### Added

- **Diagram class `flow` vs `landscape`** (`src/rule_engine/linter.py`, `.kiro/steering/diagram-lint.md`, `.kiro/steering/diagram-standards.md`): every diagram declares a class in its companion `.diagram.md` frontmatter (`diagram_class`, default `flow`). `flow` keeps the 12-node ERROR cap and the numbered-flow-marker convention unchanged, so all pre-1.3.0 artifacts lint identically. `landscape` is an as-built / inventory view: the node cap relaxes to `node-count` **WARNING at > 30** and **ERROR at > 50**, and readability is instead enforced by raising `container-padding` to **ERROR**, by the existing geometry rules, and by a mandatory cross-link to a `flow` summary. The `Artifact` model gains `diagram_class`, `summary_of`, `detailed_view`, `overlay_markers`, and `legend_overlay_terms` (all defaulted, so the change is backward-compatible), and the `lint()` aggregator now accepts a per-rule `Severity` from a predicate so one rule (`node-count`) can carry class-dependent severity.
- **`orphan-landscape` lint rule** (ERROR): a `landscape` diagram must declare `summary_of` naming the sibling `flow` summary of the same system. This encodes the "one summary + one detailed" pairing as a checked contract rather than a convention. The paired `flow` summary may declare `detailed_view` back. The CLI `.drawio` parser (`src/rule_engine/cli.py`) reads `diagram_class`/`summary_of`/`detailed_view` from the companion frontmatter and harvests overlay markers.
- **`overlay-legend-coverage` lint rule** (WARNING) and an **overlay vocabulary** (`.kiro/steering/diagram-standards.md`): an optional, double-encoded (shape + color + label) vocabulary for findings/state — `spec-required-not-deployed` (red dashed box), `observability-overlay` (blue stroke), and change markers new/changed. When any overlay marker is used, the Legend must document it or the rule warns.
- **Named routing patterns** (`.kiro/steering/diagram-standards.md`): the directional back-edge contract (exit-right / loop / enter-left, never exit the side you enter), the longer-clean-detour rule (never route a fan-out edge through the middle icon of a stacked column — use a side corridor), and corridor-before-content. Distilled from building a 40-node as-built; they apply to both classes and are independent of node count.
- **Icon-reference verifier** (`src/rule_engine/verify_icon.py`, CLI `rule-engine-verify-icon`): resolves every `resIcon`/`grIcon`/image-path reference in a `.drawio` against the provider's authoritative source — AWS `mxgraph.aws4.*` ids against the curated `mappings/aws-icons.yaml` allow-list, GCP/Azure file-path images under the fetched asset root, and OCI slugs against `assets/vendor/oci-stencils/stencils.json`. Closes the gap where `icon-resolved` only catches an *empty* style, not a well-formed-but-nonexistent id (a typo that renders as an empty box). Fail-honest: a reference is `skipped`, not `unresolved`, when its source is not present in the workspace.
- **Per-provider HA build scripts** (`scripts/ha_multiregion_common.py` + `scripts/build_{aws,azure,gcp,oci}_ha_example.py`): a shared module holds the verified HA multi-region layout geometry (node coordinates, nested account→region→AZ container boxes, orthogonal edge waypoint corridors) and four thin wrappers supply only each provider's icon renderer and region/account labels, so every provider's summary+landscape pair regenerates deterministically through `diagram_layout.build_diagram` (mirroring the existing `build_oci_example.py` pattern). The layout is identical across all four clouds; only the skin changes.
- **Golden summary+landscape pairs** (`examples/{aws,azure,gcp,oci}/`): one `flow` summary (<= 12 nodes) plus one `landscape` as-built of the same HA multi-region active-passive system per cloud, cross-linked via `summary_of` / `detailed_view`. Each pair proves the class contract end-to-end: the summary lints eligible under flow rules and the landscape lints eligible under landscape rules (WARNING-level node-count on the larger as-built, never blocked).
- **Class-branching tests** (`tests/test_linter_class.py`): pin the 30/50 landscape thresholds, the flow 12-node cap (regression), `orphan-landscape`, `overlay-legend-coverage`, and legacy mapping-input support.
- **Icon standardisation on the official bundles, indexed at install time** (`src/rule_engine/asset_index.py`, `src/rule_engine/build_icon_sets_cli.py`, CLI `rule-engine-build-icon-sets`, `mappings/roles.yaml`, `mappings/icon-index.json`): a committed `roles.yaml` declares each diagram role (the nine neutral types plus presentation-only `cdn`/`dns`/`waf`/`lb`/`cache`), and the init-time builder fetches every official pack and resolves each role → icon per provider into the committed `mappings/icon-index.json` (a `pack_summary` plus the resolved `roles`). Generators resolve a role through the index rather than hand-writing a path/slug, so a wrong or renamed icon is a re-index, not a code edit. OCI is folded into the unified index from its decoded `stencils.json`. Wired into `INSTALL.md`, `pyproject.toml`, and the CI `validate` stage (`--check`).
- **`cdn` / `dns` / `waf` presentation roles** (`mappings/roles.yaml`, `.kiro/steering/provider-profiles.md`): distinct services get their own role and correct per-provider glyph — never a look-alike. GCP follows Google's own docs taxonomy (product-first, category-fallback): Cloud CDN has no product icon, so it uses the **Networking category** icon exactly as `docs.cloud.google.com` does.
- **draw.io-internal stencil manifests** (`src/rule_engine/azure2_shapes.py`, `mappings/aws4-icons.json`, `mappings/azure2-shapes.json`): committed allow-lists of every valid `mxgraph.aws4.*` id (asar-extracted ∪ curated) and `img/lib/azure2/*.svg` path, extracted from a local draw.io `app.asar`. `rule-engine-verify-icon` now checks aws4 ids and azure2 paths against them, so a well-formed-but-nonexistent id/path (which renders as an empty/broken box) is caught — the gap that previously let `Azure_Cache_Redis.svg` (the real file is `Cache_Redis.svg`) ship as a broken image. Wired into CI. Tests in `tests/test_verify_icon_azure2.py`.
- **New geometry-enforced lint rules** (`src/rule_engine/geometry.py`, `src/rule_engine/linter.py`, `.kiro/steering/diagram-lint.md`): `container-overlap` (sibling boundaries must not partially overlap; WARNING/**ERROR** for `landscape`), `edge-direction` (exit right/bottom, enter left/top; WARNING/**ERROR** for `landscape`), `edge-float` (every edge must pin explicit contact points; WARNING/**ERROR** for `landscape`), `corridor-sharing` (two unrelated long edges may not share a straight lane; shared-trunk exempt; WARNING), and `text-padding` (a filled+stroked text box must set uniform inner padding; WARNING). `container-padding` and `node-overlap` are now **label-aware** — measured against the icon+label footprint, not the bare icon.
- **`exit-thirds` lint rule** (WARNING) (`src/rule_engine/geometry.py` `check_exit_thirds`, `src/rule_engine/linter.py`, `.kiro/steering/diagram-lint.md`): a node's service name renders under its icon, so edges fan out on the **right** side with contact points on the centred / even-thirds split — one exit at `0.5`, two at `0.25/0.75`, three at `0.25/0.5/0.75` — and a side may carry **at most three** exits (a fourth means the node is over-connected). The check reads *exit* points only (source-side fan-out) and defers left-side exits to `edge-direction`. Tests in `tests/test_geometry_hard_rules.py`.
- **Geometry-hard-rule tests** (`tests/test_geometry_hard_rules.py`): pin the label-aware footprint, container-overlap, edge-direction, edge-float, corridor-sharing (incl. shared-trunk exemption) checks and that all four golden landscapes stay clean under them.
- **Diagram design notes** (`docs/DIAGRAM-DESIGN-NOTES.md`): the rationale behind the routing, icon-fidelity, and layout rules, distilled from building and hand-reviewing the HA landscape. Linked from the README.

### Changed

- **`node-count` and `container-padding` are now class-aware** (`src/rule_engine/linter.py`, `.kiro/steering/diagram-lint.md`): `node-count` severity depends on the diagram class (flow: ERROR > 12; landscape: WARNING > 30, ERROR > 50); `container-padding` is a WARNING for `flow` and an ERROR for `landscape`. `flow` (the default) behavior is unchanged.
- **Edge-routing readability rules** (`.kiro/steering/diagram-standards.md`, `scripts/ha_multiregion_common.py`): the directional contract (exit right/bottom, enter left/top) with no floating endpoints; the **spine** rule (route a tier hop via the gap corridor beside the column, not straight down it); **stair-step** (step sideways into the gap before turning, symmetric for up-turns); **fan-out along a row** (each edge turns up in the gap just before its target, one below-row lane each, distinct exit points ≥ a third apart, a bottom fan-out exits down-then-steps); a tier-skip takes the one corridor that crosses no fan-out lane; **turn near the source** for back-edges/cross-region runs. Distilled from a reviewer's hand-edits and reproduced by the generator.
- **Connection rules unified and de-conflicted** (`.kiro/steering/diagram-standards.md`, `scripts/ha_multiregion_common.py`): the exit/entry convention was rewritten into two ordered priority ladders — **exit** (right-centre → right-biased-to-direction → straight-down-if-shortest → repeat per thirds) and **entry** (side chosen by the incoming line: horizontal→left, vertical→top; centred, extra entries shift toward their own line) — plus a single stair rule for both ends (step one grid step out before the first turn), **clockwise obstacle detours** (deterministic routing), "any overlap with an edge **or a container border** → step off one grid step", and a **widen-don't-narrow** tie-breaker when spacing and compactness conflict. This removes a real contradiction (the old "push the third edge onto the bottom" clashed with label-safe right-side exits) and the "exactly one step" vs "whole grid multiple" spacing conflict. The `app→cache/db/object-store` fan-out and the DNS/app summary fan-outs were regenerated onto the even-thirds right-side exits accordingly.
- **Raster gate skips scratch/copy files** (`src/rule_engine/raster_gate.py`): `check_rasters` now applies the same `_is_scratch_copy` exclusion `discover_artifacts` uses, so a hand-edited duplicate (`… копія.drawio`) with no exported PNG no longer fails the raster/triple check.
- **`exit-thirds` relaxed to distinctness, not a rigid grid** (`src/rule_engine/geometry.py`, `.kiro/steering/{diagram-standards,diagram-lint}.md`): the same-side fan-out rule now enforces only two soft conditions — **at most three exits per side**, and **no two exits closer than ~⅕ of the side** (they would merge into one doubled line). It no longer requires the exact `0.25/0.5/0.75` split, because the exit-priority ladder keeps a straight-line edge (a target directly opposite) on the centre while the others spread around it — more readable than forced thirds. `check_corridor_sharing` additionally exempts chained edges through a shared node (`app→db` + `db→db'` touch that node's opposite faces, not a merged corridor).
- **Landscape routing reproduces the reviewer's hand-corrected reference** (`scripts/ha_multiregion_common.py`, `.kiro/steering/diagram-standards.md`): all landscape/summary edges were re-authored so the generator emits, exactly, the reviewer's corrected AWS copy — label-safe right-side exits with the priority ladder (right-centre → biased → straight-down-if-shortest), fan-out along the row (cache straight on the upper third, db/obj each in its own below-row lane turning up just before the target), spine hops turning left in the roomy band above the AZ, the standby back-edge clearing the cdn icon, and cross-region edges in their own over-row corridors. Waypoints are authored in raw (pre-shift) coordinates so the region-balance transform moves them consistently with the nodes.
- **Equal-width region bands + symmetric on-grid node placement** (`scripts/ha_multiregion_common.py`, `.kiro/steering/diagram-standards.md`): the region-balance transform now widens **both** VPC/AZ bands toward the shared centre so peer containers are the same width (the passive region is no longer narrower), and a new `_centre_regions_in_vpc` step slides each region's whole node block (nodes + edge waypoints together) so it is centred in its VPC with equal padding, snapped to the grid. Both regions read as mirror-symmetric bands.
- **Flow/Legend pinned narrow and clear of the cloud** (`src/rule_engine/diagram_layout.py`, `scripts/ha_multiregion_common.py`, `.kiro/steering/diagram-standards.md`): `build_diagram` gained an optional `legend_w` so the Flow/Legend blocks can be pinned narrow and wrap taller (wrap-aware height) instead of running wide; the landscape places them one grid step past the account box's right edge so they never overlap the cloud.
- **Class-aware raster budget** (`src/rule_engine/raster_gate.py`, `scripts/export_raster.py`, `.kiro/steering/diagram-standards.md`): a `flow` raster stays ≤ 1200px / < 500KB; a `landscape` exports wide (≤ 3600px / < 2MB) so a 30-plus-node as-built stays legible instead of being shrunk. The gate reads each diagram's `diagram_class` from its companion and applies the matching ceiling; `export_raster.py` picks the export width by class.
- **Text-box furniture** (`src/rule_engine/diagram_layout.py`, `.kiro/steering/diagram-standards.md`): every generated text/legend cell carries uniform inner padding (`spacing*=10`), and `build_diagram` sizes the Flow and Legend boxes to **one shared width** (tight to the longest line, no wrapping) with heights fit to each box's content.
- **Container vertical envelope** (`scripts/ha_multiregion_common.py`, `.kiro/steering/diagram-standards.md`): a parent container is sized from its deepest child's footprint plus ≥ 1 grid step, so no nested box sits flush against its parent's border (the account/VPC boxes grew to clear the AZ-2 row).
- **Horizontal space balance** (`scripts/ha_multiregion_common.py`, `.kiro/steering/diagram-standards.md`): the landscape no longer leaves a wide dead gap between the two region bands while nodes hug one side. Region-A nodes are centred within their VPC and region-B is pulled in so the inter-VPC gap is one consistent step (≈140px, from ≈380px), and the Account box wraps both bands snugly with one grid step of padding (right edge 2310 → 2190); the right-margin Flow/Legend column follows. All nudges are whole grid multiples applied by a deterministic transform, so every origin stays on the grid and the change is identical across all four providers.
- **Summary routing + resolution** (`scripts/ha_multiregion_common.py`, `scripts/export_raster.py`, `src/rule_engine/raster_gate.py`): the HA summary now routes DNS fan-out straight down from distinct exit points, loops the object-store edge clockwise under the row into its left face, and draws cross-region replication as a straight line; the flow raster width was raised to 1600px so a two-region summary stays legible.
- **Scratch/copy files excluded from discovery** (`src/rule_engine/cli.py`): `discover_artifacts` skips editor/file-manager duplicates (`… копія.drawio`, `… - Copy.drawio`, `… (1).drawio`) so they are never linted or tested as golden artifacts. Regression tests in `tests/test_cli_handauthored_exclusion.py`.
- **README rewritten** with a cloud × diagram-type demo table (application-flow, HA `flow` summary, HA `landscape` as-built per cloud) linking each `.drawio` and PNG, plus the diagram-class and icon-index overview.
- **Version bumped to 1.3.0** (`VERSION`, `pyproject.toml`).

### Fixed

- **OCI HA icons rendered as empty boxes** (`scripts/build_oci_ha_example.py`): the HA generator mapped every role to a bare OCI-red labelled-box fallback instead of embedding the real stencil. It now renders every node via `OciStencilIcon` (slug per role from the 218 decoded stencils), the same mechanism as the OCI golden example — so all OCI nodes show their real glyphs.
- **GCP/AWS/Azure edge-row icons corrected** (`scripts/build_{aws,azure,gcp}_ha_example.py`, `mappings/roles.yaml`): the `edge-cdn` node was drawn with the object-store icon because it reused the `obj` role. It now resolves through the `cdn` role to CloudFront (AWS), the CDN Profiles glyph (Azure), and the Networking category icon (GCP); `Azure_Cache_Redis.svg` corrected to the real `Cache_Redis.svg`.

## [1.2.0] - 2026-09-23

OCI icon-size consistency and a documentation-correctness pass over the diagram rules (steering frontmatter, provider-accurate legend, stencil provenance, North–South geometry, container conventions), plus a CI raster gate that enforces the PNG export budget.

### Added

- **Project documentation** (`docs/ARCHITECTURE.md`, `docs/KIRO-UNIVERSITY-COMPLIANCE.md`): a structured architecture-and-algorithm document (data model, seven core components, the two output pipelines, quality gates, MCP support) and a Kiro University feature-compliance document mapping all six lessons (specs, steering, hooks, property-based testing, skills/powers, MCP) to concrete repository evidence.
- **Agent skill** (`.kiro/skills/rule-engine-artifacts/SKILL.md`): packages the on-demand workflow for authoring and validating Rule Engine artifacts (diagram triple, companion doc, inventory snapshot, icon mapping) and the exact gate commands, deferring rule values to the always-on steering docs.
- **AWS Documentation MCP registration** documented for the workspace (`.kiro/settings/mcp.json` block; active at the user level `~/.kiro/settings/mcp.json`) so the agent can look up current AWS facts via read-only `search_documentation`/`read_documentation`/`recommend` tools.
- **Hand-authored Markdown exclusion in the Linter** (`src/rule_engine/cli.py`): `--file` mode now reports a hand-authored doc (README/ARCHITECTURE/compliance/`SKILL.md`, etc.) as `[SKIP]` instead of a false `frontmatter` CRITICAL — matching the `--all` scan and fixing a lint-on-save false positive. `architecture.md`, `kiro-university-compliance.md`, and `skill.md` join the excluded-basename set. Regression tests in `tests/test_cli_handauthored_exclusion.py`.
- **GCP product icons via source priority** (`mappings/gcp-icons.yaml`, `examples/gcp/01-gcp-vertex-pipeline.drawio`, `.kiro/steering/asset-packs.md`): GCP icons now resolve by an explicit priority — (1) official **Core Product** icon (`core-products-icons.zip` → `gcp-core`) for flagship services, (2) official **Product Category** icon (`category-icons.zip` → `gcp-category`) otherwise, (3) built-in `mxgraph.gcp2.*` only as a last resort. Four neutral types (`object_store`→Cloud Storage, `managed_sql`→Cloud SQL, `managed_k8s`→GKE, `llm_platform`→Vertex AI) now use their dedicated 2025 product icons; the golden example's `api-gateway` uses the Apigee product icon so it is visually distinct from `load-balancer` (Networking category). Each mapping entry gains an `icon_provenance: product|category` marker. **Corrected a false claim** in `asset-packs.md`: `mxgraph.gcp2.*` is not "9 structural shapes only" — it defines 255 shapes including per-service icons (verified against the draw.io `app.asar` and by headless export); it is a pre-2025 style kept as the tier-3 fallback. CI (GitLab + GitHub Actions) now fetches `gcp_core` alongside `gcp_category`/`azure` so the asset-paths guard verifies the product paths.
- **Raster export helper** (`scripts/export_raster.py`): exports a `.drawio` to its `.drawio.png` within the D7 budget, inlining repo-relative `image=assets/vendor/...` icons as base64 in a temporary copy first. The headless draw.io CLI refuses to load local files during export (`Blocked loading file from file://...`), so GCP category icons (the only provider referencing `assets/vendor` file paths) rendered as the default placeholder glyph in the raster while the committed source must keep a lint-clean file path (a `data:` URI in the source trips `icon-resolved`). This helper keeps the source file-path-based and produces a raster with the real icons; AWS/OCI/Azure need no inlining (built-in stencils, embedded stencils, and draw.io-internal `img/lib` shapes respectively) and export directly.
- **Raster gate** (`src/rule_engine/raster_gate.py`, CLI `rule-engine-check-rasters`): enforces the Raster Export Dimensions budget (D7) on every exported `NN-topic.drawio.png` — width ≤ 1200px and file size < 500KB. The linter evaluates the `.drawio` source and the companion document, not the rendered PNG, so this closes the one gap that let an oversized raster (e.g. the earlier 3485px OCI export) ship. Dependency-free: PNG width is read directly from the IHDR chunk (no Pillow), keeping runtime deps at `jsonschema` + `PyYAML`. Missing PNGs hard-fail by default; `--allow-missing` downgrades them to a skip for pre-export environments. Wired into the CI `validate` stage (GitLab + GitHub Actions) and a pre-commit hook. Tests in `tests/test_raster_gate.py`.

### Fixed

- **Provider-correct legend synced across all examples and the shared builder** (`src/rule_engine/diagram_layout.py`, `examples/aws/*.drawio`, `examples/oci/*.drawio`, `examples/cross-cloud/*.puml`, `examples/generic/*.puml`): the color-independent legend fix had only reached the Azure and GCP `.drawio` files. The shared builder's `STANDARD_LEGEND_LINES` and the AWS/OCI/cross-cloud/generic examples still carried the old color-only wording (`Dashed green boundary = stack boundary` / `Dashed blue boundary = Network Boundary`) — a hidden regression that any regeneration through `build_*.py` would re-introduce. All now use `Dashed outer boundary = stack Boundary (profile brand color)` / `Dashed inner boundary = Network Boundary (profile brand color)` (the generic example double-encodes color + name, keeping its green/blue convention). The GCP and OCI generators are idempotent against their committed `.drawio`, and all six rasters (four `.drawio.png` via `export_raster.py`, two `.puml` PNGs via PlantUML) were regenerated to match.
- **OCI mapping de-fictionalized** (`mappings/oci-icons.yaml`): the nine entries declared `shape=mxgraph.oci.<name>` styles, but no `mxgraph.oci.*` namespace exists anywhere (verified against Oracle `OCI Library.xml`, which ships `shape=stencil(...)` glyphs keyed by title, not named ids) — so the general resolve path produced empty boxes. The example only rendered because `scripts/build_oci_example.py` embeds decoded stencils by slug, bypassing the mapping. Each entry now carries a logical `stencil: assets/vendor/oci-stencils/stencils.json#<slug>` reference (all nine slugs verified in the library) plus a self-contained OCI-red labelled-box `style` fallback (keeps `resolve_icon` working, passes the linter). Slugs: compartments, virtual-cloud-network-vcn, functions, object-storage, autonomous-db, streaming, vault, container-engine-for-kubernetes, artificial-intelligence.
- **Documented verified icon resolution** (`.kiro/steering/asset-packs.md`): added a per-provider resolution table (AWS `mxgraph.aws4.*` stencils incl. `group_vpc2`; Azure azure2 file-path image shapes; GCP official category icons by file path; OCI custom imported stencils; generic base shapes), the neutral-type→GCP category icon map, and the base64-vs-file-path caveat (the linter flags `image=data:image/svg` and `resolve_icon` requires a non-empty `style`).
- **AWS VPC boundary icon** (`mappings/aws-icons.yaml`, `examples/aws/01-aws-agent-platform.drawio`): the Network Boundary container used `grIcon=mxgraph.aws4.group_vpc`, but the correct current draw.io group-icon name is `group_vpc2` (verified against Sidebar-AWS4.js) — the old id left the VPC group frame without its icon. Updated the mapping and the AWS golden example. The seven AWS service resIcons (lambda, s3, rds, eks, sqs, secrets_manager, bedrock) and `group_account` were verified correct and unchanged.
- **GCP icons now resolve** (`mappings/gcp-icons.yaml`): the legacy `mxgraph.gcp2.*` service stencil ids were all invalid — that draw.io namespace ships only 9 structural shapes (zones/paths/frames), no service icons, so every GCP node rendered as an empty box. The nine neutral types now resolve to the official Google Cloud **category** icons (category-icons.zip — all nine present), referenced by file path under the fetched asset root (`image=assets/vendor/gcp-category/...`), the same file-path image-shape approach as Azure. `scripts/fetch_assets.py` + `mappings/asset-sources.yaml` already fetch the pack. (Considered base64-inlining like OCI, but the linter intentionally flags `image=data:image/svg` as unresolved, so file-path styles are used instead.)
- **GCP golden example redrawn** (`examples/gcp/01-gcp-vertex-pipeline.drawio`): all nine node styles switched from invalid `mxgraph.gcp2.*` to the official category-icon file paths; legend made color-independent. PNG re-exported (see Changed).
- **GCP example generator rewritten to match its artifact** (`scripts/build_gcp_example.py`, `src/rule_engine/diagram_layout.py`): the generator still emitted `shape=mxgraph.gcp2.*` styles via `builtin_icon`, so re-running it would have overwritten the redrawn example back to the invalid pre-2025 stencils. Added a reusable `image_icon(image_path)` renderer to `diagram_layout` (file-path `image` shape, shared 78×78 footprint and label placement, for the file-path providers — GCP official icons and Azure azure2) and switched the GCP generator's `NODE_SPECS` to the official `gcp-core`/`gcp-category` SVG paths (Apigee for `api-gateway`). The generator now reproduces the committed `.drawio` byte-for-byte; verified all nine node styles match.
- **Azure golden example redrawn to azure2** (`examples/azure/01-azure-openai-rag.drawio`): the example previously used a third namespace (`mxgraph.mscae.cloud.*`) that matched neither the old nor the new mapping; all nine node styles now use the verified azure2 image shapes (User→`identity/Users.svg`, App Gateway→`networking/Application_Gateways.svg`, etc.), and its legend was made color-independent. PNG re-exported (see Changed).
- **Azure icons now resolve** (`mappings/azure-icons.yaml`): replaced the legacy `mxgraph.azure.*` stencil ids — only 3 of 9 (`virtual_network`, `sql_database`, `service_bus`) existed in that 2018-era library, so the other 6 (Subscription, Function Apps, Storage Accounts, Key Vaults, AKS, Cognitive/OpenAI) rendered as empty boxes (`icon-resolved` risk) — with the current draw.io **azure2** image shapes (`image=img/lib/azure2/<category>/<Name>.svg`). All nine verified against the draw.io sources (`Sidebar-Azure2.js`); `llm_platform` uses `Azure_OpenAI.svg`. Container styles unchanged.
- **OCI embedded glyph sizing** (`src/rule_engine/diagram_layout.py`): scale each embedded stencil by the glyph's **real bounding box** (measured from the drawn shape cells) instead of the stencil's declared width/height, which includes the baked-in caption. A long caption (e.g. "OCI Container Engine for Kubernetes", declared width 138) previously shrank the glyph under the fit, so `training-oke` rendered noticeably smaller than its siblings. All OCI icons now normalize to one standardized footprint.
- **Steering frontmatter regression** (`diagram-standards.md`): restored the `---` / `inclusion: always` / `---` YAML frontmatter that had been corrupted into a Markdown heading, so the always-on steering document is picked up by Kiro again.
- **Legend now provider-correct** (`diagram-standards.md`): the mandatory Legend no longer claims a fixed green/blue boundary color for all providers (only `generic` used those). Boundaries are distinguished by dashed outer-vs-inner nesting and labels, with stroke color following each Provider Profile's brand palette — consistent with the never-color-alone rule.
- **Azure/OCI stencil provenance** (`diagram-standards.md`): removed the hard-coded `mxgraph.mscae.*` claim; the doc now points to `mappings/<provider>-icons.yaml` as the authoritative stencil source and states that Azure/OCI use custom-imported libraries (`icon_source: custom`), not built-in ones.
- **North–South reference geometry** (`diagram-standards.md`): added explicit grid geometry for infrastructure/deployment (North–South) diagrams (lanes→rows, AZ peers side by side); noted that an infra golden example is still a gap.
- **Container-convention wording** (`provider-profiles.md`): the table now states that only AWS ships a vendor group shape; Azure/GCP/OCI/generic render boundaries as dashed rectangles in the profile brand color (per the mappings).

### Changed

- Regenerated all four golden-example PNG rasters (AWS, Azure, GCP, OCI) from their current `.drawio` sources with draw.io 31.4.5 (`--width 1200 --border 8 --theme light`), so every raster reflects the 1.1.0 font (11 → 12) and open-arrowhead edits plus the 1.2.0 icon fixes (AWS `group_vpc2`, azure2 image shapes, GCP category icons, OCI glyph sizing). Each export meets the Raster Export Dimensions budget (D7): 1200px wide, white background, 8px padding, and < 500KB (AWS 97KB, Azure 136KB, GCP 135KB, OCI 137KB — the OCI raster was also brought within the 1200px width budget from its earlier 3485px export). The GCP raster is exported via `scripts/export_raster.py` (base64-inlines its `assets/vendor` category icons), because the headless draw.io CLI cannot load those local files directly — an earlier direct export had rendered all nine GCP service icons as placeholder glyphs.

## [1.1.0] - 2026-09-22

Diagram routing quality, an official-asset icon fallback, the steering rules that codify both, and a diagram-rules review pass (REVIEW.md findings D1–D7): accessibility, a real geometry model, and layout-quality lint enforcement.

### Added

- **Asset-path guard** (`src/rule_engine/asset_paths_guard.py`, CLI `rule-engine-check-asset-paths`): verifies every mapping `image=<path>` icon style points at a file that exists under the fetched asset root, catching typos/renames before they render as empty boxes. Fetch-aware: hard-fails on a missing path when `assets/vendor` exists, skips (exit 0) when it does not. Wired into the CI `validate` stage after a `scripts/fetch_assets.py` fetch of the GCP/Azure packs. `data:` URIs, draw.io `img/lib` references, URLs, and `shape=` stencils are not checked. Also validates OCI `stencil: <manifest>#<slug>` references (the slug must be a key in the decoded `assets/vendor/oci-stencils/stencils.json`; skipped when that manifest is absent). Tests in `tests/test_asset_paths_guard.py`.
- **Asset Index & Icon Fallback** (`src/rule_engine/asset_index.py`, CLI `rule-engine-index-assets`): indexes the official provider icon packs (AWS, Azure, GCP SVG/PNG; OCI draw.io library) and resolves a specific service name to a built-in stencil, else an official SVG/PNG, else a fail-honest `unresolved`. This covers services with no built-in stencil yet — for example AWS DevOps / FinOps / Security agents — which now resolve to their official SVGs.
- New steering document `.kiro/steering/asset-packs.md`: official pack sources, per-provider layouts, and the built-in → official-asset → unresolved order.
- Diagram-standards additions: **Edge Routing** now requires grid-step-separated parallel runs (no shared corridors), no edge–node / edge–label crossings, and a **Container Padding** rule (≥ 1 grid step around child nodes).
- **Developer tooling & CI**: a GitHub Actions workflow (`.github/workflows/ci.yml`) running lint + validate + the full pytest suite (including the property-based tests) on a Python version matrix; a `.pre-commit-config.yaml` wiring `rule-engine-lint`, schema validation, and pytest; and a `CONTRIBUTING.md` with the dev setup, checks, and raster-regeneration steps. Runtime dependency floors are pinned in `pyproject.toml` and test tools moved to the `dev` extra.
- Edge Routing additions distilled from the AWS golden example: a **shared trunk with branches in opposite directions** for fan-out from one node (fewer crossings and corners than several near-parallel detours), and a **clean arrow start** convention (`exitPerimeter=0`, exit just past the source perimeter) so arrow stubs do not bite into the icon glyph.
- **Diagram geometry model** (`src/rule_engine/geometry.py`, REVIEW.md D3/D6): the CLI `.drawio` parser now builds absolute-coordinate node/container boxes and edge contact points/waypoints and attaches them to the linted artifact, so layout rules evaluate the real file instead of being prose-only.
- **Geometry-enforced lint rules** (all WARNING): `grid-alignment` (node origins are grid multiples, D2), `node-overlap` (no overlapping icon boxes), `arrow-style` (D5: flags filled/heavy arrowheads, unspecified heads that default to filled, and sub-1pt strokes), plus real implementations of `container-padding` and `edge-routing` — previously documented but never evaluated on a file. `edge-routing` is deliberately conservative (flags non-orthogonal edges and waypoint-free edges that run straight through an unrelated node; edges with explicit waypoints are treated as deliberately routed) to avoid false positives on validly routed diagrams. Regression tests in `tests/test_review_fixes.py` cover both the clean golden examples and firing cases.
- `min-font-size`** lint rule** (WARNING, REVIEW.md D1): flags any diagram whose parsed `fontSize=<n>` tokens fall below the 12px accessibility floor; the CLI parser harvests `font_sizes`. `flow-legend` advisory rule backs the numbered-flow legend.
- New steering section **Accessibility & Contrast** (REVIEW.md D1) in `.kiro/steering/diagram-standards.md`: 12px minimum font, ≥ 4.5:1 text/line contrast, defined white background, never-color-alone (double-encode), and line/arrow weight guidance. Documented as the `min-font-size` / `arrow-style` rules in `diagram-lint.md`.
- New steering section **Diagram Orientation** (REVIEW.md D4): picks the layout axis deterministically by diagram type — **North–South** (external/users at top, internal at bottom; East–West for AZ redundancy) for infrastructure/network/deployment, **left→right** for flow/application. The Lane Order is now axis-aware. Authoring guidance (not lint-enforced: node external/internal role is not inferable from geometry).
- New steering section **Raster Export Dimensions** (REVIEW.md D7): the exported `.drawio.png` budget — ≤ 1200px wide, legible at 700px, < 500KB, 72–96 DPI, white background, 8px padding — and directs oversize diagrams to be split. Authoring guidance (the linter checks source + companion, not the rendered PNG); a CI raster gate is the suggested enforcement point.
- Numbered flow markers on diagram edges with a right-side `Flow` legend, and an explicit edge-routing convention (orthogonal routing; entries left/top, exits right/bottom; distinct contact points when a node side carries more than one edge).
- `rule_engine.diagram_layout.MIN_FONT_SIZE` (= 12) and `EDGE_STROKE_WIDTH` (= 1.5) as the single numeric sources for label/text font size and edge stroke width.

### Changed

- Redrew the AWS, Azure, and GCP golden-example diagrams to remove line overlaps and edge–icon crossings: each fan-out edge now uses its own grid-aligned corridor with explicit waypoints, the right-side Flow/Legend blocks sit clear of the diagram body, and Network Boundary containers pad away from their child services.
- Corrected the AWS `managed_k8s` (Amazon EKS) icon id from `mxgraph.aws4.elastic_kubernetes_service` to the resolvable `mxgraph.aws4.eks`.
- **Accessibility (D1):** raised node-label and legend/text font size from 11 to 12 across the shared layout builder, all five `mappings/<provider>-icons.yaml` style strings, and the AWS/Azure/GCP/OCI golden-example `.drawio` sources, so every generated and reference diagram clears the 12px floor.
- **Arrow & line style (D5):** the shared builder now draws edges with an **open** arrowhead (`endArrow=open;endFill=0`) and a 1.5pt stroke (`EDGE_STROKE_WIDTH`); all four golden-example `.drawio` sources updated to match (33 edges).
- **Grid rhythm wording (D2):** Layout Geometry now states column step 220 and row step 160 as the reference rhythm, with the `grid-alignment` rule enforcing grid-multiple node origins (individual rows may differ but stay on the grid).

### Removed

- *None recorded for this release.*

## [1.0.0] - 2026-09-22

First public release of the Diagram & Inventory Rule Engine — a cloud-agnostic Kiro project that deterministically produces architecture diagrams and inventory documents across five provider profiles (`aws`, `azure`, `gcp`, `oci`, and a vendor-neutral `generic` fallback).

### Added

- Provider-neutral core components under `src/rule_engine/`: Linter, Icon Resolver, Inventory Collector, Normalizer, Delta Engine, schema validator, and version guard.
- Five always-on steering documents in `.kiro/steering/`: `diagram-standards.md`, `inventory-standards.md`, `provider-profiles.md`, `kb-frontmatter.md`, and the authoritative `diagram-lint.md` ruleset.
- Two console entry points: `rule-engine-lint` and `rule-engine-validate-schema`, wired into the `lint-on-save` / `validate-on-task` hooks and the CI pipeline.
- Per-provider icon/shape mapping files under `mappings/` and the Normalized Resource JSON Schema at `schemas/inventory.schema.json`.
- One golden example per provider under `examples/` (`aws`, `azure`, `gcp`, `oci`, `generic`) plus a cross-cloud C4 composition, each shipping the full artifact triple (`.drawio`/`.puml` source, exported `.png`, and `.diagram.md` companion document).
- Exported raster images (`.png`) for every golden example, generated locally the same way the CI build stage packages them.
- Numbered flow markers on diagram edges with a right-side `Flow` legend, and an explicit edge-routing convention (orthogonal routing; entries left/top, exits right/bottom; distinct contact points when a node side carries more than one edge). Two advisory WARNING lint rules back this up: `flow-legend` and `edge-routing`.
- `.github/FUNDING.yml` sponsorship configuration.

### Changed

- Rebuilt every golden-example diagram to the current diagram standards: resolvable provider stencils, numbered flow markers, orthogonal non-overlapping edge routing, and a right-side Flow legend. Set the reference date across all examples and the add-a-provider runbook to `2026-09-22`.
- Extended `diagram-standards.md` (Numbered Flow Legend, Edge Routing) and `diagram-lint.md` (the `flow-legend` and `edge-routing` rules).

