# Skill helpers (`skills/memory/scripts/`)

This skill ships **stdlib Python helpers** next to this folder. They implement the workflows defined in **`SKILL.md`** and the `ref/*.md` operation guides.

**Documentation does not embed copy-paste shell for those helpers.** Hosts and agents follow the skill; the runtime invokes the helpers as wired to this repository (paths and interpreter are an integration concern, not repeated here).

## Recall helper

Supports **digest** and **structured search** (topics, keywords, entities, scopes, dates, sections, JSON output, stats, token budget). The helper deterministically handles direct matching first and fallback matching internally. Full flag and behavior reference: **`ref/recall.md`**.

## Management helper

Supports **validation**, **screening**, **guarded append** (including optional **`--outcome`** / **`--evidence`** on experiences), **duplicate checks**, **entity extraction**, **confidence updates** (including **`--no-bump-updated`** on beliefs for temporal decay), **preview-belief-decay** (JSON staleness / suggested decay deltas), **conflicts**, **pruning**, **summary suggestions**, **promotion**, **forget** (find + delete), **curation**, **maintenance-report**, **config validation**, and **config hints**. Each workflow names the operations and arguments in:

- **`ref/retain.md`** — remember / guarded write / auto-reflect
- **`ref/reflect.md`** / **`ref/reflect-techniques.md`** — reflect
- **`ref/maintain.md`** — maintain / maintenance-report
- **`ref/forget.md`** — forget
- **`ref/promote.md`** — promote
- **`ref/curate.md`** — manual **curate** (thin `MEMORY.md`; host-run, no subagent)
- **`ref/task-done.md`** — **task-done sweep** / session-end (remember what you learned)
- **`ref/config.md`** — `memory-skill.config.json`

## Automated tests

Maintainers run the bundled tests in `skills/memory/scripts/` after changing helper code, using the same Python environment the repo expects.
