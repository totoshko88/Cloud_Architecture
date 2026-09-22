# Requirements Document

## Introduction

This document specifies the requirements for a reusable, cloud-agnostic **Diagram & Inventory Rule Engine**, packaged as a Kiro project (steering documents + spec + reference artifacts). The Rule Engine codifies how AI agents deterministically produce two classes of output for multi-cloud environments:

1. **Architecture diagrams** — draw.io `.drawio` files plus PlantUML or Mermaid source, each paired with a human-readable companion document.
2. **Inventory documents** — a read-only resource snapshot that is normalized, compared against a previous snapshot to compute a delta, and rendered as a versioned Markdown document.

The Rule Engine supports five provider profiles: `aws`, `azure`, `gcp`, `oci`, and a vendor-neutral `generic` profile. The engine abstracts provider-specific rules into a provider-neutral core plus per-provider profiles, defines canonical icon and shape mappings per provider, standardizes a multi-cloud inventory schema, and is consumable by Kiro Quick assistants and an AgentCore arch-assistant.

All requirements follow EARS notation and the Absolute Context principle: no pronouns, no relative time expressions, and every entity is named explicitly. Every acceptance criterion is written so that a linter or a human reviewer can assign a pass or fail verdict.

## Glossary

- **Rule Engine**: The complete packaged Kiro project that codifies diagram generation, inventory collection, normalization, delta computation, versioning, and quality gates across the five provider profiles.
- **Provider**: A member of the enumeration `aws | azure | gcp | oci | generic`.
- **Provider Profile**: The provider-specific configuration set consumed by the Rule Engine, containing terminology mappings, icon mappings, container conventions, brand color palette, and inventory verbs for one Provider.
- **Diagram Generator**: The Rule Engine component that produces `.drawio` files, PlantUML source, Mermaid source, and companion documents.
- **Icon Resolver**: The Rule Engine component that maps a Normalized Resource Type to a Provider-specific draw.io style string and brand color.
- **Inventory Collector**: The Rule Engine component that executes read-only enumeration and produces a Snapshot.
- **Normalizer**: The Rule Engine component that transforms native provider resources into Normalized Resources conforming to the Inventory Schema.
- **Delta Engine**: The Rule Engine component that compares two Snapshots and classifies each resource as added, changed, removed, or unchanged.
- **Linter**: The Rule Engine component that evaluates diagrams and documents against the lint ruleset defined in `diagram-lint.md`.
- **Normalized Resource Type**: A vendor-neutral resource category (for example `object_store`, `serverless_fn`, `managed_sql`).
- **Normalized Resource**: A single resource represented in the neutral schema with fields `provider`, `resource_type`, `native_type`, `id`, `name`, `boundary`, `region`, `tags`, `config_digest`.
- **Inventory Schema**: The JSON Schema at `schemas/inventory.schema.json` that defines the structure of a Normalized Resource.
- **Snapshot**: A dated, read-only folder capturing enumerated resources for one Provider, boundary, and region set at one point in time.
- **Manifest**: The `00-MANIFEST.md` file at the root of a Snapshot folder recording provenance and usage instructions.
- **Boundary**: The top organizational container for a Provider (AWS Account, Azure Subscription, GCP Project, OCI Tenancy or Compartment, or generic Environment).
- **Network Boundary**: The provider network container (AWS VPC, Azure VNet, GCP VPC, OCI VCN, or generic Network).
- **Companion Document**: The `NN-topic.diagram.md` Markdown file that accompanies each `.drawio` diagram and describes shown elements, flows, and delta from the previous version.
- **Legend**: The mandatory diagram block that defines line styles, colors, and change markers.
- **Change Marker**: A symbol denoting a delta classification — 🆕 for added in version N, 🔄 for changed in version N, red styling for removed or blocked.
- **Config Digest**: A deterministic hash of a resource configuration used to detect configuration changes between Snapshots.
- **Frontmatter**: The YAML metadata block at the top of every Markdown document produced by the Rule Engine.
- **Golden Example**: A reference artifact under `examples/` that passes every ERROR-level and CRITICAL-level lint rule.
- **Arch-Assistant**: A Kiro Quick assistant or AgentCore assistant that invokes the Rule Engine contract to produce diagrams and inventory documents.
- **CI Pipeline**: The automated continuous-integration workflow that lints artifacts, validates schemas, packages a Release Bundle, and generates a Changelog.
- **Release Bundle**: The packaged, versioned archive containing the steering documents, mapping files, Inventory Schema, examples, and runbook, produced by the CI Pipeline for distribution.
- **Changelog**: The `CHANGELOG.md` document that records, per released version, the added, changed, and removed items in reverse chronological order.
- **Semantic Version**: A version identifier of the form `MAJOR.MINOR.PATCH` as defined by Semantic Versioning 2.0.0.
- **README**: The `README.md` document at the Rule Engine root describing purpose, contents, quick start, and links to steering documents and the installation guide.
- **Installation Guide**: The `INSTALL.md` document describing the prerequisites and the ordered steps to install and activate the Rule Engine in a Kiro workspace.
- **Hook**: A Kiro automation defined under `.kiro/hooks/` that runs a command or agent action on a session event.
- **Correctness Property**: An executable, universally-quantified statement derived from an acceptance criterion that a property-based test validates across generated inputs.
- **Property-Based Test**: A test that validates a Correctness Property by generating many inputs and asserting the property holds for every generated input.

## Requirements

### Requirement 1: Diagram Generation

**User Story:** As a cloud architect, I want the Rule Engine to generate architecture diagrams under deterministic rules, so that every diagram is consistent, readable, and render-target appropriate regardless of author.

#### Acceptance Criteria

1. WHERE a diagram is a C4, architecture, component, or deployment diagram, THE Diagram Generator SHALL produce the diagram source in PlantUML.
2. WHERE a diagram is a sequence, flow, or state diagram AND the render target is GitLab Markdown or Backstage TechDocs, THE Diagram Generator SHALL be permitted to produce the diagram source in Mermaid.
3. IF a diagram is a sequence, flow, or state diagram AND the render target is neither GitLab Markdown nor Backstage TechDocs, THEN THE Diagram Generator SHALL produce the diagram source in PlantUML.
4. THE Diagram Generator SHALL limit each diagram to a maximum of 12 nodes.
5. WHEN a system contains more than 12 nodes, THE Diagram Generator SHALL split the system into multiple diagrams where each diagram contains at most 12 nodes and SHALL produce one index document that references every split diagram.
6. WHERE a node name contains a space character or any character outside the set of ASCII letters, ASCII digits, hyphen, and underscore, THE Diagram Generator SHALL enclose the node name in double quotes.
7. THE Diagram Generator SHALL attach a non-empty descriptive text label to every edge.
8. WHERE a diagram includes a raster image, THE Diagram Generator SHALL provide non-empty alt text describing the raster image content.
9. THE Diagram Generator SHALL restrict PlantUML source to syntax delimited by a single `@startuml` and a single `@enduml` pair and SHALL exclude every preprocessor directive.
10. THE Diagram Generator SHALL produce, for each `.drawio` diagram named `NN-topic.drawio`, an exported raster file named `NN-topic.drawio.png` and a Companion Document named `NN-topic.diagram.md`.
11. THE Diagram Generator SHALL arrange diagram lanes left to right in the order actors, edge, router, asynchronous messaging, workers, platform core, data, on-premises.
12. IF the Diagram Generator cannot produce a required output file for a diagram, THEN THE Diagram Generator SHALL return a generation error identifying the diagram and the missing output file and SHALL exclude any partial diagram from publication.

### Requirement 2: Icon Resolution

**User Story:** As a diagram author, I want the Rule Engine to resolve a neutral resource type into the correct provider icon and brand color, so that diagrams use official assets deterministically and never fall back to placeholders.

#### Acceptance Criteria

1. WHEN the Icon Resolver receives a Normalized Resource Type and a Provider, THE Icon Resolver SHALL return a provider-specific draw.io style string and a brand color value within 200 milliseconds.
2. WHEN the Icon Resolver returns a brand color value, THE Icon Resolver SHALL format it as a six-digit hexadecimal color prefixed with a single `#` character.
3. WHERE the Provider is `aws`, THE Icon Resolver SHALL return a style string using the AWS 2019-or-later shape library in the form `shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.<service>`.
4. WHERE the Provider is `aws`, THE Icon Resolver SHALL return container group styles using `shape=mxgraph.aws4.group` with the group icons `group_aws_cloud_alt` for Cloud, `group_account` for Account, `group_on_premise` for on-premises, and a VPC group for the Network Boundary.
5. WHERE the Provider is `azure`, `gcp`, or `oci`, THE Icon Resolver SHALL return a style string and SHALL indicate the icon reference source as exactly one of two values: a custom draw.io shape library imported from unpacked assets, or a built-in library.
6. THE Icon Resolver SHALL return exactly one concrete container group style for each Provider corresponding to that Provider's Boundary, and exactly one concrete container group style corresponding to that Provider's Network Boundary.
7. WHERE the Provider is `generic`, THE Icon Resolver SHALL return only plain rectangle shapes or UML shapes, SHALL restrict fill and stroke colors to grayscale values ranging from white to black, and SHALL exclude all vendor icons.
8. IF the Icon Resolver cannot resolve a Normalized Resource Type for a Provider, THEN THE Icon Resolver SHALL return an unresolved-type error indicating the unresolved Normalized Resource Type and Provider, SHALL exclude any placeholder icon and any style string from the output, and SHALL leave the input unchanged.
9. THE Icon Resolver SHALL source every icon identifier and brand color from the authoritative asset pack declared for the corresponding Provider Profile.
10. IF the authoritative asset pack declared for the corresponding Provider Profile is missing or cannot be read, THEN THE Icon Resolver SHALL return an asset-source error indicating the affected Provider Profile, SHALL exclude any icon identifier, brand color, and placeholder icon from the output, and SHALL leave the input unchanged.

### Requirement 3: Inventory Collection

**User Story:** As a platform engineer, I want the Rule Engine to collect a read-only inventory snapshot per provider, so that account state is never mutated and no secret values are exposed.

#### Acceptance Criteria

1. THE Inventory Collector SHALL execute only read-only enumeration verbs that are explicitly listed in the corresponding Provider Profile.
2. IF a verb is not present in the read-only enumeration list of the corresponding Provider Profile, THEN THE Inventory Collector SHALL NOT execute that verb.
3. THE Inventory Collector SHALL exclude every verb that creates, updates, or deletes provider state such that the count of executed state-mutating verbs per collection run equals zero.
4. WHEN the Inventory Collector produces a Snapshot, THE Inventory Collector SHALL write the Snapshot to a folder named `inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>`, where `<YYYY-MM-DD_HHMM>` is the UTC collection start timestamp.
5. WHEN the Inventory Collector creates a Snapshot folder, THE Inventory Collector SHALL write a Manifest named `00-MANIFEST.md` at the root of that Snapshot folder.
6. THE Manifest SHALL record all of the following fields as non-empty values: the Provider, the Boundary identifier, the region set, the caller identity, the tool versions, the total file count of the Snapshot folder, and the delta instructions for the next session.
7. WHEN the Inventory Collector writes Snapshot content, THE Inventory Collector SHALL write exactly one JSON file per service domain and SHALL create one per-resource subfolder per enumerated resource within the Snapshot folder.
8. THE Inventory Collector SHALL record resource metadata only and SHALL exclude secret values, key material, and SecureString values from every Snapshot file such that no Snapshot file contains any such value.
9. IF enumeration of a single service fails, THEN THE Inventory Collector SHALL record the failure with an entry indicating the failed service and the failure reason, and SHALL continue enumeration of the remaining services without terminating the collection run.
10. WHERE cost or billing data is collected, THE Inventory Collector SHALL use only the provider-specific cost endpoint declared in the corresponding Provider Profile.

### Requirement 4: Normalization

**User Story:** As a multi-cloud analyst, I want resources from any provider normalized into one comparable schema, so that snapshots from different providers can be compared with a single model.

#### Acceptance Criteria

1. WHEN the Normalizer processes a native provider resource, THE Normalizer SHALL produce a Normalized Resource conforming to the Inventory Schema.
2. THE Normalizer SHALL populate the fields `provider`, `resource_type`, `native_type`, `id`, `name`, `boundary`, `region`, `tags`, and `config_digest` for every Normalized Resource.
3. THE Normalizer SHALL set the `resource_type` field to a Normalized Resource Type defined in the terminology normalization table of the Rule Engine.
4. THE Normalizer SHALL compute the `config_digest` field as a deterministic hash of the resource configuration such that two resources with equivalent configurations, independent of key or element ordering, produce identical digests.
5. IF a native provider resource has no defined Normalized Resource Type mapping, THEN THE Normalizer SHALL record an unmapped-type error and SHALL exclude the unmapped resource from the normalized output.
6. IF a native provider resource lacks a value required to populate a mandatory Inventory Schema field, THEN THE Normalizer SHALL record a missing-field error identifying the resource and the missing field and SHALL exclude the resource from the normalized output.
7. IF a produced Normalized Resource fails Inventory Schema validation, THEN THE Normalizer SHALL record a schema-validation error identifying the resource and the failing constraint and SHALL exclude the resource from the normalized output.
8. THE Inventory Schema SHALL validate a sample Normalized Resource produced from each of the Providers `aws`, `azure`, `gcp`, and `oci`.

### Requirement 5: Delta and Versioning

**User Story:** As a documentation owner, I want the Rule Engine to compute the delta between two snapshots and version the output, so that each document and diagram accurately reflects changes since the prior version using absolute dates.

#### Acceptance Criteria

1. WHEN the Delta Engine compares a current Snapshot against a previous Snapshot, THE Delta Engine SHALL match Normalized Resources on the tuple of `provider`, `resource_type`, and identity, where identity is `id` when `id` is present and `name` otherwise.
2. WHEN a Normalized Resource exists in the current Snapshot and is absent from the previous Snapshot, THE Delta Engine SHALL classify the Normalized Resource as added and SHALL mark the Normalized Resource with 🆕.
3. WHEN a Normalized Resource exists in both Snapshots AND the `config_digest` values differ, THE Delta Engine SHALL classify the Normalized Resource as changed and SHALL mark the Normalized Resource with 🔄.
4. WHEN a Normalized Resource exists in the previous Snapshot and is absent from the current Snapshot, THE Delta Engine SHALL classify the Normalized Resource as removed and SHALL mark the Normalized Resource with red styling.
5. WHEN a Normalized Resource exists in both Snapshots AND the `config_digest` values are equal, THE Delta Engine SHALL classify the Normalized Resource as unchanged.
6. WHEN no previous Snapshot is supplied, THE Delta Engine SHALL classify every Normalized Resource in the current Snapshot as added.
7. IF a supplied Snapshot is missing or malformed, THEN THE Delta Engine SHALL return a snapshot-input error identifying the affected Snapshot and SHALL produce no delta classification.
8. THE Delta Engine SHALL supply the delta classification to both the versioned Markdown document and the diagram Change Markers.
9. THE Diagram Generator SHALL encode in every diagram title cell the value `<provider> <workload> — <boundary id> / <region> | <date> | vN`, where `<date>` is an ISO 8601 date (YYYY-MM-DD) and `vN` is a version identifier consisting of the letter `v` followed by a positive integer.
10. THE Diagram Generator SHALL express every Change Marker description using an ISO 8601 calendar date (YYYY-MM-DD) and SHALL exclude relative time expressions.
11. THE Diagram Generator SHALL include a Legend that defines a solid line as primary flow, a dashed line as asynchronous or event-driven flow, red as blocked or missing or disabled, 🆕 as new in version N, 🔄 as changed in version N, a dashed green boundary as the stack boundary, and a dashed blue boundary as the Network Boundary.

### Requirement 6: Multi-cloud Composition

**User Story:** As a solutions architect, I want the Rule Engine to represent architectures spanning multiple providers, so that cross-cloud data flows are documented in a single coherent diagram.

#### Acceptance Criteria

1. WHERE an architecture spans more than one Provider, THE Diagram Generator SHALL represent each Provider using the icon and color conventions of the corresponding Provider Profile.
2. WHERE a cross-cloud diagram is produced, THE Diagram Generator SHALL limit the diagram to a maximum of 12 nodes.
3. THE Diagram Generator SHALL produce a C4 container diagram for a cross-cloud composition that names each Provider and labels every cross-provider edge with the data flow that the edge represents.
4. THE Diagram Generator SHALL render every Boundary and Network Boundary of each Provider in a cross-cloud diagram using the container group style of the corresponding Provider Profile.
5. IF a Provider Profile referenced by a cross-cloud diagram declares no container group style for its Boundary or Network Boundary, THEN THE Diagram Generator SHALL return a profile-convention error identifying the affected Provider and boundary and SHALL exclude the incomplete diagram from publication.

### Requirement 7: Quality Gates

**User Story:** As a reviewer, I want the Rule Engine to enforce lint rules with defined severities, so that every diagram and document meets the standard before publication.

#### Acceptance Criteria

1. THE Linter SHALL evaluate every diagram and document against the lint ruleset defined in `diagram-lint.md` and SHALL assign each finding a severity of CRITICAL, ERROR, or WARNING.
2. WHEN the Linter completes evaluation of a diagram or document with zero CRITICAL findings and zero ERROR findings, THE Linter SHALL report the diagram or document as eligible for publication.
3. WHEN the Linter completes evaluation of a diagram or document with at least one CRITICAL finding or at least one ERROR finding, THE Linter SHALL report the diagram or document as blocked from publication.
4. IF a diagram contains more than 12 nodes, THEN THE Linter SHALL report an ERROR finding.
5. IF a diagram edge has no non-empty label, THEN THE Linter SHALL report a WARNING finding.
6. IF a node name contains a space character or any character outside the set of ASCII letters, ASCII digits, hyphen, and underscore AND the node name is not enclosed in double quotes, THEN THE Linter SHALL report an ERROR finding.
7. IF a diagram has no Legend, THEN THE Linter SHALL report an ERROR finding.
8. IF a `.drawio` file has no matching `.diagram.md` Companion Document, THEN THE Linter SHALL report an ERROR finding.
9. IF a Markdown document is missing any required Frontmatter key or contains a required Frontmatter key with an empty value, THEN THE Linter SHALL report a CRITICAL finding.
10. IF an icon in a diagram is an unresolved placeholder rather than a resolved provider icon, THEN THE Linter SHALL report an ERROR finding.
11. IF a Snapshot file contains a secret value, key material, or a SecureString value, THEN THE Linter SHALL report a CRITICAL finding.
12. IF a diagram title cell has no version identifier or no date, THEN THE Linter SHALL report a WARNING finding.
13. IF a Mermaid diagram represents a diagram type other than sequence, flow, or state, THEN THE Linter SHALL report a WARNING finding.
14. IF the lint ruleset defined in `diagram-lint.md` is missing or cannot be read, THEN THE Linter SHALL return a ruleset-unavailable error and SHALL report every evaluated diagram and document as blocked from publication.

### Requirement 8: Document Frontmatter and Formatting

**User Story:** As a knowledge base maintainer, I want every generated Markdown document to carry complete frontmatter and follow formatting rules, so that the retrieval system indexes the document and readers navigate consistent structure.

#### Acceptance Criteria

1. THE Diagram Generator SHALL begin every Markdown document with YAML Frontmatter containing the keys `id`, `title`, `kb_namespace`, `section`, `category`, `status`, `updated`, `owner`, `author`, `next_review_date`, `tags`, and `related_docs`, where `updated` and `next_review_date` are ISO 8601 dates (YYYY-MM-DD), `status` is one of `draft`, `review`, or `published`, `tags` contains between 1 and 20 entries, and `related_docs` contains between 0 and 20 entries.
2. THE Diagram Generator SHALL constrain each Markdown document to a length between 300 and 2000 words inclusive.
3. THE Diagram Generator SHALL constrain each of the required sections Overview, Main Content, Troubleshooting, and See Also to a length between 100 and 200 words inclusive.
4. THE Diagram Generator SHALL include exactly one H1 heading in every Markdown document.
5. THE Diagram Generator SHALL constrain list nesting to a maximum of two levels.
6. THE Diagram Generator SHALL constrain each table to a maximum of five columns and SHALL exclude merged cells.
7. THE Diagram Generator SHALL include the sections Overview, Main Content, Troubleshooting, and See Also in every Markdown document.
8. WHERE a Markdown document contains at least one fenced code block, THE Diagram Generator SHALL include an Anti-patterns section in the document.
9. IF any required Frontmatter key from Criterion 1 is absent, empty, or has a value outside its specified format, enumeration, or bound, THEN THE Diagram Generator SHALL reject the document, SHALL NOT emit it to the knowledge base, and SHALL produce an error indication naming the offending key.
10. IF a generated document violates any constraint in Criteria 2 through 8, THEN THE Diagram Generator SHALL reject the document, SHALL NOT emit it to the knowledge base, and SHALL produce an error indication naming the violated constraint.
11. WHEN a generated document satisfies all constraints in Criteria 1 through 8, THE Diagram Generator SHALL emit the document to the knowledge base.

### Requirement 9: Reusability and Extensibility

**User Story:** As a Kiro project owner, I want the Rule Engine packaged for reuse and easy extension, so that assistants consume the standards and new providers are added through a defined runbook.

#### Acceptance Criteria

1. THE Rule Engine SHALL provide the steering documents `diagram-standards.md`, `inventory-standards.md`, `provider-profiles.md`, `kb-frontmatter.md`, and `diagram-lint.md` under `.kiro/steering/`.
2. THE Rule Engine SHALL provide the spec documents `requirements.md`, `design.md`, and `tasks.md` under `.kiro/specs/multicloud-diagram-inventory/`.
3. THE Rule Engine SHALL provide a mapping file `mappings/<provider>-icons.yaml` for each of the Providers `aws`, `azure`, `gcp`, `oci`, and `generic`.
4. THE Rule Engine SHALL provide the Inventory Schema at `schemas/inventory.schema.json` and exactly one Golden Example under `examples/` for each of the Providers `aws`, `azure`, `gcp`, `oci`, and `generic`.
5. THE Rule Engine SHALL provide a spec template under `.kiro/specs/_template/` that contains the files `requirements.md`, `design.md`, and `tasks.md` for an Arch-Assistant to copy when creating a new spec.
6. WHEN an Arch-Assistant invokes the Rule Engine contract with all of the inputs `provider`, `boundary_id`, `region`, `previous_doc_path`, and `inventory_snapshot_path` supplied, THE Rule Engine SHALL accept the invocation.
7. IF an Arch-Assistant invokes the Rule Engine contract with any of the required inputs `provider`, `boundary_id`, `region`, `previous_doc_path`, or `inventory_snapshot_path` missing, or with an unrecognized `provider` value outside `aws`, `azure`, `gcp`, `oci`, and `generic`, THEN THE Rule Engine SHALL reject the invocation, produce no output documents, and return an error indication identifying the missing or invalid input.
8. WHEN an Arch-Assistant invokes the Rule Engine contract with valid inputs, THE Rule Engine SHALL produce the outputs `.drawio`, `.drawio.png`, `.diagram.md`, and a versioned `NN-existing-infrastructure.md` document, where `NN` is a two-digit zero-padded sequence number in the range `01` to `99` and the document contains Frontmatter.
9. THE Rule Engine SHALL provide an "add a new provider" runbook that enumerates, as discrete ordered steps, adding a Provider Profile row, adding an icon mapping, adding inventory verbs, adding a Golden Example, and completing a lint run that reports zero lint violations.
10. THE Rule Engine SHALL define every Provider Profile with a terminology normalization row for each of the nine terms Boundary, Network Boundary, serverless function, object store, managed SQL, message queue, secrets store, managed Kubernetes, and LLM platform.

### Requirement 10: Distribution, Documentation, and CI/CD

**User Story:** As a Rule Engine maintainer, I want the project to build, version, package, and document itself through an automated pipeline, so that every release is reproducible, traceable, and installable by any consumer.

#### Acceptance Criteria

1. THE Rule Engine SHALL provide a CI Pipeline definition stored under version control in the repository.
2. WHEN the CI Pipeline runs, THE CI Pipeline SHALL execute the Linter against every diagram and Markdown document and SHALL validate every `mappings/<provider>-icons.yaml` file and the Inventory Schema.
3. IF the Linter reports at least one CRITICAL finding or at least one ERROR finding during a CI Pipeline run, THEN THE CI Pipeline SHALL fail the run and SHALL produce no Release Bundle.
4. WHEN the CI Pipeline runs on a release trigger, THE CI Pipeline SHALL package a Release Bundle containing the steering documents, the mapping files, the Inventory Schema, the examples, and the "add a new provider" runbook.
5. THE CI Pipeline SHALL name every Release Bundle using a Semantic Version identifier.
6. WHEN the CI Pipeline produces a release, THE CI Pipeline SHALL generate or update a Changelog that records the added, changed, and removed items for the released Semantic Version in reverse chronological order.
7. IF a release trigger specifies a Semantic Version that already exists in the Changelog, THEN THE CI Pipeline SHALL fail the run and SHALL produce no Release Bundle.
8. THE Rule Engine SHALL provide a README at the repository root that describes the purpose, the contents, a quick start, and links to the steering documents and the Installation Guide.
9. THE Rule Engine SHALL provide an Installation Guide that enumerates the prerequisites and the ordered steps to install and activate the Rule Engine in a Kiro workspace.
10. WHEN the CI Pipeline completes a successful release run, THE CI Pipeline SHALL publish the Release Bundle and the updated Changelog as release artifacts.

### Requirement 11: Kiro Automation and Correctness

**User Story:** As a Kiro project owner, I want the Rule Engine to leverage steering documents, hooks, and property-based tests, so that the standards are always applied, quality checks run automatically, and critical requirements are validated against generated inputs.

#### Acceptance Criteria

1. THE Rule Engine SHALL provide every steering document under `.kiro/steering/` with a configuration that includes the steering document in every agent turn within the workspace.
2. THE Rule Engine SHALL provide a Hook under `.kiro/hooks/` that runs the Linter when an agent saves or edits a `.drawio` file or a Markdown document.
3. THE Rule Engine SHALL provide a Hook under `.kiro/hooks/` that runs the Linter and the schema validation after a spec task is completed.
4. WHEN a Hook action fails with a blocking result, THE Rule Engine SHALL surface the failure reason to the agent session.
5. THE Rule Engine SHALL derive at least one Correctness Property from each of the acceptance criteria governing the Icon Resolver, the Normalizer, and the Delta Engine.
6. WHEN a Property-Based Test executes a Correctness Property, THE Property-Based Test SHALL generate multiple distinct inputs and SHALL assert the Correctness Property holds for every generated input.
7. IF a Property-Based Test discovers an input for which a Correctness Property does not hold, THEN THE Property-Based Test SHALL report the failing input.
8. THE Rule Engine SHALL define every Correctness Property so that the Correctness Property is traceable to the acceptance criterion from which the Correctness Property is derived.
