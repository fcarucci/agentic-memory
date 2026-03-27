# Agent Memory (skill)

Persistent, **structured agent memory** stored as Markdown—not a vector database. The skill coordinates **retain → recall → reflect** workflows; validation, deduplication, and structured recall are implemented by helpers shipped with the skill (see **`ref/scripts.md`**).

## What this skill does

- **Two tiers:** **user** memory at `~/.agents/memory/` and **project** memory at `<repo>/memory/` (shared, usually via promotion).
- **Five memory types**, each in its own file: **experiences**, **world knowledge**, **beliefs**, **reflections**, and **entity summaries**.
- **Curated master `MEMORY.md`** at scope root—a compact subset of world knowledge, beliefs, and entity summaries suitable for direct inclusion in `AGENTS.md`.
- **Operations:** remember (guarded write), show/recall (read & search), reflect, maintain, promote (user → project), forget, **migrate** (single → multi-file), **curate** (regenerate master from section files).
- **Helpers:** recall and management capabilities live under **`skills/memory/scripts/`** (stdlib only, no extra packages). See **`ref/scripts.md`**.
- **Backward compatible:** if only a single `MEMORY.md` exists (legacy layout), loading falls back to that file until section layout is used.

Authoritative behavior and trigger phrases live in **`SKILL.md`**. This README is the on-ramp for humans and for wiring the skill into other products.

## Research basis

The architecture is **inspired by [Hindsight](https://arxiv.org/abs/2512.12818)** (*Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects*), which organizes memory into multiple logical networks and emphasizes **retain / recall / reflect** over flat chat logs.

This implementation:

- Uses **Markdown files** instead of the paper's full system stack.
- Aligns with Hindsight-style **separation of facts, experiences, evolving beliefs, and entity-centric summaries**.
- Adds an explicit **Reflections** section and **two-tier scoping** (user vs project) for local vs team-shared memory.

It is **not** a faithful reproduction of every detail in the paper; it is a **practical, text-first** adaptation for coding agents.

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

### OpenAI Codex (CLI / IDE)

1. Clone this repository so the skill root (where `SKILL.md` lives) is at **`$CODEX_HOME/skills/memory`**:

   ```bash
   git clone git@github.com:fcarucci/agent-memory.git "$CODEX_HOME/skills/memory"
   ```

2. With **`CODEX_HOME`** set, Codex loads skills from **`$CODEX_HOME/skills`** by default.

3. Use memory by having the **agent** follow **`SKILL.md`**. The agent runs the skill’s helpers in the right context for your project; you do not invoke them manually for normal work.

### Claude (Claude Code / team setups)

1. Copy or symlink this repository so the skill root lives at **`.claude/skills/memory/`** (i.e. `.claude/skills/memory/SKILL.md`, `scripts/`, etc.).

2. Ensure Claude Code (or your team harness) loads skills from **`.claude/skills/`**.

3. Use memory **only through the skill:** point **agent** rules at **`SKILL.md`** (and the [recommended `AGENTS.md` snippet](#recommended-agent-wiring-agentsmd) if you use that pattern). The **agent** follows the skill when **`SKILL.md`** says to—same model as Cursor and Codex. Do not invoke the skill’s helpers yourself for routine memory work.

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

Optional JSON next to user `MEMORY.md`: **`~/.agents/memory/memory-skill.config.json`**. Maps memory **subagent** actions (`remember`, `reflect`, `maintain`, `promote`) to named presets or direct model ids so orchestrators can spawn with a **stronger** model for reflect and a **cheaper** one for routine retains when appropriate.

- **Spec:** [`ref/config.md`](ref/config.md)
- **Example:** [`ref/memory-skill.config.example.json`](ref/memory-skill.config.example.json)
- **Validate / resolved model hints for spawns:** see [`ref/config.md`](ref/config.md) and [`ref/scripts.md`](ref/scripts.md) (host / maintainer—not operator-facing).
- **Override path:** env `MEMORY_SKILL_CONFIG_PATH` or per-run skill-config override as described in [`ref/config.md`](ref/config.md).

### Scopes

- **User**, **project**, or **both** (default for queries): control which tier is read or written; exact flags are documented in **`ref/recall.md`** and management workflows in **`ref/retain.md`**.

### Behavior constants (implementation)

Duplicate detection threshold, context tags, entity heuristics, and sensitive-value screening live in the **management helper** sources under `skills/memory/scripts/` (e.g. `DUPLICATE_THRESHOLD`, `CANONICAL_CONTEXT_TAGS`).

### Tests

**Maintainers** run the bundled tests under `skills/memory/scripts/` after changing helpers, using the repo’s expected Python environment.

---

**Repository:** [github.com/fcarucci/agent-memory](https://github.com/fcarucci/agent-memory)  
**License:** See `LICENSE` in this repository.
