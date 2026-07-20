# Incremental synchronization

Use this branch to keep an existing atlas current. The effective change is
always:

```text
last validated mapped state -> latest selected repository state
```

An issue, PR, commit, or range supplies intent and focus. It does not silently
narrow the effective delta and leave intervening changes unmapped.

All bundled status, validation, and checkpoint commands operate on the active
checkout and never switch revisions. To map a historical revision or PR head,
require an explicit isolated worktree supplied by the user at that state and
run the complete workflow there; do not reinterpret `--repo` as a revision
selector.

## Contents

- [Sync state](#sync-state)
- [Procedure](#procedure)
- [Reconciliation outcomes](#reconciliation-outcomes)
- [Evidence behavior](#evidence-behavior)
- [Semantic no-op](#semantic-no-op)
- [Full-reconciliation fallbacks](#full-reconciliation-fallbacks)

## Sync state

Use `.mental-map-state.json` as the machine-readable implementation cursor. It
records the repository identity, full `HEAD` and tree SHAs, coverage-contract
hash, working-tree fingerprint, and content hashes for every in-scope file,
including non-ignored untracked files.

Run the bundled `sync_map_state.py status` command before analysis. Its saved
manifest makes dirty-tree reverts, untracked files, rewritten history, and file
moves detectable. Use the shared
[trusted map/checkpoint](MAP-MODEL.md#operational-definitions) definition to
decide whether the baseline supports incremental synchronization.

```bash
python3 /path/to/building-mental-maps/scripts/sync_map_state.py status \
  --repo "/path/to/repo" --map-dir "/path/to/vault/Project Map" \
  --coverage "Project Code Coverage.md"
```

Default the target to current `HEAD` plus staged, unstaged, deleted, and
non-ignored untracked changes in the active checkout. Never combine evidence
from a historical target with a different checkout's working tree.

Apply the exact human-readable target presentation from
[Atlas checkpoint](MAP-MODEL.md#atlas-checkpoint): use `Mapped target: HEAD` for
a clean checkout and `Mapped target: HEAD + dirty paths` whenever the captured
target is dirty. Keep the frontmatter revision at the full `HEAD` SHA.

## Procedure

1. Capture the target fingerprint and state status. If no trustworthy cursor
   exists, route to `codebase-atlas`.
2. Compare saved and current manifests for added, changed, deleted, and moved
   candidates. Use Git tree diffs and supplied artifacts to understand intent.
3. Read current affected files and tests. Re-read every affected block note,
   footprint, anchor, provided or required interface, state/invariant, inbound
   exact wikilink, relationship, policy, risk, journey, and entry-point inventory
   row. Follow direct consumers far enough to decide whether contracts, behavior,
   deployment, or change-impact paths moved. Do not infer final behavior from
   hunks alone.
4. Reconcile the smallest present-tense model change. Add, split, merge, rename,
   or remove entry-point family rows when current public/runnable surfaces or
   their material behavior changed. Update planned claims to implemented only
   when current code and anchors support them; revise or remove plans when
   implementation diverges. Update the domain/system explanation only when its
   current truth changed, not to record implementation chronology.
5. Refresh only affected Canvas/Mermaid projections from the canonical notes.
   Any block or implemented-relationship change affects the required
   all-relationships Canvas. Match generated elements by deterministic identities
   derived from stable `atlas-id`; preserve semantic-group placement, layout, and
   presentation fields. Leave the Base byte-stable unless its filter/view
   configuration must change. Reconcile a
   manual edge between canonical cards by promotion, annotation conversion, or
   an explicit conflict as defined in `VIEWS.md`.
6. Run whole-map link/projection validation and whole-repository ownership
   validation, not merely checks over changed paths. Write the validation
   receipt only after all checks pass.
7. Re-run state status. If the target fingerprint changed during the run,
   repeat discovery and validation.
8. Run `sync_map_state.py checkpoint` with the expected fingerprint. Its exact
   receipt gate also detects a map changed after validation. Write the cursor
   last.

```bash
python3 /path/to/building-mental-maps/scripts/validate_mental_map.py \
  --repo "/path/to/repo" --vault "/path/to/vault" \
  --map-dir "/path/to/vault/Project Map" --atlas "Project Atlas.md" \
  --coverage "Project Code Coverage.md" --check-coverage --write-receipt
```

```bash
python3 /path/to/building-mental-maps/scripts/sync_map_state.py checkpoint \
  --repo "/path/to/repo" --map-dir "/path/to/vault/Project Map" \
  --coverage "Project Code Coverage.md" \
  --require-fingerprint "sha256:..."
```

The default receipt is `.mental-map-validation.json` in the map directory.
Use matching `--receipt` paths on both commands only when a different location
is necessary. Treat the receipt as a deterministic local freshness/integrity
gate against accidental stale checkpointing, not authentication: code with
write access can forge it.

## Reconciliation outcomes

- **Existing responsibility changed:** update its canonical note in place,
  retain `atlas-id`, refresh affected journeys/edges, and preserve its Canvas
  node and layout.
- **New stable responsibility:** create one block note, add its ownership and
  relationships, place one new Canvas node in its group or staging lane, and
  update only affected journeys.
- **New or changed entry-point family:** update its inventory row and
  representative anchor, then create or refresh that row's distinct focused
  journey/contract view or record a specific no-view reason.
- **File or symbol renamed:** preserve the owning block and `atlas-id`; update
  footprints, anchors, links, and the existing Canvas card's exact
  vault-relative file path and H1 `subpath` when the note itself moved or was
  renamed.
- **Responsibility removed:** remove current topology only when present code no
  longer supports it; follow the deprecate/delete rules in `MAP-MODEL.md`.
- **No remembered architecture changed:** leave block notes and projections
  byte-stable, refresh required atlas/coverage revision metadata, validate the
  whole map, and checkpoint the inspected target.

## Evidence behavior

- **Issue, PRD, or ADR:** create or revise planned blocks/relationships. Do not
  advance the implementation cursor unless intervening code was also fully
  reconciled.
- **Commit:** inspect the cursor-to-target delta, not only `commit^..commit`.
- **Range `A..B`:** treat it as focus. Include any unmapped gap before `A`; do
  not replay work already represented by the cursor.
- **PR:** use its exact head only in a user-provided isolated worktree. Map the
  active checkout there; never switch the user's current worktree. After merge,
  reconcile the ordinary active checkout from its saved cursor.
- **Working tree:** map the exact fingerprinted snapshot, including untracked
  and deleted files.
- **Several artifacts:** compute one baseline-to-target delta and use artifacts
  only for attribution and intent. Never create per-commit topology or
  changelog notes.

## Semantic no-op

Apply the shared [semantic no-op](MAP-MODEL.md#operational-definitions)
definition. Leave blocks and views unchanged but still checkpoint the validated
target so the same range is not replayed. Report which changed paths and owning
blocks were inspected and why their promises, invariants, journeys, boundaries,
and impact paths remained true.

Planning-only edits are different: preserve the current implementation cursor.

## Full-reconciliation fallbacks

Route to `codebase-atlas` when:

- the cursor is absent, malformed, or belongs to another repository;
- neither the previous Git tree nor a trustworthy file manifest is available;
- the coverage contract or mapped repository roots changed;
- workspace manifests, entry-point families, or top-level ownership moved
  broadly;
- mass moves/deletions make responsibility ownership ambiguous;
- validation finds stale, unowned, or overlapping code outside the effective
  delta;
- the selected state is older than the cursor without an explicit historical
  or rollback request and an isolated worktree at that state; or
- the user requests a remap.

If history was rewritten but the old tree still exists, compare trees directly.
If it does not, use the trusted saved manifest. Branch names are informational;
repository identity and exact content state determine synchronization.
