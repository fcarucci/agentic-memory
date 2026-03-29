#!/usr/bin/env python3
"""Deterministic memory management operations for MEMORY.md.

Supports two memory tiers:
  - User memory:    ~/.agents/memory/MEMORY.md by default (see memory-recall.resolve_user_memory_path)
  - Project memory: resolved at runtime (see memory-recall.resolve_project_memory_path)

Agents and hosts follow ``skills/memory/SKILL.md`` and the ``ref/*.md``
operation guides for when and how to invoke this helper. Subcommands and
flags: run ``--help`` on this module (documentation does not embed copy-paste shell).
"""

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

_VALID_OUTCOMES = frozenset({"success", "failure", "mixed", "unknown"})

# Belief temporal decay (reflect: no fresh supporting evidence). Tuned for slow,
# calendar-based drift — not a fixed penalty every reflect run.
TEMPORAL_DECAY_GRACE_DAYS = 14
TEMPORAL_DECAY_RATE = 0.00012  # per stale day beyond grace
TEMPORAL_DECAY_MAX_DELTA = 0.04  # cap magnitude per application
TEMPORAL_DECAY_AGE_SCALE_DAYS = 365.0
TEMPORAL_DECAY_AGE_BOOST = 0.25  # up to +25% when belief is ≥1 year old

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module

recall_mod = import_module("memory-recall")


def normalize_outcome(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (normalized_outcome, error_message). *error_message* is set if *raw* is invalid."""
    if raw is None or not str(raw).strip():
        return None, None
    o = str(raw).strip().lower()
    if o not in _VALID_OUTCOMES:
        return None, (
            f"Unknown outcome '{raw}'; use one of: "
            + ", ".join(sorted(_VALID_OUTCOMES))
        )
    return o, None


def _sanitize_evidence_fragment(raw: Optional[str]) -> Optional[str]:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).replace("}", "").replace("\n", " ").strip()
    if not s:
        return None
    return s[:500]


def resolve_path(scope: str) -> Path:
    """Return the curated master MEMORY.md for a scope (legacy compat)."""
    if scope == "user":
        recall_mod.ensure_user_scope_initialized()
        return recall_mod.resolve_user_memory_path()
    return recall_mod.resolve_project_memory_path()


def resolve_section_path(scope: str, section: str) -> Path:
    """Return the section file path, creating it if needed."""
    if scope == "user":
        recall_mod.ensure_user_scope_initialized()
    section_dir = recall_mod.resolve_section_dir(scope)
    return recall_mod.ensure_section_file(section_dir, section)


# --- Subagent model config (memory-skill.config.json, user memory dir) ---

SKILL_CONFIG_ENV = "MEMORY_SKILL_CONFIG_PATH"
MEMORY_SKILL_HOST_ENV = "MEMORY_SKILL_HOST"
MEMORY_SKILL_DISABLE_HOST_INFERENCE_ENV = "MEMORY_SKILL_DISABLE_HOST_INFERENCE"
KNOWN_MEMORY_HOSTS = frozenset({"cursor", "claude", "codex"})
SUBAGENT_ACTIONS = frozenset({"remember", "reflect", "maintain", "promote"})
SKILL_CONFIG_TOP_LEVEL = frozenset({
    "version", "default_preset", "presets", "actions", "overrides", "hosts",
})
OPTIONAL_OVERRIDE_KEYS = frozenset({"remember_when_auto_reflect"})


def default_skill_config() -> dict[str, Any]:
    """Built-in defaults when no config file exists (see ``ref/config.md``)."""
    return copy.deepcopy(recall_mod.DEFAULT_USER_SKILL_CONFIG)


def merge_skill_config(base: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge user file over *base* for known sections."""
    out: dict[str, Any] = json.loads(json.dumps(base))
    if "version" in user:
        out["version"] = user["version"]
    if "default_preset" in user:
        out["default_preset"] = user["default_preset"]
    if isinstance(user.get("presets"), dict):
        presets_out = dict(out["presets"])
        for k, v in user["presets"].items():
            if isinstance(k, str) and isinstance(v, str):
                presets_out[k] = v
        out["presets"] = presets_out
    if isinstance(user.get("actions"), dict):
        actions_out = dict(out["actions"])
        for k, v in user["actions"].items():
            if isinstance(k, str) and isinstance(v, str):
                actions_out[k] = v
        out["actions"] = actions_out
    if isinstance(user.get("overrides"), dict):
        ov = dict(out["overrides"])
        for k, v in user["overrides"].items():
            if isinstance(k, str) and isinstance(v, str):
                ov[k] = v
        out["overrides"] = ov
    if isinstance(user.get("hosts"), dict):
        out_hosts: dict[str, Any] = dict(out.get("hosts") or {})
        for hk, hv in user["hosts"].items():
            if not isinstance(hk, str) or not isinstance(hv, dict):
                continue
            prev = dict(out_hosts.get(hk) or {})
            if isinstance(hv.get("default_preset"), str) and hv["default_preset"].strip():
                prev["default_preset"] = hv["default_preset"]
            for sub in ("presets", "actions", "overrides"):
                if isinstance(hv.get(sub), dict):
                    sub_prev = dict(prev.get(sub) or {})
                    for sk, sv in hv[sub].items():
                        if isinstance(sk, str) and isinstance(sv, str):
                            sub_prev[sk] = sv
                    prev[sub] = sub_prev
            out_hosts[hk] = prev
        out["hosts"] = out_hosts
    return out


def resolve_skill_config_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get(SKILL_CONFIG_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return recall_mod.resolve_user_skill_config_path()


def load_skill_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load merged skill config. Missing file → defaults only."""
    path = resolve_skill_config_path(config_path)
    base = default_skill_config()
    if not path.exists():
        return base
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("memory-skill config root must be a JSON object")
    return merge_skill_config(base, raw)


def resolve_action_model(presets: dict[str, str], raw_value: str) -> dict[str, Any]:
    """Map a preset name or direct model id to a concrete ``model_id``."""
    if raw_value in presets:
        return {
            "config_value": raw_value,
            "via": "preset",
            "model_id": presets[raw_value],
        }
    return {
        "config_value": raw_value,
        "via": "direct",
        "model_id": raw_value,
    }


def _vc_msg(path_prefix: str, message: str) -> str:
    return f"{path_prefix}: {message}" if path_prefix else message


def effective_host_config(cfg: dict[str, Any], host: Optional[str]) -> dict[str, Any]:
    """Return merged ``default_preset`` / ``presets`` / ``actions`` / ``overrides`` for *host*.

    *host* ``None`` means use top-level fields only. Known hosts merge their
    ``hosts.<name>`` block over the global defaults.
    """
    presets: dict[str, str] = dict(cfg.get("presets") or {})
    actions: dict[str, str] = dict(cfg.get("actions") or {})
    default_preset = str(cfg.get("default_preset") or "")
    overrides: dict[str, str] = dict(cfg.get("overrides") or {})
    if not host:
        return {
            "default_preset": default_preset,
            "presets": presets,
            "actions": actions,
            "overrides": overrides,
        }
    block = (cfg.get("hosts") or {}).get(host)
    if not isinstance(block, dict) or not block:
        return {
            "default_preset": default_preset,
            "presets": presets,
            "actions": actions,
            "overrides": overrides,
        }
    if isinstance(block.get("default_preset"), str) and block["default_preset"].strip():
        default_preset = block["default_preset"]
    if isinstance(block.get("presets"), dict):
        for k, v in block["presets"].items():
            if isinstance(k, str) and isinstance(v, str):
                presets[k] = v
    if isinstance(block.get("actions"), dict):
        for k, v in block["actions"].items():
            if isinstance(k, str) and isinstance(v, str):
                actions[k] = v
    if isinstance(block.get("overrides"), dict):
        for k, v in block["overrides"].items():
            if isinstance(k, str) and isinstance(v, str):
                overrides[k] = v
    return {
        "default_preset": default_preset,
        "presets": presets,
        "actions": actions,
        "overrides": overrides,
    }


def infer_memory_skill_host() -> tuple[Optional[str], Optional[str]]:
    """Best-effort host id from product-injected environment (no user setup).

    Returns ``(host, signal)`` where *signal* names the first env var that
    matched (for diagnostics).  ``(None, None)`` when unknown.

    Set ``MEMORY_SKILL_DISABLE_HOST_INFERENCE=1`` to skip (tests, CI).
    """
    if os.environ.get(MEMORY_SKILL_DISABLE_HOST_INFERENCE_ENV, "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return None, None
    # Claude Code: official — set in shells spawned by Claude Code.
    if os.environ.get("CLAUDECODE", "").strip():
        return "claude", "CLAUDECODE"
    # Cursor agent / integrated terminal signals (best-effort; may evolve).
    for key in ("CURSOR_TRACE_ID", "CURSOR_AGENT"):
        if os.environ.get(key, "").strip():
            return "cursor", key
    term = (os.environ.get("TERM_PROGRAM") or "").strip().lower()
    if term == "cursor":
        return "cursor", "TERM_PROGRAM"
    # OpenAI Codex: no single stable documented inject var yet; use
    # MEMORY_SKILL_HOST or --host until one exists.
    return None, None


def resolve_memory_host_meta(explicit: Optional[str]) -> tuple[Optional[str], str]:
    """Resolve active host for ``hosts.<tool>`` merge.

    Precedence: non-empty ``--host`` CLI value → ``MEMORY_SKILL_HOST`` →
    :func:`infer_memory_skill_host` → none (global config only).

    Second return value is ``cli``, ``MEMORY_SKILL_HOST``, ``inferred:<signal>``,
    or ``none``.
    """
    if explicit is not None and str(explicit).strip():
        h = str(explicit).strip().lower()
        if h in KNOWN_MEMORY_HOSTS:
            return h, "cli"
    env = os.environ.get(MEMORY_SKILL_HOST_ENV, "").strip().lower()
    if env in KNOWN_MEMORY_HOSTS:
        return env, MEMORY_SKILL_HOST_ENV
    inferred, signal = infer_memory_skill_host()
    if inferred and signal:
        return inferred, f"inferred:{signal}"
    return None, "none"


def resolve_memory_host(explicit: Optional[str]) -> Optional[str]:
    """Return ``cursor`` / ``claude`` / ``codex`` for ``hosts.*`` merge."""
    host, _ = resolve_memory_host_meta(explicit)
    return host


def _validate_merged_routing(
    data: dict[str, Any],
    *,
    path_prefix: str,
) -> tuple[list[str], list[str]]:
    """Validate presets / actions / default_preset / overrides for one routing view."""
    errors: list[str] = []
    warnings: list[str] = []

    presets = data.get("presets")
    if not isinstance(presets, dict) or not presets:
        errors.append(_vc_msg(path_prefix, "'presets' must be a non-empty object"))
    else:
        for pk, pv in presets.items():
            if not isinstance(pk, str) or not isinstance(pv, str):
                errors.append(_vc_msg(path_prefix, "all preset keys and values must be strings"))
                break
            if not pv.strip():
                errors.append(_vc_msg(path_prefix, f"preset {pk!r} has empty model id"))

    default_preset = data.get("default_preset", "")
    if isinstance(presets, dict) and default_preset not in presets:
        errors.append(
            _vc_msg(
                path_prefix,
                f"default_preset {default_preset!r} is not a key in presets",
            )
        )

    actions = data.get("actions")
    if not isinstance(actions, dict) or not actions:
        errors.append(_vc_msg(path_prefix, "'actions' must be a non-empty object"))
    else:
        missing_actions = SUBAGENT_ACTIONS - set(actions.keys())
        if missing_actions:
            errors.append(
                _vc_msg(
                    path_prefix,
                    "actions missing required keys: " + ", ".join(sorted(missing_actions)),
                )
            )
        for ak in actions:
            if ak not in SUBAGENT_ACTIONS:
                errors.append(_vc_msg(path_prefix, f"unknown action key: {ak!r}"))
        for ak, av in actions.items():
            if ak not in SUBAGENT_ACTIONS:
                continue
            if not isinstance(av, str) or not av.strip():
                errors.append(_vc_msg(path_prefix, f"actions.{ak} must be a non-empty string"))

    overrides = data.get("overrides", {})
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        errors.append(_vc_msg(path_prefix, "'overrides' must be an object when present"))
    else:
        for ok in overrides:
            if ok not in OPTIONAL_OVERRIDE_KEYS:
                warnings.append(
                    _vc_msg(path_prefix, f"unknown overrides key (forward-compat): {ok!r}")
                )

    return errors, warnings


def validate_skill_config_structure(data: dict[str, Any]) -> dict[str, Any]:
    """Validate merged config. Returns ``valid``, ``errors``, ``warnings``."""
    errors: list[str] = []
    warnings: list[str] = []

    for key in data:
        if key not in SKILL_CONFIG_TOP_LEVEL:
            warnings.append(f"unknown top-level key ignored by validator: {key!r}")

    ver = data.get("version", 1)
    if ver != 1:
        errors.append(f"unsupported version: {ver!r} (expected 1)")

    global_eff = effective_host_config(data, None)
    e, w = _validate_merged_routing(global_eff, path_prefix="")
    errors.extend(e)
    warnings.extend(w)

    hosts = data.get("hosts", None)
    if hosts is not None:
        if not isinstance(hosts, dict):
            errors.append("'hosts' must be an object when present")
        else:
            for hk, hv in hosts.items():
                if not isinstance(hk, str):
                    errors.append("hosts keys must be strings")
                    continue
                if hk not in KNOWN_MEMORY_HOSTS:
                    warnings.append(
                        "unknown hosts key "
                        f"(allowed: {', '.join(sorted(KNOWN_MEMORY_HOSTS))}): {hk!r}"
                    )
                if not isinstance(hv, dict):
                    errors.append(f"hosts.{hk} must be an object")
                    continue
                if not hv:
                    continue
                eff = effective_host_config(data, hk)
                e2, w2 = _validate_merged_routing(eff, path_prefix=f"hosts.{hk}")
                errors.extend(e2)
                warnings.extend(w2)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def build_config_hints(
    config_path: Optional[Path] = None,
    host: Optional[str] = None,
    *,
    host_resolution: Optional[str] = None,
) -> dict[str, Any]:
    """Structured output for orchestrators spawning memory subagents.

    *host_resolution* documents how *host* was chosen (e.g. ``inferred:CLAUDECODE``).
    """
    path = resolve_skill_config_path(config_path)
    exists = path.exists()
    try:
        cfg = load_skill_config(config_path)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        return {
            "config_path": str(path),
            "config_exists": exists,
            "load_error": str(e),
            "host": host,
            "host_resolution": host_resolution,
            "hosts_defined": [],
            "subagent_models": {},
            "optional_escalation": {},
        }

    vr = validate_skill_config_structure(cfg)
    hosts_defined = sorted(
        hk
        for hk, hv in (cfg.get("hosts") or {}).items()
        if isinstance(hk, str) and isinstance(hv, dict) and hv
    )
    if not vr["valid"]:
        return {
            "config_path": str(path),
            "config_exists": exists,
            "version": cfg.get("version", 1),
            "validation": vr,
            "host": host,
            "host_resolution": host_resolution,
            "hosts_defined": hosts_defined,
            "subagent_models": {},
            "optional_escalation": {},
            "note": "Resolve validation errors before using subagent_models.",
        }

    eff = effective_host_config(cfg, host)
    presets: dict[str, str] = dict(eff.get("presets") or {})

    subagent_models: dict[str, Any] = {}
    for action in sorted(SUBAGENT_ACTIONS):
        raw = (eff.get("actions") or {}).get(action)
        if not raw:
            dp = eff.get("default_preset", "")
            raw = dp if dp in presets else ""
        if not raw:
            subagent_models[action] = {
                "error": "missing action mapping and default_preset",
            }
            continue
        subagent_models[action] = resolve_action_model(presets, raw)

    optional_escalation: dict[str, Any] = {}
    overrides = eff.get("overrides") or {}
    if isinstance(overrides, dict):
        raw_esc = overrides.get("remember_when_auto_reflect")
        if isinstance(raw_esc, str) and raw_esc.strip():
            optional_escalation["remember_when_auto_reflect"] = resolve_action_model(
                presets, raw_esc
            )

    return {
        "config_path": str(path),
        "config_exists": exists,
        "version": cfg.get("version", 1),
        "validation": vr,
        "host": host,
        "host_resolution": host_resolution,
        "hosts_defined": hosts_defined,
        "subagent_models": subagent_models,
        "optional_escalation": optional_escalation,
        "note": (
            "Use subagent_models when spawning memory subagents. "
            "optional_escalation applies if the host splits retain vs auto-reflect. "
            "Host merge uses --host, then MEMORY_SKILL_HOST, then automatic "
            "inference (CLAUDECODE, CURSOR_TRACE_ID, CURSOR_AGENT, TERM_PROGRAM=cursor). "
            "Override with MEMORY_SKILL_HOST or --host when inference is wrong; "
            "set MEMORY_SKILL_DISABLE_HOST_INFERENCE=1 to disable inference (tests)."
        ),
    }


def run_validate_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    path = resolve_skill_config_path(config_path)
    exists = path.exists()
    try:
        cfg = load_skill_config(config_path)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "config_path": str(path),
            "config_exists": exists,
            "errors": [f"invalid JSON: {e}"],
            "warnings": [],
        }
    except (ValueError, OSError) as e:
        return {
            "valid": False,
            "config_path": str(path),
            "config_exists": exists,
            "errors": [str(e)],
            "warnings": [],
        }
    vr = validate_skill_config_structure(cfg)
    out: dict[str, Any] = {
        "valid": vr["valid"],
        "config_path": str(path),
        "config_exists": exists,
        "errors": vr["errors"],
        "warnings": vr["warnings"],
    }
    if vr["valid"]:
        out["presets"] = list((cfg.get("presets") or {}).keys())
        out["actions"] = list((cfg.get("actions") or {}).keys())
        out["hosts"] = sorted(
            hk
            for hk, hv in (cfg.get("hosts") or {}).items()
            if isinstance(hk, str) and isinstance(hv, dict) and hv
        )
    return out


DUPLICATE_THRESHOLD = 0.65

STOPWORDS = frozenset({
    "a", "an", "the", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over",
    "and", "but", "or", "nor", "not", "so", "yet",
    "it", "its", "this", "that", "these", "those",
    "i", "we", "you", "he", "she", "they", "me", "us", "him", "her", "them",
    "my", "our", "your", "his", "their",
    "today", "yesterday", "session", "currently",
})

CANONICAL_CONTEXT_TAGS = frozenset({
    "debug", "testing", "tooling", "workflow", "decision", "preference",
    "infra", "docs", "ui", "backend", "security",
})

CONTEXT_ALIASES = {
    "debugging": "debug",
    "test": "testing",
    "tests": "testing",
    "preferences": "preference",
    "infrastructure": "infra",
    "documentation": "docs",
}

PASCAL_COMMON = frozenset({
    "The", "This", "That", "These", "Those", "What", "When", "Where",
    "Which", "Who", "How", "And", "But", "For", "Not", "All", "Any",
    "Each", "Every", "Some", "Its", "Our", "His", "Her", "Can",
    "May", "Use", "Run", "Set", "Get", "Add", "See", "Try",
})

ENTITY_PATTERN = re.compile(
    r"(?:"
    r"\b[A-Z][a-zA-Z]{2,}\b"  # single PascalCase word (OpenClaw, Dioxus, Tailwind)
    r"|\b[a-zA-Z0-9]+[-_][a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*\b"  # hyphenated/underscored (e2e-mock-gateway)
    r"|`[^`]+`"  # backtick-quoted identifiers
    r")"
)

LOWERCASE_ENTITY_ALIASES = {
    "api": "api",
    "cargo": "cargo",
    "docker": "docker",
    "dioxus": "dioxus",
    "dx": "dx",
    "fastapi": "fastapi",
    "gateway": "gateway",
    "npm": "npm",
    "openclaw": "openclaw",
    "playwright": "playwright",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "redis": "redis",
    "redis-cli": "redis-cli",
    "rust": "rust",
    "sqlalchemy": "sqlalchemy",
    "sqlite": "sqlite",
    "tailwind": "tailwind",
    "websocket": "websocket",
}

SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|token|auth[_-]?token|cookie|session[_-]?id)\b"
            r"(\s*(?:=|:|is)\s*)([^\s,;]+)"
        ),
    ),
    ("private-key-material", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "known-secret-prefix",
        re.compile(r"\b(?:ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|sk_(?:live|test)_[A-Za-z0-9]+|AKIA[0-9A-Z]{16})\b"),
    ),
    ("credential-url", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s]+@")),
)


def normalize_for_comparison(text: str) -> str:
    """Normalize text for duplicate comparison.

    Strips metadata, lowercases, splits compound identifiers,
    removes stopwords and extra whitespace.
    """
    text = recall_mod.strip_metadata(text)
    text = text.lower()
    text = re.sub(r"[_\-]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w not in STOPWORDS]
    return " ".join(words)


def content_hash(text: str) -> str:
    """Return a stable content hash for optimistic concurrency checks."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text_if_unchanged(path: Path, new_text: str, expected_hash: str) -> dict:
    """Atomically replace a file only if it still matches expected_hash."""
    current_text = path.read_text(encoding="utf-8") if path.exists() else ""
    current_hash = content_hash(current_text)
    if current_hash != expected_hash:
        return {
            "success": False,
            "error": "stale write blocked: file changed since it was read",
            "expected_hash": expected_hash,
            "current_hash": current_hash,
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(new_text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    return {"success": True, "path": str(path), "hash": content_hash(new_text)}


def normalize_context_tag(context: Optional[str]) -> Optional[str]:
    """Normalize free-form context tags to the canonical vocabulary."""
    if context is None:
        return None
    normalized = context.strip().lower().replace("_", "-")
    normalized = CONTEXT_ALIASES.get(normalized, normalized)
    if normalized in CANONICAL_CONTEXT_TAGS:
        return normalized
    return None


def canonicalize_entity(entity: str) -> str:
    """Normalize entity tags to lowercase hyphenated identifiers."""
    normalized = entity.strip().strip("`").lower()
    normalized = re.sub(r"[\s_]+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9-]", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return LOWERCASE_ENTITY_ALIASES.get(normalized, normalized)


def canonicalize_entities(entities: list[str]) -> list[str]:
    """Deduplicate and sort canonical entity tags."""
    canonical = {
        canonicalize_entity(entity)
        for entity in entities
        if canonicalize_entity(entity)
    }
    return sorted(canonical)


def screen_text(text: str) -> dict:
    """Detect sensitive content and produce a sanitized preview."""
    sanitized = text
    issues = []

    for issue_type, pattern in SENSITIVE_VALUE_PATTERNS:
        if issue_type == "credential-assignment":
            def repl(match: re.Match[str]) -> str:
                issues.append({
                    "type": issue_type,
                    "match": match.group(0),
                    "field": match.group(1).lower(),
                })
                return f"{match.group(1)}{match.group(2)}[REDACTED]"

            sanitized = pattern.sub(repl, sanitized)
            continue

        match = pattern.search(sanitized)
        if match:
            issues.append({"type": issue_type, "match": match.group(0)})
            sanitized = pattern.sub("[REDACTED]", sanitized)

    return {
        "safe": len(issues) == 0,
        "issues": issues,
        "sanitized_text": sanitized,
    }


def similarity(a: str, b: str) -> float:
    """Compute similarity using three complementary metrics.

    SequenceMatcher catches rewordings that preserve order.
    Jaccard catches shared-term overlap.
    Overlap coefficient handles asymmetric lengths (short query
    contained within a longer entry).
    """
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


def _validate_bank(bank: "recall_mod.MemoryBank") -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for entries inside a parsed bank."""
    errors: list[str] = []
    warnings: list[str] = []

    for i, exp in enumerate(bank.experiences):
        if not exp.date:
            warnings.append(f"Experience {i}: missing date")
        if not exp.entities:
            warnings.append(f"Experience {i}: no entity tags")
        if len(exp.text) < 20:
            warnings.append(f"Experience {i}: very short text ({len(exp.text)} chars) — may lack narrative quality")

    for i, wf in enumerate(bank.world_knowledge):
        if wf.confidence is None:
            warnings.append(f"World fact {i}: missing confidence score")
        elif not 0.0 <= wf.confidence <= 1.0:
            errors.append(f"World fact {i}: confidence must be between 0.0 and 1.0")
        if not wf.entities:
            warnings.append(f"World fact {i}: no entity tags")

    for i, b in enumerate(bank.beliefs):
        if b.confidence is None:
            warnings.append(f"Belief {i}: missing confidence score")
        elif not 0.0 <= b.confidence <= 1.0:
            errors.append(f"Belief {i}: confidence must be between 0.0 and 1.0")
        if b.formed is None:
            warnings.append(f"Belief {i}: missing formed date")
        if not b.entities:
            warnings.append(f"Belief {i}: no entity tags")

    return errors, warnings


def validate(path: Path) -> dict:
    """Validate a single MEMORY.md (legacy or curated master)."""
    if not path.exists():
        return {"valid": False, "errors": ["MEMORY.md does not exist"], "warnings": []}

    content = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    valid_headings = (
        "# Agentic Memory",
        "# Agent Memory",  # legacy
        "# User Memory",
        "# Daneel Agentic Memory",
        "# Daneel Agent Memory",  # legacy
        "# Daneel User Memory",
    )
    if not any(h in content for h in valid_headings):
        errors.append(
            "Missing top-level heading (expected '# Agentic Memory' or '# User Memory')"
        )

    is_curated = _CURATED_MASTER_MARKER in content
    if not is_curated:
        for heading in ("## Experiences", "## World Knowledge", "## Beliefs", "## Reflections", "## Entity Summaries"):
            if heading not in content:
                errors.append(f"Missing section '{heading}'")

    bank = recall_mod.parse_memory_file(path)
    entry_errors, entry_warnings = _validate_bank(bank)
    errors.extend(entry_errors)
    warnings.extend(entry_warnings)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "experiences": len(bank.experiences),
            "world_knowledge": len(bank.world_knowledge),
            "beliefs": len(bank.beliefs),
            "entity_summaries": len(bank.entity_summaries),
        },
    }


def validate_sections(scope: str) -> dict:
    """Validate all per-section files for *scope*."""
    section_dir = recall_mod.resolve_section_dir(scope)
    if not recall_mod.has_section_files(section_dir):
        return {"valid": False, "errors": ["No section files found"], "warnings": [],
                "section_dir": str(section_dir)}

    all_errors: list[str] = []
    all_warnings: list[str] = []
    counts: dict[str, int] = {}

    for section_name, filename in recall_mod.SECTION_FILES.items():
        path = section_dir / filename
        if not path.exists():
            all_warnings.append(f"Missing section file: {filename}")
            counts[section_name] = 0
            continue
        bank = recall_mod.parse_memory_file(path)
        entry_errors, entry_warnings = _validate_bank(bank)
        all_errors.extend(f"[{filename}] {e}" for e in entry_errors)
        all_warnings.extend(f"[{filename}] {w}" for w in entry_warnings)
        counts[section_name] = len(getattr(bank, section_name))

    return {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": all_warnings,
        "counts": counts,
        "section_dir": str(section_dir),
    }


def check_duplicate(path: Path, section: str, candidate: str,
                     extra_paths: Optional[list[tuple[str, Path]]] = None) -> dict:
    """Check if a candidate text is a near-duplicate of existing entries.

    When extra_paths is provided, also checks those files for duplicates
    (used for cross-scope checking: e.g. check user memory candidate
    against project memory too).
    """
    sources: list[tuple[str, Path]] = [("target", path)]
    if extra_paths:
        sources.extend(extra_paths)

    candidate_norm = normalize_for_comparison(candidate)
    matches = []

    for source_label, source_path in sources:
        bank = recall_mod.parse_memory_file(source_path)

        items: list[str] = []
        if section == "experiences":
            items = [e.text for e in bank.experiences]
        elif section == "world_knowledge":
            items = [w.text for w in bank.world_knowledge]
        elif section == "beliefs":
            items = [b.text for b in bank.beliefs]

        for i, item in enumerate(items):
            sim = similarity(candidate, item)
            if sim >= DUPLICATE_THRESHOLD:
                entry = {
                    "index": i,
                    "similarity": round(sim, 3),
                    "existing_text": item,
                }
                if source_label != "target":
                    entry["source"] = source_label
                matches.append(entry)

    matches.sort(key=lambda m: m["similarity"], reverse=True)

    return {
        "is_duplicate": len(matches) > 0,
        "candidate_normalized": candidate_norm,
        "matches": matches,
    }


def compute_temporal_decay_delta(
    staleness_days: int,
    belief_age_days: int,
    *,
    grace_days: int = TEMPORAL_DECAY_GRACE_DAYS,
    rate: float = TEMPORAL_DECAY_RATE,
    max_delta: float = TEMPORAL_DECAY_MAX_DELTA,
    age_scale_days: float = TEMPORAL_DECAY_AGE_SCALE_DAYS,
    age_boost: float = TEMPORAL_DECAY_AGE_BOOST,
) -> float:
    """Negative confidence delta when a belief lacks support; 0 if not stale enough.

    *staleness_days* — calendar days since ``updated`` (fallback ``formed``): time
    since the belief line last reflected substantive change. Decay applications
    should use ``update_confidence(..., bump_updated=False)`` so this clock does
    not reset on decay-only updates.

    *belief_age_days* — calendar days since ``formed`` (fallback ``updated``):
    older beliefs decay slightly faster once past the grace window.
    """
    if staleness_days <= grace_days:
        return 0.0
    excess = staleness_days - grace_days
    age_factor = 1.0 + min(1.0, max(0, belief_age_days) / age_scale_days) * age_boost
    raw = rate * excess * age_factor
    return -round(min(max_delta, raw), 2)


def preview_belief_temporal_decay(path: Path, as_of: Optional[date] = None) -> dict:
    """Per-belief staleness/age and the temporal decay delta if unsupported.

    Subagents use this during reflect after deciding a belief has no fresh
    supporting evidence; reinforcement/contradiction use normal deltas with
    ``bump_updated`` left True (default).
    """
    as_of_d = as_of or date.today()
    bank = recall_mod.parse_memory_file(path)
    rows: list[dict[str, Any]] = []
    for i, b in enumerate(bank.beliefs):
        upd = _parse_iso_date_string(b.updated)
        frm = _parse_iso_date_string(b.formed)
        ref = upd or frm
        if ref is None:
            rows.append(
                {
                    "index": i,
                    "staleness_days": None,
                    "belief_age_days": None,
                    "temporal_decay_if_unsupported": 0.0,
                    "warning": True,
                    "note": "missing formed/updated dates",
                }
            )
            continue
        staleness_days = max(0, (as_of_d - ref).days)
        age_ref = frm or upd or ref  # ref is guaranteed non-None here
        belief_age_days = max(0, (as_of_d - age_ref).days)
        rows.append(
            {
                "index": i,
                "updated": (upd.isoformat() if upd else None),
                "formed": (frm.isoformat() if frm else None),
                "staleness_days": staleness_days,
                "belief_age_days": belief_age_days,
                "temporal_decay_if_unsupported": compute_temporal_decay_delta(
                    staleness_days, belief_age_days
                ),
            }
        )
    return {"as_of": as_of_d.isoformat(), "beliefs": rows}


def update_confidence(
    path: Path,
    section: str,
    index: int,
    delta: float,
    *,
    bump_updated: bool = True,
) -> dict:
    """Deterministically update a confidence score and rewrite the file.

    delta > 0 reinforces, delta < 0 weakens. Clamped to [0.0, 1.0].
    For belief *temporal decay* (no new support), pass bump_updated=False so
    ``updated`` stays unchanged and staleness accumulates until reinforcement
    or contradiction bumps it.
    """
    if section not in ("beliefs", "world_knowledge"):
        return {"success": False, "error": f"Section '{section}' does not have confidence scores"}

    content = path.read_text(encoding="utf-8")
    original_hash = content_hash(content)
    lines = content.splitlines()

    section_header = "## Beliefs" if section == "beliefs" else "## World Knowledge"
    in_section = False
    in_comment = False
    item_count = 0
    target_line_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped == section_header:
            in_section = True
            continue
        if stripped.startswith("## ") and in_section:
            break
        if in_section and stripped.startswith("- "):
            if item_count == index:
                target_line_idx = i
                break
            item_count += 1

    if target_line_idx is None:
        return {"success": False, "error": f"Index {index} not found in {section}"}

    line = lines[target_line_idx]
    conf_match = recall_mod.CONFIDENCE_RE.search(line)
    if not conf_match:
        return {"success": False, "error": f"No confidence score found at index {index}"}

    old_conf = float(conf_match.group(1))
    new_conf = round(max(0.0, min(1.0, old_conf + delta)), 2)

    new_line = line[:conf_match.start(1)] + f"{new_conf}" + line[conf_match.end(1):]

    if section == "beliefs" and bump_updated:
        today = date.today().isoformat()
        updated_match = recall_mod.UPDATED_RE.search(new_line)
        if updated_match:
            new_line = new_line[:updated_match.start(1)] + today + new_line[updated_match.end(1):]

    lines[target_line_idx] = new_line
    write_result = write_text_if_unchanged(path, "\n".join(lines) + "\n", original_hash)
    if not write_result["success"]:
        return write_result

    return {
        "success": True,
        "section": section,
        "index": index,
        "old_confidence": old_conf,
        "new_confidence": new_conf,
        "delta": delta,
    }


def extract_entities(text: str) -> dict:
    """Extract candidate entity names from free text.

    Uses heuristic patterns: PascalCase words, hyphenated identifiers,
    and backtick-quoted terms. The subagent uses this as a suggestion
    list and applies judgment to finalize the entity set.
    """
    candidates = set()
    for match in ENTITY_PATTERN.finditer(text):
        term = match.group().strip("`")
        if term.lower() not in STOPWORDS and len(term) > 1 and term not in PASCAL_COMMON:
            candidates.add(term)

    backtick_re = re.compile(r"`([^`]+)`")
    for m in backtick_re.finditer(text):
        term = m.group(1).strip()
        if term and len(term) > 1:
            candidates.add(term)

    for token in re.findall(r"\b[a-z][a-z0-9_-]*\b", text.lower()):
        if token in LOWERCASE_ENTITY_ALIASES:
            candidates.add(token)

    canonical_candidates = canonicalize_entities(sorted(candidates))

    return {
        "candidates": canonical_candidates,
        "count": len(canonical_candidates),
    }


def prune_beliefs(path: Path, threshold: float) -> dict:
    """Identify beliefs below the confidence threshold for removal."""
    bank = recall_mod.parse_memory_file(path)
    prunable = []
    for i, b in enumerate(bank.beliefs):
        if b.confidence is not None and b.confidence < threshold:
            prunable.append({
                "index": i,
                "confidence": b.confidence,
                "text": b.text,
            })
    return {
        "threshold": threshold,
        "prunable_count": len(prunable),
        "prunable": prunable,
        "total_beliefs": len(bank.beliefs),
    }


CONFLICT_SIGNALS = {
    "positive": frozenset({
        "reliable", "better", "preferred", "recommended", "effective",
        "faster", "easier", "useful", "valuable", "important", "strong",
        "always", "best", "safe", "stable", "consistent",
    }),
    "negative": frozenset({
        "unreliable", "worse", "avoid", "fragile", "slow", "harder",
        "useless", "risky", "dangerous", "weak", "never", "worst",
        "unstable", "inconsistent", "broken", "fails", "flawed",
    }),
}


def _sentiment_words(text: str) -> tuple[set[str], set[str]]:
    """Extract positive and negative sentiment words from text."""
    words = set(normalize_for_comparison(text).split())
    pos = words & CONFLICT_SIGNALS["positive"]
    neg = words & CONFLICT_SIGNALS["negative"]
    return pos, neg


def check_conflicts(path: Path) -> dict:
    """Detect potential contradictions between belief pairs.

    Two beliefs conflict when they share entities but express opposing
    sentiment. Returns pairs with a conflict score and recommendation.
    """
    bank = recall_mod.parse_memory_file(path)
    conflicts = []

    for i, a in enumerate(bank.beliefs):
        for j, b in enumerate(bank.beliefs):
            if j <= i:
                continue

            shared_entities = set(a.entities) & set(b.entities)
            if not shared_entities:
                continue

            text_sim = similarity(a.text, b.text)
            if text_sim < 0.3:
                continue

            pos_a, neg_a = _sentiment_words(a.text)
            pos_b, neg_b = _sentiment_words(b.text)

            opposing = (pos_a & neg_b) or (neg_a & pos_b)
            a_positive = len(pos_a) > len(neg_a)
            b_positive = len(pos_b) > len(neg_b)
            sentiment_conflict = (a_positive != b_positive) and (pos_a or neg_a) and (pos_b or neg_b)

            if not opposing and not sentiment_conflict:
                continue

            conf_a = a.confidence if a.confidence is not None else 0.5
            conf_b = b.confidence if b.confidence is not None else 0.5

            conflicts.append({
                "belief_a": {"index": i, "text": a.text, "confidence": conf_a},
                "belief_b": {"index": j, "text": b.text, "confidence": conf_b},
                "shared_entities": sorted(shared_entities),
                "text_similarity": round(text_sim, 3),
                "recommendation": (
                    f"keep index {i} (higher confidence)"
                    if conf_a > conf_b
                    else f"keep index {j} (higher confidence)"
                    if conf_b > conf_a
                    else "merge into a nuanced belief"
                ),
            })

    conflicts.sort(key=lambda c: c["text_similarity"], reverse=True)

    return {
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "total_beliefs": len(bank.beliefs),
    }


def suggest_summaries(path: Path) -> dict:
    """Identify entities with 3+ mentions that lack a summary."""
    bank = recall_mod.parse_memory_file(path)
    entity_index = recall_mod.collect_all_entities(bank)

    entity_counts: dict[str, int] = {}
    for exp in bank.experiences:
        for e in exp.entities:
            entity_counts[e] = entity_counts.get(e, 0) + 1
    for wf in bank.world_knowledge:
        for e in wf.entities:
            entity_counts[e] = entity_counts.get(e, 0) + 1
    for b in bank.beliefs:
        for e in b.entities:
            entity_counts[e] = entity_counts.get(e, 0) + 1

    existing_summaries = {es.name.lower() for es in bank.entity_summaries}
    suggestions = []
    for entity, count in sorted(entity_counts.items(), key=lambda x: -x[1]):
        if count >= 3 and entity.lower() not in existing_summaries:
            suggestions.append({
                "entity": entity,
                "mention_count": count,
                "sections": entity_index.get(entity, []),
            })

    return {
        "suggestions": suggestions,
        "existing_summary_count": len(bank.entity_summaries),
    }


def init_user() -> dict:
    """Idempotently ensure user memory layout (same as automatic first-use init)."""
    cfg_path = recall_mod.resolve_user_skill_config_path()
    had_config = cfg_path.exists()
    path = recall_mod.ensure_user_scope_initialized()
    section_dir = recall_mod.resolve_section_dir("user")
    created = recall_mod.ensure_section_files(section_dir)
    return {
        "success": True,
        "path": str(path),
        "section_dir": str(section_dir),
        "section_files": [str(p) for p in created],
        "created": path.exists(),
        "skill_config_path": str(cfg_path),
        "skill_config_seeded": cfg_path.exists() and not had_config,
    }


def migrate(master_path: Path, scope: str) -> dict:
    """Split a single-file MEMORY.md into per-section files.

    Existing section files are NOT overwritten; only missing entries are
    appended.  After migration the master is overwritten with the curated
    template (no ``.bak`` file).
    """
    if not master_path.exists():
        return {"success": False, "error": "Master MEMORY.md does not exist"}

    bank = recall_mod.parse_memory_file(master_path)
    if scope == "user":
        section_dir = master_path.parent
    else:
        section_dir = master_path.parent / "memory"
    section_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    for section_name in recall_mod.SECTION_FILES:
        items = getattr(bank, section_name)
        if not items:
            recall_mod.ensure_section_file(section_dir, section_name)
            written[section_name] = 0
            continue

        sf_path = recall_mod.section_file_path(section_dir, section_name)
        if sf_path.exists():
            existing_bank = recall_mod.parse_memory_file(sf_path)
            existing_raws = {entry.raw.strip() for entry in getattr(existing_bank, section_name)}
        else:
            existing_raws = set()

        new_entries = [e for e in items if e.raw.strip() not in existing_raws]
        template = recall_mod.SECTION_TEMPLATES[section_name]
        if sf_path.exists():
            content = sf_path.read_text(encoding="utf-8")
        else:
            content = template

        for entry in new_entries:
            content = content.rstrip("\n") + "\n\n" + entry.raw + "\n"

        sf_path.write_text(content, encoding="utf-8")
        written[section_name] = len(new_entries)

    template = (
        recall_mod.USER_MEMORY_TEMPLATE if scope == "user"
        else recall_mod.CURATED_MASTER_TEMPLATE
    )
    master_path.write_text(template, encoding="utf-8")

    return {
        "success": True,
        "section_dir": str(section_dir),
        "entries_migrated": written,
    }


def _curated_preview_line(text: str, max_len: int = 140) -> str:
    """Single-line preview for curated MEMORY.md (whitespace collapsed, optional ellipsis)."""
    t = " ".join(text.split())
    if not t:
        return "(empty)"
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _curated_section_href(scope: str, section_key: str) -> str:
    """Path from MEMORY.md to the section file (markdown link target)."""
    fname = recall_mod.SECTION_FILES[section_key]
    if scope == "user":
        return fname
    return f"memory/{fname}"


def curate(scope: str, *, max_world: int = 5, max_beliefs: int = 5,
           max_summaries: int = 10) -> dict:
    """Regenerate the thin curated master ``MEMORY.md``.

    **Legacy monolithic master:** If ``MEMORY.md`` is not a curated stub but
    contains memory entries, **migrate** runs first (entries go to
    per-section files; the master is overwritten—no ``.bak`` file).

    **Normal path:** Loads from section files and overwrites the master with
    **one-line previews** (highest-confidence world knowledge and beliefs,
    capped entity summaries) plus links to each section file. Any fat content
    pasted back into a curated shell is dropped in favor of section files.
    Experiences and reflections stay out of the master because they are verbose
    and temporal.
    """
    master = (recall_mod.resolve_user_memory_path() if scope == "user"
              else recall_mod.resolve_project_memory_path())
    section_dir = recall_mod.resolve_section_dir(scope)

    migrated: Optional[dict] = None
    if master.exists():
        bank_m = recall_mod.parse_memory_file(master)
        n_master = (
            len(bank_m.experiences)
            + len(bank_m.world_knowledge)
            + len(bank_m.beliefs)
            + len(bank_m.reflections)
            + len(bank_m.entity_summaries)
        )
        legacy_journal = not _memory_master_is_curated(master) and n_master > 0
        if legacy_journal:
            migrated = migrate(master, scope)
            if not migrated.get("success"):
                return migrated

    if not recall_mod.has_section_files(section_dir):
        return {
            "success": False,
            "error": (
                "No section files found; nothing to curate. "
                "For a legacy single-file MEMORY.md with entries, curate "
                "migrates automatically — ensure MEMORY.md exists and is readable."
            ),
        }

    bank = recall_mod.load_memory_from_sections(section_dir)

    lines: list[str] = []
    title = "# User Memory" if scope == "user" else "# Agentic Memory"
    lines.append(title)
    lines.append("")
    lines.append("<!-- Curated subset suitable for inclusion in AGENTS.md.")
    lines.append("     One-line previews; follow links for full markdown in section files.")
    lines.append("     Regenerate via memory skill curation (SKILL.md / ref/retain.md) -->")
    lines.append("")

    wk = sorted(bank.world_knowledge,
                key=lambda w: w.confidence if w.confidence is not None else 0,
                reverse=True)[:max_world]
    lines.append("## World Knowledge")
    lines.append("")
    for w in wk:
        lines.append(f"- {_curated_preview_line(w.text)}")
    wk_href = _curated_section_href(scope, "world_knowledge")
    wk_fname = recall_mod.SECTION_FILES["world_knowledge"]
    lines.append("")
    lines.append(f"*Full section: [{wk_fname}]({wk_href})*")
    lines.append("")

    beliefs = sorted(bank.beliefs,
                     key=lambda b: b.confidence if b.confidence is not None else 0,
                     reverse=True)[:max_beliefs]
    lines.append("## Beliefs")
    lines.append("")
    for b in beliefs:
        lines.append(f"- {_curated_preview_line(b.text)}")
    bl_href = _curated_section_href(scope, "beliefs")
    bl_fname = recall_mod.SECTION_FILES["beliefs"]
    lines.append("")
    lines.append(f"*Full section: [{bl_fname}]({bl_href})*")
    lines.append("")

    lines.append("## Entity Summaries")
    lines.append("")
    es_slice = bank.entity_summaries[:max_summaries]
    for es in es_slice:
        prev = _curated_preview_line(es.text)
        lines.append(f"- **{es.name}**: {prev}")
    es_href = _curated_section_href(scope, "entity_summaries")
    es_fname = recall_mod.SECTION_FILES["entity_summaries"]
    lines.append("")
    lines.append(f"*Full section: [{es_fname}]({es_href})*")
    lines.append("")

    master.write_text("\n".join(lines), encoding="utf-8")

    result: dict = {
        "success": True,
        "path": str(master),
        "counts": {
            "world_knowledge": len(wk),
            "beliefs": len(beliefs),
            "entity_summaries": len(es_slice),
        },
    }
    if migrated is not None:
        result["migrated"] = migrated
    return result


def _parse_iso_date_string(value: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD or return None if missing or invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _maintenance_text_preview(text: str, max_len: int = 120) -> str:
    """Single-line preview for maintenance-report JSON (ellipsis when truncated)."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def maintenance_report(
    *,
    scope_label: str = "user",
    memory_file: Optional[Path] = None,
    experience_min_age_days: int = 90,
    belief_stale_days: int = 120,
    world_max_sources: int = 1,
) -> dict:
    """List maintenance candidates: old experiences, low-source facts, stale beliefs.

    When *memory_file* is set, parse that single file (legacy or test layout).
    Otherwise load *scope_label* via the normal master + section-dir path.
    """
    if memory_file is not None:
        bank = recall_mod.parse_memory_file(memory_file)
        scope_display = "file"
    else:
        if scope_label == "user":
            recall_mod.ensure_user_scope_initialized()
            master = recall_mod.resolve_user_memory_path()
        else:
            master = recall_mod.resolve_project_memory_path()
        section_dir = recall_mod.resolve_section_dir(scope_label)
        bank = recall_mod.load_memory(master, section_dir)
        scope_display = scope_label

    today = date.today()

    stale_experiences: list[dict] = []
    for i, exp in enumerate(bank.experiences):
        exp_date = _parse_iso_date_string(exp.date)
        if exp_date is None:
            continue
        if (today - exp_date).days >= experience_min_age_days:
            stale_experiences.append(
                {
                    "section": "experiences",
                    "index": i,
                    "date": exp.date,
                    "outcome": exp.outcome,
                    "entities": exp.entities,
                    "text_preview": _maintenance_text_preview(exp.text),
                    "raw": exp.raw,
                }
            )

    low_source_world_knowledge: list[dict] = []
    for i, wf in enumerate(bank.world_knowledge):
        if wf.sources is not None and wf.sources <= world_max_sources:
            low_source_world_knowledge.append(
                {
                    "section": "world_knowledge",
                    "index": i,
                    "sources": wf.sources,
                    "confidence": wf.confidence,
                    "entities": wf.entities,
                    "text_preview": _maintenance_text_preview(wf.text),
                    "raw": wf.raw,
                }
            )

    stale_beliefs: list[dict] = []
    for i, b in enumerate(bank.beliefs):
        upd = _parse_iso_date_string(b.updated)
        if upd is None:
            continue
        if (today - upd).days >= belief_stale_days:
            stale_beliefs.append(
                {
                    "section": "beliefs",
                    "index": i,
                    "updated": b.updated,
                    "confidence": b.confidence,
                    "entities": b.entities,
                    "text_preview": _maintenance_text_preview(b.text),
                    "raw": b.raw,
                }
            )

    return {
        "success": True,
        "scope": scope_display,
        "thresholds": {
            "experience_min_age_days": experience_min_age_days,
            "belief_stale_days": belief_stale_days,
            "world_max_sources": world_max_sources,
        },
        "stale_experiences": stale_experiences,
        "low_source_world_knowledge": low_source_world_knowledge,
        "stale_beliefs": stale_beliefs,
        "counts": {
            "stale_experiences": len(stale_experiences),
            "low_source_world_knowledge": len(low_source_world_knowledge),
            "stale_beliefs": len(stale_beliefs),
        },
    }


def _ensure_memory_file(path: Path, scope_label: str) -> Path:
    """Create a template memory file when needed (legacy single-file path)."""
    if path.exists():
        return path
    if scope_label == "user":
        return recall_mod.ensure_user_scope_initialized()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(recall_mod.CURATED_MASTER_TEMPLATE, encoding="utf-8")
    return path


def _ensure_section_file(scope_label: str, section: str) -> Path:
    """Ensure the section file for *section* exists and return its path."""
    if scope_label == "user":
        recall_mod.ensure_user_scope_initialized()
    section_dir = recall_mod.resolve_section_dir(scope_label)
    return recall_mod.ensure_section_file(section_dir, section)


# Curated masters omit full sections; never treat arbitrary "per-section files" mentions as curated.
_CURATED_MASTER_MARKER = "<!-- Curated subset"


def _memory_master_is_curated(master_path: Path) -> bool:
    """True when *master_path* is a curated subset file (not a legacy all-in-one journal)."""
    if not master_path.exists():
        return False
    try:
        head = master_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return _CURATED_MASTER_MARKER in head


def _section_dir_for_path(master_path: Path, scope_label: str) -> Path:
    """Per-section directory implied by curated *master_path*."""
    if scope_label == "user":
        return master_path.parent
    return master_path.parent / "memory"


def _resolve_section_backed_path(
    master_path: Path,
    scope_label: str,
    section: str,
    *,
    create_missing: bool = True,
) -> Path:
    """Write target for *section*: ``<section>.md`` when section layout exists, else *master_path*."""
    master_path = _ensure_memory_file(master_path, scope_label)
    section_dir = _section_dir_for_path(master_path, scope_label)
    has_sections = recall_mod.has_section_files(section_dir)
    curated = _memory_master_is_curated(master_path)
    use_section_files = has_sections or curated
    if not use_section_files:
        return master_path

    if curated and not has_sections and create_missing:
        recall_mod.ensure_section_files(section_dir)

    candidate = recall_mod.section_file_path(section_dir, section)
    if create_missing and not candidate.exists():
        return recall_mod.ensure_section_file(section_dir, section)
    return candidate


def _insert_entry(content: str, section: str, raw_line: str) -> tuple[bool, Optional[str]]:
    """Insert a raw line at the top of a target section."""
    section_headers = {
        "experiences": "## Experiences",
        "world_knowledge": "## World Knowledge",
        "beliefs": "## Beliefs",
        "reflections": "## Reflections",
        "entity_summaries": "## Entity Summaries",
    }
    header = section_headers[section]

    lines = content.splitlines()
    insert_idx = None
    in_section = False
    in_comment = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
                insert_idx = i + 1
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            elif in_section:
                insert_idx = i + 1
            continue
        if stripped == header:
            in_section = True
            insert_idx = i + 1
            continue
        if in_section:
            if stripped.startswith("## "):
                break
            if stripped.startswith("- "):
                insert_idx = i
                break
            if not stripped:
                insert_idx = i
                continue

    if insert_idx is None:
        return False, None

    lines.insert(insert_idx, raw_line)
    return True, "\n".join(lines) + "\n"


def append_entry(
    path: Path,
    *,
    section: str,
    text: str,
    scope_label: str,
    date: Optional[str] = None,
    context: Optional[str] = None,
    entities: Optional[list[str]] = None,
    confidence: Optional[float] = None,
    sources: Optional[int] = None,
    formed: Optional[str] = None,
    updated: Optional[str] = None,
    outcome: Optional[str] = None,
    evidence: Optional[str] = None,
    cross_scope_path: Optional[Path] = None,
) -> dict:
    """Append a new entry to the per-section file after safety checks.

    *path* is used as a fallback when section files are unavailable
    (legacy single-file mode).  When section files exist the write
    targets the appropriate ``<section>.md`` file instead.
    """
    path = _resolve_section_backed_path(
        path,
        scope_label,
        section,
        create_missing=True,
    )

    screening = screen_text(text)
    if not screening["safe"]:
        return {
            "success": False,
            "error": "Sensitive content detected; refusing to persist memory text",
            "issues": screening["issues"],
            "sanitized_text": screening["sanitized_text"],
        }

    normalized_entities = canonicalize_entities(
        entities or extract_entities(screening["sanitized_text"])["candidates"]
    )
    if not normalized_entities:
        return {"success": False, "error": "At least one entity tag is required"}

    normalized_context = normalize_context_tag(context)
    if context and normalized_context is None:
        return {"success": False, "error": f"Unknown context tag '{context}'"}

    extra_paths = None
    if cross_scope_path and cross_scope_path.exists():
        other_scope = "project" if scope_label == "user" else "user"
        extra_paths = [(
            "other-scope",
            _resolve_section_backed_path(
                cross_scope_path,
                other_scope,
                section,
                create_missing=False,
            ),
        )]

    duplicate = check_duplicate(
        path,
        section,
        screening["sanitized_text"],
        extra_paths=extra_paths,
    )
    if duplicate["is_duplicate"]:
        return {
            "success": False,
            "error": "Duplicate or near-duplicate memory already exists",
            "matches": duplicate["matches"],
        }

    norm_outcome, outcome_err = normalize_outcome(outcome)
    if outcome_err:
        return {"success": False, "error": outcome_err}
    sanitized_evidence = _sanitize_evidence_fragment(evidence)

    build_result = _build_entry_line(
        section=section,
        text=screening["sanitized_text"],
        date=date,
        context=normalized_context,
        entities=normalized_entities,
        confidence=confidence,
        sources=sources,
        formed=formed,
        updated=updated,
        outcome=norm_outcome,
        evidence=sanitized_evidence,
    )
    if "error" in build_result:
        return {"success": False, "error": build_result["error"]}

    raw_line = build_result["raw_line"]
    original_content = path.read_text(encoding="utf-8")
    original_hash = content_hash(original_content)
    inserted, new_content = _insert_entry(original_content, section, raw_line)
    if not inserted or new_content is None:
        return {"success": False, "error": f"Could not find section '{section}' in memory file"}

    write_result = write_text_if_unchanged(path, new_content, original_hash)
    if not write_result["success"]:
        return write_result

    return {
        "success": True,
        "section": section,
        "path": str(path),
        "entry": raw_line,
        "entities": normalized_entities,
        "context": normalized_context,
        "outcome": norm_outcome,
        "evidence": sanitized_evidence,
    }


def _build_entry_line(
    *,
    section: str,
    text: str,
    date: Optional[str],
    context: Optional[str],
    entities: list[str],
    confidence: Optional[float],
    sources: Optional[int],
    formed: Optional[str],
    updated: Optional[str],
    outcome: Optional[str] = None,
    evidence: Optional[str] = None,
) -> dict:
    """Build one formatted memory line for the target section."""
    if section == "experiences":
        if not date:
            return {"error": "Experiences require a date"}
        raw_line = f"- **{date}**"
        if context:
            raw_line += f" [{context}]"
        raw_line += f" {{entities: {', '.join(entities)}}}"
        if outcome:
            raw_line += f" {{outcome: {outcome}}}"
        if evidence:
            raw_line += f" {{evidence: {evidence}}}"
        raw_line += f" {text}"
    elif section == "world_knowledge":
        if confidence is None or sources is None:
            return {"error": "World knowledge requires confidence and sources"}
        raw_line = (
            f"- {{entities: {', '.join(entities)}}} {text} "
            f"(confidence: {confidence:.2f}, sources: {sources})"
        )
    elif section == "beliefs":
        if confidence is None:
            return {"error": "Beliefs require confidence"}
        formed_value = formed or __import__("datetime").date.today().isoformat()
        updated_value = updated or formed_value
        raw_line = (
            f"- {{entities: {', '.join(entities)}}} {text} "
            f"(confidence: {confidence:.2f}, formed: {formed_value}, updated: {updated_value})"
        )
    else:
        return {"error": f"Cannot append to section '{section}'"}

    return {"raw_line": raw_line}


def promote(
    user_path: Path,
    project_path: Path,
    section: str,
    index: int,
    *,
    allow_project_promotion: bool = False,
) -> dict:
    """Copy a memory entry from user scope to project scope.

    The entry remains in user memory (not deleted). The caller can
    remove it from user memory separately if desired.
    """
    if not allow_project_promotion:
        return {
            "success": False,
            "error": "Promotion requires explicit --allow-project-promotion approval",
        }

    user_path = _ensure_memory_file(user_path, "user")
    user_section_dir = _section_dir_for_path(user_path, "user")
    if _memory_master_is_curated(user_path) and not recall_mod.has_section_files(user_section_dir):
        recall_mod.ensure_section_files(user_section_dir)
    user_bank = recall_mod.load_memory(user_path, user_section_dir)

    project_path = _ensure_memory_file(project_path, "project")
    project_target = _resolve_section_backed_path(
        project_path,
        "project",
        section,
        create_missing=True,
    )
    project_content = project_target.read_text(encoding="utf-8")
    original_hash = content_hash(project_content)

    raw_line: Optional[str] = None
    entry_context: Optional[str] = None
    entry_text: Optional[str] = None
    if section == "experiences":
        if index >= len(user_bank.experiences):
            return {"success": False, "error": f"Index {index} out of range in user experiences"}
        entry = user_bank.experiences[index]
        raw_line = entry.raw
        entry_context = entry.context
        entry_text = entry.text
        dup = check_duplicate(project_target, section, entry.text)
    elif section == "world_knowledge":
        if index >= len(user_bank.world_knowledge):
            return {"success": False, "error": f"Index {index} out of range in user world_knowledge"}
        entry = user_bank.world_knowledge[index]
        raw_line = entry.raw
        entry_text = entry.text
        dup = check_duplicate(project_target, section, entry.text)
    elif section == "beliefs":
        if index >= len(user_bank.beliefs):
            return {"success": False, "error": f"Index {index} out of range in user beliefs"}
        entry = user_bank.beliefs[index]
        raw_line = entry.raw
        entry_text = entry.text
        dup = check_duplicate(project_target, section, entry.text)
    else:
        return {"success": False, "error": f"Cannot promote from section '{section}'"}

    if dup["is_duplicate"]:
        return {
            "success": False,
            "error": "Duplicate already exists in project memory",
            "matches": dup["matches"],
        }

    if section == "experiences" and entry_context == "preference":
        return {
            "success": False,
            "error": "preference experiences cannot be promoted to project memory",
        }

    screening = screen_text(entry_text or "")
    if not screening["safe"]:
        return {
            "success": False,
            "error": "Sensitive content detected; refusing to promote memory",
            "issues": screening["issues"],
        }

    inserted, new_content = _insert_entry(project_content, section, raw_line)
    if not inserted or new_content is None:
        return {"success": False, "error": f"Could not find section '{section}' in project memory"}

    write_result = write_text_if_unchanged(project_target, new_content, original_hash)
    if not write_result["success"]:
        return write_result

    return {
        "success": True,
        "section": section,
        "index": index,
        "promoted_text": raw_line,
        "target": str(project_target),
    }


def find_matches(path: Path, query: str, threshold: float = 0.4) -> dict:
    """Fuzzy-search all sections for memories matching a query.

    Returns candidates sorted by similarity, grouped by section,
    with indices for use with delete-entry.
    Uses a lower threshold than duplicate detection since the user
    is describing a memory from (possibly faulty) recollection.
    """
    bank = recall_mod.parse_memory_file(path)
    matches = []

    sections: list[tuple[str, list]] = [
        ("experiences", bank.experiences),
        ("world_knowledge", bank.world_knowledge),
        ("beliefs", bank.beliefs),
        ("reflections", bank.reflections),
    ]

    for section_name, items in sections:
        for i, item in enumerate(items):
            text = item.text
            sim = similarity(query, text)
            if sim >= threshold:
                entry: dict = {
                    "section": section_name,
                    "index": i,
                    "similarity": round(sim, 3),
                    "text": text,
                    "raw": item.raw,
                }
                if hasattr(item, "date") and item.date:
                    entry["date"] = item.date
                if hasattr(item, "confidence") and item.confidence is not None:
                    entry["confidence"] = item.confidence
                matches.append(entry)

    matches.sort(key=lambda m: m["similarity"], reverse=True)

    return {
        "query": query,
        "threshold": threshold,
        "match_count": len(matches),
        "matches": matches,
    }


def delete_entry(path: Path, section: str, index: int) -> dict:
    """Remove a specific memory entry by section and index.

    Uses the guarded-write path to prevent stale overwrites.
    """
    valid_sections = ("experiences", "world_knowledge", "beliefs", "reflections")
    if section not in valid_sections:
        return {"success": False, "error": f"Cannot delete from section '{section}'"}

    if not path.exists():
        return {"success": False, "error": "Memory file does not exist"}

    content = path.read_text(encoding="utf-8")
    original_hash = content_hash(content)
    lines = content.splitlines()

    section_headers = {
        "experiences": "## Experiences",
        "world_knowledge": "## World Knowledge",
        "beliefs": "## Beliefs",
        "reflections": "## Reflections",
    }
    header = section_headers[section]
    in_section = False
    in_comment = False
    item_count = 0
    target_line_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped == header:
            in_section = True
            continue
        if stripped.startswith("## ") and in_section:
            break
        if in_section and stripped.startswith("- "):
            if item_count == index:
                target_line_idx = i
                break
            item_count += 1

    if target_line_idx is None:
        return {"success": False, "error": f"Index {index} not found in {section}"}

    deleted_line = lines[target_line_idx]
    del lines[target_line_idx]

    write_result = write_text_if_unchanged(path, "\n".join(lines) + "\n", original_hash)
    if not write_result["success"]:
        return write_result

    return {
        "success": True,
        "section": section,
        "index": index,
        "deleted": deleted_line,
    }


def _resolve_section_file_for_write(scope: str, section: str,
                                     file_override: Optional[Path] = None) -> Path:
    """Return the file to write *section* entries to.

    When ``--file`` is given, use it directly.
    Otherwise prefer the per-section file; fall back to legacy master.
    """
    if file_override:
        return file_override
    if scope == "user":
        recall_mod.ensure_user_scope_initialized()
    section_dir = recall_mod.resolve_section_dir(scope)
    if recall_mod.has_section_files(section_dir):
        return recall_mod.ensure_section_file(section_dir, section)
    return resolve_path(scope)


def _resolve_section_file_for_read(scope: str, section: str,
                                    file_override: Optional[Path] = None) -> Path:
    """Return the file to read *section* entries from."""
    if file_override:
        return file_override
    if scope == "user":
        recall_mod.ensure_user_scope_initialized()
    section_dir = recall_mod.resolve_section_dir(scope)
    sf = recall_mod.section_file_path(section_dir, section)
    if sf.exists():
        return sf
    return resolve_path(scope)


def _add_scope_option(parser: argparse.ArgumentParser) -> None:
    """Allow scope after the subcommand as well as before it."""
    parser.add_argument(
        "--scope",
        dest="command_scope",
        choices=["user", "project"],
        default=None,
        help="Memory scope for this command (overrides top-level --scope)",
    )


def _add_text_like_input_options(
    parser: argparse.ArgumentParser,
    *,
    name: str,
    required_help: str,
) -> None:
    """Add ergonomic input flags for free-text arguments.

    Using stdin or a file avoids brittle shell quoting for apostrophes and other
    punctuation in natural-language memory text.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(f"--{name}", dest=name, help=required_help)
    group.add_argument(
        f"--{name}-file",
        dest=f"{name}_file",
        type=Path,
        help=f"Read {name.replace('_', ' ')} from a file",
    )
    group.add_argument(
        f"--{name}-stdin",
        dest=f"{name}_stdin",
        action="store_true",
        help=f"Read {name.replace('_', ' ')} from standard input",
    )


def _resolve_text_like_input(args: argparse.Namespace, name: str) -> str:
    """Resolve a text argument supplied inline, via file, or via stdin."""
    inline_value = getattr(args, name, None)
    if inline_value is not None:
        return inline_value

    file_value = getattr(args, f"{name}_file", None)
    if file_value is not None:
        return file_value.read_text(encoding="utf-8")

    if getattr(args, f"{name}_stdin", False):
        return sys.stdin.read()

    raise ValueError(f"Missing required input for {name}")


def main():
    parser = argparse.ArgumentParser(description="Memory management operations")
    parser.add_argument(
        "--skill-config",
        type=Path,
        default=None,
        help=(
            "Path to memory-skill.config.json "
            "(default: ~/.agents/memory/ or MEMORY_SKILL_CONFIG_PATH)"
        ),
    )
    parser.add_argument("--file", type=Path, default=None,
                        help="Explicit path to a memory file (overrides --scope)")
    parser.add_argument("--scope", choices=["user", "project"], default=None,
                        help="Memory scope (default: user for all writes; project only for validate/curate/migrate)")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="Validate MEMORY.md structure")
    _add_scope_option(validate_parser)
    validate_sections_parser = sub.add_parser("validate-sections", help="Validate per-section files")
    _add_scope_option(validate_sections_parser)

    dup_parser = sub.add_parser("check-duplicate", help="Check for near-duplicates")
    _add_scope_option(dup_parser)
    dup_parser.add_argument("--section", required=True,
                            choices=["experiences", "world_knowledge", "beliefs"])
    _add_text_like_input_options(
        dup_parser,
        name="candidate",
        required_help="Candidate text",
    )
    dup_parser.add_argument("--cross-scope", action="store_true",
                            help="Also check the other scope for duplicates")

    conf_parser = sub.add_parser("update-confidence", help="Update a confidence score")
    _add_scope_option(conf_parser)
    conf_parser.add_argument("--section", required=True,
                             choices=["beliefs", "world_knowledge"])
    conf_parser.add_argument("--index", required=True, type=int)
    conf_parser.add_argument("--delta", required=True, type=float,
                             help="Amount to add (positive=reinforce, negative=weaken)")
    conf_parser.add_argument(
        "--no-bump-updated",
        action="store_true",
        help=(
            "Beliefs only: do not set updated: to today — use for temporal decay "
            "so staleness accumulates until reinforcement/contradiction"
        ),
    )

    pbd_parser = sub.add_parser(
        "preview-belief-decay",
        help="JSON: per-belief staleness/age and temporal decay delta if unsupported",
    )
    _add_scope_option(pbd_parser)
    pbd_parser.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        default=None,
        help="Reference date (default: today)",
    )

    ent_parser = sub.add_parser("extract-entities", help="Extract entity candidates from text")
    _add_text_like_input_options(
        ent_parser,
        name="text",
        required_help="Text to analyze",
    )

    screen_parser = sub.add_parser("screen-text", help="Screen text for secrets or sensitive content")
    _add_text_like_input_options(
        screen_parser,
        name="text",
        required_help="Text to screen",
    )

    prune_parser = sub.add_parser("prune-beliefs", help="Find beliefs below confidence threshold")
    _add_scope_option(prune_parser)
    prune_parser.add_argument("--threshold", type=float, default=0.2)

    suggest_parser = sub.add_parser("suggest-summaries", help="Suggest entities needing summaries")
    _add_scope_option(suggest_parser)
    conflicts_parser = sub.add_parser("check-conflicts", help="Detect contradictions between belief pairs")
    _add_scope_option(conflicts_parser)
    sub.add_parser(
        "init-user",
        help="Idempotent: ensure user memory layout (same as automatic first-use init)",
    )

    find_parser = sub.add_parser("find-matches", help="Fuzzy-search memories for forget operation")
    find_parser.add_argument("--query", required=True, help="Fuzzy description of the memory to find")
    find_parser.add_argument("--threshold", type=float, default=0.4,
                             help="Minimum similarity (default: 0.4, lower than dedup)")

    del_parser = sub.add_parser("delete-entry", help="Delete a specific memory entry by section and index")
    _add_scope_option(del_parser)
    del_parser.add_argument("--section", required=True,
                            choices=["experiences", "world_knowledge", "beliefs", "reflections"])
    del_parser.add_argument("--index", required=True, type=int)

    append_parser = sub.add_parser("append-entry", help="Append a new memory entry safely")
    append_parser.add_argument("--section", required=True,
                               choices=["experiences", "world_knowledge", "beliefs"])
    append_parser.add_argument("--text", required=True)
    append_parser.add_argument("--scope", choices=["user", "project"], default="user")
    append_parser.add_argument("--date", help="Required for experiences")
    append_parser.add_argument("--context", help="Optional context tag for experiences")
    append_parser.add_argument("--entities", default="",
                               help="Comma-separated entity tags; omitted = auto-extract")
    append_parser.add_argument("--confidence", type=float)
    append_parser.add_argument("--sources", type=int)
    append_parser.add_argument("--formed")
    append_parser.add_argument("--updated")
    append_parser.add_argument(
        "--outcome",
        choices=sorted(_VALID_OUTCOMES),
        default=None,
        help="Experiences only: outcome signal (success, failure, mixed, unknown)",
    )
    append_parser.add_argument(
        "--evidence",
        default=None,
        help=(
            "Experiences only: external pointer (issue URL, CI run id); "
            "no secrets; '}' stripped"
        ),
    )

    mr_parser = sub.add_parser(
        "maintenance-report",
        help=(
            "List stale experiences, low-source world knowledge, stale beliefs"
        ),
    )
    mr_parser.add_argument(
        "--scope", choices=["user", "project"], default="user",
        help="Ignored when --file is set",
    )
    mr_parser.add_argument(
        "--experience-days",
        type=int,
        default=90,
        help="Experiences older than this many days (default: 90)",
    )
    mr_parser.add_argument(
        "--belief-days",
        type=int,
        default=120,
        help="Beliefs with updated: older than this many days (default: 120)",
    )
    mr_parser.add_argument(
        "--max-sources",
        type=int,
        default=1,
        help="World knowledge with sources <= N (default: 1)",
    )
    mr_parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Parse this MEMORY.md only (single-file layout)",
    )

    promote_parser = sub.add_parser("promote", help="Copy a memory from user to project scope")
    _add_scope_option(promote_parser)
    promote_parser.add_argument("--section", required=True,
                                choices=["experiences", "world_knowledge", "beliefs"])
    promote_parser.add_argument("--index", required=True, type=int,
                                help="Index of the entry in user memory to promote")
    promote_parser.add_argument("--allow-project-promotion", action="store_true",
                                help="Required explicit approval before writing to project memory")

    migrate_parser = sub.add_parser("migrate", help="Split a single-file MEMORY.md into per-section files")
    _add_scope_option(migrate_parser)

    curate_parser = sub.add_parser(
        "curate",
        help="Regenerate thin curated MEMORY.md (previews + links) from section files",
    )
    _add_scope_option(curate_parser)
    curate_parser.add_argument("--max-world", type=int, default=5)
    curate_parser.add_argument("--max-beliefs", type=int, default=5)
    curate_parser.add_argument("--max-summaries", type=int, default=10)

    sub.add_parser(
        "validate-config",
        help="Validate memory-skill.config.json (user memory dir; see ref/config.md)",
    )
    ch_parser = sub.add_parser(
        "config-hints",
        help="Print resolved model ids for memory subagent actions",
    )
    ch_parser.add_argument(
        "--host",
        choices=sorted(KNOWN_MEMORY_HOSTS),
        default=None,
        help=(
            "Tool: cursor, claude, or codex — merge hosts.<name> over globals. "
            "If omitted: use MEMORY_SKILL_HOST, else auto-detect (see config.md), "
            f"else global only. Set {MEMORY_SKILL_DISABLE_HOST_INFERENCE_ENV}=1 to skip detection."
        ),
    )

    args = parser.parse_args()

    def get_path(default_scope: str = "project") -> Path:
        if args.file:
            return args.file
        scope = args.scope or default_scope
        return resolve_path(scope)

    def effective_scope(default: str = "user") -> str:
        return getattr(args, "command_scope", None) or args.scope or default

    if args.command == "validate":
        result = validate(resolve_path(effective_scope("project")) if not args.file else args.file)
    elif args.command == "validate-sections":
        result = validate_sections(effective_scope("project"))
    elif args.command == "check-duplicate":
        scope = effective_scope("user")
        target_path = _resolve_section_file_for_read(scope, args.section, args.file)
        candidate = _resolve_text_like_input(args, "candidate")
        extra: Optional[list[tuple[str, Path]]] = None
        if getattr(args, "cross_scope", False):
            other_scope = "project" if scope == "user" else "user"
            other_path = _resolve_section_file_for_read(other_scope, args.section)
            if other_path.exists():
                extra = [(other_scope, other_path)]
        result = check_duplicate(target_path, args.section, candidate,
                                  extra_paths=extra)
    elif args.command == "update-confidence":
        scope = effective_scope("user")
        target = _resolve_section_file_for_write(scope, args.section, args.file)
        bump = True
        if args.section == "beliefs":
            bump = not args.no_bump_updated
        result = update_confidence(
            target, args.section, args.index, args.delta, bump_updated=bump
        )
    elif args.command == "preview-belief-decay":
        scope = effective_scope("user")
        target = _resolve_section_file_for_read(scope, "beliefs", args.file)
        as_of = _parse_iso_date_string(args.as_of) if args.as_of else None
        result = preview_belief_temporal_decay(target, as_of=as_of)
    elif args.command == "extract-entities":
        result = extract_entities(_resolve_text_like_input(args, "text"))
    elif args.command == "screen-text":
        result = screen_text(_resolve_text_like_input(args, "text"))
    elif args.command == "prune-beliefs":
        scope = effective_scope("user")
        target = _resolve_section_file_for_read(scope, "beliefs", args.file)
        result = prune_beliefs(target, args.threshold)
    elif args.command == "suggest-summaries":
        scope = effective_scope("user")
        master, sec_dir = recall_mod.resolve_memory_sources(scope)
        bank = recall_mod.load_memory(master, sec_dir)
        entity_index = recall_mod.collect_all_entities(bank)
        entity_counts: dict[str, int] = {}
        for exp in bank.experiences:
            for e in exp.entities:
                entity_counts[e] = entity_counts.get(e, 0) + 1
        for wf in bank.world_knowledge:
            for e in wf.entities:
                entity_counts[e] = entity_counts.get(e, 0) + 1
        for b in bank.beliefs:
            for e in b.entities:
                entity_counts[e] = entity_counts.get(e, 0) + 1
        existing_summaries = {es.name.lower() for es in bank.entity_summaries}
        suggestions = []
        for entity, count in sorted(entity_counts.items(), key=lambda x: -x[1]):
            if count >= 3 and entity.lower() not in existing_summaries:
                suggestions.append({
                    "entity": entity,
                    "mention_count": count,
                    "sections": entity_index.get(entity, []),
                })
        result = {
            "suggestions": suggestions,
            "existing_summary_count": len(bank.entity_summaries),
        }
    elif args.command == "check-conflicts":
        scope = effective_scope("user")
        target = _resolve_section_file_for_read(scope, "beliefs", args.file)
        result = check_conflicts(target)
    elif args.command == "init-user":
        result = init_user()
    elif args.command == "find-matches":
        scope = effective_scope("user")
        master, sec_dir = recall_mod.resolve_memory_sources(scope)
        bank = recall_mod.load_memory(master, sec_dir)
        from types import SimpleNamespace
        fake_path = sec_dir / "__combined__"
        result_matches = []
        sections_list: list[tuple[str, list]] = [
            ("experiences", bank.experiences),
            ("world_knowledge", bank.world_knowledge),
            ("beliefs", bank.beliefs),
            ("reflections", bank.reflections),
        ]
        for section_name, items in sections_list:
            for i, item in enumerate(items):
                sim = similarity(args.query, item.text)
                if sim >= args.threshold:
                    entry: dict = {
                        "section": section_name,
                        "index": i,
                        "similarity": round(sim, 3),
                        "text": item.text,
                        "raw": item.raw,
                    }
                    if hasattr(item, "date") and item.date:
                        entry["date"] = item.date
                    if hasattr(item, "confidence") and item.confidence is not None:
                        entry["confidence"] = item.confidence
                    result_matches.append(entry)
        result_matches.sort(key=lambda m: m["similarity"], reverse=True)
        result = {
            "query": args.query,
            "threshold": args.threshold,
            "match_count": len(result_matches),
            "matches": result_matches,
        }
    elif args.command == "delete-entry":
        scope = effective_scope("user")
        target = _resolve_section_file_for_write(scope, args.section, args.file)
        result = delete_entry(target, args.section, args.index)
    elif args.command == "append-entry":
        scope = args.scope or "user"
        target_path = get_path(scope)
        other_scope = "project" if scope == "user" else "user"
        entity_list = [e.strip() for e in args.entities.split(",") if e.strip()]
        result = append_entry(
            target_path,
            section=args.section,
            text=args.text,
            scope_label=scope,
            date=args.date,
            context=args.context,
            entities=entity_list,
            confidence=args.confidence,
            sources=args.sources,
            formed=args.formed,
            updated=args.updated,
            outcome=getattr(args, "outcome", None),
            evidence=getattr(args, "evidence", None),
            cross_scope_path=resolve_path(other_scope),
        )
    elif args.command == "maintenance-report":
        result = maintenance_report(
            scope_label=args.scope,
            memory_file=args.file,
            experience_min_age_days=args.experience_days,
            belief_stale_days=args.belief_days,
            world_max_sources=args.max_sources,
        )
    elif args.command == "promote":
        result = promote(
            recall_mod.resolve_user_memory_path(),
            recall_mod.resolve_project_memory_path(),
            args.section,
            args.index,
            allow_project_promotion=args.allow_project_promotion,
        )
    elif args.command == "migrate":
        scope = effective_scope("project")
        result = migrate(get_path(scope), scope)
    elif args.command == "curate":
        scope = effective_scope("project")
        result = curate(scope,
                        max_world=args.max_world,
                        max_beliefs=args.max_beliefs,
                        max_summaries=args.max_summaries)
    elif args.command == "validate-config":
        result = run_validate_config(args.skill_config)
    elif args.command == "config-hints":
        h, src = resolve_memory_host_meta(args.host)
        result = build_config_hints(args.skill_config, host=h, host_resolution=src)
    else:
        parser.error(f"Unknown command: {args.command}")
        return

    print(json.dumps(result, indent=2))
    if args.command == "validate-config" and not result.get("valid", True):
        sys.exit(1)


if __name__ == "__main__":
    main()
