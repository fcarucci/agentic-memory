---
name: memory
description: >
  Persistent memory system for the agent. Two-tier storage: user
  (~/.agents/memory/MEMORY.md) and project (<repo>/MEMORY.md).
  Five memory networks: experiences, world knowledge, beliefs,
  reflections, entity summaries.
---

# Memory System

## Step 1: Determine the action

**Read this table FIRST before doing anything else.** Match the user's
request to an action, then follow only that action's instructions.

| User says | Action | Subagent? | Read these refs |
|-----------|--------|-----------|----------------|
| "Remember this", "Don't forget", "Note that", "Keep in mind" | **remember** | **YES — spawn subagent** | `ref/format.md` + `ref/retain.md` |
| "What do you remember?", "Show me memories", "What are your last memories?" | **show** | No | `ref/recall.md` |
| "What do you know about X?", "Any memories about Y?" | **recall** | No | `ref/recall.md` |
| "Reflect on your memory", "Dream", "Time for a reflection", "Review your beliefs" | **reflect** | **YES — spawn subagent** | `ref/reflect.md` + `ref/reflect-techniques.md` + `ref/profile.md` |
| "Forget about X", "Delete that memory", "Remove the belief about Y" | **forget** | No | `ref/forget.md` |
| "Promote this to the project" | **promote** | **YES — spawn subagent** | `ref/promote.md` |

**Critical rule:** If the user asks to **store** something (remember,
don't forget, note that, keep in mind), you MUST spawn a subagent.
Do not load a memory digest first, do not run recall, do not do anything else
first. Spawn the subagent immediately with the content to remember.

### How to spawn a remember subagent

```text
Read and follow skills/memory/SKILL.md.

action: remember
content: <the thing to remember, in the user's words or summarized>
context: <tag: debug|testing|tooling|workflow|decision|preference|infra|docs|ui|backend|security>
```

The subagent reads SKILL.md, follows the dispatch to `ref/format.md` +
`ref/retain.md`, and executes the full retain workflow: entity extraction,
duplicate checking, format validation, guarded write, and auto-reflect.

After the subagent completes, tell the user what was remembered.

## Architecture

Four-network memory model inspired by
[Hindsight](https://arxiv.org/abs/2512.12818), adapted for text-only
markdown storage.

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

After completing any task — **before committing** — ask:

> "What did I learn that would be useful in a future session?"

If non-empty, **spawn a memory subagent** with `action: remember` for
each lesson, then **tell the user what was remembered**:

> **Remembered:**
> - [debug] The integration test hangs if port 5432 is already bound.
> - [workflow] Running the combined dev command avoids CSS rebuild issues.

This is **not optional** — it is part of the mandatory task completion
sequence (see `docs/agent-workflows/DANEEL_WORKFLOW.md`).

### Session-end review

When the conversation is winding down ("thanks", "goodbye", "that's
all", or task done with no follow-up):

1. Scan for uncaptured lessons, surprises, decisions, or workarounds.
2. **Spawn a memory subagent** with `action: remember` for each item.
3. **Tell the user what was remembered.**
4. If the session was substantial, also spawn `action: reflect`.

## Subagent parameters (for write operations)

| Field | Required | Description |
|------|----------|-------------|
| `action` | yes | `remember`, `recall`, `reflect`, `maintain`, or `promote` |
| `content` | if remember | Narrative memory candidate |
| `context` | no | Tag: `debug`, `testing`, `tooling`, `workflow`, `decision`, `preference`, `infra`, `docs`, `ui`, `backend`, `security` |
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

**Per product (Cursor vs Claude vs Codex):** optional **`hosts.cursor`**, **`hosts.claude`**, and **`hosts.codex`** in `memory-skill.config.json` override presets (and optionally `actions` / `overrides`) for that tool only. Set environment variable **`MEMORY_SKILL_HOST`** to `cursor`, `claude`, or `codex` when running **config-hints** so the merged routing matches the active product (see **`ref/config.md`**).

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

```text
Read and follow skills/memory/SKILL.md.

action: reflect
```

### Maintain (spawn subagent)

```text
Read and follow skills/memory/SKILL.md.

action: maintain
```

### Promote (spawn subagent)

```text
Read and follow skills/memory/SKILL.md.

action: promote
section: experiences
index: 0
allow_project_promotion: true
```

### Forget (run directly)

See `ref/forget.md` for the full workflow.
