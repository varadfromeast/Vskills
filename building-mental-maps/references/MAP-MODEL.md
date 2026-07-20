# Canonical map model

Read this before editing any atlas. Markdown notes and ordinary wikilinks are
the source model. Canvas, Bases, Mermaid, and Graph are views over it.

The map must stand on its own for ordinary architecture orientation. A reader
should not need source code to learn the system's purpose, domain boundary,
logical responsibilities, interfaces, state rules, runtime outcomes,
deployment shape, policies, important decisions, quality posture, risks, or
likely change impact. Code, tests, configuration, and decisions are evidence
for those claims, not substitutes for them.

## Contents

- [Operational definitions](#operational-definitions)
- [Native project shape](#native-project-shape)
- [Atlas checkpoint](#atlas-checkpoint)
- [Entry-point inventory](#entry-point-inventory)
- [Block notes](#block-notes)
- [Concrete anchors](#concrete-anchors)
- [Ownership](#ownership)
- [Relationships](#relationships)
- [Coverage note](#coverage-note)
- [Lifecycle](#lifecycle)
- [Validate version 2](#validate-version-2)

## Operational definitions

Use these meanings wherever the skill or its references use the terms:

- **Trusted map/checkpoint:** a version 2 map whose
  `sync_map_state.py status` result has both `trusted: true` and
  `comparisonAvailable: true`. This means the state sidecar is valid and its
  repository identity, coverage contract, and inventory strategy match the
  active target. A fresh validation receipt is still required before writing a
  new checkpoint.
- **Coherent legacy map:** a map with `map-version` absent or set to `1` whose
  atlas, Blocks Index, canonical block notes, and links pass the bundled
  validator without version 2 receipt or coverage flags. A validator error
  makes the map incomplete or inconsistent rather than coherent.
- **Maintained first-party file:** a tracked or non-ignored untracked inventory
  path whose runtime, configuration, build, migration, script, or
  operational behavior is authored or maintained by the project. Treat an
  ambiguous path as maintained until the coverage note explicitly excludes it
  with a current reason. Test code, fixtures, snapshots, and test-only
  configuration are maintained evidence but remain outside atlas ownership.
- **Significant relationship:** a cross-block dependency whose omission would
  cause a reader to misjudge a consumer-visible contract, state or invariant,
  critical runtime or failure journey, deployment boundary, policy, or likely
  change impact. Incidental utility, vocabulary, and implementation-detail
  dependencies are `detail-only`.
- **Entry-point family:** public APIs, commands, jobs, workers, event consumers,
  callbacks, hooks, or library entry points that share one trigger-to-outcome
  contract and the same material handoffs and failure behavior. Split families
  when initiator, trigger, execution mode, main effect, state transition,
  asynchronous boundary, or architecture-relevant failure/recovery differs.
- **Semantic no-op:** an inspected implementation delta that changes no
  canonical responsibility, interface, state or invariant, runtime behavior,
  deployment, policy, risk, relationship, ownership footprint, anchor, status,
  lifecycle, or projection. Record the inspected paths and owners, validate,
  and advance the implementation checkpoint without rewriting model artifacts.

## Native project shape

Create new maps as version 2:

```text
<Project Map>/
├── <Project> Atlas.md
├── <Project> Atlas.canvas
├── <Project> Blocks.base
├── <Project> Code Coverage.md
├── .mental-map-state.json
├── .mental-map-validation.json
├── Blocks/
│   └── <Block Name>.md
├── Views/
│   ├── <Project> All Relationships.canvas
│   └── <Scoped Architecture>.canvas
└── Flows/
    └── <Question-shaped Journey>.md
```

Always create `Views/<Project> All Relationships.canvas` as a separately spaced
exhaustive projection of every implemented relationship. Omit `Flows/` only
when the map needs no artifact of that kind. The compact atlas remains the
front door; focused Mermaid flows remain the preferred way to explain dense or
ordered slices.

Preflight the map before mutation. If it is coherent but not version 2, inspect
it read-only and explain the migration boundary; do not write, validate as
version 2, or checkpoint until the user explicitly approves migration. Canvas
file paths are vault-relative, not map-relative. The two hidden JSON files are
machine sidecars, not canonical model content and remain outside repository
coverage.

The Canvas is the visual entrance. The atlas note supplies purpose, reading
order, coverage summary, unresolved questions, and ordinary links to the
Canvas, Base, coverage note, scoped views, and flows. The Base replaces a
hand-maintained blocks index for version 2 maps.

Keep the atlas note short but independently useful:

```md
# Project Atlas

Purpose: Who the system serves and the outcome it creates.

Domain boundary: What belongs inside the system and what remains external.

Quality priorities: The two or three qualities that shape the architecture.

Current risks: Material uncertainty, constraint, or failure exposure.

Coverage summary: What the Include/Exclude boundary covers and deliberately omits.

Mapped target: HEAD

Unresolved questions: Material unknowns, or `None` after they are genuinely resolved.

Start here: [[Project Atlas.canvas]] · [[Critical Success Journey]] ·
[[Critical Failure Journey]] · [[Project Blocks.base]] ·
[[Project Code Coverage]]

## Entry-point families

| Family | Representative anchor | Focused view | No-view reason |
| --- | --- | --- | --- |
| Request submission | `src/api/submit.ts :: submitRequest` | [[Engineering/Project Map/Flows/How Does A Request Complete.md]] | |
| Value parsing API | `src/parser.ts :: parseValue` | | Pure synchronous transformation has no architectural ordering, handoff, state transition, or recovery. |

## Canvas semantic groups

| Group | Scope key | Question | Members |
| --- | --- | --- | --- |
| Request control plane | request-control | How is accepted work coordinated to completion? | [[Request Admission]] · [[Work Coordination]] · [[Run State]] |
| Execution boundary | execution | Where does coordinated work cross into local execution? | [[Worker Supervision]] · [[Terminal Execution]] |

## Needs review

![[Project Blocks.base#Needs review]]
```

In a real nested map, make these wikilinks exact vault-relative paths. Atlas
frontmatter artifact fields remain map-relative paths.

Link decisions, deployment views, policy views, and change-impact paths when
they materially affect how the system is understood or changed.

## Atlas checkpoint

Use:

```yaml
---
type: mental-map-atlas
map-version: 2
project: Project Name
mapping-mode: codebase-atlas
revision: <full HEAD SHA>
canvas: Project Atlas.canvas
relationships-canvas: Views/Project All Relationships.canvas
base: Project Blocks.base
sync-state: .mental-map-state.json
---
```

Always set `relationships-canvas` to a separate all-relationships Canvas and
link that Canvas from the atlas note.

Keep `revision` as an exact commit SHA. The sync-state sidecar records the exact
tree, dirty snapshot, coverage contract, and file manifest. `mapping-mode` is
`codebase-atlas` or `change-map` and describes the latest implemented mapping
run. Planning-only edits do not change the implementation checkpoint.

Keep the atlas's human-readable `Mapped target:` line synchronized with the
active checkout:

- `Mapped target: HEAD` when no staged, unstaged, deleted, or non-ignored
  untracked path exists;
- `Mapped target: HEAD + dirty paths` when any such path exists.

The validator requires the exact matching value. `revision` deliberately stays
at the full `HEAD` commit in both cases; the state and validation sidecars bind
the exact dirty snapshot.

## Entry-point inventory

Keep exactly one `## Entry-point families` table in the atlas using the four
headers shown above. Inventory every public or independently runnable family
before accepting responsibility boundaries. Each row requires:

- a unique family name in domain language;
- one representative current `path` or `path :: symbol` anchor;
- exactly one unaliased whole-note wikilink to a focused view, or one specific
  no-view reason; and
- for a focused view, `type: mental-map-view`, `view: journey` or
  `view: contract`, and an `entry-point-family` frontmatter value exactly equal
  to the inventory family name.

Use a `journey` when order, asynchronous handoffs, state transitions, failure,
retry, or recovery matter. Use a `contract` flowchart when static providers,
consumers, ownership, or data movement are the architectural point. Give each
inventory row its own focused view; pair success and failure diagrams inside
that note or link companion views from it. Do not reuse one broad view for
several rows.

Use a no-view reason only when canonical block contracts fully explain a family
with no meaningful ordering, handoff, state transition, or failure topology.
State that reason concretely; “simple,” “covered elsewhere,” “none,” or a desire
to reduce view count is not sufficient. Keep table cells on one line and avoid
`|` characters or aliased wikilinks inside them.

The validator proves that each declared row has a current anchor and exactly
one valid view or waiver. Repository inspection remains responsible for proving
that no public or runnable family was omitted from the inventory.

## Canvas semantic-group contract

Keep exactly one `## Canvas semantic groups` table in every version 2 atlas,
using `Group | Scope key | Question | Members`. This table is the semantic
source for both required Canvases; Canvas rectangles are its rendering, not an
independent classification.

Each row requires a domain-language group name, a unique stable lowercase
dot-or-hyphen scope key, a question that explains why the members cohere, and
one or more canonical block wikilinks. Every implemented root, context, and
runtime block must appear on the compact Canvas. Deeper child responsibilities
and planned topology may stay in scoped views. Every compact canonical card
must occur in exactly one group row, and every declared member must have a
compact file-backed card.

Render each row as one JSON Canvas `group` node with id
`mental-map:group:<scope-key>` and an exact matching `label`. Put group nodes
before their cards in the Canvas `nodes` array, fully contain every member card,
and keep group rectangles disjoint. Canonical Canvas relationships must give
every implemented card a place in the orientation backbone and weakly connect
all groups containing implemented cards. A clearly labelled planned-only group
may preview future cards without inventing current edges. Mermaid, a scoped
Canvas, or an all-relationships Canvas may add detail, but none can substitute
for implemented front-door topology.

Render the same group nodes in the all-relationships Canvas. Place directly
declared members in their group and place deeper cards in the group inherited
from their nearest declared ancestor. Keep every card fully contained, with no
card or group overlaps. An all-relationships edge may omit its label when its
direction and endpoint pair identify exactly one implemented relationship; label
parallel relationships between the same directed pair so every claim remains
unambiguous and mechanically checkable.

These rules deliberately impose no card, group, or edge count. The hierarchy
and architectural questions decide the shape. Repository review still decides
whether the chosen names and grouping are semantically honest; the validator
proves that the declared grouping is rendered consistently and is not hollow.

## Block notes

A block is an actor, system, external system, runtime, store, or stable code
responsibility. Packages, folders, files, classes, endpoints, and tickets are
evidence rather than automatic blocks.

```md
---
type: mental-map-block
project: Project Name
atlas-id: project.stable-block-id
kind: responsibility
level: responsibility
status: implemented
confidence: traced
reviewed-revision: <full SHA>
---

# Block Name

Parent: [[Parent Block]]

Purpose: One sentence.

Hides: One sentence naming the complexity kept local.

Code footprint:
- `src/example/**`

Concrete anchors:
- `src/example/entry.ts :: startExample`
- `src/example/model.ts :: ExampleModel`

Provides:
- `submit work` -> accepts a validated request and returns its durable id

Requires:
- [[Other Block]] :: `publish result` -> accepts one completed result exactly once

State and invariants:
- State: Owns request lifecycle and retry status.
- Invariant: A completed request is never returned to active processing.

Runtime behavior:
- Success: Persists accepted work before acknowledging it.
- Failure: Rejects invalid work and retries transient persistence failures.

Deployment: Runs in the worker process; scales independently of the API.

Policies:
- [[Authorization Policy]] -> restricts submission by tenant and role

Quality and risks:
- Priority: Preserve accepted work across process failure.
- Risk: Duplicate delivery depends on downstream idempotency.

Connects:
- [implemented] [[Other Block]] -> sends validated work to
- [planned] [[Future Block]] -> will publish results to
- [detail-only] [[Vocabulary]] -> uses terms defined by

Evidence:
- `mapped at <full SHA>`
- [ADR-0004](relative-or-external-link)

Open question: Optional one-sentence uncertainty that could change the map.
```

Use only:

- `kind`: `actor`, `system`, `external-system`, `runtime`, `store`, or
  `responsibility`;
- `level`: `context`, `runtime`, or `responsibility`;
- `status`: `implemented`, `planned`, or `deprecated`;
- `confidence`: `accounted`, `traced`, or `deeply-inspected`.

Keep `atlas-id` stable across renames; generated Canvas node IDs derive from it.
Use one link-safe title for the filename, H1, wikilinks, and Canvas heading
subpath. It must be one trimmed filename component, must not end in a dot, must
contain no control characters, and must not contain `/`, `\`, `:`, `*`, `?`,
`"`, `<`, `>`, `|`, `#`, `^`, `[`, `]`, or `%%`. Apostrophes are allowed.
Put that H1 first after frontmatter, before comments or other body content.
Top-level blocks may omit `Parent`. Implemented responsibility blocks require a
non-empty footprint, current anchors, and revision evidence. Planned blocks may
omit code fields but require an issue, PRD, ADR, or architecture source. Actors,
external systems, and stores outside the repository may omit code fields.

Only an implemented `kind: responsibility` block may declare `Code footprint`
and own in-scope files. `runtime` and `store` blocks describe execution and state
topology; assign their implementation files to the logical responsibility that
maintains them. Parent/runtime grouping never duplicates primary ownership.

Every `Parent` must resolve to exactly one active canonical block, and the
parent graph must be acyclic. A block cannot parent itself directly or through
an ancestor chain.

Use the orientation fields selectively but concretely:

- `Provides` names stable entry points, events, protocols, or operator
  capabilities and states the promise each makes.
- `Requires` names the supplying block, interface, and assumption relied on.
- For a cross-runtime, store, or external interface, record the mechanism,
  input/event, output/effect, failure surface, and delivery, ordering,
  consistency, authorization, versioning, or quality semantics that materially
  affect consumers. Keep a simple in-process contract to one sentence.
- `State and invariants` identifies durable or lifecycle state ownership and the
  rules that must remain true, including material writers/readers and lifecycle;
  omit it only when the block owns neither.
- `Runtime behavior` records at least one meaningful success outcome and, for a
  critical responsibility, its important rejection, degradation, retry, or
  recovery behavior.
- `Deployment` states the process, job, device, or external boundary only when
  it changes ownership, scaling, trust, availability, or failure behavior.
- `Policies` links cross-cutting enforcement such as authorization, tenancy,
  observability, privacy, consistency, or resilience to the block that owns it.
- `Quality and risks` records only architecture-shaping priorities, known
  compromises, and live risks. Link the governing ADR or decision note in
  `Evidence` instead of restating its history.

Do not turn these fields into symbol inventories. Describe consumer-visible
promises and maintained rules in domain language; keep code details in
`Concrete anchors` and `Evidence`.

## Concrete anchors

Use this exact grammar after Markdown code-span markers are removed:

```text
anchor  := repo-relative-path [ " :: " symbol ]
symbol  := segment [ "." segment ]*
segment := one or more Unicode word characters, "$", or "-"
```

The delimiter is one space, two colons, and one space. The path must name one
existing file using normalized repository-relative POSIX syntax, with no glob,
leading `./`, backslash, absolute prefix, or `..` segment. These are valid:

```md
- `src/example/entry.ts`
- `src/example/entry.ts :: startExample`
- `src/example/model.py :: ExampleModel.validate`
```

A bare symbol must occur as a complete token in the file. For a dotted
qualified symbol such as `ExampleModel.validate`, every segment must occur as a
complete token in that file. Qualification is descriptive and useful for human
orientation; the language-neutral validator does not claim to prove AST
nesting. Use tests or other `Evidence` when nesting or dispatch identity is
architecture-significant. Do not add calls, line numbers, whitespace, `#`, or
language-specific separators to the symbol; choose a supported dotted name, a
bare symbol, or the exact file-only form.

## Ownership

Treat `Code footprint` as exhaustive primary ownership, not examples. Use
repo-relative POSIX paths and simple `*`, `**`, and `?` globs.

- Match every included file exactly once.
- Reject overlapping ownership and stale patterns.
- Exclude test code, fixtures, snapshots, and test-only configuration from
  ownership. Cite representative tests only under `Evidence`.
- Assign a mixed file to its best current owner and record the coupling as an
  open question.
- Exclude generated, vendored, test, fixture, or build output only in the
  coverage note with a reason.
- Never create a miscellaneous catch-all.

Assign code to the deepest coherent block. Parent runtime blocks group children
without duplicating their file ownership.

## Relationships

The source note owns each directed claim:

- `[implemented]` — current relationship; eligible for Canvas and solid Mermaid
  edges.
- `[planned]` — supported future relationship; show in a focused Mermaid view
  or planned Canvas group without pretending it is current.
- `[detail-only]` — useful link context intentionally absent from architecture
  views. Prefer it for incidental calls, shared utilities, vocabulary links,
  and other dependencies a reader need not retain to understand system shape.

Write a directionally correct verb phrase after `->`. Record two claims for a
truly bidirectional relationship. Every implemented or planned relationship
must appear in at least one relevant view; every view edge must match its source
note.

Every block/view wikilink must resolve to exactly one vault artifact. A bare
title is acceptable only when unique; otherwise use its normalized
vault-relative path, such as `[[Engineering/Project Map/Blocks/Other Block]]`.
Do not accept basename fallback for a missing or ambiguous path-qualified link.

An interface dependency normally has both forms: `Requires` explains the
consumer's assumption, while `Connects` supplies the canonical directed
architecture relationship used by projections. Keep their direction and labels
consistent.

An architecture-significant relationship needs `[implemented]` or `[planned]`
and one relevant projection. Every `[implemented]` relationship must also
appear in the required all-relationships Canvas, but it need not appear on the
main Canvas. Use focused Canvas or Mermaid views to keep dense or ordered slices
readable.

## Coverage note

```md
---
type: mental-map-coverage
project: Project Name
revision: <full HEAD SHA>
---

# Project Name Code Coverage

Include:
- `src/**`
- `scripts/**`
- `package.json`

Exclude:
- `src/generated/**` -> generated from the schema
- `tests/**` -> test evidence outside atlas ownership
```

Choose the boundary after inventorying the repository. Include maintained
runtime, library, build/config, migration, script, and operational behavior.
Exclude every discovered test path while continuing to use representative tests
as evidence. Atlas and coverage revisions must describe the same validated
repository state.

Classify every path returned by
`git ls-files --cached --others --exclude-standard` as either matching at least
one `Include` or matching a reasoned `Exclude`; Exclude wins if patterns overlap.
An unmatched path is an error, not an implicit omission. Every Include and
Exclude pattern must match at least one current inventory path, and at least one
included path must remain after exclusions.

Discover test paths from repository conventions, manifests, and test-runner
configuration. Record matching reasoned exclusions for test code, fixtures,
snapshots, and test-only configuration; test behavior may support a canonical
claim but does not receive primary ownership or projection coverage.

## Lifecycle

- **Rename:** preserve `atlas-id`; update the filename, heading, exact wikilinks,
  Canvas file paths and heading `subpath` values, Base-derived views, and
  Mermaid labels inside the map.
- **Deprecate:** retain the note, add `status: deprecated` and one-sentence
  `Deprecation:`; link a replacement when known and remove it from current
  topology.
- **Delete:** only an accidental or duplicate block with no evidence or inbound
  links.
- **No semantic change:** leave block/view content alone, but advance a verified
  implementation checkpoint so the same range is not replayed.

## Validate version 2

Resolve the installed skill directory and run its bundled script:

```bash
skill_dir="/absolute/path/to/building-mental-maps"
python3 "$skill_dir/scripts/validate_mental_map.py" \
  --repo "/path/to/repo" --vault "/path/to/vault" \
  --map-dir "/path/to/vault/Project Map" --atlas "Project Atlas.md" \
  --coverage "Project Code Coverage.md" --check-coverage --write-receipt
```

For version 2, always supply `--repo`, `--vault`, `--map-dir`, `--atlas`,
`--coverage`, `--check-coverage`, and `--write-receipt`. Add `--state` or
`--receipt` only when using non-default sidecar paths, and pass the same paths
to the checkpoint command.

Success is exit status `0` plus a schema 2 JSON receipt at
`<map-dir>/.mental-map-validation.json` by default. A custom `--receipt` must
remain inside the map directory. The receipt contains exactly these fields:

```json
{
  "schema": 2,
  "targetFingerprint": "sha256:...",
  "coverageContractSha256": "sha256:...",
  "changedPaths": [],
  "statusContext": {},
  "mapDigest": "sha256:...",
  "validationContractDigest": "sha256:..."
}
```

The validator writes the receipt only after all checks pass and confirms that
the repository target and map digest remained stable during validation. A
nonzero exit, missing script/runtime, or absent receipt leaves the run without
mechanical validity: report validation as blocked and leave the checkpoint
unchanged. Ad hoc JSON, Markdown, or Obsidian inspection cannot substitute for
the bundled validator.

Version 2 validation uses the Base as the catalog; do not create a redundant
Blocks Index solely for validation. It also requires the atlas orientation
lines and entry-point inventory. It rejects generated Canvas cards whose literal
`file` value is not the canonical block note's exact vault-relative path or
whose `subpath` does not focus its exact H1. It requires and validates
`relationships-canvas` separately, as well as every linked scoped Canvas or
Markdown view, verifies each inventory row's focused-view binding or no-view
reason, then combines projections for active-block and relationship coverage. The receipt
binds the exact repository fingerprint, coverage contract, map artifacts, and
validator contract that passed. Any later code, map, coverage, or validator
change makes it stale and blocks checkpointing.

The receipt is a deterministic local freshness and integrity gate against
accidental stale checkpointing, not an authentication or security boundary. Any
process with write access to the map and scripts can forge or replace it.
