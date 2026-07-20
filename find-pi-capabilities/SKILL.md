---
name: find-pi-capabilities
description: Scout the smallest verified Pi capability set before execution. Use when the user asks what Agent Skill, Pi package, MCP/tool integration, or subagent can handle a task.
---

# Find Pi Capabilities

Operate as a **scout**: inspect enough to prescribe the route, then stop. Treat
the prompt as evidence for a later executing turn; do not answer or implement
it. Return install commands as inert user-run options, never actions.

## 1. Diagnose the gap

Inspect the named artifacts and the narrow project context needed to understand
the intended outcome, constraints, inputs, and evidence standard. Record
inaccessible evidence instead of filling it with assumptions.

Derive a private list of requirements and classify each by capability kind:

- a **core tool** supplies an action already built into the session;
- an **Agent Skill** supplies a reusable method;
- a **Pi package** supplies missing runtime behaviour through an extension or
  integration;
- an **MCP server or external integration** supplies runtime behaviour through a
  local or remote tool/API surface;
- a **subagent** supplies a separate context, specialist, or worker.

Classify what each artifact itself supplies. When a Skill depends on a CLI,
service, or MCP server, record that runtime separately; do not attribute the
runtime's features to the Skill instructions.

Compare each requirement with the capabilities exposed in the current session.
Read the full `SKILL.md` of plausible active Skills. List available subagents
when separate contexts could materially help. Mark each requirement **covered**,
**partial**, **missing**, or **provisional**; treat partial coverage as a gap.

**Complete when:** every requirement has one classification and one status, and
every provisional status names the inaccessible evidence behind it.

## 2. Search the relevant branch

Choose discovery from the remaining gaps:

- **method gap** → follow [`AGENT-SKILLS.md`](AGENT-SKILLS.md);
- **runtime gap** → follow [`PI-PACKAGES.md`](PI-PACKAGES.md);
- **broad Skill-or-package request** → follow both references and compare
  their method/runtime roles;
- **MCP or external-integration gap** → follow
  [`MCP-SERVERS.md`](MCP-SERVERS.md);
- **separate-context gap** → compare available subagents;
- **no gap** → keep the active capability and skip online discovery.

Do not search MCP or subagent surfaces merely because the user names them as
alternatives; require a matching diagnosed gap.

Use the strongest gap as the first query and the best active or partial
capability as its comparator. For each searched surface, record the exact query
and mechanism, whether it was semantic or lexical, active comparator, finalist,
and keep/reject reason.

For each surface, inspect the top finalist first and inspect a second only after
rejecting it. Stop as soon as one verified candidate closes the gap. After two
failed queries or two rejected finalists, record no fit instead of broadening.

Across the whole task, make at most eight external evidence retrievals, counting
search commands, page opens, repository fetches, and inventory commands. Reuse
search metadata and fetch each finalist's repository at most once; inspect its
files and history locally. Do not make separate requests for popularity or
activity when the search result or repository already supplies those signals.

**Complete when:** every selected online surface has a recorded live query and
every gap has a kept candidate or recorded no-fit decision.

## 3. Verify and minimize

Keep a candidate only when its actual instructions or source directly cover the
gap and materially improve on the active comparator. Prefer an active capability
when the difference is negligible. Default to one recommendation; retain
multiple capabilities only when they cover distinct requirements that one
candidate cannot satisfy.

Do not retain optional accelerators, extra workers, or convenient integrations
that are unnecessary for the user's stated outcome. Record them as rejected
finalists in discovery evidence when relevant.

For each retained addition, verify provenance, maintenance, adoption, overlap,
installation command, and the security implications relevant to its capability
kind. Treat popularity as supporting evidence rather than proof of fit or safety.

**Complete when:** every known requirement is covered or explicitly unresolved,
every retained capability has a distinct role, and every addition beats the
active alternative for that role. Label the result **Qualified** when an
unresolved gap or inaccessible evidence could change the set.

## 4. Return the recommendation

Use `# Recommended capability` for one item and `# Recommended capability set`
for multiple items. When no candidate closes any gap, use
`# No additional capability found`, name the best active fallback, and include
the search evidence instead of padding the set. When some gaps close and others
remain unresolved, return the retained recommendation and name the unresolved
gaps under **Uncertainty**.

```markdown
# Recommended capability

## Name — Core tool | Agent Skill | Pi package | MCP server | External integration | Subagent
- **What it adds:** the requirement it covers
- **Why needed:** why active capabilities are insufficient, or why this active capability is sufficient
- **Verification:** direct-fit and trust signals actually checked
- **Status:** Already available | User-run option | Installation unresolved
- **Install:** `<exact command>`
- **Source:** verified URL or local source path

## Discovery evidence
- **Surface:** `<exact query>` via `<mechanism>` → `<finalist>` kept/rejected because `<decision>`.

## Execution shape
`capability + capability → parent execution`

## Uncertainty
- Evidence that could change the recommendation.
```

Omit **Install** for active capabilities, **Source** for core tools and
subagents, and every empty optional section. Include discovery evidence only for
surfaces actually searched. Keep rejected finalists there and nowhere else.
Include an execution shape only when multiple capabilities or handoffs need
coordination. Keep it to a single routing line; do not add configuration or
implementation examples.
