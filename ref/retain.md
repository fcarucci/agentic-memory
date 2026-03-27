# Retain Operation (`action: remember`)

> **Prerequisite:** Read `ref/format.md` before this file — it defines
> the section formats you need to write entries correctly.

## Scope and safety

This skill manages **only** `MEMORY.md` and the per-section layout beside it.

Non-negotiable:

1. **Read before write.** Always read `MEMORY.md` in full before planning
   changes.
2. **Use the guarded writer.** Use the **append-entry** operation of the **management helper** (`skills/memory/scripts/`) instead of manual edits so secret screening, duplicate checks, entity
   canonicalization, and optimistic concurrency checks are enforced.
3. **Single final write.** Do not write partial state. Compute the final
   target content first, then write once.
4. **Re-read before write.** Immediately before writing, read `MEMORY.md`
   again. If it changed since the first read, merge against the latest
   state and recompute.
5. **No side effects.** Do not edit `AGENTS.md`, code, config, or any
   other file. Report drift in the subagent output instead.
6. **Preserve structure.** Never remove or rename section headers or HTML
   comments.
7. **Idempotent reruns.** Running the skill twice with the same input must
   produce the same file.
8. **Fail closed.** If you cannot safely determine the correct final state,
   stop and report a blocked result.
9. **World knowledge is verified only.** The World Knowledge section never
   contains guesses, placeholders, or `[unverified]` entries.

## Sensitive data policy

Never persist raw sensitive data. Never store:

- Tokens, API keys, passwords, secrets, cookies, SSH material
- Full private URLs with embedded secrets
- Raw logs or stack traces that may contain secrets
- Personal data unless the user explicitly asked for it

When useful knowledge depends on sensitive input, store the sanitized
lesson, not the raw value. Prefer abstraction ("the database password came
from the environment config") over the token itself.

## Scope

**Always write to user scope** unless one of these conditions is met:

- The user **explicitly** says "remember this in the project" (or equivalent).
- The entry is being **promoted** from user scope via `action: promote`.

Do **not** infer project scope from the topic being project-related.
Personal observations about project infrastructure still belong in user
memory and can be promoted later if the user decides to share them.

User memory under `~/.agents/memory/` is **created automatically** the first time recall or a guarded write touches user scope. You do not run a separate init step for normal operation.

## Workflow

1. Read and parse the target `MEMORY.md` (user scope by default; auto-created if missing).
2. Validate structure: **validate** operation, `--scope user`.
3. Screen the incoming `content` before any write: **screen-text** with `--text` set to the candidate memory text. If the result is unsafe, store only a sanitized lesson or stop.
4. **Classify** the memory into the correct network:
   - Is it something that happened to/around the agent? → **Experience**
   - Is it an objective, verifiable fact about the project? → **World Knowledge**
   - Is it the agent's subjective judgment or preference? → **Belief**
5. **Extract entities:** **extract-entities** with `--text` set to the memory text. Review the candidates and finalize the entity set.
6. **Check for duplicates** across both scopes: **check-duplicate** with appropriate `--section`, `--candidate`, and `--cross-scope` as needed. If a clear duplicate exists in either scope, do not add a new entry.
7. Write the final entry via **append-entry**: set `--section`, `--scope user`, and for experiences `--date`, optional `--context`, `--entities`, `--text`. For world knowledge, also pass `--confidence` and `--sources`. For beliefs, also pass `--confidence` and optionally `--formed` / `--updated`.
8. For new beliefs, set initial confidence based on evidence strength:
   - `0.4–0.5`: tentative, based on a single observation
   - `0.6–0.7`: moderate, based on 2+ observations
   - `0.8+`: strong, based on repeated consistent evidence
9. **Reflect**: check whether the new memory reinforces or contradicts
   any existing beliefs. If so, update confidence scores with **update-confidence** (`--section beliefs`, `--index`, `--delta`, `--scope user`). Use `+0.1` for reinforcement, `-0.1` for weakening, `-0.2` for
   strong contradiction. Beliefs below `0.2` are pruning candidates.
10. Check if any entity now has 3+ mentions and lacks a summary. If so,
    write a new entity summary.
11. Verify the written file matches the plan.
12. **Auto-reflect check** (see below).

## Classification guide

| Signal | Network |
|--------|---------|
| "I found that…", "The test showed…", "When I tried…" | Experience |
| Tool version, config location, API behavior, file path | World Knowledge |
| "X is better than Y", "I think…", "Prefer…" | Belief |
| Summarizes an entity from 3+ memories | Entity Summary |

## Promotion from experience to world knowledge

An experience can be promoted to world knowledge when:

1. **Convergence**: 3+ independent experiences point to the same truth.
2. **Consistency**: supporting experiences do not contradict each other.
3. **Verification**: confirmed against the current repo state.
4. **Relevance**: non-obvious, actionable, and likely durable.
5. **Generality**: wording removes one-off context.

When promoting, set the initial confidence based on the strength of
evidence and record the source count.

## Deterministic normalization

Before comparing, pruning, or writing memories, normalize using:

1. Trim whitespace and collapse repeated spaces.
2. Redact sensitive values first.
3. Normalize context tags to the canonical vocabulary.
4. Ignore date, tag, and framing when comparing duplicates.
5. Normalize tense and trivial synonyms.

For deterministic duplicate detection, use **check-duplicate** with the
appropriate section and candidate text. The helper uses three complementary similarity metrics (sequence ratio,
Jaccard, overlap coefficient) with a threshold of 0.65.

## Auto-reflect

After every successful retain, check whether a full reflect pass is
warranted. This keeps beliefs and entity summaries from going stale
without requiring the caller to explicitly schedule reflection.

### Trigger conditions (any one is sufficient)

1. **Volume**: 5+ experiences exist that are newer than the most recent
   belief `updated` date. This means beliefs haven't been reviewed
   against recent evidence.
2. **Staleness**: any belief has an `updated` date older than 14 days.
3. **Low-confidence accumulation**: 2+ beliefs are below `0.3` confidence
   (candidates for pruning).
4. **Missing summaries**: an entity appears in 3+ memories but has no
   summary in the Entity Summaries section.

### How to check

After completing the retain write, run **prune-beliefs** (e.g. threshold `0.3`) and **suggest-summaries**. Inspect the belief `updated` dates from the file you just wrote.
If any trigger condition is met, run the full reflect workflow
(see `ref/reflect.md`) **in the same subagent invocation** — do not
return and ask the caller to spawn a separate reflect.

### Post-reflect curation

After the auto-reflect pass completes (or is skipped), **always**
regenerate the curated master so `MEMORY.md` stays in sync: **curate**
with `--scope user` (or `--scope project` when working on project memory).

### What to report

In the subagent output, include:

- Whether auto-reflect was triggered and which condition(s) fired.
- If triggered: the reflect output (belief updates, pruning, summaries).
- If not triggered: "auto-reflect: no action needed."
- Whether the curated master was regenerated.

## Required output

At the end of the run, report:

- Whether a new memory was added, and to which section.
- Classification reasoning (why experience vs. world knowledge vs. belief).
- Entity tags applied.
- Duplicate check result.
- Any belief confidence updates triggered.
- Any new entity summaries generated.
- Final counts per section.
- Whether concurrent-write detection triggered.
- Any documentation drift noticed.
- If blocked, exactly why.

## Error handling

- **`MEMORY.md` does not exist**: create the standard template and continue.
- **Recoverable format issue**: repair if you can preserve all existing content.
- **Unrecoverable format issue**: stop and report blocked.
- **Sensitive data in existing memory**: redact if possible, otherwise remove and report.
- **Ambiguous duplicate**: stop and report the ambiguity; do not bypass the guarded write path.
- **Helpers unavailable**: fall back to manual parsing but warn that deterministic operations are degraded.
