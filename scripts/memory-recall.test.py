#!/usr/bin/env python3
"""Tests for memory-recall.py and memory-manage.py."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module
recall = import_module("memory-recall")
manage = import_module("memory-manage")

# Deterministic suite: host inference off unless a test clears this.
os.environ["MEMORY_SKILL_DISABLE_HOST_INFERENCE"] = "1"


SAMPLE_MEMORY = """\
# Agentic Memory

## Experiences

<!-- Newest first. Format: - **YYYY-MM-DD** [context] {entities: e1, e2} Narrative memory text. -->

- **2026-03-26** [debug] {entities: integration-tests, port-5432} The integration test suite hung indefinitely because another process was already bound to port 5432. Killing the stale process fixed the hang.
- **2026-03-20** [tooling] {entities: dev-server, build-watcher} Running the dev server alone is insufficient for CSS hot reload because the build watcher must regenerate output from the source stylesheets separately.
- **2026-03-15** [workflow] {entities: dev-command} The combined dev command starts both the build watcher and the application server together, which is the intended hot-reload workflow.
- **2026-02-10** [ui] {entities: dashboard, api-status} The dashboard status card initially showed a loading spinner that never resolved because the API endpoint was not returning the expected response shape.

## World Knowledge

<!-- Verified, objective facts about the project and environment. Format:
- {entities: e1} Fact text. (confidence: 0.XX, sources: N) -->

- {entities: postgresql} PostgreSQL 16 requires explicit listen_addresses configuration for remote connections. (confidence: 0.95, sources: 3)
- {entities: esbuild} The project uses esbuild for bundling instead of webpack, configured via build.config.js. (confidence: 0.90, sources: 2)
- {entities: api-gateway, auth} The API gateway config lives at ~/.config/myapp/config.json with host and auth_token fields. (confidence: 0.85, sources: 2)

## Beliefs

<!-- Agent's subjective judgments that evolve over time. Format:
- {entities: e1} Belief text. (confidence: 0.XX, formed: YYYY-MM-DD, updated: YYYY-MM-DD) -->

- {entities: dev-command, dev-server} Running the combined dev command is more reliable than starting the server alone for day-to-day development. (confidence: 0.70, formed: 2026-03-15, updated: 2026-03-20)
- {entities: integration-tests} The integration test suite is the most valuable automated test in the project. (confidence: 0.60, formed: 2026-03-26, updated: 2026-03-26)

## Reflections

<!-- Higher-level patterns synthesized from multiple experiences and beliefs. Format:
- **YYYY-MM-DD** {entities: e1, e2} Reflection text. -->

- **2026-03-26** {entities: dev-server, integration-tests, port-5432} Multiple debugging sessions revealed that the dev environment does not clean up child processes on exit, causing port conflicts across unrelated tools. This is a systemic issue, not isolated incidents.

## Entity Summaries

<!-- Synthesized profiles of key entities, regenerated when underlying memories change. Format:
### entity-name
Summary paragraph. -->

### postgresql
PostgreSQL 16.x is the primary database. Config requires explicit listen_addresses for remote access. Connection pooling is handled by the application layer. Migrations run via the ORM's built-in migration tool.

### dev-server
The application dev server runs the fullstack app. It requires a config file to be present. Running it alone without the build watcher means frontend changes are not reflected until a manual rebuild.
"""


def _write_sample(tmp: Path) -> Path:
    p = tmp / "MEMORY.md"
    p.write_text(SAMPLE_MEMORY, encoding="utf-8")
    return p


class TestResolveProjectMemoryPath(unittest.TestCase):
    def test_project_path_cwd_walk(self):
        with tempfile.TemporaryDirectory() as td:
            deep = Path(td) / "a" / "b"
            deep.mkdir(parents=True)
            mem = deep / "MEMORY.md"
            mem.write_text("# Agentic Memory\n\n## Experiences\n", encoding="utf-8")
            old = os.getcwd()
            try:
                os.chdir(deep)
                self.assertEqual(recall.resolve_project_memory_path(), mem.resolve())
            finally:
                os.chdir(old)


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)
        self.bank = recall.parse_memory_file(self.path)

    def test_experience_count(self):
        self.assertEqual(len(self.bank.experiences), 4)

    def test_world_knowledge_count(self):
        self.assertEqual(len(self.bank.world_knowledge), 3)

    def test_beliefs_count(self):
        self.assertEqual(len(self.bank.beliefs), 2)

    def test_entity_summaries_count(self):
        self.assertEqual(len(self.bank.entity_summaries), 2)

    def test_experience_fields(self):
        exp = self.bank.experiences[0]
        self.assertEqual(exp.date, "2026-03-26")
        self.assertEqual(exp.context, "debug")
        self.assertIn("integration-tests", exp.entities)
        self.assertIn("port-5432", exp.entities)
        self.assertIn("hung indefinitely", exp.text)
        self.assertIsNone(exp.outcome)
        self.assertIsNone(exp.evidence)

    def test_world_fact_fields(self):
        wf = self.bank.world_knowledge[0]
        self.assertIn("postgresql", wf.entities)
        self.assertEqual(wf.confidence, 0.95)
        self.assertEqual(wf.sources, 3)
        self.assertIn("listen_addresses", wf.text)

    def test_belief_fields(self):
        b = self.bank.beliefs[0]
        self.assertIn("dev-command", b.entities)
        self.assertEqual(b.confidence, 0.70)
        self.assertEqual(b.formed, "2026-03-15")
        self.assertEqual(b.updated, "2026-03-20")

    def test_entity_summary_fields(self):
        es = self.bank.entity_summaries[0]
        self.assertEqual(es.name, "postgresql")
        self.assertIn("PostgreSQL 16.x", es.text)

    def test_nonexistent_file(self):
        bank = recall.parse_memory_file(self.tmp / "nonexistent.md")
        self.assertEqual(len(bank.experiences), 0)
        self.assertEqual(len(bank.world_knowledge), 0)


class TestRecall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)
        self.bank = recall.parse_memory_file(self.path)

    def test_keyword_filter(self):
        result = recall.recall(self.bank, keyword="hung")
        self.assertEqual(len(result.get("experiences", [])), 1)
        self.assertIn("hung indefinitely", result["experiences"][0])

    def test_entity_filter(self):
        result = recall.recall(self.bank, entity="postgresql")
        self.assertTrue(len(result.get("world_knowledge", [])) >= 1)
        self.assertTrue(len(result.get("entity_summaries", [])) >= 1)

    def test_entity_cross_section(self):
        result = recall.recall(self.bank, entity="postgresql", cross_section=True)
        sections_with_results = [k for k, v in result.items() if v]
        self.assertIn("world_knowledge", sections_with_results)
        self.assertIn("entity_summaries", sections_with_results)

    def test_date_filter_since(self):
        result = recall.recall(self.bank, since="2026-03-20", keyword=" ")
        exps = result.get("experiences", [])
        self.assertTrue(all("2026-02" not in e for e in exps))

    def test_date_filter_until(self):
        result = recall.recall(self.bank, until="2026-03-15", keyword=" ")
        exps = result.get("experiences", [])
        self.assertTrue(len(exps) >= 1)
        self.assertTrue(all("2026-03-26" not in e for e in exps))

    def test_section_filter(self):
        result = recall.recall(self.bank, section="beliefs", keyword="reliable")
        self.assertIn("beliefs", result)
        self.assertNotIn("experiences", result)

    def test_no_results(self):
        result = recall.recall(self.bank, keyword="xyznonexistent")
        self.assertEqual(len(result), 0)

    def test_entity_filter_in_summaries(self):
        result = recall.recall(self.bank, entity="dev-server", cross_section=True)
        self.assertIn("entity_summaries", result)

    def test_fuzzy_entity_fallback(self):
        result = recall.recall(self.bank, entity="integration test", cross_section=True)
        self.assertIn("experiences", result)
        self.assertTrue(any("integration test suite hung indefinitely" in item for item in result["experiences"]))

    def test_fuzzy_entity_fallback_avoids_shared_stem_noise(self):
        noisy_path = self.tmp / "noisy.md"
        noisy_memory = SAMPLE_MEMORY.replace(
            "- {entities: api-gateway, auth} The API gateway config lives at ~/.config/myapp/config.json with host and auth_token fields. (confidence: 0.85, sources: 2)\n",
            "- {entities: api-gateway, auth} The API gateway config lives at ~/.config/myapp/config.json with host and auth_token fields. (confidence: 0.85, sources: 2)\n"
            "- {entities: withings-integration} The Withings integration facade coordinates OAuth helpers. (confidence: 0.80, sources: 1)\n",
        )
        noisy_path.write_text(noisy_memory, encoding="utf-8")
        bank = recall.parse_memory_file(noisy_path)

        result = recall.recall(bank, entity="integration test", cross_section=True)
        flattened = "\n".join(item for items in result.values() for item in items)

        self.assertIn("integration test suite hung indefinitely", flattened)
        self.assertNotIn("Withings integration facade", flattened)

    def test_fuzzy_topic_fallback(self):
        result = recall.recall(self.bank, keyword="hot reload workflow")
        self.assertIn("experiences", result)
        self.assertTrue(any("combined dev command" in item for item in result["experiences"]))


class TestStats(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)
        self.bank = recall.parse_memory_file(self.path)

    def test_counts(self):
        s = recall.stats(self.bank)
        self.assertEqual(s["counts"]["experiences"], 4)
        self.assertEqual(s["counts"]["world_knowledge"], 3)
        self.assertEqual(s["counts"]["beliefs"], 2)
        self.assertEqual(s["counts"]["reflections"], 1)
        self.assertEqual(s["counts"]["entity_summaries"], 2)
        self.assertEqual(s["counts"]["total"], 12)

    def test_entity_index(self):
        s = recall.stats(self.bank)
        self.assertIn("postgresql", s["entities"])
        self.assertIn("dev-server", s["entities"])
        self.assertTrue(s["unique_entities"] > 0)


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_valid_file(self):
        path = _write_sample(self.tmp)
        result = manage.validate(path)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)

    def test_missing_section(self):
        p = self.tmp / "bad.md"
        p.write_text("# Agentic Memory\n\n## Experiences\n\n## Facts\n")
        result = manage.validate(p)
        self.assertFalse(result["valid"])
        self.assertTrue(any("World Knowledge" in e for e in result["errors"]))

    def test_missing_reflections_section_is_invalid(self):
        p = self.tmp / "missing-reflections.md"
        p.write_text(
            "# Agentic Memory\n\n"
            "## Experiences\n\n"
            "- **2026-03-27** [testing] {entities: x} Something happened during testing.\n\n"
            "## World Knowledge\n\n"
            "- {entities: x} A fact. (confidence: 0.90, sources: 1)\n\n"
            "## Beliefs\n\n"
            "- {entities: x} A belief. (confidence: 0.50, formed: 2026-03-27, updated: 2026-03-27)\n\n"
            "## Entity Summaries\n",
            encoding="utf-8",
        )
        result = manage.validate(p)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Reflections" in e for e in result["errors"]))

    def test_legacy_per_section_phrase_in_body_still_requires_reflections(self):
        """Do not skip heading checks when an entry mentions per-section storage."""
        p = self.tmp / "legacy-phrase-in-body.md"
        p.write_text(
            "# Agentic Memory\n\n"
            "## Experiences\n\n"
            "- **2026-03-27** [docs] {entities: memory-layout} "
            "We documented per-section files for the memory layout.\n\n"
            "## World Knowledge\n\n"
            "## Beliefs\n\n"
            "## Entity Summaries\n",
            encoding="utf-8",
        )
        result = manage.validate(p)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Reflections" in e for e in result["errors"]))

    def test_nonexistent_file(self):
        result = manage.validate(self.tmp / "nope.md")
        self.assertFalse(result["valid"])

    def test_warnings_for_missing_metadata(self):
        p = self.tmp / "warn.md"
        p.write_text(
            "# Daneel Agentic Memory\n\n"
            "## Experiences\n\n"
            "- short\n\n"
            "## World Knowledge\n\n"
            "- {entities: x} A fact without confidence.\n\n"
            "## Beliefs\n\n"
            "- {entities: x} A belief. (confidence: 0.5)\n\n"
            "## Reflections\n\n"
            "## Entity Summaries\n"
        )
        result = manage.validate(p)
        self.assertTrue(result["valid"])
        self.assertTrue(len(result["warnings"]) > 0)


class TestDuplicateDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_exact_duplicate(self):
        result = manage.check_duplicate(
            self.path, "experiences",
            "The integration test suite hung indefinitely because another process was already bound to port 5432"
        )
        self.assertTrue(result["is_duplicate"])
        self.assertTrue(result["matches"][0]["similarity"] > 0.8)

    def test_near_duplicate(self):
        result = manage.check_duplicate(
            self.path, "experiences",
            "The integration test hangs when port 5432 is already in use by another process"
        )
        self.assertTrue(result["is_duplicate"])

    def test_non_duplicate(self):
        result = manage.check_duplicate(
            self.path, "experiences",
            "The screenshot comparison tool uses headless Chrome for visual regression"
        )
        self.assertFalse(result["is_duplicate"])


class TestConfidenceUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_reinforce_belief(self):
        result = manage.update_confidence(self.path, "beliefs", 0, 0.1)
        self.assertTrue(result["success"])
        self.assertEqual(result["old_confidence"], 0.70)
        self.assertEqual(result["new_confidence"], 0.80)

        bank = recall.parse_memory_file(self.path)
        self.assertEqual(bank.beliefs[0].confidence, 0.80)

    def test_weaken_belief(self):
        result = manage.update_confidence(self.path, "beliefs", 1, -0.15)
        self.assertTrue(result["success"])
        self.assertEqual(result["old_confidence"], 0.60)
        self.assertEqual(result["new_confidence"], 0.45)

    def test_clamp_to_one(self):
        result = manage.update_confidence(self.path, "beliefs", 0, 0.5)
        self.assertTrue(result["success"])
        self.assertEqual(result["new_confidence"], 1.0)

    def test_clamp_to_zero(self):
        result = manage.update_confidence(self.path, "beliefs", 1, -1.0)
        self.assertTrue(result["success"])
        self.assertEqual(result["new_confidence"], 0.0)

    def test_update_world_knowledge(self):
        result = manage.update_confidence(self.path, "world_knowledge", 0, 0.05)
        self.assertTrue(result["success"])
        self.assertEqual(result["old_confidence"], 0.95)
        self.assertEqual(result["new_confidence"], 1.0)

    def test_invalid_index(self):
        result = manage.update_confidence(self.path, "beliefs", 99, 0.1)
        self.assertFalse(result["success"])

    def test_invalid_section(self):
        result = manage.update_confidence(self.path, "experiences", 0, 0.1)
        self.assertFalse(result["success"])

    def test_no_bump_updated_preserves_belief_date(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / "mem.md"
        path.write_text(
            "## Beliefs\n\n"
            "- {entities: x} Test belief. "
            "(confidence: 0.65, formed: 2025-01-01, updated: 2025-06-01)\n\n",
            encoding="utf-8",
        )
        result = manage.update_confidence(
            path, "beliefs", 0, -0.02, bump_updated=False
        )
        self.assertTrue(result["success"])
        bank = recall.parse_memory_file(path)
        self.assertEqual(bank.beliefs[0].updated, "2025-06-01")
        self.assertEqual(bank.beliefs[0].confidence, 0.63)


class TestTemporalDecay(unittest.TestCase):
    def test_grace_window_zero(self):
        self.assertEqual(manage.compute_temporal_decay_delta(14, 400), 0.0)
        self.assertEqual(manage.compute_temporal_decay_delta(5, 400), 0.0)

    def test_beyond_grace_negative(self):
        d = manage.compute_temporal_decay_delta(60, 30)
        self.assertLess(d, 0.0)

    def test_capped_magnitude(self):
        d = manage.compute_temporal_decay_delta(10_000, 10_000)
        self.assertGreaterEqual(d, -0.04)
        self.assertLessEqual(d, 0.0)

    def test_preview_belief_temporal_decay_shape(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / "mem.md"
        path.write_text(
            "## Beliefs\n\n"
            "- {entities: a} One. "
            "(confidence: 0.70, formed: 2025-01-01, updated: 2025-01-01)\n\n",
            encoding="utf-8",
        )
        as_of = __import__("datetime").date(2026, 3, 27)
        out = manage.preview_belief_temporal_decay(path, as_of=as_of)
        self.assertEqual(out["as_of"], "2026-03-27")
        self.assertEqual(len(out["beliefs"]), 1)
        b = out["beliefs"][0]
        self.assertIn("staleness_days", b)
        self.assertIn("temporal_decay_if_unsupported", b)
        self.assertEqual(b["updated"], "2025-01-01")
        self.assertEqual(b["formed"], "2025-01-01")


class TestEntityExtraction(unittest.TestCase):
    def test_backtick_entities_are_canonicalized(self):
        result = manage.extract_entities(
            "The `docker compose` command and `Redis CLI` work together"
        )
        self.assertIn("docker-compose", result["candidates"])
        self.assertIn("redis-cli", result["candidates"])

    def test_pascal_case_is_canonicalized(self):
        result = manage.extract_entities(
            "The FastAPI gateway connects to SQLAlchemy server functions"
        )
        self.assertIn("fastapi", result["candidates"])
        self.assertIn("sqlalchemy", result["candidates"])

    def test_hyphenated(self):
        result = manage.extract_entities(
            "The e2e-test-runner test uses port-5432"
        )
        self.assertIn("e2e-test-runner", result["candidates"])
        self.assertIn("port-5432", result["candidates"])

    def test_common_lowercase_tech_terms(self):
        result = manage.extract_entities(
            "The postgres adapter connects to redis and docker"
        )
        self.assertIn("postgresql", result["candidates"])
        self.assertIn("redis", result["candidates"])
        self.assertIn("docker", result["candidates"])

    def test_empty_input(self):
        result = manage.extract_entities("")
        self.assertEqual(result["count"], 0)


class TestManageCliErgonomics(unittest.TestCase):
    def test_validate_accepts_scope_after_subcommand(self):
        script = Path(manage.__file__).resolve()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = os.environ.copy()
            env["HOME"] = td
            subprocess.run(
                [sys.executable, str(script), "init-user"],
                cwd=str(script.parent),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            # Make project scope invalid so the command must honor the
            # subcommand-level --scope user override to pass.
            (root / "MEMORY.md").write_text("not a valid memory file\n", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(script), "validate", "--scope", "user"],
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            data = json.loads(r.stdout)
            self.assertTrue(data["valid"])

    def test_check_duplicate_accepts_scope_after_subcommand(self):
        script = Path(manage.__file__).resolve()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_sample(root)
            r = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "check-duplicate",
                    "--scope",
                    "project",
                    "--section",
                    "experiences",
                    "--candidate",
                    "The integration test suite hung indefinitely because another process was already bound to port 5432.",
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            data = json.loads(r.stdout)
            self.assertTrue(data["is_duplicate"])

    def test_screen_text_accepts_stdin_input(self):
        script = Path(manage.__file__).resolve()
        text = "OpenClaw's gateway layer routed the request correctly."
        r = subprocess.run(
            [sys.executable, str(script), "screen-text", "--text-stdin"],
            cwd=str(script.parent),
            input=text,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        data = json.loads(r.stdout)
        self.assertTrue(data["safe"])
        self.assertEqual(data["sanitized_text"], text)


class TestSensitiveScreening(unittest.TestCase):
    def test_detects_secret_assignment(self):
        result = manage.screen_text(
            "The database password is hunter2 and should not be stored."
        )
        self.assertFalse(result["safe"])
        self.assertTrue(result["issues"])
        self.assertNotIn("hunter2", result["sanitized_text"])


class TestAtomicWriteGuard(unittest.TestCase):
    def test_write_text_if_unchanged_rejects_stale_hash(self):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "MEMORY.md"
        path.write_text("# Agentic Memory\n", encoding="utf-8")
        expected_hash = manage.content_hash(path.read_text(encoding="utf-8"))

        path.write_text("# Agentic Memory\n\nchanged\n", encoding="utf-8")

        result = manage.write_text_if_unchanged(
            path,
            "# Agentic Memory\n\nreplacement\n",
            expected_hash,
        )

        self.assertFalse(result["success"])
        self.assertIn("stale", result["error"])
        self.assertIn("changed", path.read_text(encoding="utf-8"))


class TestAppendEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_append_entry_rejects_sensitive_text(self):
        result = manage.append_entry(
            self.path,
            section="experiences",
            text="The API token is sk_live_123456 and must not be persisted.",
            scope_label="user",
            date="2026-03-27",
            context="debug",
            entities=["stripe"],
        )
        self.assertFalse(result["success"])
        self.assertIn("sensitive", result["error"].lower())

    def test_append_entry_normalizes_context_and_entities(self):
        result = manage.append_entry(
            self.path,
            section="experiences",
            text="The Postgres adapter connects to redis and docker.",
            scope_label="user",
            date="2026-03-27",
            context="debugging",
            entities=["Postgres", "Redis CLI", "docker"],
        )
        self.assertTrue(result["success"])

        bank = recall.parse_memory_file(self.path)
        exp = bank.experiences[0]
        self.assertEqual(exp.context, "debug")
        self.assertEqual(exp.entities, ["docker", "postgresql", "redis-cli"])

    def test_append_entry_outcome_and_evidence(self):
        result = manage.append_entry(
            self.path,
            section="experiences",
            text="CI failed then passed after cache clear.",
            scope_label="user",
            date="2026-03-29",
            context="testing",
            entities=["ci-pipeline"],
            outcome="mixed",
            evidence="run-12345",
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result.get("outcome"), "mixed")
        self.assertEqual(result.get("evidence"), "run-12345")
        bank = recall.parse_memory_file(self.path)
        exp = bank.experiences[0]
        self.assertEqual(exp.outcome, "mixed")
        self.assertEqual(exp.evidence, "run-12345")

    def test_append_entry_rejects_invalid_outcome(self):
        result = manage.append_entry(
            self.path,
            section="experiences",
            text="Narrative only.",
            scope_label="user",
            date="2026-03-29",
            context="testing",
            entities=["x"],
            outcome="bogus",
        )
        self.assertFalse(result["success"])
        self.assertIn("Unknown outcome", result["error"])

    def test_append_entry_evidence_sanitizes_braces(self):
        result = manage.append_entry(
            self.path,
            section="experiences",
            text="Lesson learned.",
            scope_label="user",
            date="2026-03-29",
            context="docs",
            entities=["docs"],
            outcome="success",
            evidence="ticket-42}",
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result.get("evidence"), "ticket-42")
        bank = recall.parse_memory_file(self.path)
        self.assertEqual(bank.experiences[0].evidence, "ticket-42")
        self.assertIn("{evidence: ticket-42}", bank.experiences[0].raw)


class TestNormalizeOutcome(unittest.TestCase):
    def test_valid_outcomes(self):
        for o in ("success", "FAILURE", " Mixed "):
            norm, err = manage.normalize_outcome(o)
            self.assertIsNone(err)
            self.assertEqual(norm, o.strip().lower())

    def test_none_and_empty(self):
        self.assertEqual(manage.normalize_outcome(None), (None, None))
        self.assertEqual(manage.normalize_outcome("   "), (None, None))

    def test_invalid(self):
        norm, err = manage.normalize_outcome("win")
        self.assertIsNone(norm)
        self.assertIsNotNone(err)
        self.assertIn("win", err)


class TestMaintenanceReport(unittest.TestCase):
    def test_flags_old_experience_and_low_sources(self):
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "MEMORY.md"
        p.write_text(
            "# Agentic Memory\n\n## Experiences\n\n"
            "- **2020-01-01** [debug] {entities: legacy} Ancient lesson.\n\n"
            "## World Knowledge\n\n"
            "- {entities: x} Solo-sourced fact. (confidence: 0.80, sources: 1)\n\n"
            "## Beliefs\n\n"
            "- {entities: y} Old belief. "
            "(confidence: 0.50, formed: 2020-01-01, updated: 2020-02-01)\n\n"
            "## Reflections\n\n## Entity Summaries\n",
            encoding="utf-8",
        )
        rep = manage.maintenance_report(
            memory_file=p,
            experience_min_age_days=30,
            belief_stale_days=30,
            world_max_sources=1,
        )
        self.assertTrue(rep["success"])
        self.assertEqual(rep["counts"]["stale_experiences"], 1)
        self.assertEqual(rep["counts"]["low_source_world_knowledge"], 1)
        self.assertEqual(rep["counts"]["stale_beliefs"], 1)

    def test_empty_sections_yield_zero_counts(self):
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "MEMORY.md"
        p.write_text(
            "# Agentic Memory\n\n## Experiences\n\n<!-- c -->\n\n"
            "## World Knowledge\n\n<!-- c -->\n\n"
            "## Beliefs\n\n<!-- c -->\n\n"
            "## Reflections\n\n<!-- c -->\n\n"
            "## Entity Summaries\n\n<!-- c -->\n",
            encoding="utf-8",
        )
        rep = manage.maintenance_report(memory_file=p)
        self.assertTrue(rep["success"])
        self.assertEqual(rep["counts"]["stale_experiences"], 0)
        self.assertEqual(rep["counts"]["low_source_world_knowledge"], 0)
        self.assertEqual(rep["counts"]["stale_beliefs"], 0)

    def test_world_knowledge_above_max_sources_not_flagged(self):
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "MEMORY.md"
        p.write_text(
            "# Agentic Memory\n\n## Experiences\n\n<!-- c -->\n\n"
            "## World Knowledge\n\n"
            "- {entities: z} Well supported. (confidence: 0.90, sources: 3)\n\n"
            "## Beliefs\n\n<!-- c -->\n\n"
            "## Reflections\n\n<!-- c -->\n\n"
            "## Entity Summaries\n\n<!-- c -->\n",
            encoding="utf-8",
        )
        rep = manage.maintenance_report(
            memory_file=p,
            world_max_sources=1,
        )
        self.assertEqual(rep["counts"]["low_source_world_knowledge"], 0)


class TestPruneBeliefs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_no_prunable_at_default(self):
        result = manage.prune_beliefs(self.path, 0.2)
        self.assertEqual(result["prunable_count"], 0)

    def test_prunable_with_high_threshold(self):
        result = manage.prune_beliefs(self.path, 0.75)
        self.assertEqual(result["prunable_count"], 2)


class TestSuggestSummaries(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_existing_summaries_not_suggested(self):
        result = manage.suggest_summaries(self.path)
        entity_names = [s["entity"] for s in result["suggestions"]]
        self.assertNotIn("postgresql", entity_names)

    def test_suggest_returns_dict(self):
        result = manage.suggest_summaries(self.path)
        self.assertIn("suggestions", result)
        self.assertIn("existing_summary_count", result)
        self.assertEqual(result["existing_summary_count"], 2)


class TestNormalization(unittest.TestCase):
    def test_stopword_removal(self):
        n = manage.normalize_for_comparison("The test was hanging in the session today")
        self.assertNotIn("the", n.split())
        self.assertNotIn("was", n.split())
        self.assertNotIn("today", n.split())

    def test_case_insensitive(self):
        n = manage.normalize_for_comparison("FastAPI Gateway Status")
        self.assertEqual(n, "fastapi gateway status")

    def test_punctuation_removal(self):
        n = manage.normalize_for_comparison("port-5432: bound!")
        self.assertNotIn(":", n)
        self.assertNotIn("!", n)


SAMPLE_USER_MEMORY = """\
# User Memory

## Experiences

<!-- Newest first. Format: - **YYYY-MM-DD** [context] {entities: e1, e2} Narrative memory text. -->

- **2026-03-27** [preference] {entities: vim, editor} I prefer using vim keybindings in all editors. This is a personal workflow preference that should not be pushed to the project.

## World Knowledge

<!-- Verified, objective facts about the project and environment. Format:
- {entities: e1} Fact text. (confidence: 0.XX, sources: N) -->

- {entities: language-server} The language server requires at least 4GB of RAM for this project. (confidence: 0.80, sources: 2)

## Beliefs

<!-- Agent's subjective judgments that evolve over time. Format:
- {entities: e1} Belief text. (confidence: 0.XX, formed: YYYY-MM-DD, updated: YYYY-MM-DD) -->

- {entities: linter} Running the linter before every commit catches more issues than a basic syntax check alone. (confidence: 0.75, formed: 2026-03-20, updated: 2026-03-27)

## Entity Summaries

<!-- Synthesized profiles of key entities, regenerated when underlying memories change. Format:
### entity-name
Summary paragraph. -->
"""


def _write_both(tmp: Path) -> tuple[Path, Path]:
    """Write both a project and user memory file in a temp directory."""
    project = tmp / "project" / "MEMORY.md"
    user = tmp / "user" / "MEMORY.md"
    project.parent.mkdir(parents=True)
    user.parent.mkdir(parents=True)
    project.write_text(SAMPLE_MEMORY, encoding="utf-8")
    user.write_text(SAMPLE_USER_MEMORY, encoding="utf-8")
    return project, user


class TestMultiScopeRecall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project_path, self.user_path = _write_both(self.tmp)
        self.project_bank = recall.parse_memory_file(self.project_path)
        self.user_bank = recall.parse_memory_file(self.user_path)

    def test_recall_multi_tags_results(self):
        banks = [("user", self.user_bank), ("project", self.project_bank)]
        result = recall.recall_multi(banks, keyword="vim")
        exps = result.get("experiences", [])
        self.assertEqual(len(exps), 1)
        self.assertTrue(exps[0].startswith("[user]"))

    def test_recall_multi_merges_sections(self):
        banks = [("user", self.user_bank), ("project", self.project_bank)]
        result = recall.recall_multi(banks, keyword="port")
        exps = result.get("experiences", [])
        self.assertTrue(any("[project]" in e for e in exps))

    def test_recall_multi_entity_cross_scope(self):
        banks = [("user", self.user_bank), ("project", self.project_bank)]
        result = recall.recall_multi(banks, entity="postgresql", cross_section=True)
        all_items = []
        for items in result.values():
            all_items.extend(items)
        self.assertTrue(any("[project]" in i for i in all_items))

    def test_stats_multi(self):
        banks = [("user", self.user_bank), ("project", self.project_bank)]
        result = recall.stats_multi(banks)
        self.assertEqual(result["scope"], "combined")
        self.assertEqual(len(result["per_scope"]), 2)
        self.assertEqual(result["per_scope"][0]["scope"], "user")
        self.assertEqual(result["per_scope"][1]["scope"], "project")
        self.assertEqual(result["counts"]["experiences"], 5)  # 4 project + 1 user
        self.assertEqual(result["counts"]["world_knowledge"], 4)  # 3 project + 1 user

    def test_merge_banks(self):
        banks = [("user", self.user_bank), ("project", self.project_bank)]
        merged = recall.merge_banks(banks)
        self.assertEqual(len(merged.experiences), 5)
        self.assertEqual(len(merged.world_knowledge), 4)
        self.assertEqual(len(merged.beliefs), 3)

    def test_single_scope_recall(self):
        result = recall.recall(self.user_bank, keyword="vim")
        self.assertEqual(len(result.get("experiences", [])), 1)
        result2 = recall.recall(self.project_bank, keyword="vim")
        self.assertEqual(len(result2), 0)


class TestCrossScopeDuplicate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project_path, self.user_path = _write_both(self.tmp)

    def test_cross_scope_finds_project_duplicate(self):
        result = manage.check_duplicate(
            self.user_path, "experiences",
            "The integration test hung because port 5432 was bound",
            extra_paths=[("project", self.project_path)],
        )
        self.assertTrue(result["is_duplicate"])
        project_matches = [m for m in result["matches"] if m.get("source") == "project"]
        self.assertTrue(len(project_matches) > 0)

    def test_cross_scope_no_false_positive(self):
        result = manage.check_duplicate(
            self.user_path, "experiences",
            "I prefer using vim keybindings",
            extra_paths=[("project", self.project_path)],
        )
        project_matches = [m for m in result["matches"] if m.get("source") == "project"]
        self.assertEqual(len(project_matches), 0)


class TestPromote(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project_path, self.user_path = _write_both(self.tmp)

    def test_promote_requires_explicit_approval_flag(self):
        result = manage.promote(
            self.user_path,
            self.project_path,
            "world_knowledge",
            0,
            allow_project_promotion=False,
        )
        self.assertFalse(result["success"])
        self.assertIn("allow-project-promotion", result["error"])

    def test_promote_preference_experience_blocked(self):
        result = manage.promote(
            self.user_path,
            self.project_path,
            "experiences",
            0,
            allow_project_promotion=True,
        )
        self.assertFalse(result["success"])
        self.assertIn("preference", result["error"])

    def test_promote_world_knowledge(self):
        result = manage.promote(
            self.user_path,
            self.project_path,
            "world_knowledge",
            0,
            allow_project_promotion=True,
        )
        self.assertTrue(result["success"])
        project_bank = recall.parse_memory_file(self.project_path)
        self.assertEqual(len(project_bank.world_knowledge), 4)

    def test_promote_belief(self):
        result = manage.promote(
            self.user_path,
            self.project_path,
            "beliefs",
            0,
            allow_project_promotion=True,
        )
        self.assertTrue(result["success"])
        project_bank = recall.parse_memory_file(self.project_path)
        self.assertEqual(len(project_bank.beliefs), 3)

    def test_promote_duplicate_blocked(self):
        self.project_path.write_text(
            SAMPLE_MEMORY.replace(
                "## World Knowledge",
                "- **2026-03-27** [preference] {entities: vim, editor} I prefer using vim keybindings in all editors. This is a personal workflow preference that should not be pushed to the project.\n\n## World Knowledge"
            ),
            encoding="utf-8",
        )
        result = manage.promote(
            self.user_path,
            self.project_path,
            "experiences",
            0,
            allow_project_promotion=True,
        )
        self.assertFalse(result["success"])
        self.assertIn("Duplicate", result["error"])

    def test_promote_invalid_index(self):
        result = manage.promote(
            self.user_path,
            self.project_path,
            "experiences",
            99,
            allow_project_promotion=True,
        )
        self.assertFalse(result["success"])

    def test_promote_invalid_section(self):
        result = manage.promote(
            self.user_path,
            self.project_path,
            "entity_summaries",
            0,
            allow_project_promotion=True,
        )
        self.assertFalse(result["success"])


class TestInitUser(unittest.TestCase):
    def test_init_creates_template(self):
        result = manage.init_user()
        self.assertTrue(result["success"])
        self.assertTrue(Path(result["path"]).exists())


class TestOutcomeEvidenceParsing(unittest.TestCase):
    def test_parse_outcome_and_evidence(self):
        line = (
            "- **2026-03-28** [testing] {entities: e2e} {outcome: failure} "
            "{evidence: ci-99} The suite timed out."
        )
        exp = recall.parse_experience(line)
        self.assertEqual(exp.outcome, "failure")
        self.assertEqual(exp.evidence, "ci-99")
        self.assertNotIn("{outcome:", exp.text)
        self.assertNotIn("{evidence:", exp.text)
        self.assertIn("timed out", exp.text)


class TestDigest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project_path, self.user_path = _write_both(self.tmp)
        self.project_bank = recall.parse_memory_file(self.project_path)
        self.user_bank = recall.parse_memory_file(self.user_path)

    def test_single_scope_digest(self):
        output = recall.digest([("project", self.project_bank)])
        self.assertIn("[project] memory", output)
        self.assertIn("World Knowledge", output)
        self.assertIn("listen_addresses", output)
        self.assertIn("Recent Experiences", output)

    def test_dual_scope_digest(self):
        banks = [("user", self.user_bank), ("project", self.project_bank)]
        output = recall.digest(banks)
        self.assertIn("[user] memory", output)
        self.assertIn("[project] memory", output)
        self.assertIn("vim", output)
        self.assertIn("listen_addresses", output)

    def test_digest_last_limits_experiences(self):
        output = recall.digest([("project", self.project_bank)], last=2)
        section = output.split("**Recent Experiences")[-1] if "**Recent Experiences" in output else ""
        lines = [l for l in section.splitlines() if l.startswith("- 2026-")]
        self.assertEqual(len(lines), 2)

    def test_digest_last_all(self):
        output = recall.digest([("project", self.project_bank)], last=100)
        section = output.split("**Recent Experiences")[-1] if "**Recent Experiences" in output else ""
        lines = [l for l in section.splitlines() if l.startswith("- 2026-")]
        self.assertEqual(len(lines), 4)

    def test_digest_days_filter(self):
        output = recall.digest([("project", self.project_bank)], days=7)
        section = output.split("**Recent Experiences")[-1] if "**Recent Experiences" in output else ""
        exp_lines = [l for l in section.splitlines() if l.startswith("- 2026-")]
        self.assertTrue(len(exp_lines) <= 2)
        for line in exp_lines:
            self.assertNotIn("2026-02-10", line)

    def test_digest_includes_beliefs(self):
        output = recall.digest([("project", self.project_bank)])
        self.assertIn("Beliefs", output)
        self.assertIn("combined dev command is more reliable", output)

    def test_digest_includes_entity_summaries(self):
        output = recall.digest([("project", self.project_bank)])
        self.assertIn("Entity Summaries", output)
        self.assertIn("**postgresql**", output)

    def test_digest_confidence_shown(self):
        output = recall.digest([("project", self.project_bank)])
        self.assertIn("(0.95)", output)
        self.assertIn("(0.7)", output)

    def test_digest_empty_bank(self):
        empty = recall.MemoryBank()
        output = recall.digest([("user", empty)])
        self.assertEqual(output, "(no memories found)")

    def test_digest_empty_both(self):
        empty = recall.MemoryBank()
        output = recall.digest([("user", empty), ("project", empty)])
        self.assertEqual(output, "(no memories found)")

    def test_digest_orders_failures_before_successes(self):
        mem = """\
# Agentic Memory

## Experiences

- **2026-03-27** [testing] {entities: a} {outcome: success} All green.
- **2026-03-26** [testing] {entities: b} {outcome: failure} Build broke.

## World Knowledge

## Beliefs

## Reflections

## Entity Summaries
"""
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "MEMORY.md"
        p.write_text(mem, encoding="utf-8")
        bank = recall.parse_memory_file(p)
        output = recall.digest([("project", bank)], last=2)
        self.assertIn("failures/mixed listed first", output)
        section = output.split("**Recent Experiences")[-1]
        lines = [ln for ln in section.splitlines() if ln.startswith("- 2026-")]
        self.assertEqual(len(lines), 2)
        self.assertIn("failure", lines[0])
        self.assertIn("success", lines[1])


CONFLICT_MEMORY = """\
# Agentic Memory

## Experiences

<!-- comment -->

## World Knowledge

<!-- comment -->

## Beliefs

<!-- comment -->

- {entities: dev-server} The dev server is reliable and stable for daily use. (confidence: 0.70, formed: 2026-03-10, updated: 2026-03-20)
- {entities: dev-server} The dev server is unreliable and frequently fails under load. (confidence: 0.50, formed: 2026-03-15, updated: 2026-03-22)
- {entities: ci-pipeline} The CI pipeline is the best safeguard against regressions. (confidence: 0.80, formed: 2026-03-01, updated: 2026-03-25)

## Reflections

<!-- comment -->

## Entity Summaries

<!-- comment -->
"""


class TestReflectionParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)
        self.bank = recall.parse_memory_file(self.path)

    def test_reflection_count(self):
        self.assertEqual(len(self.bank.reflections), 1)

    def test_reflection_fields(self):
        r = self.bank.reflections[0]
        self.assertEqual(r.date, "2026-03-26")
        self.assertIn("dev-server", r.entities)
        self.assertIn("integration-tests", r.entities)
        self.assertIn("port-5432", r.entities)
        self.assertIn("child processes", r.text)

    def test_reflection_in_recall(self):
        result = recall.recall(self.bank, keyword="child processes")
        self.assertIn("reflections", result)
        self.assertEqual(len(result["reflections"]), 1)

    def test_reflection_entity_recall(self):
        result = recall.recall(self.bank, entity="dev-server", cross_section=True)
        self.assertIn("reflections", result)

    def test_reflection_in_stats(self):
        s = recall.stats(self.bank)
        self.assertEqual(s["counts"]["reflections"], 1)
        self.assertEqual(s["counts"]["total"], 12)  # 4+3+2+1+2

    def test_reflection_in_digest(self):
        output = recall.digest([("project", self.bank)])
        self.assertIn("Reflections", output)
        self.assertIn("child processes", output)

    def test_reflection_in_entity_index(self):
        entities = recall.collect_all_entities(self.bank)
        self.assertIn("reflections", entities.get("dev-server", []))


class TestCheckConflicts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "MEMORY.md"
        self.path.write_text(CONFLICT_MEMORY, encoding="utf-8")

    def test_detects_conflict(self):
        result = manage.check_conflicts(self.path)
        self.assertGreaterEqual(result["conflict_count"], 1)
        conflict = result["conflicts"][0]
        self.assertIn("dev-server", conflict["shared_entities"])

    def test_conflict_recommendation(self):
        result = manage.check_conflicts(self.path)
        conflict = result["conflicts"][0]
        self.assertIn("keep index", conflict["recommendation"])

    def test_no_conflict_between_unrelated(self):
        result = manage.check_conflicts(self.path)
        for c in result["conflicts"]:
            self.assertNotIn("ci-pipeline", c["shared_entities"])

    def test_no_conflicts_when_empty(self):
        p = self.tmp / "empty.md"
        p.write_text(
            "# Agentic Memory\n\n## Experiences\n\n<!-- c -->\n\n"
            "## World Knowledge\n\n<!-- c -->\n\n"
            "## Beliefs\n\n<!-- c -->\n\n"
            "## Reflections\n\n<!-- c -->\n\n"
            "## Entity Summaries\n\n<!-- c -->\n"
        )
        result = manage.check_conflicts(p)
        self.assertEqual(result["conflict_count"], 0)

    def test_total_beliefs_reported(self):
        result = manage.check_conflicts(self.path)
        self.assertEqual(result["total_beliefs"], 3)


class TestEmptyMemory(unittest.TestCase):
    def test_empty_template(self):
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "MEMORY.md"
        p.write_text(
            "# Agentic Memory\n\n"
            "## Experiences\n\n"
            "<!-- comment -->\n\n"
            "## World Knowledge\n\n"
            "<!-- comment -->\n\n"
            "## Beliefs\n\n"
            "<!-- comment -->\n\n"
            "## Reflections\n\n"
            "<!-- comment -->\n\n"
            "## Entity Summaries\n\n"
            "<!-- comment -->\n"
        )
        bank = recall.parse_memory_file(p)
        self.assertEqual(len(bank.experiences), 0)
        self.assertEqual(len(bank.world_knowledge), 0)
        self.assertEqual(len(bank.beliefs), 0)
        self.assertEqual(len(bank.reflections), 0)
        self.assertEqual(len(bank.entity_summaries), 0)

        result = manage.validate(p)
        self.assertTrue(result["valid"])


CAUSAL_MEMORY = """\
# Agentic Memory

## Experiences

<!-- comment -->

- **2026-03-26** [debug] {entities: build-watcher, port-5432} {causes: dev-server} The build watcher left a child process bound to port 5432, which crashed the dev server on next startup.
- **2026-03-25** [debug] {entities: dev-server} {caused-by: build-watcher} The dev server failed to start because port 5432 was already bound by a stale build-watcher child process.
- **2026-03-20** [tooling] {entities: config-loader} {enables: api-gateway} The config loader now validates all fields at startup, which enables the API gateway to start reliably.

## World Knowledge

<!-- comment -->

## Beliefs

<!-- comment -->

## Reflections

<!-- comment -->

## Entity Summaries

<!-- comment -->
"""


class TestCausalLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "MEMORY.md"
        self.path.write_text(CAUSAL_MEMORY, encoding="utf-8")
        self.bank = recall.parse_memory_file(self.path)

    def test_causal_links_parsed(self):
        exp = self.bank.experiences[0]
        self.assertEqual(len(exp.causal_links), 1)
        self.assertEqual(exp.causal_links[0].relation, "causes")
        self.assertEqual(exp.causal_links[0].target, "dev-server")

    def test_caused_by_parsed(self):
        exp = self.bank.experiences[1]
        self.assertEqual(len(exp.causal_links), 1)
        self.assertEqual(exp.causal_links[0].relation, "caused-by")
        self.assertEqual(exp.causal_links[0].target, "build-watcher")

    def test_enables_parsed(self):
        exp = self.bank.experiences[2]
        self.assertEqual(exp.causal_links[0].relation, "enables")
        self.assertEqual(exp.causal_links[0].target, "api-gateway")

    def test_causal_tags_stripped_from_text(self):
        exp = self.bank.experiences[0]
        self.assertNotIn("{causes:", exp.text)
        self.assertIn("child process", exp.text)

    def test_no_causal_links_when_absent(self):
        bank = recall.parse_memory_file(
            _write_sample(Path(tempfile.mkdtemp()))
        )
        for exp in bank.experiences:
            self.assertEqual(len(exp.causal_links), 0)

    def test_causal_keyword_search(self):
        result = recall.recall(self.bank, keyword="causes:")
        self.assertIn("experiences", result)


class TestTokenBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)
        self.bank = recall.parse_memory_file(self.path)

    def test_budget_limits_results(self):
        all_results = recall.recall(self.bank, keyword=" ")
        total_chars = sum(len(item) for items in all_results.values() for item in items)
        budget_tokens = total_chars // 8
        limited = recall.recall(self.bank, keyword=" ", budget=budget_tokens)
        limited_chars = sum(len(item) for items in limited.values() for item in items)
        self.assertLess(limited_chars, total_chars)

    def test_budget_none_returns_all(self):
        result = recall.recall(self.bank, keyword=" ", budget=None)
        total = sum(len(items) for items in result.values())
        self.assertGreater(total, 0)

    def test_budget_zero_returns_empty(self):
        result = recall.recall(self.bank, keyword=" ", budget=0)
        self.assertEqual(len(result), 0)

    def test_budget_large_returns_all(self):
        all_results = recall.recall(self.bank, keyword=" ")
        large = recall.recall(self.bank, keyword=" ", budget=999999)
        self.assertEqual(
            sum(len(v) for v in all_results.values()),
            sum(len(v) for v in large.values()),
        )

    def test_budget_prioritizes_world_knowledge(self):
        result = recall.recall(self.bank, keyword=" ", budget=50)
        if result:
            first_section = list(result.keys())[0]
            self.assertEqual(first_section, "world_knowledge")


class TestFindMatches(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_finds_matching_experience(self):
        result = manage.find_matches(self.path, "integration test hung port")
        self.assertGreater(result["match_count"], 0)
        self.assertEqual(result["matches"][0]["section"], "experiences")

    def test_finds_matching_belief(self):
        result = manage.find_matches(self.path, "dev command reliable")
        found_belief = any(m["section"] == "beliefs" for m in result["matches"])
        self.assertTrue(found_belief)

    def test_no_matches_for_unrelated(self):
        result = manage.find_matches(self.path, "quantum entanglement physics")
        self.assertEqual(result["match_count"], 0)

    def test_low_threshold_finds_more(self):
        strict = manage.find_matches(self.path, "server", threshold=0.8)
        loose = manage.find_matches(self.path, "server", threshold=0.2)
        self.assertGreaterEqual(loose["match_count"], strict["match_count"])

    def test_matches_include_metadata(self):
        result = manage.find_matches(self.path, "integration test hung")
        if result["matches"]:
            m = result["matches"][0]
            self.assertIn("section", m)
            self.assertIn("index", m)
            self.assertIn("similarity", m)
            self.assertIn("text", m)
            self.assertIn("raw", m)


class TestDeleteEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = _write_sample(self.tmp)

    def test_delete_experience(self):
        bank_before = recall.parse_memory_file(self.path)
        count_before = len(bank_before.experiences)
        result = manage.delete_entry(self.path, "experiences", 0)
        self.assertTrue(result["success"])
        self.assertIn("deleted", result)
        bank_after = recall.parse_memory_file(self.path)
        self.assertEqual(len(bank_after.experiences), count_before - 1)

    def test_delete_belief(self):
        bank_before = recall.parse_memory_file(self.path)
        count_before = len(bank_before.beliefs)
        result = manage.delete_entry(self.path, "beliefs", 0)
        self.assertTrue(result["success"])
        bank_after = recall.parse_memory_file(self.path)
        self.assertEqual(len(bank_after.beliefs), count_before - 1)

    def test_delete_invalid_index(self):
        result = manage.delete_entry(self.path, "experiences", 99)
        self.assertFalse(result["success"])

    def test_delete_invalid_section(self):
        result = manage.delete_entry(self.path, "entity_summaries", 0)
        self.assertFalse(result["success"])

    def test_delete_nonexistent_file(self):
        result = manage.delete_entry(self.tmp / "nope.md", "experiences", 0)
        self.assertFalse(result["success"])

    def test_delete_last_entry_leaves_section_intact(self):
        bank = recall.parse_memory_file(self.path)
        for i in range(len(bank.experiences) - 1, -1, -1):
            manage.delete_entry(self.path, "experiences", i)
        bank_after = recall.parse_memory_file(self.path)
        self.assertEqual(len(bank_after.experiences), 0)
        result = manage.validate(self.path)
        self.assertTrue(result["valid"])


# ---- Multi-file section tests -----------------------------------------------

def _write_section_files(section_dir: Path):
    """Create populated section files for testing."""
    section_dir.mkdir(parents=True, exist_ok=True)
    (section_dir / "experiences.md").write_text(
        "## Experiences\n\n<!-- comment -->\n\n"
        "- **2026-03-26** [debug] {entities: integration-tests, port-5432} The integration test suite hung because port 5432 was bound.\n"
        "- **2026-03-20** [tooling] {entities: dev-server} Running the dev server alone is insufficient for CSS hot reload.\n",
        encoding="utf-8",
    )
    (section_dir / "world_knowledge.md").write_text(
        "## World Knowledge\n\n<!-- comment -->\n\n"
        "- {entities: postgresql} PostgreSQL 16 requires listen_addresses for remote connections. (confidence: 0.95, sources: 3)\n",
        encoding="utf-8",
    )
    (section_dir / "beliefs.md").write_text(
        "## Beliefs\n\n<!-- comment -->\n\n"
        "- {entities: dev-command} The combined dev command is more reliable. (confidence: 0.70, formed: 2026-03-15, updated: 2026-03-20)\n",
        encoding="utf-8",
    )
    (section_dir / "reflections.md").write_text(
        "## Reflections\n\n<!-- comment -->\n\n"
        "- **2026-03-26** {entities: dev-server, port-5432} Port conflicts are systemic.\n",
        encoding="utf-8",
    )
    (section_dir / "entity_summaries.md").write_text(
        "## Entity Summaries\n\n<!-- comment -->\n\n"
        "### postgresql\nThe primary database.\n",
        encoding="utf-8",
    )


class TestSectionFileLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.section_dir = self.tmp / "memory"
        _write_section_files(self.section_dir)

    def test_has_section_files(self):
        self.assertTrue(recall.has_section_files(self.section_dir))

    def test_load_memory_from_sections(self):
        bank = recall.load_memory_from_sections(self.section_dir)
        self.assertEqual(len(bank.experiences), 2)
        self.assertEqual(len(bank.world_knowledge), 1)
        self.assertEqual(len(bank.beliefs), 1)
        self.assertEqual(len(bank.reflections), 1)
        self.assertEqual(len(bank.entity_summaries), 1)

    def test_load_memory_prefers_sections(self):
        master = self.tmp / "MEMORY.md"
        master.write_text(SAMPLE_MEMORY, encoding="utf-8")
        bank = recall.load_memory(master, self.section_dir)
        self.assertEqual(len(bank.experiences), 2)

    def test_load_memory_falls_back_to_master(self):
        master = self.tmp / "MEMORY.md"
        master.write_text(SAMPLE_MEMORY, encoding="utf-8")
        empty_dir = self.tmp / "empty"
        bank = recall.load_memory(master, empty_dir)
        self.assertEqual(len(bank.experiences), 4)

    def test_digest_from_sections(self):
        bank = recall.load_memory_from_sections(self.section_dir)
        output = recall.digest([("project", bank)])
        self.assertIn("listen_addresses", output)
        self.assertIn("Recent Experiences", output)

    def test_recall_from_sections(self):
        bank = recall.load_memory_from_sections(self.section_dir)
        result = recall.recall(bank, keyword="hung")
        self.assertEqual(len(result.get("experiences", [])), 1)


class TestSectionEnsure(unittest.TestCase):
    def test_ensure_section_file_creates(self):
        tmp = Path(tempfile.mkdtemp())
        section_dir = tmp / "memory"
        path = recall.ensure_section_file(section_dir, "experiences")
        self.assertTrue(path.exists())
        self.assertIn("## Experiences", path.read_text(encoding="utf-8"))

    def test_ensure_section_files_creates_all(self):
        tmp = Path(tempfile.mkdtemp())
        section_dir = tmp / "memory"
        paths = recall.ensure_section_files(section_dir)
        self.assertEqual(len(paths), 5)
        for p in paths:
            self.assertTrue(p.exists())


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.master = self.tmp / "MEMORY.md"
        self.master.write_text(SAMPLE_MEMORY, encoding="utf-8")
        self.section_dir = self.tmp / "memory"

    def test_migrate_creates_section_files(self):
        result = manage.migrate(self.master, "project")
        self.assertTrue(result["success"])
        self.assertTrue((self.section_dir / "experiences.md").exists())
        self.assertTrue((self.section_dir / "world_knowledge.md").exists())
        self.assertTrue((self.section_dir / "beliefs.md").exists())
        self.assertTrue((self.section_dir / "reflections.md").exists())
        self.assertTrue((self.section_dir / "entity_summaries.md").exists())

    def test_migrate_entries_count(self):
        result = manage.migrate(self.master, "project")
        self.assertEqual(result["entries_migrated"]["experiences"], 4)
        self.assertEqual(result["entries_migrated"]["world_knowledge"], 3)
        self.assertEqual(result["entries_migrated"]["beliefs"], 2)
        self.assertEqual(result["entries_migrated"]["reflections"], 1)

    def test_migrate_does_not_create_bak(self):
        manage.migrate(self.master, "project")
        self.assertFalse((self.tmp / "MEMORY.md.bak").exists())

    def test_migrate_replaces_master_with_curated(self):
        manage.migrate(self.master, "project")
        content = self.master.read_text(encoding="utf-8")
        self.assertIn("Curated subset", content)

    def test_migrated_sections_parse_correctly(self):
        manage.migrate(self.master, "project")
        bank = recall.load_memory_from_sections(self.section_dir)
        self.assertEqual(len(bank.experiences), 4)
        self.assertEqual(len(bank.world_knowledge), 3)
        self.assertEqual(len(bank.beliefs), 2)
        self.assertEqual(len(bank.entity_summaries), 2)


class TestCurate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.section_dir = self.tmp / "memory"
        _write_section_files(self.section_dir)
        self.master = self.tmp / "MEMORY.md"
        self.master.write_text(recall.CURATED_MASTER_TEMPLATE, encoding="utf-8")

    def test_curate_writes_master(self):
        old_recall = recall.resolve_project_memory_path
        old_section = recall.resolve_section_dir
        recall.resolve_project_memory_path = lambda: self.master
        recall.resolve_section_dir = lambda scope: self.section_dir
        try:
            result = manage.curate("project")
            self.assertTrue(result["success"])
            content = self.master.read_text(encoding="utf-8")
            self.assertIn("listen_addresses", content)
            self.assertIn("combined dev command", content)
            self.assertIn("postgresql", content)
            self.assertIn("[world_knowledge.md](memory/world_knowledge.md)", content)
            self.assertIn("[beliefs.md](memory/beliefs.md)", content)
            self.assertIn("[entity_summaries.md](memory/entity_summaries.md)", content)
            self.assertNotIn("migrated", result)
        finally:
            recall.resolve_project_memory_path = old_recall
            recall.resolve_section_dir = old_section

    def test_curate_migrates_legacy_monolithic_master_then_thins(self):
        """Big single-file MEMORY.md with no section dir: migrate + thin master."""
        tmp = Path(tempfile.mkdtemp())
        master = tmp / "MEMORY.md"
        master.write_text(SAMPLE_MEMORY, encoding="utf-8")
        section_dir = tmp / "memory"
        self.assertFalse(section_dir.exists())

        old_recall = recall.resolve_project_memory_path
        old_section = recall.resolve_section_dir
        recall.resolve_project_memory_path = lambda: master
        recall.resolve_section_dir = lambda s: section_dir if s == "project" else old_section(s)
        try:
            result = manage.curate("project")
            self.assertTrue(result["success"], result)
            self.assertIn("migrated", result)
            self.assertTrue(result["migrated"]["success"])
            self.assertFalse((tmp / "MEMORY.md.bak").exists())
            self.assertTrue((section_dir / "experiences.md").exists())
            content = master.read_text(encoding="utf-8")
            self.assertIn("Curated subset", content)
            self.assertIn("listen_addresses", content)
            self.assertLess(len(content), len(SAMPLE_MEMORY) // 2)
            self.assertNotIn(
                "The integration test suite hung indefinitely because another process",
                content,
            )
            self.assertNotIn("Multiple debugging sessions revealed", content)
        finally:
            recall.resolve_project_memory_path = old_recall
            recall.resolve_section_dir = old_section


class TestValidateSections(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.section_dir = self.tmp / "memory"
        _write_section_files(self.section_dir)

    def test_valid_sections(self):
        old_fn = recall.resolve_section_dir
        recall.resolve_section_dir = lambda scope: self.section_dir
        try:
            result = manage.validate_sections("project")
            self.assertTrue(result["valid"])
            self.assertEqual(result["counts"]["experiences"], 2)
        finally:
            recall.resolve_section_dir = old_fn


class TestAppendToSectionFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.section_dir = self.tmp / "memory"
        _write_section_files(self.section_dir)
        self.master = self.tmp / "MEMORY.md"
        self.master.write_text(recall.CURATED_MASTER_TEMPLATE, encoding="utf-8")

    def test_append_goes_to_section_file(self):
        sf = self.section_dir / "experiences.md"
        result = manage.append_entry(
            sf,
            section="experiences",
            text="New test entry for section file append.",
            scope_label="project",
            date="2026-03-27",
            context="testing",
            entities=["test-append"],
        )
        self.assertTrue(result["success"])
        bank = recall.parse_memory_file(sf)
        self.assertEqual(len(bank.experiences), 3)

    def test_append_from_user_master_uses_user_section_file(self):
        user_root = self.tmp / "user"
        user_root.mkdir()
        user_master = user_root / "MEMORY.md"
        user_master.write_text(recall.USER_MEMORY_TEMPLATE, encoding="utf-8")
        recall.ensure_section_files(user_root)

        result = manage.append_entry(
            user_master,
            section="experiences",
            text="User master appends should land in the section file.",
            scope_label="user",
            date="2026-03-27",
            context="testing",
            entities=["user-append"],
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["path"], str(user_root / "experiences.md"))
        self.assertNotIn(
            "User master appends should land in the section file.",
            user_master.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "User master appends should land in the section file.",
            (user_root / "experiences.md").read_text(encoding="utf-8"),
        )

    def test_append_user_curated_master_without_section_files_targets_section_file(self):
        """Curated user MEMORY.md alone must not receive experience appends."""
        user_root = self.tmp / "solo-user"
        user_root.mkdir()
        user_master = user_root / "MEMORY.md"
        user_master.write_text(recall.USER_MEMORY_TEMPLATE, encoding="utf-8")
        self.assertFalse(recall.has_section_files(user_root))

        result = manage.append_entry(
            user_master,
            section="experiences",
            text="First experience stored only in section file after layout bootstrap.",
            scope_label="user",
            date="2026-03-27",
            context="testing",
            entities=["layout-bootstrap"],
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["path"], str(user_root / "experiences.md"))
        self.assertTrue(recall.has_section_files(user_root))
        self.assertNotIn(
            "First experience stored only in section file",
            user_master.read_text(encoding="utf-8"),
        )


class TestPromoteWithSectionFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.user_root = self.tmp / "user"
        self.project_root = self.tmp / "project"
        self.user_root.mkdir()
        self.project_root.mkdir()
        self.user_master = self.user_root / "MEMORY.md"
        self.project_master = self.project_root / "MEMORY.md"
        self.user_master.write_text(recall.USER_MEMORY_TEMPLATE, encoding="utf-8")
        self.project_master.write_text(recall.CURATED_MASTER_TEMPLATE, encoding="utf-8")
        recall.ensure_section_files(self.user_root)
        recall.ensure_section_files(self.project_root / "memory")

        (self.user_root / "experiences.md").write_text(
            "## Experiences\n\n<!-- comment -->\n\n"
            "- **2026-03-27** [testing] {entities: promotion-test} Promotable experience entry.\n",
            encoding="utf-8",
        )

    def test_promote_reads_user_sections_and_writes_project_section(self):
        result = manage.promote(
            self.user_master,
            self.project_master,
            "experiences",
            0,
            allow_project_promotion=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["target"], str(self.project_root / "memory" / "experiences.md"))
        self.assertNotIn(
            "Promotable experience entry.",
            self.project_master.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Promotable experience entry.",
            (self.project_root / "memory" / "experiences.md").read_text(encoding="utf-8"),
        )

    def test_promote_user_curated_master_only_bootstrap_sections_then_reads_sections(self):
        """User has curated master + no section files; entries live in section files after ensure."""
        user_root = self.tmp / "promote-solo-user"
        user_root.mkdir(parents=True)
        user_master = user_root / "MEMORY.md"
        user_master.write_text(recall.USER_MEMORY_TEMPLATE, encoding="utf-8")
        self.assertFalse(recall.has_section_files(user_root))

        app = manage.append_entry(
            user_master,
            section="experiences",
            text="Row to promote from bootstrapped user section files.",
            scope_label="user",
            date="2026-03-28",
            context="testing",
            entities=["promote-bootstrap"],
        )
        self.assertTrue(app["success"], app)

        result = manage.promote(
            user_master,
            self.project_master,
            "experiences",
            0,
            allow_project_promotion=True,
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["target"], str(self.project_root / "memory" / "experiences.md"))
        self.assertIn(
            "Row to promote from bootstrapped user section files.",
            (self.project_root / "memory" / "experiences.md").read_text(encoding="utf-8"),
        )


class TestAutoMigrate(unittest.TestCase):
    """load_memory should auto-split a legacy single-file MEMORY.md."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.master = self.tmp / "MEMORY.md"
        self.master.write_text(SAMPLE_MEMORY, encoding="utf-8")
        self.section_dir = self.tmp / "memory"

    def test_auto_migrates_on_load(self):
        self.assertFalse(self.section_dir.exists())
        bank = recall.load_memory(self.master, self.section_dir)
        self.assertTrue(self.section_dir.is_dir())
        self.assertTrue((self.section_dir / "experiences.md").exists())
        self.assertEqual(len(bank.experiences), 4)
        self.assertEqual(len(bank.world_knowledge), 3)
        self.assertEqual(len(bank.beliefs), 2)

    def test_master_replaced_with_curated(self):
        recall.load_memory(self.master, self.section_dir)
        content = self.master.read_text(encoding="utf-8")
        self.assertIn("Curated subset", content)

    def test_no_bak_after_auto_migrate(self):
        recall.load_memory(self.master, self.section_dir)
        self.assertFalse((self.tmp / "MEMORY.md.bak").exists())
        exp = (self.section_dir / "experiences.md").read_text(encoding="utf-8")
        self.assertIn("## Experiences", exp)

    def test_no_auto_migrate_when_sections_exist(self):
        _write_section_files(self.section_dir)
        bank = recall.load_memory(self.master, self.section_dir)
        self.assertEqual(len(bank.experiences), 2)
        bak = self.tmp / "MEMORY.md.bak"
        self.assertFalse(bak.exists())

    def test_no_auto_migrate_for_curated_master(self):
        self.master.write_text(recall.CURATED_MASTER_TEMPLATE, encoding="utf-8")
        bank = recall.load_memory(self.master, self.section_dir)
        self.assertEqual(len(bank.experiences), 0)
        self.assertFalse(self.section_dir.exists())

    def test_second_load_uses_section_files(self):
        recall.load_memory(self.master, self.section_dir)
        bank2 = recall.load_memory(self.master, self.section_dir)
        self.assertEqual(len(bank2.experiences), 4)


class TestSkillConfigPath(unittest.TestCase):
    def test_user_skill_config_same_dir_as_memory(self):
        p = recall.resolve_user_skill_config_path()
        self.assertEqual(p.parent, recall.resolve_user_memory_path().parent)
        self.assertEqual(p.name, "memory-skill.config.json")


class TestSkillConfig(unittest.TestCase):
    def test_defaults_validate(self):
        cfg = manage.default_skill_config()
        vr = manage.validate_skill_config_structure(cfg)
        self.assertTrue(vr["valid"], vr["errors"])

    def test_merge_partial_actions_preserves_defaults(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(
            json.dumps({"actions": {"remember": "custom-direct-id"}}),
            encoding="utf-8",
        )
        cfg = manage.load_skill_config(p)
        self.assertEqual(cfg["actions"]["remember"], "custom-direct-id")
        self.assertEqual(cfg["actions"]["reflect"], "strong")

    def test_build_config_hints_direct_and_preset(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(
            json.dumps(
                {
                    "presets": {"p1": "flagship"},
                    "actions": {
                        "remember": "raw-mini-model",
                        "reflect": "p1",
                        "maintain": "p1",
                        "promote": "p1",
                    },
                }
            ),
            encoding="utf-8",
        )
        hints = manage.build_config_hints(p)
        self.assertNotIn("load_error", hints)
        self.assertTrue(hints["validation"]["valid"])
        self.assertIsNone(hints.get("host"))
        self.assertEqual(hints.get("hosts_defined"), [])
        self.assertEqual(hints["subagent_models"]["remember"]["via"], "direct")
        self.assertEqual(hints["subagent_models"]["remember"]["model_id"], "raw-mini-model")
        self.assertEqual(hints["subagent_models"]["reflect"]["model_id"], "flagship")
        self.assertEqual(
            hints["optional_escalation"]["remember_when_auto_reflect"]["model_id"],
            "reasoning",
        )

    def test_config_hints_empty_when_validation_fails(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(json.dumps({"version": 2}), encoding="utf-8")
        hints = manage.build_config_hints(p)
        self.assertFalse(hints["validation"]["valid"])
        self.assertEqual(hints["subagent_models"], {})
        self.assertEqual(hints["optional_escalation"], {})

    def test_validate_config_rejects_bad_version(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(json.dumps({"version": 2}), encoding="utf-8")
        out = manage.run_validate_config(p)
        self.assertFalse(out["valid"])
        self.assertTrue(any("version" in e for e in out["errors"]))

    def test_validate_config_rejects_invalid_json(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text("{not json", encoding="utf-8")
        out = manage.run_validate_config(p)
        self.assertFalse(out["valid"])
        self.assertTrue(any("JSON" in e for e in out["errors"]))

    def test_validate_config_unknown_action_key(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(
            json.dumps({"actions": {"remember": "fast", "bogus": "x"}}),
            encoding="utf-8",
        )
        out = manage.run_validate_config(p)
        self.assertFalse(out["valid"])
        self.assertTrue(any("bogus" in e for e in out["errors"]))

    def test_validate_structure_requires_all_actions(self):
        cfg = dict(manage.default_skill_config())
        del cfg["actions"]["promote"]
        vr = manage.validate_skill_config_structure(cfg)
        self.assertFalse(vr["valid"])
        self.assertTrue(any("missing required keys" in e for e in vr["errors"]))

    def test_validate_config_cli_nonzero_on_invalid_json(self):
        script = Path(manage.__file__).resolve()
        root = Path(tempfile.mkdtemp())
        bad = root / "x.json"
        bad.write_text("{not", encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(script),
                "--skill-config",
                str(bad),
                "validate-config",
            ],
            cwd=str(script.parent),
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 1)

    def test_init_user_seeds_skill_config_in_fresh_home(self):
        script = Path(manage.__file__).resolve()
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            r = subprocess.run(
                [sys.executable, str(script), "init-user"],
                cwd=str(script.parent),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            cfg_path = Path(td) / ".agents" / "memory" / "memory-skill.config.json"
            self.assertTrue(cfg_path.is_file())
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 1)
            self.assertEqual(set(data["actions"]), manage.SUBAGENT_ACTIONS)
            self.assertIn("hosts", data)
            self.assertEqual(data["hosts"], {})

    def test_config_hints_per_host_presets(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(
            json.dumps(
                {
                    "presets": {
                        "strong": "g-strong",
                        "balanced": "g-bal",
                        "fast": "g-fast",
                    },
                    "actions": {
                        "remember": "fast",
                        "reflect": "strong",
                        "maintain": "balanced",
                        "promote": "balanced",
                    },
                    "hosts": {
                        "codex": {
                            "presets": {"fast": "codex-light"},
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        g = manage.build_config_hints(p, host=None)
        self.assertTrue(g["validation"]["valid"])
        self.assertEqual(g["subagent_models"]["remember"]["model_id"], "g-fast")
        self.assertEqual(g["hosts_defined"], ["codex"])
        c = manage.build_config_hints(p, host="codex")
        self.assertEqual(c["host"], "codex")
        self.assertEqual(c["subagent_models"]["remember"]["model_id"], "codex-light")

    def test_validate_warns_unknown_host_key(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(
            json.dumps(
                {
                    "hosts": {
                        "vim": {"presets": {"strong": "x", "balanced": "y", "fast": "z"}},
                    },
                }
            ),
            encoding="utf-8",
        )
        cfg = manage.load_skill_config(p)
        vr = manage.validate_skill_config_structure(cfg)
        self.assertTrue(any("vim" in w for w in vr["warnings"]))


class TestHostInference(unittest.TestCase):
    """Host auto-detection (production); disabled for rest of suite via env."""

    def setUp(self):
        self._env_snapshot = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_snapshot)
        os.environ["MEMORY_SKILL_DISABLE_HOST_INFERENCE"] = "1"

    def test_infer_claude_from_claudecode(self):
        os.environ.pop("MEMORY_SKILL_DISABLE_HOST_INFERENCE", None)
        os.environ["CLAUDECODE"] = "1"
        host, src = manage.resolve_memory_host_meta(None)
        self.assertEqual(host, "claude")
        self.assertEqual(src, "inferred:CLAUDECODE")

    def test_infer_cursor_from_trace_id(self):
        os.environ.pop("MEMORY_SKILL_DISABLE_HOST_INFERENCE", None)
        os.environ["CURSOR_TRACE_ID"] = "abc"
        host, src = manage.resolve_memory_host_meta(None)
        self.assertEqual(host, "cursor")
        self.assertEqual(src, "inferred:CURSOR_TRACE_ID")

    def test_memory_skill_host_overrides_infer(self):
        os.environ.pop("MEMORY_SKILL_DISABLE_HOST_INFERENCE", None)
        os.environ["CLAUDECODE"] = "1"
        os.environ["MEMORY_SKILL_HOST"] = "codex"
        host, src = manage.resolve_memory_host_meta(None)
        self.assertEqual(host, "codex")
        self.assertEqual(src, "MEMORY_SKILL_HOST")

    def test_cli_host_overrides_env_and_infer(self):
        os.environ.pop("MEMORY_SKILL_DISABLE_HOST_INFERENCE", None)
        os.environ["CLAUDECODE"] = "1"
        os.environ["MEMORY_SKILL_HOST"] = "codex"
        host, src = manage.resolve_memory_host_meta("claude")
        self.assertEqual(host, "claude")
        self.assertEqual(src, "cli")

    def test_config_hints_includes_host_resolution(self):
        root = Path(tempfile.mkdtemp())
        p = root / "memory-skill.config.json"
        p.write_text(json.dumps(manage.default_skill_config()), encoding="utf-8")
        h = manage.build_config_hints(
            p, host="codex", host_resolution="cli"
        )
        self.assertEqual(h["host_resolution"], "cli")


if __name__ == "__main__":
    unittest.main()
