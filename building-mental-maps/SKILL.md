---
name: building-mental-maps
description: Build and maintain a living Obsidian codebase atlas. Use for whole-system orientation, planned mapping from issues, PRDs, or ADRs, or synchronization from PRs, commits, diffs, or working-tree changes.
---

# Building Mental Maps

Maintain a **living atlas**: a present-tense codebase model carried across
bounded runs. End every run with a coherent, validated map; end every
implementation run with a resumable checkpoint. Preserve stable identities and
make only justified model or projection changes. Never write a one-off report
or implementation chronology.

**Map all code; do not draw all code.** Account for every maintained first-party
file, but visualize only the responsibilities and journeys a maintainer needs to
remember.

## Core contract

- Apply the shared [operational definitions](references/MAP-MODEL.md#operational-definitions)
  whenever deciding map trust, migration, coverage, relationship significance,
  or semantic no-op status.
- Classify repository test code, fixtures, snapshots, and test-only
  configuration as reasoned coverage exclusions. Read representative tests as
  evidence, but keep them out of block footprints, concrete anchors, and views.
- Require an explicit vault root containing `.obsidian/`. Never guess or search
  for one. If the user explicitly requests a new vault, use the approved
  [new-vault bootstrap](references/CODEBASE-ATLAS.md#choose-or-create-the-vault)
  only after its absolute path is explicit.
- Operate on the active checkout only and never switch it. For a historical
  revision or PR head, require the user to provide an explicit isolated
  worktree at that state and treat that worktree as the repository.
- Write project-map artifacts only inside the vault and outside the repository;
  read the repository as evidence. Refuse a repo/map overlap that would make
  the map change its own target fingerprint.
- Preflight the map version before mutation. Treat a coherent legacy map as
  read-only until the user explicitly approves a version 2 migration.
- Make the atlas sufficient for architecture orientation without source. Keep
  code as linked evidence or on-demand detail.
- Inventory every public or runnable entry-point family. Give each family its
  own focused journey/contract view, or a specific reason no focused view is
  useful; never merge distinct families merely to minimize view count.

## Route the run

Identify the repository, vault, and project-map directory. The current
repository is sufficient when unambiguous.

Choose one mode:

- **`codebase-atlas`** — no trusted map/checkpoint exists, the user requests a
  whole-codebase map, or incremental safety requires full reconciliation.
- **`change-map`** — synchronize an existing trusted map. Compare the last
  validated state to active `HEAD` plus staged, unstaged, deleted, and
  non-ignored untracked changes.

An issue, PRD, or ADR supports planned claims but never advances the
implementation checkpoint. A commit, PR, or range is evidence and focus; do
not let it silently skip changes since the checkpoint. If the user asks only
for an explanation, read the map and repository without editing either.

## Load only the branch you need

Before editing, read [MAP-MODEL.md](references/MAP-MODEL.md).

- For `codebase-atlas`, also read
  [CODEBASE-ATLAS.md](references/CODEBASE-ATLAS.md) and
  [VIEWS.md](references/VIEWS.md).
- For `change-map`, also read [CHANGE-MAP.md](references/CHANGE-MAP.md). Read
  [VIEWS.md](references/VIEWS.md) only when blocks, relationships, hierarchy,
  journeys, or native projections may change.

## Steps

1. **Resolve the boundary.** Fix the mode, active checkout, vault, map directory,
   baseline, target, and supplied evidence before writing. Confirm the map is
   version 2, outside the repository, and has a complete Include/Exclude
   classification; otherwise stop for migration or boundary correction.
   Continue only when every boundary value is explicit and passes preflight.
2. **Inspect current truth.** Read the existing model, entry-point inventory,
   relevant project language, effective diff, current affected files, tests,
   and anchors. Keep scratch inventories and deltas out of Obsidian. Continue
   only when every repository-inventory path in a bootstrap, or every
   effective-delta path and material consumer in a sync, has evidence and a
   coverage, ownership, impact, or explicit-uncertainty disposition.
3. **Reconcile the model.** Make the smallest justified responsibility,
   interface, state, behavior, deployment, policy, risk, relationship, footprint,
   anchor, status, or lifecycle changes. A semantic no-op is valid. Continue
   only when every inspected path, family, and claim has one present-tense model
   outcome and no known stale claim remains.
4. **Refresh affected projections.** Reconcile each changed entry-point family,
   then refresh the required all-relationships Canvas and affected compact,
   scoped, or Mermaid views from canonical notes under the
   [native-view contract](references/VIEWS.md). Continue only when every affected
   active block, significant relationship, and entry-point row is
   projected or validly waived; the main Canvas independently contains every
   orientation block in exactly one declared semantic group and forms one
   canonical backbone with no unexplained implemented-card isolates; stable
   presentation is preserved; and artifacts that need no change remain
   byte-stable where the contract requires it. Mermaid and scoped views may
   deepen the map but never pay for a missing front-door card, group, or
   backbone connection.
5. **Validate the whole contract.** Run the
   [bundled validator](references/MAP-MODEL.md#validate-version-2) with its
   required arguments. Check exhaustive ownership on every run. Fix all errors,
   write its exact validation receipt, and apply the
   [visual-verification states](references/VIEWS.md#visual-verification) to every
   changed view. Continue only when validation has zero errors, the receipt binds
   the exact target and map, and each changed view has an explicit verification
   state; otherwise report the blocked or skipped check.
6. **Checkpoint last.** Confirm the repository target did not change during the
   run, then checkpoint using that receipt. Finish only when the target
   fingerprint is unchanged and the checkpoint accepts the exact receipt.
   Advance after an inspected implementation no-op; leave the checkpoint
   unchanged for planning-only work, stale maps, or failed validation.

## Completion

For `codebase-atlas`, apply every item in the
[bootstrap completion gate](references/CODEBASE-ATLAS.md#bootstrap-completion-gate).
For `change-map`, complete every
[procedure](references/CHANGE-MAP.md#procedure) step against the entire
baseline-to-target delta. Validator success never substitutes for either
semantic bound.

Across both modes, finish only when every inventory path is classified, every
included file has exactly one owner, every active block and significant
relationship is projected, the separate all-relationships Canvas contains every
implemented relationship, preserves the declared semantic groups, and has no
overlapping cards or groups; every entry-point family has its own focused view or
specific waiver; the Canvas semantic-group declaration and rendered topology
agree; every native link resolves exactly; and every changed view has an explicit
verification state. The all-relationships Canvas is mandatory even when focused
Mermaid flows are more readable, but it may omit unambiguous edge labels to
reduce visual noise. A new codebase atlas must reach CLI screenshot verification
when the CLI probe succeeds; unavailable rendering is reported as a blocked
visual check. A sync also requires an exact validated-target checkpoint.

Report the mode, revision and mapped-target presentation, map directory, changed
blocks and views, contract/state/behavior/relationship changes, entry-point
coverage and waivers, mapped/excluded/unresolved counts, all-relationships Canvas
path and verification state, validation receipt, checkpoint, and performed or
skipped checks.
