# Agent Memory (skill)

Persistent, **structured agent memory** stored as Markdown—not a vector database. The skill coordinates **retain → recall → reflect** workflows, with Python helpers for validation, deduplication, and JSON recall for tooling.

## What this skill does

- **Two tiers:** **user** memory at `~/.agents/memory/` and **project** memory at `<repo>/memory/` (shared, usually via promotion).
- **Five memory types**, each in its own file: **experiences**, **world knowledge**, **beliefs**, **reflections**, and **entity summaries**.
- **Curated master `MEMORY.md`** at scope root—a compact subset of world knowledge, beliefs, and entity summaries suitable for direct inclusion in `AGENTS.md`.
- **Operations:** remember (guarded write), show/recall (read & search), reflect, maintain, promote (user → project), forget, **migrate** (single → multi-file), **curate** (regenerate master from section files).
- **Scripts:** `memory-recall.py` (digest and structured query) and `memory-manage.py` (append, validate, duplicates, confidence updates, promotion, migration, curation, etc.). No extra pip packages.
- **Backward compatible:** if only a single `MEMORY.md` exists (legacy layout), the scripts fall back to reading/writing it.

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

Writes go to the **per-section files**. The curated master is regenerated on demand with `memory-manage.py curate`.

## Install

Requirements: **Python 3** on `PATH` (`python3`). Scripts are plain stdlib.

### Path discovery

The skill **does not assume** a fixed install path. Scripts resolve the **project** `MEMORY.md` by:

1. Walking **upward from cwd** for the first `MEMORY.md`.
2. Walking **upward from the script's directory**.
3. Falling back to **`./MEMORY.md`** (natural default when cwd is the project root).

Section files are derived from the master path: **`<master-parent>/memory/`** for project scope, **`<master-parent>/`** for user scope.

### Cursor

1. Copy or clone this repository so the skill root (where `SKILL.md` lives) appears as:

   **`.cursor/skills/memory/`**  
   i.e. `.cursor/skills/memory/SKILL.md`, `.cursor/skills/memory/scripts/`, etc.

   Options:

   - **Submodule (recommended for teams):** add this repo as a submodule at `skills/memory`, then symlink:

     `ln -s ../../skills/memory .cursor/skills/memory`

   - **Direct copy:** clone into `.cursor/skills/memory/` (contents at that folder's root, not nested `agent-memory/SKILL.md`).

2. Ensure **Agent Skills** loads project skills from `.cursor/skills/`.

3. Agents can run from the **repository root**:

   `python3 skills/memory/scripts/memory-recall.py --show`

### OpenAI Codex (CLI / IDE)

```bash
git clone git@github.com:fcarucci/agent-memory.git "$CODEX_HOME/skills/memory"
```

Run memory scripts with **cwd** under the project tree so upward discovery finds the correct `MEMORY.md`.

### Claude (Claude Code / team setups)

Copy or symlink this repo so you have `.claude/skills/memory/SKILL.md`, etc. Use the same Python commands from the repo root.

### Initialize user memory (once per machine)

```bash
python3 skills/memory/scripts/memory-manage.py init-user
```

This creates `~/.agents/memory/MEMORY.md` (curated master) and all five section files.

### Migrate from single-file layout

If you have an existing single-file `MEMORY.md` with all sections, split it into per-section files:

```bash
python3 skills/memory/scripts/memory-manage.py migrate --scope project
python3 skills/memory/scripts/memory-manage.py migrate --scope user
```

This backs up the original as `MEMORY.md.bak`, creates the section files, and replaces the master with the curated template.

## How to use

1. **Session start:** load context without reading raw files:

   `python3 skills/memory/scripts/memory-recall.py --show`

2. **Before a task:** targeted recall:

   `python3 skills/memory/scripts/memory-recall.py --entity "<topic>" --cross-section --json`

3. **Storing memories:** follow **`SKILL.md`**—user phrases like "remember this" require spawning a subagent with `action: remember`.

4. **Regenerate curated master:**

   `python3 skills/memory/scripts/memory-manage.py curate --scope project`

5. **Validate section files:**

   `python3 skills/memory/scripts/memory-manage.py validate-sections --scope user`

Full CLI examples: **`ref/scripts.md`**.

### Minimal `AGENTS.md` (or global agent instructions)

```markdown
## Agent memory

**Skill:** read and follow [`skills/memory/SKILL.md`](skills/memory/SKILL.md).

**Session start:** run structured recall (not raw file reads):

`python3 skills/memory/scripts/memory-recall.py --show`

**Before starting work on a task:** run targeted recall, e.g.:

`python3 skills/memory/scripts/memory-recall.py --entity "<task-topic>" --cross-section --json`

**Storing memories:** follow `SKILL.md` and spawn a subagent for `action: remember`—do not edit memory files directly for routine writes.

**Curated master:** `MEMORY.md` at the repo root is a curated subset of
world knowledge, beliefs, and entity summaries. Regenerate with
`memory-manage.py curate --scope project`. Full memories live in
per-section files under `memory/`.
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

Use **`--file <path>`** on `memory-recall.py` or `memory-manage.py` to override scope resolution for a single invocation.

### Scopes (CLI)

- **`--scope user`**, **`--scope project`**, **`--scope both`** (default for queries): control which scope(s) are read or written.

### Behavior constants (code)

Duplicate detection threshold, context tags, entity heuristics, and sensitive-value screening live in **`memory-manage.py`** (e.g. `DUPLICATE_THRESHOLD`, `CANONICAL_CONTEXT_TAGS`).

### Tests

```bash
python3 skills/memory/scripts/memory-recall.test.py
```

---

**Repository:** [github.com/fcarucci/agent-memory](https://github.com/fcarucci/agent-memory)  
**License:** See `LICENSE` in this repository.
