# Recall and Show Operations

Use the **recall helper** in `skills/memory/scripts/` as integrated with this repository. **`SKILL.md`** defines when to run it; this file documents **flags and behavior** only—no copy-paste shell.

## Show (`action: show`)

Produces a compact, context-ready digest of memories. No subagent is needed—the calling agent runs the digest operation directly.

| Intent | Arguments |
|--------|-----------|
| Both scopes (default) | `--show` |
| User scope only | `--show --scope user` |
| Project scope only | `--show --scope project` |
| Cap recent experiences by count | `--show --last N` (default experience window if omitted) |
| Cap recent experiences by age | `--show --days N` |
| Wider experience window | increase `--last` as needed |

The digest contains, for each scope with content:

1. **World Knowledge** — verified facts with confidence scores  
2. **Beliefs** — beliefs with confidence scores  
3. **Entity Summaries** — synthesized entity profiles  
4. **Recent Experiences** — bounded by `--last N` (default: 5) or `--days N`

Output is plain text, not JSON. Display directly to the user.

## Recall (`action: recall`)

Recall searches **both** user and project memory by default, tagging results with `[user]` or `[project]` so the caller knows the source.

| Intent | Typical arguments |
|--------|-------------------|
| Keyword, both scopes | `--keyword "<text>" --json` |
| Keyword, user only | `--keyword "<text>" --scope user --json` |
| Keyword, project only | `--keyword "<text>" --scope project --json` |
| Entity, all sections | `--entity "<name>" --cross-section --json` |
| Date range | `--since YYYY-MM-DD --until YYYY-MM-DD --json` |
| Section + keyword | `--section beliefs --keyword "<text>" --json` |
| Statistics | `--stats` or `--stats --scope user` |
| Token budget (approx.) | `--keyword "<text>" --budget N --json` |

When to use recall vs. full read:

- < 20 total memories: reading the full file is fine  
- 20–50 memories: recall for targeted queries, full read for maintenance  
- 50+ memories: always use recall for queries  

## Required output (recall subagent)

- Query parameters used.  
- Number of results per section.  
- The matched memories (raw text).  
