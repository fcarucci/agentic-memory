# Memory Format Reference

## Memory file structure

### Canonical layout (current)

**Full memories** are stored **one file per memory network** (section). The
helpers load these when present; see `scripts/memory-recall.py` (`SECTION_FILES`).

| Network | Filename |
|---------|----------|
| Experiences | `experiences.md` |
| World Knowledge | `world_knowledge.md` |
| Beliefs | `beliefs.md` |
| Reflections | `reflections.md` |
| Entity Summaries | `entity_summaries.md` |

Each section file contains a single `##` heading for that network (see
templates in `memory-recall.py` `SECTION_TEMPLATES`) and the bullets or
subsections described later in this document under each format heading.

**Where the section files live** depends on scope:

- **User**: alongside `~/.agents/memory/MEMORY.md` — same directory
  (`~/.agents/memory/`).
- **Project**: under `<repo>/memory/` (next to the repo-root `MEMORY.md`).

**Curated master `MEMORY.md`** (user or project root) is **not** a duplicate
of everything. The **`curate`** helper (see `memory-manage.py`) **replaces**
the master with **one-line previews** of the top world-knowledge / belief /
entity-summary items (by confidence and order), plus **markdown links** to
the section files for full text—intended for a thin include from
`AGENTS.md`. If `MEMORY.md` is still a **legacy monolithic** journal (not a
curated stub) with entries, **`curate` runs `migrate` first**: content moves
into per-section files, then the master is overwritten with the thin curated
file (no `MEMORY.md.bak`). Full entries live in the per-section files.
Regeneration is driven by the memory skill (curation / retain / reflect); see
`SKILL.md` and `ref/retain.md`.

**Project root note:** `<repo>/MEMORY.md` is still the anchor path the
helpers use to resolve the repo; section files for project scope are under
`<repo>/memory/`.

### Legacy single-file layout

Older setups may use **one `MEMORY.md`** containing all five `##` sections in
a single document (same headings and bullet rules as today). The recall
loader can **migrate** that into per-section files when appropriate (see
`load_memory` / `auto_migrate` / split operations in `memory-manage.py`).
Prefer the canonical layout for new writes.

Legacy monolithic template (backward compatibility only):

```markdown
# Agentic Memory

## Experiences

<!-- Newest first. Optional {outcome: ...} {evidence: ref}. See Experience format below. -->

## World Knowledge

<!-- Verified, objective facts about the project and environment. Format:
- {entities: e1} Fact text. (confidence: 0.XX, sources: N) -->

## Beliefs

<!-- Agent's subjective judgments that evolve over time. Format:
- {entities: e1} Belief text. (confidence: 0.XX, formed: YYYY-MM-DD, updated: YYYY-MM-DD) -->

## Reflections

<!-- Higher-level patterns synthesized from multiple experiences and beliefs. Format:
- **YYYY-MM-DD** {entities: e1, e2} Reflection text. -->

## Entity Summaries

<!-- Synthesized profiles of key entities, regenerated when underlying memories change. Format:
### entity-name
Summary paragraph. -->
```

## Experience format

Each experience is one bullet with a narrative, self-contained description:

```text
- **2026-03-26** [debug] {entities: integration-tests, port-5432} The integration test suite hung indefinitely because another process was already bound to port 5432. Killing the stale database process resolved the issue.
```

Rules:

- Use today's date in `YYYY-MM-DD` format.
- Context tag is optional but strongly encouraged.
- **Entity tags are required.** Use `{entities: name1, name2}` inline.
- Text must be **narrative and self-contained**: a reader with no context
  should understand what happened, why it mattered, and what was learned.
  Avoid fragments like "port 5432 conflict" — instead write the full story.
- Keep entries newest-first.
- No duplicates or near-duplicates.

### Structured episodic traces

For debugging- and incident-style **experiences**, shape the narrative as a
short **trace**: what was attempted → what happened (symptoms or errors
**in the abstract**) → what fixed it or what was learned. This aids
auditability and later reflection without raw logs. Never paste secrets or
full stack traces—follow the sensitive-data rules in `ref/retain.md`.
Optional **causal tags** (below) fit naturally when cause-effect is clear.

Example:

```text
- **2026-03-27** [debug] {entities: ci-pipeline, rust-toolchain} Ran `cargo test` on the default CI image; the job failed because the `wasm32-unknown-unknown` target was missing. Adding an explicit `rustup target add` step (and aligning with the repo toolchain file) fixed the pipeline.
```

### Outcome and evidence (experiences)

Optional tags after `{entities: ...}`, before causal tags (if any) and the
narrative:

| Tag | Values | Use |
|-----|--------|-----|
| `{outcome: success}` | `success`, `failure`, `mixed`, `unknown` | Observable end state of the episode — drives **digest ordering** (failures first) and **reflect** weighting (`ref/reflect.md`). |
| `{evidence: …}` | Short external pointer | **Ticket id**, **CI run id**, or **doc path** — not raw logs or secrets. Lets humans and agents re-open the source without pasting PII or tokens. |

Example:

```text
- **2026-03-28** [testing] {entities: e2e-suite} {outcome: failure} {evidence: ci-run-18492} E2E timed out waiting for the mock gateway; increasing the startup wait in the harness fixed the flake on retry.
```

**append-entry** accepts `--outcome` and `--evidence` for experiences; the
helper injects these tags. Do not put `}` inside the evidence string.

## Causal links

Experiences and reflections can optionally annotate cause-effect
relationships using inline causal tags. These are lightweight directed
edges that help the reflect operation trace reasoning chains.

### Format

Place causal tags after entity tags, before the narrative text:

```text
- **2026-03-26** [debug] {entities: dev-server, port-5432} {caused-by: build-watcher} The dev server crashed because the build watcher left a child process bound to port 5432.
- **2026-03-26** [debug] {entities: build-watcher} {causes: port-5432} The build watcher does not clean up child processes on exit, leaving ports bound.
```

### Supported causal tags

| Tag | Meaning | Example |
|-----|---------|---------|
| `{causes: entity}` | This event caused a problem in `entity` | Stale process → port conflict |
| `{caused-by: entity}` | This event was caused by `entity` | Port conflict ← stale process |
| `{enables: entity}` | This event makes `entity` possible | Config change → feature works |
| `{prevents: entity}` | This event blocks `entity` | Missing dep → build fails |

### Rules

- Causal tags are **optional**. Most experiences won't have them.
- Only add causal tags when the cause-effect relationship is clear
  from the experience, not speculative.
- The entity in the causal tag should also appear somewhere in the
  memory bank (as an entity tag on another entry, or as a known entity).
- Multiple causal tags are allowed on one entry.
- Causal tags are metadata for the reflect operation — they help the
  subagent trace impact chains during counterfactual analysis.

### Querying causal chains

Use keyword search via the **recall helper** to find causal relationships (e.g. keywords `caused-by: dev-server` or `causes:` with JSON output—see `ref/recall.md`).

> **Design note:** In the Hindsight paper, causal links are edges in a
> graph database traversed with spreading activation. Our flat-file
> equivalent uses inline annotations that the subagent follows manually
> during reflect. This trades automatic traversal for simplicity and
> zero infrastructure.

## Narrative quality standard

Memories must be narrative, not fragmentary. Each entry should read as a
self-contained story that captures the full context: what happened, why,
and what was learned.

Bad (fragmented):
```text
- **2026-03-26** [debug] Port 5432 conflict.
```

Good (narrative):
```text
- **2026-03-26** [debug] {entities: integration-tests, port-5432} The integration test suite hung indefinitely because another process was already bound to port 5432. Killing the stale database process resolved the hang and allowed the test suite to complete normally.
```

## World knowledge format

Each world fact is one bullet with confidence and source count:

```text
- {entities: postgresql} PostgreSQL 16 requires explicit listen_addresses configuration for remote connections. (confidence: 0.95, sources: 3)
```

Rules:

- Entity tags required.
- Confidence is a float in `[0.0, 1.0]`.
- Sources count is the number of independent experiences supporting this.
- Facts must be objective, verifiable, and project-relevant.
- No duplicates.

> **Design note:** In the Hindsight paper, only opinions carry confidence
> scores — world facts are treated as objectively true. This implementation
> adds confidence to world knowledge as a practical extension: in real
> projects, "verified facts" can have varying certainty, and the sources
> count maps to the paper's convergence concept. This is a deliberate
> departure, not an oversight.

## Belief format

Each belief is one bullet with confidence and temporal metadata:

```text
- {entities: dev-server, build-watcher} Running the combined dev command is more reliable than starting the server alone for day-to-day development. (confidence: 0.70, formed: 2026-03-15, updated: 2026-03-20)
```

Rules:

- Entity tags required.
- Confidence in `[0.0, 1.0]` — represents strength of conviction.
- `formed` date is when the belief was first created.
- `updated` date changes whenever confidence is adjusted.
- Beliefs are subjective — they represent the agent's judgments, not
  verified truths.

## Reflection format

Reflections are higher-level patterns synthesized from multiple
experiences and beliefs during a reflect pass. They capture cross-entity
insights that no single experience or belief contains.

```text
- **2026-03-26** {entities: integration-tests, dev-server, port-5432} Three separate debugging sessions all involved port conflicts from stale processes. The underlying pattern is that the dev environment does not clean up child processes on exit, causing cascading issues across unrelated tools.
```

Rules:

- Use the date of the reflect pass, not the dates of source memories.
- Entity tags required — include all entities the pattern spans.
- Text must be a synthesis, not a copy of any single experience.
- Keep entries newest-first.
- Reflections are created during reflect passes, not during retain.
- A reflection should connect 2+ experiences or beliefs into a pattern
  that is more useful than any of them individually.

## Entity summary format

Each entity gets a `###` heading and a summary paragraph:

```text
### postgresql
PostgreSQL 16.x is the primary database. Config requires explicit listen_addresses for remote access. Connection pooling is handled by the application layer, not PgBouncer. Migrations run via the ORM's built-in migration tool.
```

Rules:

- One summary per entity.
- Preference-neutral: no opinions, just synthesized facts.
- Regenerated when underlying experiences or world knowledge change.
- Only created for entities with 3+ mentions across memories.

## Entity tag guidelines

Entity tags connect memories across sections. Use consistent, lowercase,
hyphenated names:

- `dev-server`, `postgresql`, `build-watcher`, `integration-tests`
- `api-gateway`, `redis`, `docker`, `ci-pipeline`
- `port-5432`, `dashboard`, `auth-service`

When in doubt about what to tag, run **extract-entities** with `--text` set to your memory candidate (management helper—see `ref/retain.md`).

## Canonical context tags

Normalize free-form context into this vocabulary:

`debug`, `testing`, `tooling`, `workflow`, `decision`, `preference`,
`infra`, `docs`, `ui`, `backend`, `security`

Omit the tag rather than inventing a noisy synonym.
