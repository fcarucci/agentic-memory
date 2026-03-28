---
name: memory
description: >
  Persistent memory system for the agent. Two-tier storage: user
  (~/.agents/memory/MEMORY.md) and project (<repo>/MEMORY.md).
  Five memory networks: experiences, world knowledge, beliefs,
  reflections, entity summaries. Task closure ("we're done", etc.)
  triggers a mandatory task-done memory sweep (remember subagents per
  ref/task-done.md). All reflect workflow execution runs inside a
  subagent (reflect-only or remember+auto-reflect)—never on the
  host/orchestrator turn.
---

# Memory System

## Step 1: Determine the action

**Read this table FIRST before doing anything else.** Match the user's
request to an action, then follow only that action's instructions.

| User says | Action | Subagent? | Read these refs |
|-----------|--------|-----------|----------------|
| "Remember this", "Don't forget", "Note that", "Keep in mind" | **remember** | **YES — spawn subagent** | `ref/format.md` + `ref/retain.md` |
| "We're done", "We are done", "That's all", "Task is done", "We're finished", "That wraps it up", "Nothing else", "All set", "Thanks, we're done" (and other **task / conversation closure** after real work — see `ref/task-done.md`) | **task-done sweep** | **YES — one `remember` subagent per lesson** | `ref/task-done.md` + `ref/retain.md` |
| "What do you remember?", "Show me memories", "What are your last memories?" | **show** | No | `ref/recall.md` |
| "What do you know about X?", "Any memories about Y?" | **recall** | No | `ref/recall.md` |
| "Reflect on your memory", "Reflect on your memories", "Reflect on what you remember", "Dream", "Time for a reflection", "Review your beliefs", "Memory reflection", "Do a memory reflect" | **reflect** | **YES — dedicated subagent ONLY (host never runs reflect)** | `ref/reflect.md` + `ref/reflect-techniques.md` + `ref/profile.md` |
| "Maintain memory", "Clean up memory", "Prune stale memories", "Memory hygiene" | **maintain** | **YES — spawn subagent** | `ref/maintain.md` + `ref/reflect.md` (belief rules) |
| "Curate your memories", "Curate my memories", "Curate memory", "Memory curate", "Thin MEMORY.md", "Shrink MEMORY.md", "Regenerate the memory index" | **curate** | No | `ref/curate.md` + `ref/format.md` |
| "Forget about X", "Delete that memory", "Remove the belief about Y" | **forget** | No | `ref/forget.md` |
| "Promote this to the project" | **promote** | **YES — spawn subagent** | `ref/promote.md` |

### Invariant: reflection always runs inside a subagent

The **host / orchestrator** (this conversation turn, main agent, or any
caller that is **not** a spawned memory subagent) **must never** execute
the workflow in `ref/reflect.md`—not even by invoking helpers directly
from the host while skipping a spawn.

**Only two valid execution contexts** for that workflow exist:

1. **Dedicated reflect subagent** — payload `action: reflect` (user asked
   to reflect, session-end reflect step, or any explicit reflect request).
2. **Auto-reflect inside a remember subagent** — when `ref/retain.md`
   triggers after `action: remember`; the **same** remember subagent runs
   the reflect steps; the host still **must not** run them.

There is **no third context**. If reflection happened, a subagent ran it.

**Critical rule (remember):** If the user asks to **store** something (remember,
don't forget, note that, keep in mind), you MUST spawn a subagent.
Do not load a memory digest first, do not run recall, do not do anything else
first. Spawn the subagent immediately with the content to remember.

**Critical rule (reflect):** If the user asks you to **reflect** on memory
—**any** phrasing, including **"reflect on your memories"**, "reflect on
your memory", "reflect on what you remember", dream, review your beliefs,
time for a reflection, memory review—you **MUST spawn a dedicated
`action: reflect` subagent** as the **first** action. See **Invariant:
reflection always runs inside a subagent** above.

You **MUST NOT** (on the **host** turn):

- approximate reflection by reading a digest, `MEMORY.md`, or recall output
  and narrating insights here;
- run `memory-manage.py` / recall helpers from the host to "simulate" a
  reflect pass while skipping a subagent;
- skip the full workflow in `ref/reflect.md` + `ref/reflect-techniques.md` +
  `ref/profile.md`.

**Auto-reflect** after `action: remember` is **only** valid when it ran
**inside the remember subagent** (`ref/retain.md`). It does **not** count
as satisfying a **new** user request to reflect; for that you still
**spawn `action: reflect`**.

**Claiming reflection completed without a subagent having run the
workflow is a skill violation.** After the reflect subagent returns,
report what **it** did (belief deltas, pruning, reflections, curate, etc.)—
do not substitute your own analysis for the subagent’s pass.

**Same non-negotiable pattern** applies to **maintain** and **promote**:
never replace a required subagent with an inline "I'll just read the
files" shortcut; see the Subagent? column in the table above.

**Critical rule (task closure / task-done sweep):** When the user's message
matches **task-done sweep** in the table — or **session-end review** below
(thanks, goodbye, that's all as **closure** after substantive work) — you
**must** run the **remember-what-you-learned** sequence in **`ref/task-done.md`**
**before** ending the turn with only pleasantries. Ask what you learned;
spawn a **`remember` subagent for each** lesson worth keeping; report what
was remembered (or that nothing met the bar). **Do not** skip this because
the user sounded informal ("thanks, we're done"). If the thread had **no**
substantive work, you may state that nothing needed capture after the
internal check. Optional **reflect** subagent after substantial sessions
per **`ref/task-done.md`**.

### How to spawn a remember subagent

```text
Read and follow skills/memory/SKILL.md.

action: remember
content: <the thing to remember, in the user's words or summarized>
context: <tag: debug|testing|tooling|workflow|decision|preference|infra|docs|ui|backend|security>
outcome: <optional: success|failure|mixed|unknown — for clear episode end states>
evidence: <optional: issue id, CI id, doc path — never secrets>
```

The subagent reads SKILL.md, follows the dispatch to `ref/format.md` +
`ref/retain.md`, and executes the full retain workflow: entity extraction,
duplicate checking, format validation, guarded write, and **auto-reflect
when triggered**—**inside this same subagent**, never on the host
(`ref/retain.md`).

After the subagent completes, tell the user what was remembered.

### How to spawn a reflect subagent

Do this **immediately** when the user’s request matches **reflect** in the
table—before narrating, before optional chit-chat, before loading a digest
for your own summary.

```text
Read and follow skills/memory/SKILL.md.

action: reflect
```

If the user restricts reflection to **project** or **user** memory only,
state that in the same spawn message in plain language; the subagent
applies `ref/reflect.md` and **curate** to the appropriate scope.

The subagent executes the **entire** workflow in `ref/reflect.md`
(including techniques and profile), updates beliefs/confidence as
specified, synthesizes reflections when warranted, regenerates the curated
master, and returns a completion report. **You** summarize that report for
the user; you do not substitute your own one-shot analysis for the
subagent’s pass.

## Architecture

Four-network memory model inspired by
[Hindsight](https://arxiv.org/abs/2512.12818), adapted for text-only
markdown storage.

### Cache, not source of truth

`MEMORY.md` (and section files) are a **cache of useful execution and
verified facts**, not an authoritative record of the repo, runtime, or
tools. For high-stakes work, **re-check** code, configs, tests, and live
behavior. Memory should improve future task success, not replace search,
tests, or tooling. Prefer **no new entry** over accumulating low-signal
volume. See `ref/retain.md` (outcome-linked transfer, temporal validity)
and `ref/format.md` (structured episodic traces).

### Procedures vs episodic memory

**`MEMORY.md`** holds **episodic cache**, **verified facts**, **beliefs**,
and **reflections** — optimized for session-to-session recall. **Durable
procedures** (checklists, how-tos, conventions many agents must follow)
should live in **versioned repo skills**, **`AGENTS.md`**, or **docs**
where they are reviewable in PRs. When a lesson stabilizes, prefer
**capturing it there** and keeping memory as a pointer or short reminder,
not a second copy of the full procedure. See `ref/maintain.md`.

### Two-tier scoping

| Scope | Location | Purpose |
|-------|----------|---------|
| **User** | `~/.agents/memory/` | **All new memories go here by default.** |
| **Project** | `<repo>/memory/` | Promotion target only — never written to unless explicitly asked or promoted. |

The **user** directory, curated master, section files, and default `memory-skill.config.json` are **created automatically** on first recall or write to user scope. No separate initialization step.

**Policy:** always write to **user** scope unless the user explicitly says
"remember this in the project" or an entry is explicitly promoted with
`action: promote`.  Recall searches **both** scopes by default so nothing
is lost.

### Five memory networks

| Network | Epistemic role | Has confidence? |
|---------|---------------|----------------|
| **Experiences** | What the agent observed or did | No |
| **World Knowledge** | Verified objective facts | Yes |
| **Beliefs** | Subjective judgments that evolve | Yes |
| **Reflections** | Higher-level patterns from multiple memories | No |
| **Entity Summaries** | Synthesized entity profiles | No |

**Auto-reflect:** The `remember` action automatically triggers a
reflect pass when beliefs are stale, low-confidence, or unsupported
by recent experiences. See `ref/retain.md` for trigger conditions.

Helper layout (no shell recipes): `ref/scripts.md`

## Automatic memory retrieval

### Session-start loading

At the start of every session, load the memory digest into context using the **recall helper** per **`ref/recall.md`** (*Show / digest*): both scopes, structured digest—not raw `MEMORY.md`. The digest includes world knowledge, beliefs, reflections, entity summaries, and recent experiences from user and project scopes where present.

### Pre-task recall

Before starting any task, run a targeted recall against the task topic using the **recall helper** per **`ref/recall.md`** (*Recall*): entity and/or keyword search, cross-section as appropriate, JSON output when useful.

| User says | Recall shape (see `ref/recall.md`) |
|-----------|-----------------------------------|
| "Fix the integration tests" | entity `integration-tests`, cross-section |
| "Work on the API gateway" | entity `api-gateway`, cross-section |
| "The build is failing" | keyword `build`, cross-section |

If no memories match, proceed normally.

## Automatic memory capture

### Post-task sweep (after every completed task)

After completing any task — **before committing** — follow **`ref/task-done.md`**
(the **task-done sweep**): ask:

> "What did I learn that would be useful in a future session?"

If non-empty, **spawn a memory subagent** with `action: remember` for
each lesson, then **tell the user what was remembered**:

> **Remembered:**
> - [debug] The integration test hangs if port 5432 is already bound.
> - [workflow] Running the combined dev command avoids CSS rebuild issues.

This is **not optional** — it is part of the mandatory task completion
sequence (see `docs/agent-workflows/DANEEL_WORKFLOW.md`). The user saying
**we're done** or equivalent is an explicit trigger for the same sweep — see
**Step 1** table (**task-done sweep**) and **Critical rule (task closure)**.

### Session-end review

When the conversation is winding down ("thanks", "goodbye", "that's
all", or task done with no follow-up) **after substantive work**, this is
the **same** sweep as **`ref/task-done.md`** — not optional chit-chat:

1. Scan for uncaptured lessons, surprises, decisions, or workarounds.
2. **Spawn a memory subagent** with `action: remember` for each item.
3. **Tell the user what was remembered** (or that nothing met the bar).
4. If the session was substantial, also spawn a **dedicated**
   **`action: reflect` subagent** (never run reflect from the host turn;
   see **Invariant: reflection always runs inside a subagent**).

Mid-thread "thanks" without closure intent does **not** cancel the
requirement when the user later signals **done**; see **`ref/task-done.md`**
for disambiguation.

## Subagent parameters (for write operations)

| Field | Required | Description |
|------|----------|-------------|
| `action` | yes | `remember`, `recall`, `reflect`, `maintain`, or `promote` |
| `content` | if remember | Narrative memory candidate |
| `context` | no | Tag: `debug`, `testing`, `tooling`, `workflow`, `decision`, `preference`, `infra`, `docs`, `ui`, `backend`, `security` |
| `outcome` | no | Experiences: `success`, `failure`, `mixed`, or `unknown` — sharpens reflect and digest ordering |
| `evidence` | no | Experiences: external pointer (issue URL, CI id); never secrets — see `ref/format.md` |
| `query` | if recall | Search terms, entity, or date range |
| `section` | no | Limit to one section |
| `scope` | no | `user` (default writes), `project`, or `both` (default reads) |
| `index` | if promote | Index in user memory to promote |
| `model_preset` | no | Optional opaque model id or preset label for **this** subagent; the host decides how it maps to a real model. If omitted, resolve presets using the **config-hints** operation described in **`ref/config.md`**. |

### Subagent model selection (orchestrator)

Memory helpers do not call language models. To use **different models** per subagent action (`remember`, `reflect`, `maintain`, `promote`), configure:

`~/.agents/memory/memory-skill.config.json`

Full schema, defaults, rationale, and how to obtain resolved model ids: **`ref/config.md`**. Example: **`ref/memory-skill.config.example.json`**.

Before spawning a memory subagent, the host resolves `model_id` for the matching action per **`ref/config.md`** (or honors `model_preset` on the subagent payload when the user overrides). Use **`overrides.remember_when_auto_reflect`** when splitting a cheap retain pass from a stronger auto-reflect pass.

**Per product (Cursor vs Claude vs Codex):** optional **`hosts.*`** in `memory-skill.config.json` override globals for that tool. **config-hints** resolves the active tool via **`--host`**, then **`MEMORY_SKILL_HOST`**, then **automatic inference** (e.g. **`CLAUDECODE`** for Claude Code, Cursor trace/agent env vars). See **`ref/config.md`** and **`host_resolution`** in the hints JSON. Override with **`MEMORY_SKILL_HOST`** or **`--host`** when inference is wrong; use **`MEMORY_SKILL_DISABLE_HOST_INFERENCE=1`** to disable inference (e.g. tests).

## Invocation examples

### Remember (spawn subagent)

```text
Read and follow skills/memory/SKILL.md.

action: remember
content: The integration test suite requires port 5432 to be free; it hangs if another process is already bound.
context: testing
```

### Remember to project scope (spawn subagent)

```text
Read and follow skills/memory/SKILL.md.

action: remember
content: PostgreSQL 16 requires explicit listen_addresses for remote connections.
context: infra
scope: project
```

### Show (run directly)

Run digest recall per **`ref/recall.md`**: default both scopes; optional user-only or project-only; tune recent experience window with `--last` or `--days`.

### Recall (run directly)

Run structured recall per **`ref/recall.md`**: e.g. entity `api-gateway` with cross-section JSON, or keyword `database` with JSON—see that file for the full flag matrix.

### Reflect (spawn subagent)

Same payload as **How to spawn a reflect subagent** above. **Invariant:**
the host never runs `ref/reflect.md`; only a subagent does. See **Critical
rule (reflect)**.

```text
Read and follow skills/memory/SKILL.md.

action: reflect
```

### Maintain (spawn subagent)

```text
Read and follow skills/memory/SKILL.md.

action: maintain
```

Follow **`ref/maintain.md`** (validation, **maintenance-report**, belief
review, curate).

### Promote (spawn subagent)

After a successful promote, follow **`ref/promote.md`** **Post-promotion
deduplication**: remove the user-scope copy with **delete-entry** unless the
user asked to keep both.

```text
Read and follow skills/memory/SKILL.md.

action: promote
section: experiences
index: 0
allow_project_promotion: true
```

### Curate (run directly)

When the user asks to **curate** memories (see dispatch table), run the
management helper **curate** per **`ref/curate.md`**. No subagent — report
paths, counts, and any **migrate** that ran.

### Forget (run directly)

See `ref/forget.md` for the full workflow.

### Task-done / session-end (memory sweep)

When the user signals **task completion** or **conversation closure** after
real work (see **Step 1** table: **task-done sweep**), follow **`ref/task-done.md`**
end-to-end: internal learnings question → one **`remember` subagent per
lesson** → report to user → optional **`reflect`** if substantial.
