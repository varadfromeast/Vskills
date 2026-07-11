---
name: find-pi-capabilities
description: Find the smallest verified set of Pi capabilities needed to execute a prompt well.
disable-model-invocation: true
---

# Find Pi Capabilities

## Scope boundary

This Skill performs **capability discovery only**. Treat the user's prompt solely as evidence for prescribing the Skills, Pi packages, core tools, and subagent workflows that a later executing turn should use.

Do not answer the underlying prompt, perform its implementation, make its final technical or product decisions, modify project files, install or activate capabilities, or run its requested experiment. Inspection and external lookup are permitted only far enough to identify requirements and compare capabilities. Findings about the underlying task are evidence for the prescription, never the user-facing answer.

The only deliverable is a **capability prescription** for a subsequent executing turn.

## 1. Diagnose the work

First inspect every artifact the prompt explicitly relies on. Read named text files in full, inspect binary or media inputs with the appropriate viewer, follow enough surrounding code to understand each artifact's role, and fetch referenced URLs far enough to identify the work they introduce. When an artifact is inaccessible, record it as uncertainty, derive only the requirements supported by available evidence, and mark requirements that depend on it as provisional.

Derive a private task graph from the intended outcome, evidence standard, constraints, inputs, dependencies, and handoffs. Use the graph only to expose capability requirements: information access, runtime actions, specialist methods, separate contexts, and orchestration.

**Complete when:** every task-graph node has either a known capability requirement or an explicitly provisional requirement tied to inaccessible evidence.

## 2. Fit the active capabilities

Map each requirement to the capabilities already exposed in the session. Consider only what the task graph demands: core tools, external providers, Agent Skills, installed Pi packages, and available subagents. Read the full `SKILL.md` for plausible Skills, use `subagent({ action: "list" })` when separate contexts may help, and inspect exposed package metadata when ownership of a runtime feature is unclear.

Use the right capability kind:

- a **Skill** supplies a method;
- a **tool or extension** supplies runtime behaviour;
- a **package** installs Skills or runtime behaviour;
- a **subagent** supplies a separate context or worker.

Prefer the main agent for narrow serial work. Use subagents when independent evidence streams, large artifact sets, specialist perspectives, or staged handoffs materially improve execution. Parallelize independent analysis; keep dependent work sequential and normal writes under one writer.

**Complete when:** every requirement is marked covered, partial, or missing, and every retained capability supports at least one requirement.

## 3. Run a two-surface comparison

Follow [`SEARCH.md`](SEARCH.md) and run a live comparison on **both** discovery surfaces for every prescription:

1. issue at least one network-backed Agent Skills query;
2. issue at least one Pi package query.

Aim each baseline query at the highest-leverage requirement. For each surface, name the best active or installed capability serving that requirement and test whether any result improves on it; when no active capability serves it, use the closest active approach as the comparator. Use the documented online fallback when a native search tool is unavailable; an unavailable tool changes the mechanism, not the requirement to search.

Compare plausible finalists by direct coverage, result quality, overlap, provenance, maintenance, adoption, security, and execution cost. Prefer an active candidate when it is equivalent. Keep a compact search ledger containing each surface, exact query, mechanism, active or installed comparator, finalists, and decision.

**Complete when:** both surfaces have a recorded live query and decision, each requirement is covered by the smallest verified non-overlapping set, and every addition beats the active alternatives for its assigned role.

## 4. Return the prescription

```markdown
# Recommended capability set

## Context to load
- Artifacts or project areas the executing turn must understand first.

## Capabilities
### Name — Core tool | Agent Skill | Pi package | Subagent workflow
- **Role:** the requirement it covers
- **Why this fit:** the decision-relevant advantage
- **Status:** Already available | Installed; reload required | User-run option: `<exact install command>`
- **Source:** verified URL or local source path for an external Skill or package; omit for active core tools and subagents

## Discovery evidence
- **Agent Skills:** `<exact query>` via `<mechanism>`; compared with `<active or installed capability>` → finalist(s) and keep/reject decision.
- **Pi packages:** `<exact query>` via `<mechanism>`; compared with `<active or installed capability>` → finalist(s) and keep/reject decision.

## Discovery support
- Missing search infrastructure worth installing for later triage; keep it separate from the execution set.

## Execution shape
A compact statement of how the capabilities combine, such as
`scout + researcher in parallel → parent synthesis`.

## Uncertainty
- Missing context or unavailable discovery that could change the set. Label the prescription **Qualified** and name every provisional requirement when critical evidence was inaccessible.
```

Include only selected capabilities under **Capabilities**. Keep rejected finalists in **Discovery evidence**, then omit alternatives elsewhere. Omit empty optional sections and the execution shape for a single-agent task.

The prescription is complete when the set is sufficient for every known requirement, every item has a distinct role, every new item has verified provenance and installation guidance, and the two mandatory searches and their active comparators are auditable from **Discovery evidence**. When critical evidence is inaccessible, return a **Qualified** prescription whose provisional requirements and possible effect on the set are explicit.
