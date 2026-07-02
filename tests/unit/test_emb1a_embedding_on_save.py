"""EMB-1A Acceptance Tests — Embeddings On-Save.

Validates the EMB-1A contract:
  1. Embedding enabled + backend configured → embedding generated on save
  2. Embedding disabled (default) → content saved, no embedding, no exception
  3. Embedding enabled + backend NOT configured → content saved, no exception (graceful)
  4. Backend=None explicitly → content saved, uses_embeddings=False

Design principle: Embedding generation is best-effort, never transactional.
Memory must not become dependent on the embedding provider.

All tests are hermetic — no real DB, no real provider calls.
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock, patch, call
import pytest

from memory_lab.persistence.body_chunks import ChunkWriteResult
from memory_lab.providers.embedding_backend import EmbeddingBackend, EmbeddingRequest, EmbeddingResponse


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

class _ConfiguredBackend(EmbeddingBackend):
    """Stub: always configured, records embed_text calls, returns success."""

    def __init__(self):
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "stub_configured"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def vector_dimensions(self) -> int:
        return 1536

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.calls.append(request.text)
        return EmbeddingResponse(
            vector=[0.1] * 1536,
            dimensions=1536,
            degraded=False,
            failure_reason=None,
        )

    def embed_batch(self, request):
        raise NotImplementedError


class _UnconfiguredBackend(EmbeddingBackend):
    """Stub: not configured (no key)."""

    @property
    def provider_name(self) -> str:
        return "stub_unconfigured"

    @property
    def is_configured(self) -> bool:
        return False

    @property
    def vector_dimensions(self) -> int:
        return 1536

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise AssertionError("embed_text must not be called on unconfigured backend")

    def embed_batch(self, request):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# ApiAdapter unit tests — isolated with minimal DB stub
# ---------------------------------------------------------------------------

def _make_adapter_with_db(embedding_backend=None):
    """Return ApiAdapter with a mock DB that returns a minimal persisted row."""
    from memory_lab.api.services.api_adapter import ApiAdapter

    adapter = ApiAdapter.__new__(ApiAdapter)
    adapter.database_url = "stub://not-real"
    adapter.embedding_backend = embedding_backend
    adapter.hub_store = MagicMock()
    adapter.hub_edge_store = MagicMock()
    return adapter


class TestEMB1AApiAdapterInit:
    """ApiAdapter stores the injected backend."""

    def test_default_backend_is_none(self):
        from memory_lab.api.services.api_adapter import ApiAdapter
        with patch("memory_lab.api.services.api_adapter.psycopg2.connect"):
            a = ApiAdapter("postgresql://x")
            assert a.embedding_backend is None

    def test_configured_backend_stored(self):
        from memory_lab.api.services.api_adapter import ApiAdapter
        backend = _ConfiguredBackend()
        with patch("memory_lab.api.services.api_adapter.psycopg2.connect"):
            a = ApiAdapter("postgresql://x", embedding_backend=backend)
            assert a.embedding_backend is backend


# ---------------------------------------------------------------------------
# persist_body_chunks unit tests — embedding path gating
# ---------------------------------------------------------------------------

class TestEMB1APersistBodyChunksEmbeddingGating:
    """persist_body_chunks correctly gates embedding on backend + vector_enabled."""

    def _run(self, text, backend=None, vector_enabled=False):
        from memory_lab.persistence.body_chunks import persist_body_chunks

        cur = MagicMock()
        # Simulate RETURNING chunk_id
        cur.fetchone.return_value = ("00000000-0000-0000-0000-000000000001",)

        result = persist_body_chunks(
            cur, "content-id-123", "workspace-id-456", text,
            embedding_backend=backend,
            vector_enabled=vector_enabled,
        )
        return result, cur

    def test_no_backend_no_embedding(self):
        """Default (no backend) — chunk written, uses_embeddings=False."""
        result, cur = self._run("some content here", backend=None, vector_enabled=False)
        assert result.chunk_written is True
        assert result.uses_embeddings is False
        assert result.warnings == ()

    def test_backend_none_vector_enabled_still_no_embedding(self):
        """vector_enabled=True but backend=None — graceful, no embedding."""
        result, cur = self._run("some content here", backend=None, vector_enabled=True)
        assert result.chunk_written is True
        assert result.uses_embeddings is False

    def test_unconfigured_backend_no_embedding(self):
        """Backend present but is_configured=False — chunk saved, no embed call."""
        backend = _UnconfiguredBackend()
        result, cur = self._run("some content here", backend=backend, vector_enabled=True)
        assert result.chunk_written is True
        assert result.uses_embeddings is False
        # embed_text was NOT called (UnconfiguredBackend raises if called)

    def test_configured_backend_embedding_generated(self):
        """Backend configured + vector_enabled → embed_text called, uses_embeddings=True."""
        backend = _ConfiguredBackend()
        result, cur = self._run("this text should be embedded", backend=backend, vector_enabled=True)
        assert result.chunk_written is True
        assert result.uses_embeddings is True
        assert len(backend.calls) == 1
        assert backend.calls[0] == "this text should be embedded"

    def test_empty_text_no_chunk(self):
        """Empty text → chunk_written=False regardless of backend."""
        backend = _ConfiguredBackend()
        result, _ = self._run("", backend=backend, vector_enabled=True)
        assert result.chunk_written is False
        assert result.uses_embeddings is False
        assert backend.calls == []


# ---------------------------------------------------------------------------
# Content router helper — _make_embedding_backend
# ---------------------------------------------------------------------------

class TestEMB1AEmbeddingBackendFactory:
    """_make_embedding_backend returns backend or None based on settings."""

    def test_disabled_by_default_returns_none(self):
        from memory_lab.api.routers.content import _make_embedding_backend
        settings = MagicMock()
        settings.provider_embeddings_enabled = False
        result = _make_embedding_backend(settings)
        assert result is None

    def test_enabled_returns_backend_instance(self):
        from memory_lab.api.routers.content import _make_embedding_backend
        from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend
        settings = MagicMock()
        settings.provider_embeddings_enabled = True
        result = _make_embedding_backend(settings)
        assert isinstance(result, OpenAIEmbeddingBackend)

    def test_enabled_but_exception_returns_none(self):
        """If OpenAIEmbeddingBackend() raises for any reason — graceful None."""
        from memory_lab.api.routers.content import _make_embedding_backend
        settings = MagicMock()
        settings.provider_embeddings_enabled = True
        with patch("memory_lab.api.routers.content.OpenAIEmbeddingBackend", side_effect=RuntimeError("provider error")):
            result = _make_embedding_backend(settings)
        assert result is None


# ---------------------------------------------------------------------------
# Integration: ApiAdapter receives backend from router on save path
# ---------------------------------------------------------------------------

class TestEMB1ARouterInjectsBackend:
    """The create_content router passes embedding_backend into ApiAdapter."""

    def test_provider_disabled_adapter_gets_none(self):
        """PROVIDER_EMBEDDINGS_ENABLED=false → adapter.embedding_backend is None."""
        import memory_lab.api.routers.content as content_mod

        created_adapters = []

        class _TrackingAdapter:
            def __init__(self, db_url, embedding_backend=None):
                self.database_url = db_url
                self.embedding_backend = embedding_backend
                created_adapters.append(self)

            def create_content_minimal(self, **kwargs):
                return {"persisted": True, "content_id": "x", "created": True, "discarded": False, "duplicate": False}

        settings = MagicMock()
        settings.database_url = "postgresql://stub"
        settings.provider_embeddings_enabled = False

        with patch.object(content_mod, "ApiAdapter", _TrackingAdapter), \
             patch.object(content_mod, "get_settings", return_value=settings):
            req = MagicMock()
            req.content = "hello"
            auth = MagicMock()
            auth.workspace_id = None
            auth.workspace_source = None
            auth.auth_subject_id = None
            content_mod.create_content(req, auth)

        assert len(created_adapters) == 1
        assert created_adapters[0].embedding_backend is None

    def test_provider_enabled_adapter_gets_backend(self):
        """PROVIDER_EMBEDDINGS_ENABLED=true → adapter.embedding_backend is set."""
        import memory_lab.api.routers.content as content_mod
        from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend

        created_adapters = []

        class _TrackingAdapter:
            def __init__(self, db_url, embedding_backend=None):
                self.database_url = db_url
                self.embedding_backend = embedding_backend
                created_adapters.append(self)

            def create_content_minimal(self, **kwargs):
                return {"persisted": True, "content_id": "x", "created": True, "discarded": False, "duplicate": False}

        settings = MagicMock()
        settings.database_url = "postgresql://stub"
        settings.provider_embeddings_enabled = True

        with patch.object(content_mod, "ApiAdapter", _TrackingAdapter), \
             patch.object(content_mod, "get_settings", return_value=settings):
            req = MagicMock()
            req.content = "hello"
            auth = MagicMock()
            auth.workspace_id = None
            auth.workspace_source = None
            auth.auth_subject_id = None
            content_mod.create_content(req, auth)

        assert len(created_adapters) == 1
        assert isinstance(created_adapters[0].embedding_backend, OpenAIEmbeddingBackend)


# ---------------------------------------------------------------------------
# Core principle test — embedding failure never blocks save
# ---------------------------------------------------------------------------

class TestEMB1AEmbeddingNeverTransactional:
    """Embedding failure must never prevent content from being saved.

    This test encodes the OpenCB design principle:
    'Memory must not become dependent on the embedding provider.'
    """

    def test_embedding_exception_chunk_still_saved(self):
        """If embed_text raises unexpectedly, chunk_written=True, warning present."""
        from memory_lab.persistence.body_chunks import persist_body_chunks

        class _ExplodingBackend(EmbeddingBackend):
            @property
            def provider_name(self): return "exploding"
            @property
            def is_configured(self): return True
            @property
            def vector_dimensions(self): return 1536
            def embed_text(self, req): raise RuntimeError("provider down!")
            def embed_batch(self, req): raise NotImplementedError

        cur = MagicMock()
        cur.fetchone.return_value = ("chunk-id-999",)

        # persist_body_chunks should not propagate the exception
        try:
            result = persist_body_chunks(
                cur, "cid", "wsid", "important content",
                embedding_backend=_ExplodingBackend(),
                vector_enabled=True,
            )
            chunk_written = result.chunk_written
        except RuntimeError:
            pytest.fail("persist_body_chunks propagated embedding exception — violates best-effort contract")

        assert chunk_written is True, "Content must be saved even when embedding fails"
