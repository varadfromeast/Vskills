# Whole-codebase bootstrap

Use this branch when no trusted atlas exists or a full reconciliation is
required. Build exhaustive code accounting and a selective explanation—not a
file tree drawn as a graph.

## Contents

- [Choose or create the vault](#choose-or-create-the-vault)
- [Scaffold the native project](#scaffold-the-native-project)
- [Establish the coverage boundary](#1-establish-the-coverage-boundary)
- [Inventory entry-point families](#2-inventory-entry-point-families)
- [Fast first synthesis proposal](#fast-first-synthesis-proposal)
- [Establish purpose and boundaries](#3-establish-purpose-and-boundaries)
- [Find logical responsibilities and contracts](#4-find-logical-responsibilities-and-contracts)
- [Trace critical journeys](#5-trace-critical-journeys)
- [Synthesize responsibility blocks](#6-synthesize-responsibility-blocks)
- [Reconcile exhaustive ownership](#7-reconcile-exhaustive-ownership)
- [Build the native reading path](#8-build-the-native-reading-path)
- [Bootstrap completion gate](#bootstrap-completion-gate)

## Choose or create the vault

For an existing vault, require the exact absolute root that already contains
`.obsidian/`. Do not search for candidates.

When the user explicitly asks for a new vault, first obtain or confirm its exact
absolute path and verify that it does not overlap the repository. Then create
only that approved root and marker:

```bash
vault_root="/absolute/path/chosen-by-user"
mkdir -p "$vault_root/.obsidian"
(cd "$vault_root" && pwd -P)
test -d "$vault_root/.obsidian"
```

Report the resolved path as the confirmed vault root before scaffolding the
project map. Creating `.obsidian/` is the approved new-vault bootstrap; it does
not authorize guessing a path, importing another vault, or writing map
artifacts before the boundary checks pass.

## Scaffold the native project

After the repository, vault, map directory, project name, and coverage boundary
are explicit, use the bundled scaffold for a new version 2 map:

```bash
python3 /path/to/building-mental-maps/scripts/scaffold_mental_map.py \
  --repo "/path/to/repo" --vault "/path/to/vault" \
  --map-dir "/path/to/vault/Engineering/Project Map" \
  --project "Project" --include "src/**" \
  --exclude "tests/**=test evidence outside atlas ownership"
```

The scaffold requires an explicit `.obsidian/`-backed vault root, absolute
paths, a map directory outside the repository, and coverage patterns that
classify the complete Git inventory; it refuses an existing destination and
creates only incomplete atlas/Canvas/Base/coverage files
and `Blocks/`, `Views/`, and `Flows/` directories. It never writes a validation
receipt or checkpoint. Fill every empty orientation, coverage-summary, and
unresolved-questions field, replace the entry-point and Canvas semantic-group
placeholders, and build the canonical model before validation.

## 1. Establish the coverage boundary

Inventory top-down before interpreting:

- tracked and non-ignored untracked files;
- manifests, build files, runtime and test configuration;
- runnable applications, workers, jobs, CLIs, and public library entry points;
- source, test, migration, script, generated, and vendored areas;
- stores, queues/topics, files, and external integrations; and
- architecture/domain docs, ADRs, service objectives, threat models, runbooks,
  and deployment manifests.

Prefer `git ls-files --cached --others --exclude-standard` in Git repositories.
Classify every inventory path in the coverage note with at least one `Include`
or a reasoned `Exclude`; no path may remain implicit. Do not infer logical
blocks from directory names alone. Discover test paths from manifests,
test-runner configuration, and repository naming conventions, then exclude all
test code, fixtures, snapshots, and test-only configuration from ownership.

## 2. Inventory entry-point families

Before accepting responsibility boundaries, enumerate every public API family,
CLI or command family, independently runnable application or job, worker or
event consumer, callback or hook surface, and public library surface. Start
from manifests, routers, exports, executable declarations, deployment
configuration, and framework registration, then verify each family in current
code.

Group entries only when they share one trigger-to-outcome contract and the same
material handoffs and failure behavior. Split a broad “API,” “worker,” or
“library” row when initiator, execution mode, main effect, state transition,
asynchronous boundary, or recovery differs. Give every row one representative
exact code anchor. Apply the canonical definition and table contract in
[Entry-point inventory](MAP-MODEL.md#entry-point-inventory).

Keep this inventory in scratch until repository evidence supports it, then
replace the scaffold placeholder in the atlas before drawing focused views.
Reconcile the rows after tracing; a changed trace may split, merge, or rename a
family, but reducing the number of views is never by itself a reason to merge.

## Fast first synthesis proposal

For a medium-size repository, turn the first inventory into a reviewable
proposal before deep tracing:

1. **Inventory:** group paths by maintained role, not merely by folder.
2. **Candidate responsibilities:** propose one owner for each stable promise,
   invariant, orchestration role, or external boundary.
3. **Ownership:** assign every included path family to exactly one candidate and
   expose ambiguous files immediately.
4. **Trace entry points:** follow one representative success and material
   failure path per inventory row; split, merge, or rename families and
   candidates when the traces disprove the first clustering.

Use this compact scratch template outside the vault:

| Pass | Record |
| --- | --- |
| Inventory | `path family` · maintained role · Include/Exclude evidence |
| Entry points | `family` · representative anchor · trigger → outcome · material failure |
| Candidates | `responsibility` · promise · hidden complexity · state/invariant |
| Ownership | `path/glob` · exactly one candidate · reason or open question |
| Traces | `entrypoint anchor` · trigger → outcome · material failure · candidates crossed |

The output is a first block/ownership proposal, not accepted architecture.
Verify it against code, configuration, and representative tests before writing
canonical block notes.

## 3. Establish purpose and boundaries

State the served actors, intended outcome, core domain concepts, explicit
non-goals, and external systems before decomposing implementation. Verify the
claims against entry points, public contracts, configuration, tests, and current
decisions. Record material quality priorities and risks that explain why the
shape is the way it is.

For a domain-heavy system, record a few concrete domain stories in its own
language: who initiates an activity, which work or information changes hands,
and what outcome results. Establish the normal story before abstracting rules
or translating it into software blocks.

Then identify independently runnable units, deployment and trust boundaries,
stores, asynchronous channels, and operator-controlled jobs. Separate logical
responsibility from deployment: co-located blocks may have different purposes,
and one responsibility may execute in several instances.

## 4. Find logical responsibilities and contracts

Read architecture and domain docs first, then verify them against code and
configuration. Identify actors, external systems, independently runnable units,
stores, asynchronous channels, entry-point families, protocols, and important
failure boundaries.

Keep context, runtime, and responsibility levels separate. Deployment units,
folders, and packages are evidence until their runtime or ownership meaning is
verified.

For each candidate responsibility, capture what it provides, what it requires,
state it owns, invariants it protects, policies it enforces or consumes, and the
quality or risk that materially constrains it. Prefer externally observable
promises over classes, functions, routes, or schemas.

## 5. Trace critical journeys

Trace at least one representative path for every entry-point inventory row.
Follow current code from trigger to meaningful result, state change, message,
or external effect. Include validation, orchestration, state ownership, and
important asynchronous handoffs; omit incidental utility calls. Trace both the
normal outcome and the most architecture-relevant rejection, timeout, retry,
partial failure, or recovery path for each critical entry-point family.

Use representative tests to confirm outcomes and important error paths. Trace a
second path when behavior materially differs, such as synchronous versus queued
execution. Keep scratch traces as `source -> verb -> target` with file/symbol
evidence and never write them as changelog notes. Record the resulting behavior
in ordinary language before projecting it as Mermaid. Then bind that row to its
own focused `journey` or `contract` view. Use a documented no-view reason only
for a static contract with no meaningful ordering, handoff, state transition,
or failure topology.

## 6. Synthesize responsibility blocks

Cluster code using:

- shared purpose and reason to change;
- state, invariant, or orchestration ownership;
- cohesive interfaces and hidden complexity;
- import/call locality and representative tests; and
- project domain language.

Apply the deletion test: fold a proposed block into its parent when removing its
note loses no useful mental leverage. Split vague blocks when they hide
independent purposes, lifecycles, state ownership, or entry points. Avoid names
such as “utilities,” “manager,” or “business logic” unless they are genuinely
stable project language.

Model a cross-cutting concern as a block only when one responsibility owns its
policy or mechanism. Otherwise record it as a required policy on affected
blocks. Model decisions as linked evidence, not timeless blocks; preserve their
current consequence, quality tradeoff, and residual risk in canonical notes.

## 7. Reconcile exhaustive ownership

Assign every included file to the deepest coherent implemented responsibility.
For an unowned or multiply-owned file, narrow or widen a footprint, create a
block that passes the granularity test, assign a shared file to its primary
conceptual owner and record the coupling, or exclude it with a reason.

Do not create a miscellaneous block or claim completion with an unexplained
remainder. Mechanical validation must report zero unowned and zero
multiply-owned in-scope files.

## 8. Build the native reading path

Create hierarchy and directed relationships in canonical notes before drawing
views. Then follow [VIEWS.md](VIEWS.md): generate the main Canvas, required
all-relationships Canvas, block Base, critical journey notes, and only the scoped
Canvases that improve progressive zoom. Link every Canvas and Markdown journey
into the native reading path with an exact, unambiguous wikilink.

For monorepos, make the atlas Canvas a system landscape and give each
independently owned system its own scoped Canvas. Share external/platform block
notes instead of copying their facts.

Before checkpointing, verify that every entry-point inventory row has a current
representative anchor and its own linked focused view or a specific no-view
reason, every traced family reaches a critical outcome, every store/integration
appears in a relevant view, every block has valid evidence, all Canvas/Mermaid
edges derive from canonical relationships, the main Canvas renders the declared
semantic groups as one legible orientation backbone with no unexplained
implemented-card isolates, the all-relationships Canvas contains every
implemented relationship inside the same non-overlapping semantic groups, and
coverage is exact. When the Obsidian CLI probe succeeds, inspect screenshots of
both required Canvases before calling the bootstrap complete.

## Bootstrap completion gate

Do not call the atlas ready until a reader can answer, from the map alone:

- why the system exists, where its domain ends, and which actors/external
  systems participate;
- which logical responsibility owns each important promise, interface, state
  transition, invariant, and cross-cutting policy;
- how every public or runnable entry-point family succeeds and how its material
  failure or recovery path behaves;
- which runtime, deployment, trust, scaling, and persistence boundaries shape
  behavior;
- which current decisions and quality priorities explain the shape, and which
  risks or uncertainties remain; and
- where a change to a public contract, invariant, store, policy, or deployment
  boundary is likely to propagate.

The front-door Canvas must also let that reader identify the system's coherent
semantic regions and follow one dominant route across them before inspecting
secondary branches. More focused flows do not compensate for a grouped Canvas
that is visually or topologically empty.

These are semantic checks in addition to mechanical validation. Record a
specific open question rather than inventing an answer. Coverage still requires
zero unowned and zero multiply-owned in-scope files.

Use confidence precisely:

- `accounted` — ownership coverage and anchors are known;
- `traced` — representative runtime journeys were followed through current
  code/tests;
- `deeply-inspected` — internal behavior was read in detail.

Never turn “all files accounted for” into “all behavior proven.”
