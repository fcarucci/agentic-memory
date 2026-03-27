# Promote Operation (`action: promote`)

Copies a memory from user scope to project scope. The original stays
in user memory (not deleted automatically).

## When to promote

- A personal observation has proven to be a durable, project-relevant fact.
- The user explicitly asks to share a memory with the team/repo.
- A belief has been reinforced enough to become shared knowledge.

## Management helper

Run **promote** with:

- `--section` — `experiences`, `world_knowledge`, or `beliefs`
- `--index` — index in user memory
- `--allow-project-promotion` — required explicit approval flag

The promote operation automatically:

- Requires explicit `--allow-project-promotion` approval.
- Checks for duplicates in project memory before promoting.
- Refuses preference-scoped experiences and sensitive content.
- Inserts the entry at the top of the target section.
- Reports the promoted text and target path.

## Post-promotion deduplication (required)

After a **successful** promote, the **user-scope copy must be removed** so
the same fact does not appear twice when recall searches both scopes.

1. Use **delete-entry** with `--scope user`, the same `--section` and
   `--index` that were passed to **promote** (the source index is unchanged
   until deletion).
2. Skip removal only if the user **explicitly** asked to keep the entry in
   both scopes.
3. If promote was **blocked** because a duplicate already existed in project
   memory, do not delete from user memory unless the user wants to dedupe
   manually—report the block and the existing project line instead.

See **`ref/forget.md`** for **delete-entry** semantics; promotion uses the
direct index path (no fuzzy find) because the source index is known.

## Required output

- Whether promotion succeeded or was blocked (duplicate, policy, or safety).
- The promoted text.
- Final counts per section in the target file.
- Whether the user-scope entry was **deleted** after success (or skipped per
  explicit user request).
