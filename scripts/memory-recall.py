#!/usr/bin/env python3
"""Structured recall over MEMORY.md (user and project scopes).

Supports two memory tiers:
  - User memory:    ~/.agents/memory/MEMORY.md (personal, fixed path).
  - Project memory: resolved per run from cwd and script location; see resolve_project_memory_path().

Recall searches both by default. Results are tagged with their source
scope so the caller can distinguish personal from shared memories.

Agents and hosts follow ``skills/memory/SKILL.md`` and ``ref/recall.md`` for
when and how to invoke this helper. Flag reference: run ``--help`` on this
module (documentation does not embed copy-paste shell).
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

DEFAULT_USER_MEMORY_DIR = Path.home() / ".agents" / "memory"
DEFAULT_USER_MEMORY_PATH = DEFAULT_USER_MEMORY_DIR / "MEMORY.md"

# ---------------------------------------------------------------------------
# Section files: one .md per memory type
# ---------------------------------------------------------------------------

SECTION_FILES: dict[str, str] = {
    "experiences": "experiences.md",
    "world_knowledge": "world_knowledge.md",
    "beliefs": "beliefs.md",
    "reflections": "reflections.md",
    "entity_summaries": "entity_summaries.md",
}

SECTION_TEMPLATES: dict[str, str] = {
    "experiences": (
        "## Experiences\n\n"
        "<!-- Newest first. Format: - **YYYY-MM-DD** [context] {entities: e1, e2} "
        "optional {outcome: success|failure|mixed|unknown} optional {evidence: ref} "
        "optional causal tags, then narrative. -->\n"
    ),
    "world_knowledge": (
        "## World Knowledge\n\n"
        "<!-- Verified, objective facts about the project and environment. Format:\n"
        "- {entities: e1} Fact text. (confidence: 0.XX, sources: N) -->\n"
    ),
    "beliefs": (
        "## Beliefs\n\n"
        "<!-- Agent's subjective judgments that evolve over time. Format:\n"
        "- {entities: e1} Belief text. (confidence: 0.XX, formed: YYYY-MM-DD, updated: YYYY-MM-DD) -->\n"
    ),
    "reflections": (
        "## Reflections\n\n"
        "<!-- Higher-level patterns synthesized from multiple experiences and beliefs. Format:\n"
        "- **YYYY-MM-DD** {entities: e1, e2} Reflection text. -->\n"
    ),
    "entity_summaries": (
        "## Entity Summaries\n\n"
        "<!-- Synthesized profiles of key entities, regenerated when underlying memories change. Format:\n"
        "### entity-name\nSummary paragraph. -->\n"
    ),
}

CURATED_MASTER_TEMPLATE = """\
# Agentic Memory

<!-- Curated subset suitable for inclusion in AGENTS.md.
     One-line previews + links to per-section files for full text.
     Regenerate via memory skill curation (SKILL.md / ref/retain.md) -->

## World Knowledge

## Beliefs

## Entity Summaries
"""

USER_MEMORY_TEMPLATE = """\
# User Memory

<!-- Curated subset: short preview lines; open linked section files for full entries. -->

## World Knowledge

## Beliefs

## Entity Summaries
"""

# Default ``memory-skill.config.json`` (must stay aligned with ``default_skill_config`` in memory-manage).
DEFAULT_USER_SKILL_CONFIG: dict = {
    "version": 1,
    "default_preset": "balanced",
    "presets": {
        "strong": "reasoning",
        "balanced": "default",
        "fast": "fast",
    },
    "actions": {
        "remember": "fast",
        "reflect": "strong",
        "maintain": "balanced",
        "promote": "balanced",
    },
    "overrides": {
        "remember_when_auto_reflect": "strong",
    },
    "hosts": {},
}

# Legacy single-file template (used for backward-compat validation only).
LEGACY_SINGLE_FILE_TEMPLATE = """\
# Agentic Memory

## Experiences

<!-- Newest first. Format: - **YYYY-MM-DD** [context] {entities: e1, e2} optional {outcome: ...} optional {evidence: ref} narrative. -->

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
"""

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _first_memory_md_in_parents(anchor: Path) -> Optional[Path]:
    """Return the first existing MEMORY.md walking anchor, then its parents."""
    here = anchor.resolve()
    for d in [here, *here.parents]:
        candidate = d / "MEMORY.md"
        if candidate.is_file():
            return candidate
    return None


def resolve_project_memory_path() -> Path:
    """Resolve the project-scope MEMORY.md (curated master) path.

    Precedence:
    1. Walk ``Path.cwd()`` upward for the first ``MEMORY.md``.
    2. Walk upward from this script's directory.
    3. ``Path.cwd() / "MEMORY.md"`` (may not exist yet).
    """
    found = _first_memory_md_in_parents(Path.cwd())
    if found:
        return found
    script_dir = Path(__file__).resolve().parent
    found = _first_memory_md_in_parents(script_dir)
    if found:
        return found
    return Path.cwd() / "MEMORY.md"


def resolve_user_memory_path() -> Path:
    """Return the user-scope MEMORY.md path (``~/.agents/memory/MEMORY.md``)."""
    return DEFAULT_USER_MEMORY_PATH


def resolve_user_skill_config_path() -> Path:
    """Return ``memory-skill.config.json`` next to user ``MEMORY.md``."""
    return resolve_user_memory_path().parent / "memory-skill.config.json"


def resolve_section_dir(scope: str) -> Path:
    """Return the directory that holds per-section files for *scope*.

    - **user**: ``~/.agents/memory/`` (section files alongside MEMORY.md).
    - **project**: ``<repo>/memory/`` (subdirectory next to repo-root MEMORY.md).
    """
    if scope == "user":
        return resolve_user_memory_path().parent
    return resolve_project_memory_path().parent / "memory"


def section_file_path(section_dir: Path, section: str) -> Path:
    """Full path to a section file inside *section_dir*."""
    return section_dir / SECTION_FILES[section]


def has_section_files(section_dir: Path) -> bool:
    """True if at least one section file exists in *section_dir*."""
    if not section_dir.is_dir():
        return False
    return any((section_dir / f).exists() for f in SECTION_FILES.values())


# Legacy compat names.
USER_MEMORY_DIR = DEFAULT_USER_MEMORY_DIR
USER_MEMORY_PATH = DEFAULT_USER_MEMORY_PATH

SCOPES = ("user", "project", "both")
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "for",
    "from", "if", "in", "into", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "then", "there", "these", "this", "to", "was", "were",
    "with",
})
FUZZY_RECALL_THRESHOLD = 0.55
FUZZY_ENTITY_THRESHOLD = 0.72

# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_memory_from_sections(section_dir: Path) -> "MemoryBank":
    """Build a MemoryBank by reading individual section files."""
    bank = MemoryBank()
    for section_name in SECTION_FILES:
        path = section_dir / SECTION_FILES[section_name]
        if path.exists():
            section_bank = parse_memory_file(path)
            getattr(bank, section_name).extend(getattr(section_bank, section_name))
    return bank


def _is_legacy_single_file(master_path: Path) -> bool:
    """True if master_path is a populated all-in-one MEMORY.md (not curated)."""
    if not master_path.exists():
        return False
    content = master_path.read_text(encoding="utf-8")
    if "per-section files" in content:
        return False
    bank = parse_memory_file(master_path)
    total = (len(bank.experiences) + len(bank.world_knowledge)
             + len(bank.beliefs) + len(bank.reflections)
             + len(bank.entity_summaries))
    return total > 0


def auto_migrate(master_path: Path, section_dir: Path) -> None:
    """Split a legacy single-file MEMORY.md into per-section files.

    Called transparently on first load when section files are absent
    but the master contains entries.  Replaces the master with the
    curated template after writing section files (no ``.bak`` backup).
    """
    bank = parse_memory_file(master_path)
    section_dir.mkdir(parents=True, exist_ok=True)

    for section_name, filename in SECTION_FILES.items():
        items = getattr(bank, section_name)
        sf = section_dir / filename
        if sf.exists():
            continue
        content = SECTION_TEMPLATES[section_name]
        for entry in items:
            content = content.rstrip("\n") + "\n\n" + entry.raw + "\n"
        sf.write_text(content, encoding="utf-8")

    is_user = "User Memory" in master_path.read_text(encoding="utf-8")
    template = USER_MEMORY_TEMPLATE if is_user else CURATED_MASTER_TEMPLATE
    master_path.write_text(template, encoding="utf-8")


def load_memory(master_path: Path, section_dir: Path) -> "MemoryBank":
    """Load from section files when available, else from a single master.

    If the master is a legacy all-in-one file with entries and no
    section files exist yet, auto-migrates before loading.
    """
    try:
        user_master = resolve_user_memory_path().resolve()
        is_user_scope = master_path.resolve() == user_master
    except OSError:
        is_user_scope = master_path == resolve_user_memory_path()
    if is_user_scope:
        ensure_user_scope_initialized()
        master_path = resolve_user_memory_path()
        section_dir = resolve_section_dir("user")

    if has_section_files(section_dir):
        return load_memory_from_sections(section_dir)
    if _is_legacy_single_file(master_path):
        auto_migrate(master_path, section_dir)
        return load_memory_from_sections(section_dir)
    return parse_memory_file(master_path)


def resolve_memory_sources(scope: str) -> tuple[Path, Path]:
    """Return ``(master_path, section_dir)`` for the given scope."""
    if scope == "user":
        return resolve_user_memory_path(), resolve_section_dir("user")
    return resolve_project_memory_path(), resolve_section_dir("project")


def resolve_memory_paths(scope: str) -> list[tuple[str, Path]]:
    """Return (label, path) pairs for the requested scope (legacy compat)."""
    if scope == "user":
        return [("user", resolve_user_memory_path())]
    elif scope == "project":
        return [("project", resolve_project_memory_path())]
    else:
        return [
            ("user", resolve_user_memory_path()),
            ("project", resolve_project_memory_path()),
        ]


def ensure_section_file(section_dir: Path, section: str) -> Path:
    """Create a section file from its template if it does not exist."""
    path = section_file_path(section_dir, section)
    if not path.exists():
        section_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(SECTION_TEMPLATES[section], encoding="utf-8")
    return path


def ensure_section_files(section_dir: Path) -> list[Path]:
    """Create all section files that do not yet exist."""
    return [ensure_section_file(section_dir, s) for s in SECTION_FILES]


def ensure_user_memory() -> Path:
    """Create user memory directory, curated master, and section files."""
    path = resolve_user_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(USER_MEMORY_TEMPLATE, encoding="utf-8")
    ensure_section_files(path.parent)
    return path


def ensure_user_scope_initialized() -> Path:
    """Ensure ``~/.agents/memory`` has master, section files, and default skill config.

    Called automatically when loading or writing user scope so operators never
    need a separate ``init-user`` step.
    """
    path = ensure_user_memory()
    cfg_path = resolve_user_skill_config_path()
    if not cfg_path.exists():
        cfg_path.write_text(
            json.dumps(DEFAULT_USER_SKILL_CONFIG, indent=2) + "\n",
            encoding="utf-8",
        )
    return path


SECTION_NAMES = ("experiences", "world_knowledge", "beliefs", "reflections", "entity_summaries")

ENTITY_RE = re.compile(r"\{entities:\s*([^}]+)\}")
DATE_RE = re.compile(r"\*\*(\d{4}-\d{2}-\d{2})\*\*")
CONFIDENCE_RE = re.compile(r"\(confidence:\s*([\d.]+)")
SOURCES_RE = re.compile(r"sources:\s*(\d+)\)")
FORMED_RE = re.compile(r"formed:\s*(\d{4}-\d{2}-\d{2})")
UPDATED_RE = re.compile(r"updated:\s*(\d{4}-\d{2}-\d{2})")
CONTEXT_RE = re.compile(r"\[(\w[\w-]*)\]")
CAUSAL_RE = re.compile(r"\{(causes|caused-by|enables|prevents):\s*([^}]+)\}")
OUTCOME_RE = re.compile(r"\{outcome:\s*(success|failure|mixed|unknown)\}")
EVIDENCE_RE = re.compile(r"\{evidence:\s*([^}]+)\}")
SUMMARY_HEADING_RE = re.compile(r"^###\s+(.+)$")

# Order for digest: surface failures before successes (unknown last with successes bucket edge)
OUTCOME_DIGEST_PRIORITY = {"failure": 0, "mixed": 1, "success": 2, "unknown": 3}


@dataclass
class CausalLink:
    relation: str  # causes, caused-by, enables, prevents
    target: str    # entity name

@dataclass
class Experience:
    date: Optional[str]
    context: Optional[str]
    entities: list[str]
    causal_links: list[CausalLink]
    outcome: Optional[str]  # success | failure | mixed | unknown
    evidence: Optional[str]  # external pointer, e.g. CI URL or ticket id (no secrets)
    text: str
    raw: str

@dataclass
class WorldFact:
    entities: list[str]
    text: str
    confidence: Optional[float]
    sources: Optional[int]
    raw: str

@dataclass
class Belief:
    entities: list[str]
    text: str
    confidence: Optional[float]
    formed: Optional[str]
    updated: Optional[str]
    raw: str

@dataclass
class Reflection:
    date: Optional[str]
    entities: list[str]
    causal_links: list[CausalLink]
    text: str
    raw: str

@dataclass
class EntitySummary:
    name: str
    text: str
    raw: str

@dataclass
class MemoryBank:
    experiences: list[Experience] = field(default_factory=list)
    world_knowledge: list[WorldFact] = field(default_factory=list)
    beliefs: list[Belief] = field(default_factory=list)
    reflections: list[Reflection] = field(default_factory=list)
    entity_summaries: list[EntitySummary] = field(default_factory=list)


def parse_causal_links(line: str) -> list[CausalLink]:
    return [CausalLink(relation=m.group(1), target=m.group(2).strip())
            for m in CAUSAL_RE.finditer(line)]


def parse_entities(line: str) -> list[str]:
    m = ENTITY_RE.search(line)
    if not m:
        return []
    return [e.strip() for e in m.group(1).split(",") if e.strip()]


def strip_metadata(line: str) -> str:
    """Remove inline metadata markers to get the core text."""
    text = line.lstrip("- ").strip()
    text = DATE_RE.sub("", text).strip()
    text = CONTEXT_RE.sub("", text, count=1).strip()
    text = ENTITY_RE.sub("", text).strip()
    text = OUTCOME_RE.sub("", text).strip()
    text = EVIDENCE_RE.sub("", text).strip()
    text = CAUSAL_RE.sub("", text).strip()
    text = re.sub(r"\(confidence:.*?\)", "", text).strip()
    text = re.sub(r"\(sources:.*?\)", "", text).strip()
    text = re.sub(r"\(formed:.*?\)", "", text).strip()
    text = re.sub(r"\(updated:.*?\)", "", text).strip()
    return text


def parse_outcome(line: str) -> Optional[str]:
    m = OUTCOME_RE.search(line)
    return m.group(1).lower() if m else None


def parse_evidence(line: str) -> Optional[str]:
    m = EVIDENCE_RE.search(line)
    return m.group(1).strip() if m else None


def parse_experience(line: str) -> Experience:
    date_match = DATE_RE.search(line)
    ctx_match = CONTEXT_RE.search(line)
    return Experience(
        date=date_match.group(1) if date_match else None,
        context=ctx_match.group(1) if ctx_match else None,
        entities=parse_entities(line),
        causal_links=parse_causal_links(line),
        outcome=parse_outcome(line),
        evidence=parse_evidence(line),
        text=strip_metadata(line),
        raw=line,
    )


def parse_world_fact(line: str) -> WorldFact:
    conf_match = CONFIDENCE_RE.search(line)
    src_match = SOURCES_RE.search(line)
    return WorldFact(
        entities=parse_entities(line),
        text=strip_metadata(line),
        confidence=float(conf_match.group(1)) if conf_match else None,
        sources=int(src_match.group(1)) if src_match else None,
        raw=line,
    )


def parse_belief(line: str) -> Belief:
    conf_match = CONFIDENCE_RE.search(line)
    formed_match = FORMED_RE.search(line)
    updated_match = UPDATED_RE.search(line)
    return Belief(
        entities=parse_entities(line),
        text=strip_metadata(line),
        confidence=float(conf_match.group(1)) if conf_match else None,
        formed=formed_match.group(1) if formed_match else None,
        updated=updated_match.group(1) if updated_match else None,
        raw=line,
    )


def parse_reflection(line: str) -> Reflection:
    date_match = DATE_RE.search(line)
    return Reflection(
        date=date_match.group(1) if date_match else None,
        entities=parse_entities(line),
        causal_links=parse_causal_links(line),
        text=strip_metadata(line),
        raw=line,
    )


def parse_memory_file(path: Path) -> MemoryBank:
    if not path.exists():
        return MemoryBank()

    content = path.read_text(encoding="utf-8")
    bank = MemoryBank()

    current_section = None
    summary_name = None
    summary_lines: list[str] = []

    in_comment = False

    for line in content.splitlines():
        stripped = line.strip()

        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue

        if stripped == "## Experiences":
            _flush_summary(bank, summary_name, summary_lines)
            summary_name = None
            summary_lines = []
            current_section = "experiences"
            continue
        elif stripped == "## World Knowledge":
            _flush_summary(bank, summary_name, summary_lines)
            summary_name = None
            summary_lines = []
            current_section = "world_knowledge"
            continue
        elif stripped == "## Beliefs":
            _flush_summary(bank, summary_name, summary_lines)
            summary_name = None
            summary_lines = []
            current_section = "beliefs"
            continue
        elif stripped == "## Reflections":
            _flush_summary(bank, summary_name, summary_lines)
            summary_name = None
            summary_lines = []
            current_section = "reflections"
            continue
        elif stripped == "## Entity Summaries":
            _flush_summary(bank, summary_name, summary_lines)
            summary_name = None
            summary_lines = []
            current_section = "entity_summaries"
            continue
        elif stripped.startswith("## "):
            _flush_summary(bank, summary_name, summary_lines)
            summary_name = None
            summary_lines = []
            current_section = None
            continue

        if not stripped:
            continue

        if current_section == "experiences" and stripped.startswith("- "):
            bank.experiences.append(parse_experience(stripped))
        elif current_section == "world_knowledge" and stripped.startswith("- "):
            bank.world_knowledge.append(parse_world_fact(stripped))
        elif current_section == "beliefs" and stripped.startswith("- "):
            bank.beliefs.append(parse_belief(stripped))
        elif current_section == "reflections" and stripped.startswith("- "):
            bank.reflections.append(parse_reflection(stripped))
        elif current_section == "entity_summaries":
            heading_match = SUMMARY_HEADING_RE.match(stripped)
            if heading_match:
                _flush_summary(bank, summary_name, summary_lines)
                summary_name = heading_match.group(1).strip()
                summary_lines = []
            elif summary_name is not None:
                summary_lines.append(stripped)

    _flush_summary(bank, summary_name, summary_lines)
    return bank


def _flush_summary(bank: MemoryBank, name: Optional[str], lines: list[str]):
    if name and lines:
        text = " ".join(l for l in lines if l).strip()
        if text:
            bank.entity_summaries.append(EntitySummary(
                name=name,
                text=text,
                raw=f"### {name}\n" + "\n".join(lines),
            ))


def collect_all_entities(bank: MemoryBank) -> dict[str, list[str]]:
    """Return a map of entity -> list of sections it appears in."""
    index: dict[str, set[str]] = {}
    for exp in bank.experiences:
        for e in exp.entities:
            index.setdefault(e, set()).add("experiences")
    for wf in bank.world_knowledge:
        for e in wf.entities:
            index.setdefault(e, set()).add("world_knowledge")
    for b in bank.beliefs:
        for e in b.entities:
            index.setdefault(e, set()).add("beliefs")
    for r in bank.reflections:
        for e in r.entities:
            index.setdefault(e, set()).add("reflections")
    for es in bank.entity_summaries:
        index.setdefault(es.name, set()).add("entity_summaries")
    return {k: sorted(v) for k, v in sorted(index.items())}


def normalize_for_comparison(text: str) -> str:
    """Normalize free text for forgiving topic/entity comparison."""
    text = strip_metadata(text)
    text = text.lower()
    text = re.sub(r"[_\-]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w not in STOPWORDS]
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    """Compute forgiving similarity for fuzzy topic/entity recall."""
    na = normalize_for_comparison(a)
    nb = normalize_for_comparison(b)
    if not na or not nb:
        return 0.0
    seq_ratio = SequenceMatcher(None, na, nb).ratio()
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    intersection = len(tokens_a & tokens_b)
    union = tokens_a | tokens_b
    jaccard = intersection / len(union) if union else 0.0
    min_size = min(len(tokens_a), len(tokens_b))
    overlap = intersection / min_size if min_size else 0.0
    return max(seq_ratio, jaccard, overlap)


def _best_fuzzy_score(query: str, candidates: list[str]) -> float:
    best = 0.0
    for candidate in candidates:
        score = similarity(query, candidate)
        if score > best:
            best = score
    return best


def _resolve_fuzzy_entity_targets(bank: "MemoryBank", query: str) -> list[str]:
    """Return likely entity names for a fuzzy entity query."""
    query_norm = normalize_for_comparison(query)
    if not query_norm:
        return []

    scored: list[tuple[float, str]] = []
    for entity_name in collect_all_entities(bank):
        score = similarity(query_norm, entity_name)
        if score >= FUZZY_ENTITY_THRESHOLD:
            scored.append((score, entity_name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entity_name for _, entity_name in scored]


def _direct_recall(
    bank: "MemoryBank",
    *,
    keyword: Optional[str] = None,
    entity: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    section: Optional[str] = None,
    cross_section: bool = False,
    budget: Optional[int] = None,
) -> dict:
    """Direct recall using literal keyword and entity matching."""
    results: dict[str, list[str]] = {
        "experiences": [],
        "world_knowledge": [],
        "beliefs": [],
        "reflections": [],
        "entity_summaries": [],
    }

    sections_to_search = SECTION_NAMES
    if section and not cross_section:
        sections_to_search = (section,)
    if cross_section and entity:
        sections_to_search = SECTION_NAMES

    since_date = _parse_date(since) if since else None
    until_date = _parse_date(until) if until else None

    if "experiences" in sections_to_search:
        for exp in bank.experiences:
            if since_date and exp.date and _parse_date(exp.date) < since_date:
                continue
            if until_date and exp.date and _parse_date(exp.date) > until_date:
                continue
            if keyword:
                kw_lower = keyword.lower()
                if kw_lower not in exp.text.lower() and kw_lower not in exp.raw.lower():
                    continue
            if entity:
                if not _entity_matches(exp.entities, entity.lower()):
                    continue
            results["experiences"].append(exp.raw)

    if "world_knowledge" in sections_to_search:
        for wf in bank.world_knowledge:
            if keyword:
                kw_lower = keyword.lower()
                if kw_lower not in wf.text.lower() and kw_lower not in wf.raw.lower():
                    continue
            if entity:
                if not _entity_matches(wf.entities, entity.lower()):
                    continue
            results["world_knowledge"].append(wf.raw)

    if "beliefs" in sections_to_search:
        for b in bank.beliefs:
            if keyword:
                kw_lower = keyword.lower()
                if kw_lower not in b.text.lower() and kw_lower not in b.raw.lower():
                    continue
            if entity:
                if not _entity_matches(b.entities, entity.lower()):
                    continue
            results["beliefs"].append(b.raw)

    if "reflections" in sections_to_search:
        for r in bank.reflections:
            if since_date and r.date and _parse_date(r.date) < since_date:
                continue
            if until_date and r.date and _parse_date(r.date) > until_date:
                continue
            if keyword:
                kw_lower = keyword.lower()
                if kw_lower not in r.text.lower() and kw_lower not in r.raw.lower():
                    continue
            if entity:
                if not _entity_matches(r.entities, entity.lower()):
                    continue
            results["reflections"].append(r.raw)

    if "entity_summaries" in sections_to_search:
        for es in bank.entity_summaries:
            if keyword:
                kw_lower = keyword.lower()
                if kw_lower not in es.text.lower() and kw_lower not in es.name.lower():
                    continue
            if entity:
                if entity.lower() not in es.name.lower():
                    continue
            results["entity_summaries"].append(es.raw)

    filtered = {k: v for k, v in results.items() if v}
    if budget is not None:
        filtered = _apply_budget(filtered, budget)
    return filtered


def _fallback_recall(
    bank: "MemoryBank",
    *,
    keyword: Optional[str] = None,
    entity: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    section: Optional[str] = None,
    cross_section: bool = False,
    budget: Optional[int] = None,
) -> dict:
    """Fallback recall when direct matching misses."""
    if entity:
        targets = _resolve_fuzzy_entity_targets(bank, entity)
        if not targets:
            return {}

        results: dict[str, list[str]] = {}
        seen: dict[str, set[str]] = {}
        for target in targets:
            target_results = _direct_recall(
                bank,
                entity=target,
                since=since,
                until=until,
                section=section,
                cross_section=cross_section,
                budget=None,
            )
            for section_name, items in target_results.items():
                bucket = results.setdefault(section_name, [])
                section_seen = seen.setdefault(section_name, set())
                for item in items:
                    if item in section_seen:
                        continue
                    section_seen.add(item)
                    bucket.append(item)

        filtered = {k: v for k, v in results.items() if v}
        if budget is not None:
            filtered = _apply_budget(filtered, budget)
        return filtered

    results: dict[str, list[str]] = {
        "experiences": [],
        "world_knowledge": [],
        "beliefs": [],
        "reflections": [],
        "entity_summaries": [],
    }
    query = entity or keyword or ""
    if not normalize_for_comparison(query):
        return {}

    sections_to_search = SECTION_NAMES
    if section and not cross_section:
        sections_to_search = (section,)
    if cross_section and entity:
        sections_to_search = SECTION_NAMES

    since_date = _parse_date(since) if since else None
    until_date = _parse_date(until) if until else None

    def matches_score(candidates: list[str]) -> bool:
        return _best_fuzzy_score(query, candidates) >= FUZZY_RECALL_THRESHOLD

    if "experiences" in sections_to_search:
        for exp in bank.experiences:
            if since_date and exp.date and _parse_date(exp.date) < since_date:
                continue
            if until_date and exp.date and _parse_date(exp.date) > until_date:
                continue
            if matches_score([exp.text, exp.raw, *exp.entities]):
                results["experiences"].append(exp.raw)

    if "world_knowledge" in sections_to_search:
        for wf in bank.world_knowledge:
            if matches_score([wf.text, wf.raw, *wf.entities]):
                results["world_knowledge"].append(wf.raw)

    if "beliefs" in sections_to_search:
        for b in bank.beliefs:
            if matches_score([b.text, b.raw, *b.entities]):
                results["beliefs"].append(b.raw)

    if "reflections" in sections_to_search:
        for r in bank.reflections:
            if since_date and r.date and _parse_date(r.date) < since_date:
                continue
            if until_date and r.date and _parse_date(r.date) > until_date:
                continue
            if matches_score([r.text, r.raw, *r.entities]):
                results["reflections"].append(r.raw)

    if "entity_summaries" in sections_to_search:
        for es in bank.entity_summaries:
            if matches_score([es.name, es.text, es.raw]):
                results["entity_summaries"].append(es.raw)

    filtered = {k: v for k, v in results.items() if v}
    if budget is not None:
        filtered = _apply_budget(filtered, budget)
    return filtered


def recall(
    bank: MemoryBank,
    *,
    keyword: Optional[str] = None,
    entity: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    section: Optional[str] = None,
    cross_section: bool = False,
    budget: Optional[int] = None,
) -> dict:
    """Search memories via one deterministic entry point.

    The helper tries direct matching first, then broader fallback matching
    when the direct pass returns no results.
    """
    direct = _direct_recall(
        bank,
        keyword=keyword,
        entity=entity,
        since=since,
        until=until,
        section=section,
        cross_section=cross_section,
        budget=budget,
    )
    if direct or not (keyword or entity):
        return direct
    return _fallback_recall(
        bank,
        keyword=keyword,
        entity=entity,
        since=since,
        until=until,
        section=section,
        cross_section=cross_section,
        budget=budget,
    )


def _apply_budget(results: dict, budget: int) -> dict:
    """Trim results to fit within a character budget.

    Iterates through sections in priority order, keeping items until
    the cumulative character count exceeds the budget. Roughly
    approximates token count as chars / 4.
    """
    char_budget = budget * 4
    used = 0
    trimmed: dict = {}
    for section_name in ("world_knowledge", "beliefs", "reflections",
                          "experiences", "entity_summaries"):
        items = results.get(section_name, [])
        kept = []
        for item in items:
            item_len = len(item)
            if used + item_len > char_budget:
                break
            kept.append(item)
            used += item_len
        if kept:
            trimmed[section_name] = kept
        if used >= char_budget:
            break
    return trimmed


def stats(bank: MemoryBank, label: Optional[str] = None) -> dict:
    entity_index = collect_all_entities(bank)
    result = {
        "counts": {
            "experiences": len(bank.experiences),
            "world_knowledge": len(bank.world_knowledge),
            "beliefs": len(bank.beliefs),
            "reflections": len(bank.reflections),
            "entity_summaries": len(bank.entity_summaries),
            "total": (
                len(bank.experiences) + len(bank.world_knowledge)
                + len(bank.beliefs) + len(bank.reflections)
                + len(bank.entity_summaries)
            ),
        },
        "unique_entities": len(entity_index),
        "entities": entity_index,
    }
    if label:
        result["scope"] = label
    return result


def merge_banks(banks: list[tuple[str, MemoryBank]]) -> MemoryBank:
    """Merge multiple labeled banks into one."""
    merged = MemoryBank()
    for _, bank in banks:
        merged.experiences.extend(bank.experiences)
        merged.world_knowledge.extend(bank.world_knowledge)
        merged.beliefs.extend(bank.beliefs)
        merged.reflections.extend(bank.reflections)
        merged.entity_summaries.extend(bank.entity_summaries)
    return merged


def recall_multi(
    banks: list[tuple[str, MemoryBank]],
    **kwargs,
) -> dict:
    """Run recall across multiple scoped banks, tagging results by source."""
    combined: dict = {}
    for label, bank in banks:
        result = recall(bank, **kwargs)
        for section_name, items in result.items():
            tagged = [f"[{label}] {item}" for item in items]
            combined.setdefault(section_name, []).extend(tagged)
    return {k: v for k, v in combined.items() if v}


def stats_multi(banks: list[tuple[str, MemoryBank]]) -> dict:
    """Compute stats per scope and combined totals."""
    per_scope = []
    for label, bank in banks:
        per_scope.append(stats(bank, label=label))

    merged = merge_banks(banks)
    combined = stats(merged)
    combined["scope"] = "combined"
    combined["per_scope"] = per_scope
    return combined


def digest(
    banks: list[tuple[str, MemoryBank]],
    *,
    last: int = 5,
    days: Optional[int] = None,
) -> str:
    """Produce a human-readable memory digest for context injection.

    Shows world knowledge, beliefs, entity summaries, and recent
    experiences (bounded by count or day range). Each entry is tagged
    with its source scope.
    """
    lines: list[str] = []

    for label, bank in banks:
        has_content = (
            bank.world_knowledge or bank.beliefs or bank.reflections
            or bank.entity_summaries or bank.experiences
        )
        if not has_content:
            continue

        lines.append(f"### [{label}] memory")
        lines.append("")

        if bank.world_knowledge:
            lines.append("**World Knowledge:**")
            for wf in bank.world_knowledge:
                conf = f" ({wf.confidence})" if wf.confidence is not None else ""
                lines.append(f"- {wf.text}{conf}")
            lines.append("")

        if bank.beliefs:
            lines.append("**Beliefs:**")
            for b in bank.beliefs:
                conf = f" ({b.confidence})" if b.confidence is not None else ""
                lines.append(f"- {b.text}{conf}")
            lines.append("")

        if bank.reflections:
            lines.append("**Reflections:**")
            for r in bank.reflections:
                date_str = r.date or "unknown"
                lines.append(f"- {date_str}: {r.text}")
            lines.append("")

        if bank.entity_summaries:
            lines.append("**Entity Summaries:**")
            for es in bank.entity_summaries:
                lines.append(f"- **{es.name}**: {es.text}")
            lines.append("")

        exps = _filter_experiences(bank.experiences, last=last, days=days)
        if exps:
            range_desc = f"last {days} days" if days else f"last {len(exps)}"
            lines.append(
                f"**Recent Experiences ({range_desc}; failures/mixed listed first):**"
            )
            for exp in exps:
                lines.append(_format_digest_experience_line(exp))
            lines.append("")

    if not lines:
        return "(no memories found)"
    return "\n".join(lines).rstrip()


def _format_digest_experience_line(exp: Experience) -> str:
    """One digest line for an experience (date, tags, narrative)."""
    date_str = exp.date or "unknown"
    ctx = f" [{exp.context}]" if exp.context else ""
    oc = f" [outcome:{exp.outcome}]" if exp.outcome else ""
    ev = f" [evidence:{exp.evidence}]" if exp.evidence else ""
    return f"- {date_str}{ctx}{oc}{ev}: {exp.text}"


def _filter_experiences(
    experiences: list[Experience],
    *,
    last: int = 5,
    days: Optional[int] = None,
) -> list[Experience]:
    """Return recent experiences by count or day range."""
    if days is not None:
        cutoff = date.today() - timedelta(days=days)
        filtered = [
            e for e in experiences
            if e.date and _parse_date(e.date) >= cutoff
        ]
    else:
        filtered = experiences[:last]
    return _sort_experiences_for_digest(filtered)


def _experience_date_ordinal(exp: Experience) -> int:
    if not exp.date:
        return 0
    try:
        return _parse_date(exp.date).toordinal()
    except ValueError:
        return 0


def _sort_experiences_for_digest(experiences: list[Experience]) -> list[Experience]:
    """Surface failure/mixed outcomes first, then newer dates within each bucket."""

    def sort_key(e: Experience) -> tuple:
        o = (e.outcome or "").lower()
        pri = OUTCOME_DIGEST_PRIORITY.get(o, 3)
        return (pri, -_experience_date_ordinal(e))

    return sorted(experiences, key=sort_key)


def _entity_matches(entities: list[str], query: str) -> bool:
    return any(query in e.lower() for e in entities)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(
        description="Structured recall over MEMORY.md (user + project)"
    )
    parser.add_argument("--file", type=Path, default=None,
                        help="Explicit path to a single MEMORY.md (overrides --scope)")
    parser.add_argument("--scope", choices=list(SCOPES), default="both",
                        help="Memory scope: user, project, or both (default: both)")
    parser.add_argument("--keyword", "-k", help="Keyword substring filter")
    parser.add_argument("--entity", "-e", help="Entity name filter")
    parser.add_argument("--since", help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--until", help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--section", "-s",
                        choices=list(SECTION_NAMES),
                        help="Limit to one section")
    parser.add_argument("--cross-section", "-x", action="store_true",
                        help="With --entity, search all sections")
    parser.add_argument("--show", action="store_true",
                        help="Show a digest: world knowledge, beliefs, entity summaries, and recent experiences")
    parser.add_argument("--last", type=int, default=5,
                        help="With --show, number of recent experiences to include (default: 5)")
    parser.add_argument("--days", type=int, default=None,
                        help="With --show, include experiences from the last N days instead of --last count")
    parser.add_argument("--budget", type=int, default=None,
                        help="Max tokens for recall results (approx; chars/4)")
    parser.add_argument("--stats", action="store_true",
                        help="Print memory statistics instead of recall")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")

    args = parser.parse_args()

    if args.file:
        banks = [("file", parse_memory_file(args.file))]
    else:
        scopes_to_load = (
            ["user", "project"] if args.scope == "both"
            else [args.scope]
        )
        banks = []
        for sc in scopes_to_load:
            master, sec_dir = resolve_memory_sources(sc)
            banks.append((sc, load_memory(master, sec_dir)))

    if args.show:
        output = digest(banks, last=args.last, days=args.days)
        print(output)
        return

    if args.stats:
        if len(banks) == 1:
            result = stats(banks[0][1], label=banks[0][0])
        else:
            result = stats_multi(banks)
        print(json.dumps(result, indent=2))
        return

    if not any([args.keyword, args.entity, args.since, args.until, args.section]):
        parser.error("Specify at least one filter (--keyword, --entity, --since, --until, --section) or --stats")

    kwargs = dict(
        keyword=args.keyword,
        entity=args.entity,
        since=args.since,
        until=args.until,
        section=args.section,
        cross_section=args.cross_section,
        budget=args.budget,
    )

    if len(banks) == 1:
        result = recall(banks[0][1], **kwargs)
    else:
        result = recall_multi(banks, **kwargs)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for section_name, items in result.items():
            print(f"\n=== {section_name} ({len(items)}) ===")
            for item in items:
                print(item)

    if not result:
        print("No memories matched the query.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
