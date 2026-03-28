# Task closure — memory sweep (`task-done sweep`)

When the user **signals that work is finished** or the **conversation is
winding down** after substantive collaboration, the host **must** run the
**remember-what-you-learned** sequence before treating the turn as closed.
This is the same substance as **Post-task sweep** and **Session-end review**
in **`SKILL.md`**; this file is the operational checklist.

## Dispatch (see `SKILL.md` Step 1 table)

Typical **task-done** phrases (non-exhaustive; match user **intent**):

- "We're done", "We are done", "I'm done"
- "That's all", "That's everything", "Nothing else"
- "Task is done", "The task is complete", "We're finished"
- "That wraps it up", "We're good here", "All set"
- "Thanks, we're done" / "Thanks — done" when clearly **closing** the thread

**Session-end** phrasing (also triggers this sweep):

- "Thanks", "goodbye", "bye", "that's all" in a **closing** sense after real work

**Do not** treat a **mid-task** "thanks" (e.g. thanks for the explanation)
as task closure — only when the user is **ending** or **handing off**.

If there was **no substantive work** in the thread (pure Q&A, single
factual answer, no implementation), you may skip remember spawns after
briefly noting there is nothing to capture — still **ask yourself** the
learnings question once internally.

## Mandatory sequence (host)

1. **Ask internally** (and, if useful, state briefly to the user that you
   are saving learnings):

   > What did I learn in this thread that would be useful in a future session?

2. For **each** non-empty, non-duplicate lesson, **spawn a remember
   subagent** immediately — same payload pattern as **`SKILL.md` / How to
   spawn a remember subagent** (`ref/format.md`, `ref/retain.md`). One
   spawn per distinct lesson; do **not** batch into a single vague remember.

3. After the subagents return, **tell the user what was remembered** (bulleted
   list with context tags), or state clearly that **nothing** met the bar
   to store.

4. If the session was **substantial** (long arc, many decisions, or explicit
   user ask to reflect), also spawn a dedicated **`action: reflect`**
   subagent — **never** run `ref/reflect.md` on the host turn (`SKILL.md`
   invariant).

## Violations (do not)

- Replying with only "You're welcome" / "Glad to help" and **no** sweep when
  the thread included real task work.
- Claiming you "remembered" without **remember subagents** having run retain
  for each stored lesson.
- Skipping the sweep because the user already said "thanks" once earlier —
  closure signals still require the sequence.

## Relation to other actions

- Explicit **"Remember this …"** in the same message: run that remember first
  (user-directed), then still run the **learnings question** for anything
  *else* learned in the thread.
- **Curate** / **maintain** / **reflect** are separate user requests unless
  folded into a reflect subagent’s own post-pass steps per `ref/reflect.md`.
