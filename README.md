# Agent Memory (skill)

Persistent, **structured agent memory** stored as Markdown—not a vector database. The skill coordinates **retain → recall → reflect** workflows, with Python helpers for validation, deduplication, and JSON recall for tooling.

## What this skill does

- **Two tiers:** **user** memory at `~/.agents/memory/MEMORY.md` (default for new writes) and **project** memory at `<repository-root>/MEMORY.md` (shared, usually via promotion).
- **Five networks** in each file: **Experiences**, **World knowledge**, **Beliefs**, **Reflections**, and **Entity summaries**—each with a defined epistemic role (see `SKILL.md` and `ref/format.md`).
- **Operations:** remember (guarded write), show/recall (read & search), reflect, maintain, promote (user → project), forget—driven by `SKILL.md` dispatch tables and `ref/*.md` playbooks.
- **Scripts:** `memory-recall.py` (digest and structured query) and `memory-manage.py` (append, validate, duplicates, confidence updates, promotion, etc.). No extra pip packages for core flows.

Authoritative behavior and trigger phrases live in **`SKILL.md`**. This README is the on-ramp for humans and for wiring the skill into other products.

## Research basis

The architecture is **inspired by [Hindsight](https://arxiv.org/abs/2512.12818)** (*Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects*), which organizes memory into multiple logical networks and emphasizes **retain / recall / reflect** over flat chat logs.

This implementation:

- Uses **Markdown files** instead of the paper’s full system stack.
- Aligns with Hindsight-style **separation of facts, experiences, evolving beliefs, and entity-centric summaries**.
- Adds an explicit **Reflections** section and **two-tier scoping** (user vs project) for local vs team-shared memory—see `SKILL.md` → Architecture.

It is **not** a faithful reproduction of every detail in the paper; it is a **practical, text-first** adaptation for coding agents.

## Install

Requirements: **Python 3** on `PATH` (`python3`). Scripts are plain stdlib.

### Where `MEMORY.md` is found (project scope)

The skill **does not assume** a fixed folder layout. **`memory-recall.py`** and **`memory-manage.py`** resolve the project file in this order:

1. **`AGENT_MEMORY_PROJECT_FILE`** — explicit path to `MEMORY.md`.
2. **`AGENT_MEMORY_PROJECT_ROOT`** — directory; the file is `<root>/MEMORY.md`.
3. Walk **upward from the current working directory** and use the first `MEMORY.md` found (typical when the agent runs from the repo root or a subdirectory).
4. Walk **upward from the script’s directory** (so the skill can live under `.cursor/skills/memory`, `skills/memory`, or anywhere else **inside** the repo tree and still find the project’s `MEMORY.md`).
5. If nothing exists yet: **`./MEMORY.md`** relative to the current working directory (creates a natural default when you start from the project root).

**User** memory defaults to `~/.agents/memory/MEMORY.md` unless you set **`AGENT_MEMORY_USER_FILE`** or **`AGENT_MEMORY_USER_ROOT`** (see [Configuration options](#configuration-options)).

### Cursor

1. Copy or clone this repository so the skill root (where `SKILL.md` lives) appears as:

   **`.cursor/skills/memory/`**  
   i.e. `.cursor/skills/memory/SKILL.md`, `.cursor/skills/memory/scripts/`, etc.

   Options:

   - **Submodule (recommended for teams):** add this repo as a submodule at `skills/memory`, then symlink:

     `ln -s ../../skills/memory .cursor/skills/memory`  
     (paths relative to your repo layout—keep `SKILL.md` at the symlink target root.)

   - **Direct copy:** clone into `.cursor/skills/memory/` (contents at that folder’s root, not nested `agent-memory/SKILL.md`).

2. Ensure **Agent Skills** (or your Cursor version’s equivalent) loads project skills from `.cursor/skills/`.

3. From the **repository root**, agents can run:

   `python3 skills/memory/scripts/memory-recall.py --show`  
   only if that path exists; if the skill exists **only** under `.cursor/skills/memory`, use:

   `python3 .cursor/skills/memory/scripts/memory-recall.py --show`  
   or symlink `skills/memory` → `.cursor/skills/memory` for one canonical path.

### OpenAI Codex (CLI / IDE)

Codex loads skills from user skill directories (e.g. under **`$CODEX_HOME/skills`**). Install by placing this skill as a folder named **`memory`** with `SKILL.md` at its root:

```bash
# Example: clone into Codex user skills (adjust if your install uses another root)
git clone git@github.com:fcarucci/agent-memory.git "$CODEX_HOME/skills/memory"
```

If you use a **project-relative** skill path instead, mirror the same **flat** layout: `…/memory/SKILL.md`, not `…/memory/agent-memory/SKILL.md`.

Restart or refresh Codex so new skills are discovered. Prefer running tools with **cwd = project root**, or set **`AGENT_MEMORY_PROJECT_FILE`** / **`AGENT_MEMORY_PROJECT_ROOT`** so project memory is unambiguous.

### Claude (Claude Code / team setups)

Typical pattern: project skills under **`.claude/skills/`**. Copy or symlink this repo so you have:

`.claude/skills/memory/SKILL.md`  
`.claude/skills/memory/scripts/*.py`  
etc.

Point your agent instructions at **`SKILL.md`** and use the same Python commands from the git **repository root** where `MEMORY.md` should live, adjusting script prefixes if needed.

### Initialize user memory (once per machine)

```bash
python3 skills/memory/scripts/memory-manage.py init-user
```

(Run from project root, or substitute your install path.)

## How to use

1. **Session start:** load context without reading raw files:

   `python3 skills/memory/scripts/memory-recall.py --show`

2. **Before a task:** targeted recall:

   `python3 skills/memory/scripts/memory-recall.py --entity "<topic>" --cross-section --json`

3. **Storing memories:** follow **`SKILL.md`**—user phrases like “remember this” require spawning a subagent with `action: remember` (see SKILL for exact payload).

4. **Editing `MEMORY.md` by hand:** discouraged for writes; use the retain workflow and `memory-manage.py` so format, entities, and duplicates stay consistent (`ref/retain.md`, `ref/format.md`).

Full CLI examples: **`ref/scripts.md`**.

### Minimal `AGENTS.md` (or global agent instructions)

Add a short block so every agent knows where the skill lives and to use scripts instead of raw `MEMORY.md`:

```markdown
## Agent memory

**Skill:** read and follow [`skills/memory/SKILL.md`](skills/memory/SKILL.md) (or `.cursor/skills/memory/SKILL.md` if that is your only copy).

**Session start:** run structured recall (not raw file reads):

`python3 skills/memory/scripts/memory-recall.py --show`

**Before starting work on a task:** run targeted recall, e.g.:

`python3 skills/memory/scripts/memory-recall.py --entity "<task-topic>" --cross-section --json`

**Storing memories:** when the user asks to remember something, follow `SKILL.md` and spawn a subagent for `action: remember` as specified there—do not edit `MEMORY.md` directly for routine writes.

**Maintaining memory:** use `skills/memory/scripts/memory-manage.py` and the `ref/*.md` workflows; see `ref/scripts.md` for commands.

For write operations, memory subagents must read `SKILL.md` and the referenced `ref/*.md` files in full.
```

Adjust **`skills/memory/`** in every path if your install uses `.cursor/skills/memory/` or another prefix.

**Optional:** if the agent’s working directory is not the repo root, set **`AGENT_MEMORY_PROJECT_ROOT`** or **`AGENT_MEMORY_PROJECT_FILE`** in the environment (see [Configuration options](#configuration-options)).

## Configuration options

### Environment variables (paths)

| Variable | Effect |
|----------|--------|
| **`AGENT_MEMORY_PROJECT_FILE`** | Full path to the project `MEMORY.md` (highest precedence). |
| **`AGENT_MEMORY_PROJECT_ROOT`** | Project directory; uses `<root>/MEMORY.md`. |
| **`AGENT_MEMORY_USER_FILE`** | Full path to the user `MEMORY.md`. |
| **`AGENT_MEMORY_USER_ROOT`** | Directory for user scope; uses `<root>/MEMORY.md`. |

If project variables are unset, resolution uses **cwd walk → script-directory walk → `./MEMORY.md`**, as described above. User scope defaults to **`~/.agents/memory/MEMORY.md`**.

Set these in the agent environment, shell profile, or tool wrapper (Cursor / Codex / Claude) when cwd is not the repo or when multiple projects share one checkout.

### Scopes (CLI)

- **`--scope user`**, **`--scope project`**, **`--scope both`** (default for many queries): control which file(s) are read or written. See `memory-recall.py --help` and `memory-manage.py --help`.

### Behavior constants (code)

Duplicate detection threshold, context tags, entity heuristics, and sensitive-value screening live in **`memory-manage.py`** (e.g. `DUPLICATE_THRESHOLD`, `CANONICAL_CONTEXT_TAGS`). Tune there if you need stricter or looser policies.

### Tests

From repository root:

```bash
python3 skills/memory/scripts/memory-recall.test.py
```

---

**Repository:** [github.com/fcarucci/agent-memory](https://github.com/fcarucci/agent-memory)  
**License:** See `LICENSE` in this repository.
