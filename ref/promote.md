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

After promoting, consider whether the entry should be removed from user
memory to avoid redundancy.

## Required output

- Whether promotion succeeded or was blocked (duplicate, policy, or safety).
- The promoted text.
- Final counts per section in the target file.
