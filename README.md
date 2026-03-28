# Agentic Memory (skill)

Your coding agent doesn’t have to start from zero every session. **Agentic Memory** is a small, opinionated system that actually *keeps* what matters—facts, hunches, war stories, and the occasional hard-won reflection—so the next run can pick up where the last one left off.

No vector DB, no hosted black box: just **Markdown on disk**, a clear **retain → recall → reflect** loop, and stdlib helpers that keep writes safe and reads searchable. It’s built for operators who want memory they can **read, diff, and commit**, not embeddings they have to trust blindly.

## What this skill does

- **Two tiers:** **user** memory at `~/.agents/memory/` and **project** memory at `<repo>/memory/`.
- **Five memory types**, each in its own file: **experiences**, **world knowledge**, **beliefs**, **reflections**, and **entity summaries**.
- **Curated master `MEMORY.md`** at scope root—**one-line previews** of the top world knowledge, beliefs, and entity summaries, with **links** to the full section files; suitable for a thin include in `AGENTS.md` (regenerate with **`curate`**, which can **migrate** an oversized legacy master automatically). Users can ask explicitly: **“Curate your memories”** — see **`ref/curate.md`**.
- **Operations:** remember (guarded write), show/recall (read & search), reflect, maintain (including **maintenance-report** for stale / weak-source candidates), promote (user → project), forget, **migrate** (single → multi-file), **curate** (thin master from sections; **auto-migrates** a fat monolithic `MEMORY.md` first).
- **Task closure:** When the user signals **we're done** / **task complete** / session **goodbye** after real work, the host runs the **task-done sweep** (`ref/task-done.md`): learnings question → one **`remember` subagent per lesson** → report (optional **`reflect`** if substantial). Not optional pleasantries-only exits.
- **Strict subagents:** The **host** must **never** run `ref/reflect.md` itself. Reflection **always** executes inside a subagent: **`action: reflect`** (dedicated) or **auto-reflect inside `action: remember`** (`ref/retain.md`). Explicit requests (e.g. **"reflect on your memories"**) require a **dedicated reflect subagent**. The same non-negotiable pattern applies to **remember**, **maintain**, and **promote** for their workflows.
- **Procedures vs memory:** durable team **how-tos** belong in **versioned skills / docs / `AGENTS.md`**; `MEMORY.md` stays the **episodic and belief cache** (see **`SKILL.md`** and **`ref/maintain.md`**).
- **Experience outcomes:** optional `{outcome: …}` / `{evidence: …}` on experiences sharpen **reflect** and put **failures first** in digests (`ref/format.md`, **`ref/reflect.md`**).
- **Helpers:** recall and management capabilities live under **`skills/memory/scripts/`** (stdlib only, no extra packages). See **`ref/scripts.md`**.
- **Per-product model presets (integrators):** optional **`hosts.*`** in **`~/.agents/memory/memory-skill.config.json`**. **config-hints** auto-detects the active product when possible (e.g. **`CLAUDECODE`**); use **`MEMORY_SKILL_HOST`** or **`--host`** to override—see [Configuration options](#configuration-options).
- **Backward compatible:** if only a single `MEMORY.md` exists (legacy layout), loading falls back to that file until section layout is used.

Authoritative behavior and trigger phrases live in **`SKILL.md`**. This README is the on-ramp for humans and for wiring the skill into other products.

## Research basis

The architecture is **inspired by [Hindsight](https://arxiv.org/abs/2512.12818)** (*Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects*), which organizes memory into multiple logical networks and emphasizes **retain / recall / reflect** over flat chat logs.

This implementation:

- Uses **Markdown files** instead of the paper's full system stack.
- Aligns with Hindsight-style **separation of facts, experiences, evolving beliefs, and entity-centric summaries**.
- Adds an explicit **Reflections** section and **two-tier scoping** (user vs project) for local vs team-shared memory.

It is **not** a faithful reproduction of every detail in the paper; it is a **practical, text-first** adaptation for coding agents.

## Install

Requirements: **Python 3** available to the host that runs the skill’s stdlib helpers.

**Operators** only need to place this skill where the product loads skills from. **Routine memory use** (recall, remember, reflect, etc.) happens when the **agent** follows **`SKILL.md`**—you do not invoke helpers yourself. See [Using memory](#using-memory). **Configuration** and **Tests** below are for **integrators and maintainers** only. **User** memory under `~/.agents/memory/` is created automatically the first time recall or a write touches user scope (no manual initialization).

### Cursor

1. Copy or clone this repository so the skill root (where `SKILL.md` lives) appears as:

   **`.cursor/skills/memory/`**
   i.e. `.cursor/skills/memory/SKILL.md`, `.cursor/skills/memory/scripts/`, etc.

   Options:

   - **Submodule (recommended for teams):** add this repo as a submodule at `skills/memory`, then symlink:

     `ln -s ../../skills/memory .cursor/skills/memory`

   - **Direct copy:** clone into `.cursor/skills/memory/` (contents at that folder's root, not nested `agent-memory/SKILL.md`).

2. Ensure **Agent Skills** loads project skills from `.cursor/skills/`.

3. Point your **agent** instructions at **`SKILL.md`** (and optionally the [recommended `AGENTS.md` snippet](#recommended-agent-wiring-agentsmd)) so the agent performs recall and other memory actions—you do not invoke helpers yourself for day-to-day work.

4. **Integrators only:** with [per-tool `hosts.*` blocks](#subagent-model-presets-memory-skillconfigjson), **`config-hints`** usually auto-selects **cursor** when Cursor-injected env vars are present; use **`MEMORY_SKILL_HOST=cursor`** or **`--host cursor`** only if inference is wrong (see **`ref/config.md`**).

### OpenAI Codex (CLI / IDE)

1. Clone this repository so the skill root (where `SKILL.md` lives) is at **`$CODEX_HOME/skills/memory`**:

   ```bash
   git clone git@github.com:fcarucci/agent-memory.git "$CODEX_HOME/skills/memory"
   ```

2. With **`CODEX_HOME`** set, Codex loads skills from **`$CODEX_HOME/skills`** by default.

3. Use memory by having the **agent** follow **`SKILL.md`**. The agent runs the skill’s helpers in the right context for your project; you do not invoke them manually for normal work.

4. **Integrators only:** for **Codex**, set **`MEMORY_SKILL_HOST=codex`** or pass **`--host codex`** to **config-hints** (auto-detection for Codex is not available yet). See [Subagent model presets](#subagent-model-presets-memory-skillconfigjson).

### Claude (Claude Code / team setups)

1. Copy or symlink this repository so the skill root lives at **`.claude/skills/memory/`** (i.e. `.claude/skills/memory/SKILL.md`, `scripts/`, etc.).

2. Ensure Claude Code (or your team harness) loads skills from **`.claude/skills/`**.

3. Use memory **only through the skill:** point **agent** rules at **`SKILL.md`** (and the [recommended `AGENTS.md` snippet](#recommended-agent-wiring-agentsmd) if you use that pattern). The **agent** follows the skill when **`SKILL.md`** says to—same model as Cursor and Codex. Do not invoke the skill’s helpers yourself for routine memory work.

4. **Integrators only:** **Claude Code** sets **`CLAUDECODE`** in spawned shells, so **`config-hints`** typically auto-merges **`hosts.claude`** without extra env. Override with **`MEMORY_SKILL_HOST`** if needed (see [Subagent model presets](#subagent-model-presets-memory-skillconfigjson)).

## File layout

### Project scope

```
<repo>/MEMORY.md                          # curated master (world knowledge + beliefs + entity summaries)
<repo>/memory/experiences.md              # all experiences
<repo>/memory/world_knowledge.md          # verified facts
<repo>/memory/beliefs.md                  # subjective judgments
<repo>/memory/reflections.md              # higher-level patterns
<repo>/memory/entity_summaries.md         # synthesized entity profiles
```

### User scope

```
~/.agents/memory/MEMORY.md                # curated master
~/.agents/memory/experiences.md           # all experiences
~/.agents/memory/world_knowledge.md
~/.agents/memory/beliefs.md
~/.agents/memory/reflections.md
~/.agents/memory/entity_summaries.md
```

### Path discovery

The skill **does not assume** a fixed install path. Path resolution for the **project** `MEMORY.md` walks:

1. Walking **upward from cwd** for the first `MEMORY.md`.
2. Walking **upward from the helper’s directory** in `scripts/`.
3. Falling back to **`./MEMORY.md`** (natural default when cwd is the project root).

Section files are derived from the master path: **`<master-parent>/memory/`** for project scope, **`<master-parent>/`** for user scope.

Writes go to the **per-section files**. The curated master is regenerated automatically at the end of every **reflect** and **retain** (auto-reflect) operation, or on demand via the **curation** step in **`SKILL.md`** / **`ref/retain.md`**.

## Using memory

**End users and operators** do not run the memory Python scripts. You interact **only through your coding agent**, which follows **`SKILL.md`**. Natural language is enough:

- **Orient at session start:** rely on your product’s rules (or ask the agent) to load memory context the way **`SKILL.md`** describes under *Automatic memory retrieval*—not by running recall commands yourself.
- **Before deep work on a topic:** ask what it remembers about that topic (or equivalent); the skill’s recall workflow applies.
- **Save something for later:** use the trigger phrases in **`SKILL.md`** (e.g. “remember this”, “don’t forget …”); the agent runs the guarded retain path and subagent rules defined there.
- **Project vs user scope, promotion, reflection, maintenance:** all dispatch tables and procedures live in **`SKILL.md`** and **`ref/`**—still no direct script use on your side.

The helpers under **`skills/memory/scripts/`** exist so the **agent** (and integrators) can implement those workflows. What they expose is summarized in **`ref/scripts.md`**; that file does not list copy-paste shell—follow **`SKILL.md`** for procedure.

### Recommended agent wiring (`AGENTS.md`)

Paste something minimal like this into repo or global agent instructions so behavior stays skill-driven:

```markdown
## Agent memory

Read and follow [`skills/memory/SKILL.md`](skills/memory/SKILL.md) for every memory operation: session and pre-task recall, remember / reflect / maintain / promote, subagent spawns, and when supporting helpers may run. Do not edit `MEMORY.md` or per-section files directly for routine writes. Do not tell end users to invoke anything under `skills/memory/scripts/`; they use memory only through this skill.

If you resolve models from `memory-skill.config.json`, run **config-hints** in the same environment as the agent: host selection is **`--host` → `MEMORY_SKILL_HOST` → auto-inference** (`CLAUDECODE`, Cursor signals, …). Inspect **`host_resolution`** in the JSON output (see [`ref/config.md`](ref/config.md)).
```

Adjust paths if your install uses `.cursor/skills/memory/` or another prefix.

## Configuration options

### Paths

| Location | How it is chosen |
|----------|------------------|
| Project `MEMORY.md` | cwd walk → script-dir walk → `cwd/MEMORY.md`. |
| Project section files | `<MEMORY.md parent>/memory/*.md`. |
| User `MEMORY.md` | `~/.agents/memory/MEMORY.md`. |
| User section files | `~/.agents/memory/*.md` (alongside master). |

Hosts may pass an explicit memory file path when the skill’s workflows allow it (see **`ref/scripts.md`** / helper docs); not an end-user step.

### Subagent model presets (`memory-skill.config.json`)

**Audience:** integrators wiring subagent spawns (Cursor, Claude Code, Codex, or custom hosts)—not end users.

Optional file next to user `MEMORY.md`: **`~/.agents/memory/memory-skill.config.json`**. It maps memory **subagent** actions (`remember`, `reflect`, `maintain`, `promote`) to **preset names** or **direct model ids**, and optional **overrides** (e.g. a stronger model when auto-reflect runs after retain). Goal: use a **cheaper** model for routine retains and a **stronger** one for reflect when your platform allows it.

| Layer | Purpose |
|-------|---------|
| **Global** (`presets`, `actions`, `overrides`, `default_preset`) | Default routing for every product unless a **host** block overrides it. |
| **`hosts.cursor`**, **`hosts.claude`**, **`hosts.codex`** | Per-tool overrides. Each block may define its own `presets` and/or `actions` and/or `overrides` and/or `default_preset`. Values are **merged over** the global layer for that product only—omit a tool entirely if global settings are enough. |

**Merge order for one product:** start from the global fields, then apply `hosts.<tool>` on top. Preset **names** (`strong`, `balanced`, `fast`) stay stable; the **model id strings** inside `presets` differ per vendor.

**Which `hosts.*` block applies:** the helper resolves **`cursor` / `claude` / `codex`** automatically when it can (see **`ref/config.md`** for signals). Precedence is **`config-hints --host`** → **`MEMORY_SKILL_HOST`** → **inference**. **`config-hints`** prints **`host`** and **`host_resolution`** so you can confirm. Use **`MEMORY_SKILL_DISABLE_HOST_INFERENCE=1`** to force globals-only unless `--host` / **`MEMORY_SKILL_HOST`** is set (common in tests).

**Example — host-specific model ids** (same preset *names*, different vendor strings):

```json
{
  "version": 1,
  "default_preset": "balanced",
  "presets": {
    "strong": "gpt-5.2",
    "balanced": "gpt-5-mini",
    "fast": "gpt-5-nano"
  },
  "actions": {
    "remember": "fast",
    "reflect": "strong",
    "maintain": "balanced",
    "promote": "balanced"
  },
  "overrides": {
    "remember_when_auto_reflect": "strong"
  },
  "hosts": {
    "cursor": {
      "presets": {
        "strong": "claude-sonnet-4-5-thinking",
        "balanced": "default",
        "fast": "claude-haiku-4-5"
      }
    },
    "claude": {
      "presets": {
        "strong": "claude-opus-4-5-20251101",
        "balanced": "claude-sonnet-4-5-20250929",
        "fast": "claude-haiku-4-5-20251001"
      }
    },
    "codex": {
      "presets": {
        "strong": "o3",
        "balanced": "gpt-5.1-codex",
        "fast": "gpt-5-nano"
      }
    }
  }
}
```

In **Claude Code**, **`CLAUDECODE=1`** usually makes **config-hints** merge **`hosts.claude`** without setting **`MEMORY_SKILL_HOST`**. In **Cursor**, **`CURSOR_TRACE_ID`** or **`CURSOR_AGENT`** typically selects **`hosts.cursor`**. For **Codex**, set **`MEMORY_SKILL_HOST=codex`** (or **`--host codex`**) until a stable auto-detect signal exists.

A fuller template with placeholder ids is in [`ref/memory-skill.config.example.json`](ref/memory-skill.config.example.json).

**Alternate config file location:** **`MEMORY_SKILL_CONFIG_PATH`** points at a different JSON path (tests or nonstandard layouts).

**Further reading:**

- **Spec:** [`ref/config.md`](ref/config.md)
- **Example (global + all three `hosts` stubs):** [`ref/memory-skill.config.example.json`](ref/memory-skill.config.example.json)
- **What the helpers expose:** [`ref/scripts.md`](ref/scripts.md) (no copy-paste shell; see **`SKILL.md`** for agent procedure)

### Scopes

- **User**, **project**, or **both** (default for queries): control which tier is read or written; exact flags are documented in **`ref/recall.md`** and management workflows in **`ref/retain.md`**.

### Behavior constants (implementation)

Duplicate detection threshold, context tags, entity heuristics, and sensitive-value screening live in the **management helper** sources under `skills/memory/scripts/` (e.g. `DUPLICATE_THRESHOLD`, `CANONICAL_CONTEXT_TAGS`).

### Tests

**Maintainers** run the bundled tests under `skills/memory/scripts/` after changing helpers, using the repo’s expected Python environment.

---

**Repository:** [github.com/fcarucci/agent-memory](https://github.com/fcarucci/agent-memory)
**License:** See `LICENSE` in this repository.
