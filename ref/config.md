# Memory skill configuration (`memory-skill.config.json`)

Optional JSON file in the **user memory directory** (next to `MEMORY.md`):

`~/.agents/memory/memory-skill.config.json`

The memory helpers stay **model-agnostic**. This file is for **orchestrators** (IDE agent, `AGENTS.md`, custom wrappers) so each **memory subagent** spawn can use an appropriate model: stronger reasoning where it matters, cheaper where deterministic helpers already do most of the work.

Keep **behavioral tuning** (skepticism, literalism, etc.) in `profile.json`. This file only names **model presets** for subagent routing.

## Schema (`version` 1)

| Field | Type | Purpose |
|-------|------|---------|
| `version` | int | Must be `1`. |
| `default_preset` | string | Name of a key in `presets`. Used if an action entry is missing after merge. |
| `presets` | object | Maps preset name → opaque model identifier your host understands (API id, Cursor model alias, etc.). |
| `actions` | object | Maps subagent action → preset name **or** a raw model id string (if the value is not a key in `presets`, it is treated as the model id). |
| `overrides` | object | Optional. Keys defined by the skill; hosts may use them for conditional routing. |

### `actions` keys (subagent operations)

- `remember` — retain / classify / write (often auto-reflect in the same run).
- `reflect` — belief evolution, conflicts, synthesis, curate.
- `maintain` — lighter maintenance cycle than full reflect.
- `promote` — judgment plus CLI-backed promotion.

### `overrides` keys

| Key | Intended use |
|-----|----------------|
| `remember_when_auto_reflect` | Stronger model when the host splits **retain** vs **auto-reflect**, or when retain triggers reflect (see `ref/retain.md`). |

## Defaults

If the file is missing, built-in defaults match the recommended tiering:

- `reflect` → strong preset  
- `remember` → fast preset  
- `maintain` / `promote` → balanced preset  
- `remember_when_auto_reflect` → strong preset  

Default preset **names** map to placeholder model ids (`reasoning`, `default`, `fast`) until you copy the example and set real ids.

## Config operations (management helper)

The **management helper** exposes JSON-only operations for this file:

| Operation | Purpose |
|-----------|---------|
| **validate-config** | Check syntax and known keys (uses defaults if the file is missing). |
| **config-hints** | Emit resolved model ids per subagent action for spawn instructions. |

For nonstandard layouts or tests, the host may supply an alternate config path via the **`MEMORY_SKILL_CONFIG_PATH`** environment variable or the helper’s per-run skill-config override (see helper sources under `skills/memory/scripts/`).

## Subagent prompt field

Orchestrators may pass through an optional `model_preset` or concrete model id on the subagent payload; see **`SKILL.md`** — behavior is defined by the host, not by the helpers.

## Bootstrap

On first use of **user** scope, recall and management operations create `~/.agents/memory/` (master, section files, and—if missing—`memory-skill.config.json` with built-in defaults). The **init-user** operation is an optional idempotent no-op after that.

## Copying the example

```bash
cp skills/memory/ref/memory-skill.config.example.json ~/.agents/memory/memory-skill.config.json
# Edit presets to match your environment.
```
