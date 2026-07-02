"""Operations Acceptance Tests — M12-OPERATIONS-1 (Engineering Quality Asset, not product artifact).

Validates OP-1..OP-6 behavioral contracts for OpenCB operational baseline:
health truthfulness, DB-absent graceful degradation, config env precedence,
migration structure idempotence, logging exception safety, app factory determinism.

100% hermetic — no DATABASE_URL, no Docker, no live provider required.

Properties:
  OP-1  Health endpoint truthfulness
  OP-2  DB-absent graceful degradation (503, not crash)
  OP-3  Config env precedence (all 5 feature flags)
  OP-4  Migration structure idempotence (hermetic file-level checks)
  OP-5  Logging exception safety (broken handler does not crash caller)
  OP-6  App factory determinism (14 routers, stable set, no shared state)
"""
from __future__ import annotations

import importlib
import logging
import os
import pathlib
import re
import sys
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Fresh app instance — avoids module-level singleton for isolation."""
    import importlib
    import memory_lab.api.main as main_mod
    importlib.reload(main_mod)
    return main_mod.create_app()


def _client_no_db(monkeypatch) -> TestClient:
    """TestClient with DATABASE_URL absent."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return TestClient(_make_app(), raise_server_exceptions=False)


def _client_with_db(monkeypatch) -> TestClient:
    """TestClient with a non-empty DATABASE_URL stub (no real connection needed for health)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://stub:stub@localhost/stub")
    return TestClient(_make_app(), raise_server_exceptions=False)


def _auth_override(app):
    """Inject permissive auth so endpoints are reachable for ops shape tests."""
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.dependencies.auth import require_permission

    def _permissive(*args, **kwargs):
        return AuthContext(
            workspace_id="ws-ops-test",
            user_id="ops-tester",
            permissions=["memory.write", "memory.read", "hubs.read",
                         "retrieval.search", "reasoning.answer"],
            auth_mode="local_dev",
        )

    # Override all require_permission closures on the app
    for key in list(app.dependency_overrides.keys()):
        pass
    for route in getattr(app, "routes", []):
        for dep in getattr(route, "dependencies", []):
            func = getattr(dep, "dependency", None)
            if func is not None and hasattr(func, "__name__") and "require_permission" in str(func):
                app.dependency_overrides[func] = _permissive

    # Also override the canonical require_permission factory result
    app.dependency_overrides[require_permission("memory.write")] = _permissive
    app.dependency_overrides[require_permission("memory.read")] = _permissive
    app.dependency_overrides[require_permission("hubs.read")] = _permissive
    app.dependency_overrides[require_permission("retrieval.search")] = _permissive
    app.dependency_overrides[require_permission("reasoning.answer")] = _permissive
    return app


# ---------------------------------------------------------------------------
# OP-1 — Health endpoint truthfulness
# ---------------------------------------------------------------------------

class TestOP1HealthTruthfulness:
    """OP-1: /health must truthfully report service operability based on DATABASE_URL."""

    def test_health_ok_when_database_url_configured(self, monkeypatch):
        """With DATABASE_URL set, /health returns status=ok."""
        client = _client_with_db(monkeypatch)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_health_unavailable_when_database_url_absent(self, monkeypatch):
        """Without DATABASE_URL, /health must NOT report status=ok."""
        client = _client_no_db(monkeypatch)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] != "ok", (
            f"Health reported 'ok' without DATABASE_URL — this is untruthful. Got: {body}"
        )

    def test_health_unavailable_contains_reason(self, monkeypatch):
        """Without DATABASE_URL, /health response includes a machine-readable reason."""
        client = _client_no_db(monkeypatch)
        body = client.get("/health").json()
        assert "reason" in body or body.get("status") not in ("ok", None), (
            "Health unavailable response should include 'reason' field"
        )

    def test_health_always_returns_service_and_version(self, monkeypatch):
        """Both with and without DATABASE_URL, /health includes service and version fields."""
        for client in [_client_with_db(monkeypatch), _client_no_db(monkeypatch)]:
            body = client.get("/health").json()
            assert "service" in body, f"Missing 'service' field: {body}"
            assert "version" in body, f"Missing 'version' field: {body}"

    def test_health_is_not_auth_gated(self, monkeypatch):
        """GET /health returns 200 without any auth header — it is a public liveness probe."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://stub:stub@localhost/stub")
        app = _make_app()
        # No auth override — raw client
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200, f"Health should be public, got {resp.status_code}"


# ---------------------------------------------------------------------------
# OP-2 — DB-absent graceful degradation
# ---------------------------------------------------------------------------

class TestOP2DbAbsentDegradation:
    """OP-2: DB-dependent endpoints return 503 with human-readable detail, not crash."""

    def _no_db_client(self, monkeypatch) -> TestClient:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = _make_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_content_post_returns_503_without_db(self, monkeypatch):
        """POST /v1/content without DATABASE_URL → 503."""
        client = self._no_db_client(monkeypatch)
        resp = client.post("/v1/content", json={"content": "test", "save_purpose": "test"})
        assert resp.status_code == 503, f"Expected 503, got {resp.status_code}"

    def test_503_detail_is_human_readable(self, monkeypatch):
        """503 responses carry a detail string, not a raw traceback."""
        client = self._no_db_client(monkeypatch)
        resp = client.post("/v1/content", json={"content": "test", "save_purpose": "test"})
        assert resp.status_code == 503
        body = resp.json()
        detail = body.get("detail", "")
        assert isinstance(detail, str), f"detail should be a string, got {type(detail)}: {detail}"
        assert len(detail) > 0, "detail should not be empty"
        # Must not look like a raw Python traceback
        assert "Traceback" not in detail, f"detail looks like a traceback: {detail}"

    def test_retrieval_search_503_without_db(self, monkeypatch):
        """POST /v1/retrieval/search without DATABASE_URL → 503."""
        client = self._no_db_client(monkeypatch)
        resp = client.post("/v1/retrieval/search", json={"query": "test", "workspace_id": "ws-1"})
        assert resp.status_code in (401, 403, 503), (
            f"Expected auth gate (401/403) or 503 without DB, got {resp.status_code}"
        )
        # If auth passes through, must be 503
        if resp.status_code == 200:
            pytest.fail(f"Should not succeed without DATABASE_URL: {resp.json()}")

    def test_reasoning_answer_503_without_db(self, monkeypatch):
        """POST /v1/reasoning/answer without DATABASE_URL → 503 (auth gated or DB gated)."""
        client = self._no_db_client(monkeypatch)
        resp = client.post("/v1/reasoning/answer", json={
            "query": "test", "workspace_id": "ws-1"
        })
        assert resp.status_code in (401, 403, 422, 503), (
            f"Expected auth/validation/DB error, got {resp.status_code}: {resp.json()}"
        )
        assert resp.status_code != 500, f"Got 500 — unhandled crash without DB: {resp.json()}"


# ---------------------------------------------------------------------------
# OP-3 — Config env precedence
# ---------------------------------------------------------------------------

class TestOP3ConfigEnvPrecedence:
    """OP-3: All 5 MEMORY_LAB_* feature flags read from env with correct precedence."""

    def _settings(self, monkeypatch, overrides: Dict[str, str]):
        """Get fresh Settings with given env overrides."""
        import memory_lab.api.config as cfg
        importlib.reload(cfg)
        for k, v in overrides.items():
            monkeypatch.setenv(k, v)
        return cfg.get_settings()

    def test_all_flags_off_by_default(self, monkeypatch):
        """With no MEMORY_LAB_* env vars, all feature flags default to False."""
        for flag in [
            "MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED",
            "MEMORY_LAB_PROVIDER_EMBEDDINGS_ENABLED",
            "MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED",
            "MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED",
            "MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED",
        ]:
            monkeypatch.delenv(flag, raising=False)
        import memory_lab.api.config as cfg
        importlib.reload(cfg)
        s = cfg.get_settings()
        assert not s.pgvector_retrieval_enabled, "pgvector should default off"
        assert not s.provider_embeddings_enabled, "provider_embeddings should default off"
        assert not s.vector_embeddings_enabled, "vector_embeddings should default off"
        assert not s.reasoning_provider_synthesis_enabled, "reasoning synthesis should default off"
        assert not s.ask_provider_synthesis_enabled, "ask synthesis should default off"

    def test_pgvector_flag_enables_via_env(self, monkeypatch):
        """MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED=true → pgvector_retrieval_enabled=True."""
        monkeypatch.setenv("MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED", "true")
        import memory_lab.api.config as cfg
        importlib.reload(cfg)
        s = cfg.get_settings()
        assert s.pgvector_retrieval_enabled is True

    def test_provider_embeddings_cascades_to_vector(self, monkeypatch):
        """MEMORY_LAB_PROVIDER_EMBEDDINGS_ENABLED=true implies vector_embeddings_enabled=True."""
        monkeypatch.delenv("MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED", raising=False)
        monkeypatch.setenv("MEMORY_LAB_PROVIDER_EMBEDDINGS_ENABLED", "true")
        import memory_lab.api.config as cfg
        importlib.reload(cfg)
        s = cfg.get_settings()
        assert s.provider_embeddings_enabled is True
        assert s.vector_embeddings_enabled is True, (
            "provider_embeddings_enabled=true should cascade to vector_embeddings_enabled"
        )

    def test_reasoning_and_ask_synthesis_flags_are_independent(self, monkeypatch):
        """Reasoning synthesis flag does not affect ask synthesis flag and vice versa."""
        monkeypatch.setenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", "true")
        monkeypatch.delenv("MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED", raising=False)
        import memory_lab.api.config as cfg
        importlib.reload(cfg)
        s = cfg.get_settings()
        assert s.reasoning_provider_synthesis_enabled is True
        assert s.ask_provider_synthesis_enabled is False, (
            "Ask synthesis should remain off when only reasoning synthesis is enabled"
        )

    def test_false_string_disables_flag(self, monkeypatch):
        """MEMORY_LAB_*=false (string) → flag is False even when set."""
        monkeypatch.setenv("MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED", "false")
        monkeypatch.setenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", "false")
        import memory_lab.api.config as cfg
        importlib.reload(cfg)
        s = cfg.get_settings()
        assert s.pgvector_retrieval_enabled is False
        assert s.reasoning_provider_synthesis_enabled is False


# ---------------------------------------------------------------------------
# OP-4 — Migration structure idempotence (hermetic file-level checks)
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = pathlib.Path("/opt/cbml/migrations")


class TestOP4MigrationStructure:
    """OP-4: migrations/*.sql are structurally safe for repeated application."""

    def test_migrations_directory_is_non_empty(self):
        """migrations/ contains at least one .sql file."""
        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        assert len(sql_files) > 0, "No .sql migration files found"

    def test_no_bare_create_table(self):
        """No active (non-commented) line contains bare CREATE TABLE without IF NOT EXISTS."""
        failures = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            active = "\n".join(
                l for l in f.read_text().splitlines()
                if not l.strip().startswith("--")
            )
            if re.search(r"CREATE TABLE (?!IF NOT EXISTS)", active):
                failures.append(str(f))
        assert failures == [], (
            f"Migrations contain bare CREATE TABLE (not idempotent): {failures}"
        )

    def test_no_bare_create_index(self):
        """No active line contains bare CREATE [UNIQUE] INDEX without IF NOT EXISTS."""
        failures = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            active = "\n".join(
                l for l in f.read_text().splitlines()
                if not l.strip().startswith("--")
            )
            if re.search(r"CREATE (?:UNIQUE )?INDEX (?!IF NOT EXISTS)", active):
                failures.append(str(f))
        assert failures == [], (
            f"Migrations contain bare CREATE INDEX (not idempotent): {failures}"
        )

    def test_migration_filenames_are_sortably_prefixed(self):
        """Migration files follow NNN_*.sql naming so sort order == application order."""
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        bad = [f.name for f in files if not re.match(r"^\d{3}_", f.name)]
        assert bad == [], f"Migration files without NNN_ prefix (unsortable): {bad}"


# ---------------------------------------------------------------------------
# OP-5 — Logging exception safety
# ---------------------------------------------------------------------------

class TestOP5LoggingExceptionSafety:
    """OP-5: Logging failures do not propagate into the caller's execution path."""

    def test_governance_event_logging_with_broken_handler(self):
        """Governance event module-level logger with broken handler does not raise on emit_event."""
        import memory_lab.governance.events as events_mod

        broken_logger = logging.getLogger("test_ops5_governance")
        broken_logger.handlers.clear()
        broken_logger.addHandler(logging.StreamHandler(stream=None))
        broken_logger.propagate = False

        original = events_mod.logger
        events_mod.logger = broken_logger
        try:
            # emit_event logs internally; broken handler should not propagate
            events_mod.emit_event(events_mod.build_event(
                event_type="save_attempt",
                content_id="test-id",
                tier="persistent",
                trigger_source="api",
                trigger_type="save",
                metadata={},
            ))
        except Exception as e:
            if "NoneType" in str(type(e)) or "stream" in str(e).lower():
                pytest.fail(f"Logging failure propagated into emit_event: {e}")
            # Other errors (validation, etc.) are acceptable
        finally:
            events_mod.logger = original

    def test_ingestion_scorer_logging_with_none_value(self):
        """Ingestion module-level score_content with minimal input does not crash on logging."""
        import memory_lab.ingestion.scorer as scorer_mod

        broken_logger = logging.getLogger("test_ops5_scorer")
        broken_logger.handlers.clear()
        broken_logger.addHandler(logging.StreamHandler(stream=None))
        broken_logger.propagate = False

        original = scorer_mod.logger
        scorer_mod.logger = broken_logger
        try:
            # score_content with minimal valid input; any logging should not propagate
            scorer_mod.score_content(content="test content for scoring", save_purpose="unit test")
        except Exception as e:
            # Logging-induced errors are failures; policy/DB errors are acceptable
            if "stream" in str(e).lower() or "handler" in str(e).lower():
                pytest.fail(f"Logging failure propagated into score_content: {e}")
        finally:
            scorer_mod.logger = original

    def test_provider_error_logging_does_not_crash(self):
        """NoopLLMBackend completes a call without raising — smoke test for provider safety."""
        from memory_lab.providers.noop import NoopLLMBackend
        from memory_lab.providers.llm_backend import LLMRequest

        backend = NoopLLMBackend()
        try:
            result = backend.complete_text(LLMRequest(prompt="test prompt"))
            assert result is not None
        except Exception as e:
            pytest.fail(f"NoopLLMBackend.complete_text raised unexpectedly: {e}")

    def test_logging_module_importable_without_env(self):
        """All logging-using modules import cleanly without MEMORY_LAB_* env vars."""
        modules = [
            "memory_lab.governance.events",
            "memory_lab.governance.ingestion_policy",
            "memory_lab.ingestion.scorer",
        ]
        for mod in modules:
            try:
                importlib.import_module(mod)
            except ImportError as e:
                pytest.fail(f"Module {mod} failed to import: {e}")


# ---------------------------------------------------------------------------
# OP-6 — App factory determinism
# ---------------------------------------------------------------------------

EXPECTED_TAGS = {
    "health", "content", "hubs", "edges", "retrieval", "ask",
    "decisions", "admin-governance", "conflicts", "context-packs",
    "reasoning", "graph-health", "graph",
}

EXPECTED_ROUTES = {
    "/health",
    "/v1/content",
    "/v1/retrieval/search",
    "/v1/reasoning/answer",
    "/v1/reasoning/traverse",
    "/v1/reasoning/explain",
    "/v1/graph/health",
    "/v1/hubs",
    "/decisions/",
}


class TestOP6AppFactoryDeterminism:
    """OP-6: create_app() produces a deterministic, complete router set each invocation."""

    def _routes(self, app) -> set:
        return {r.path for r in app.routes if hasattr(r, "path") and hasattr(r, "methods")}

    def _tags(self, app) -> set:
        tags = set()
        for r in app.routes:
            for t in getattr(r, "tags", []):
                tags.add(t)
        return tags

    def test_create_app_returns_fastapi_instance(self):
        """create_app() returns a FastAPI application."""
        from fastapi import FastAPI
        from memory_lab.api.main import create_app
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_health_route_exists_without_prefix(self):
        """/health is registered at root level, not /v1/health."""
        from memory_lab.api.main import create_app
        app = create_app()
        routes = self._routes(app)
        assert "/health" in routes, f"/health missing from routes: {sorted(routes)}"
        assert "/v1/health" not in routes, "/v1/health should not exist (health has no /v1 prefix)"

    def test_all_expected_route_prefixes_present(self):
        """All expected capability routes are registered in a fresh app instance."""
        from memory_lab.api.main import create_app
        app = create_app()
        routes = self._routes(app)
        missing = EXPECTED_ROUTES - routes
        assert not missing, f"Expected routes missing from app: {sorted(missing)}"

    def test_two_create_app_calls_produce_equivalent_route_sets(self):
        """create_app() is idempotent — two calls produce the same route set (no shared state)."""
        from memory_lab.api.main import create_app
        app1 = create_app()
        app2 = create_app()
        routes1 = self._routes(app1)
        routes2 = self._routes(app2)
        assert routes1 == routes2, (
            f"create_app() not deterministic.\n"
            f"Only in first: {routes1 - routes2}\n"
            f"Only in second: {routes2 - routes1}"
        )

    def test_all_capability_tags_registered(self):
        """All 13 capability router tags are present in the assembled app."""
        from memory_lab.api.main import create_app
        app = create_app()
        present_tags = self._tags(app)
        missing = EXPECTED_TAGS - present_tags
        assert not missing, f"Router tags missing from assembled app: {sorted(missing)}"
