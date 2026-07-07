"""
test_openai_embedding_adapter.py

Focused mocked unit tests for OpenAIEmbeddingBackend.
No live OpenAI calls. No real API keys.
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to inject/remove a fake openai module
# ---------------------------------------------------------------------------

def _make_fake_openai(vectors_per_call=None, raise_exc=None):
    """Return a fake openai module whose OpenAI().embeddings.create(...) is mocked."""
    fake = types.ModuleType("openai")

    def make_response(texts_or_text):
        if isinstance(texts_or_text, str):
            texts = [texts_or_text]
        else:
            texts = texts_or_text
        items = []
        for i, _ in enumerate(texts):
            item = MagicMock()
            item.embedding = vectors_per_call[i] if vectors_per_call else [0.1] * 1536
            items.append(item)
        resp = MagicMock()
        resp.data = items
        return resp

    def create_fn(model, input, **kwargs):
        if raise_exc:
            raise raise_exc
        return make_response(input)

    client_instance = MagicMock()
    client_instance.embeddings.create.side_effect = create_fn

    fake.OpenAI = MagicMock(return_value=client_instance)

    # Typical error classes
    fake.RateLimitError = type("RateLimitError", (Exception,), {"__module__": "openai"})
    fake.APITimeoutError = type("APITimeoutError", (Exception,), {"__module__": "openai"})
    fake.AuthenticationError = type("AuthenticationError", (Exception,), {"__module__": "openai"})
    fake.APIStatusError = type("APIStatusError", (Exception,), {"__module__": "openai"})
    fake.APIConnectionError = type("APIConnectionError", (Exception,), {"__module__": "openai"})

    return fake


def _inject_openai(module):
    sys.modules["openai"] = module


def _remove_openai():
    sys.modules.pop("openai", None)


def _get_backend():
    """Import fresh backend after sys.modules manipulation."""
    # Remove cached module so deferred import picks up current sys.modules state
    sys.modules.pop("memory_lab.providers.openai_embedding", None)
    from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend
    return OpenAIEmbeddingBackend()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOpenAIEmbeddingAdapter(unittest.TestCase):

    def setUp(self):
        # Ensure clean env
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("OPENAI_EMBEDDING_MODEL", None)
        # Save the process-wide module objects so tearDown can RESTORE identity:
        # leaving the adapter module popped makes later imports mint a NEW
        # OpenAIEmbeddingBackend class while earlier importers (the content
        # router) keep the old one — isinstance checks then fail suite-wide.
        self._saved_openai = sys.modules.get("openai")
        self._saved_adapter = sys.modules.get("memory_lab.providers.openai_embedding")
        _remove_openai()
        # Re-remove cached adapter module
        sys.modules.pop("memory_lab.providers.openai_embedding", None)

    def tearDown(self):
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("OPENAI_EMBEDDING_MODEL", None)
        _remove_openai()
        sys.modules.pop("memory_lab.providers.openai_embedding", None)
        if self._saved_openai is not None:
            sys.modules["openai"] = self._saved_openai
        if self._saved_adapter is not None:
            sys.modules["memory_lab.providers.openai_embedding"] = self._saved_adapter

    # -----------------------------------------------------------------------
    # Identity / configuration
    # -----------------------------------------------------------------------

    def test_provider_name(self):
        _inject_openai(_make_fake_openai())
        b = _get_backend()
        self.assertEqual(b.provider_name, "openai")

    def test_vector_dimensions_property(self):
        _inject_openai(_make_fake_openai())
        b = _get_backend()
        self.assertEqual(b.vector_dimensions, 1536)

    def test_is_configured_false_no_key(self):
        _inject_openai(_make_fake_openai())
        b = _get_backend()
        # No OPENAI_API_KEY in env
        self.assertFalse(b.is_configured)

    def test_is_configured_true_with_key(self):
        _inject_openai(_make_fake_openai())
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        self.assertTrue(b.is_configured)

    def test_is_configured_false_no_package(self):
        _remove_openai()
        # Make import fail by removing from sys.modules and not injecting
        sys.modules["openai"] = None  # sentinel that causes ImportError on 'import openai'
        try:
            b = _get_backend()
            self.assertFalse(b.is_configured)
        finally:
            sys.modules.pop("openai", None)

    # -----------------------------------------------------------------------
    # embed_text: degraded paths
    # -----------------------------------------------------------------------

    def test_no_key_embed_text_returns_degraded(self):
        _inject_openai(_make_fake_openai())
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingRequest
        from memory_lab.providers.failure import FailureCode
        resp = b.embed_text(EmbeddingRequest(text="hello"))
        self.assertTrue(resp.degraded)
        self.assertEqual(resp.failure_reason, FailureCode.MISSING_API_KEY)
        self.assertEqual(resp.vector, [])

    def test_import_missing_embed_text_returns_degraded(self):
        sys.modules["openai"] = None
        try:
            b = _get_backend()
            from memory_lab.providers.embedding_backend import EmbeddingRequest
            from memory_lab.providers.failure import FailureCode
            resp = b.embed_text(EmbeddingRequest(text="hello"))
            self.assertTrue(resp.degraded)
            self.assertEqual(resp.failure_reason, FailureCode.PROVIDER_IMPORT_MISSING)
            self.assertEqual(resp.vector, [])
        finally:
            sys.modules.pop("openai", None)

    def test_embed_text_dimension_mismatch(self):
        bad_vec = [0.5] * 768  # wrong dims
        _inject_openai(_make_fake_openai(vectors_per_call=[bad_vec]))
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingRequest
        from memory_lab.providers.failure import FailureCode
        resp = b.embed_text(EmbeddingRequest(text="hello"))
        self.assertTrue(resp.degraded)
        self.assertEqual(resp.failure_reason, FailureCode.DIMENSION_MISMATCH)

    # -----------------------------------------------------------------------
    # embed_text: success
    # -----------------------------------------------------------------------

    def test_embed_text_success_1536(self):
        _inject_openai(_make_fake_openai())
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingRequest
        resp = b.embed_text(EmbeddingRequest(text="hello"))
        self.assertFalse(resp.degraded)
        self.assertEqual(len(resp.vector), 1536)
        self.assertEqual(resp.dimensions, 1536)
        self.assertEqual(resp.provider, "openai")

    # -----------------------------------------------------------------------
    # embed_batch
    # -----------------------------------------------------------------------

    def test_embed_batch_degraded_no_key(self):
        _inject_openai(_make_fake_openai())
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingBatchRequest
        from memory_lab.providers.failure import FailureCode
        resp = b.embed_batch(EmbeddingBatchRequest(texts=["a", "b"]))
        self.assertTrue(resp.degraded)
        self.assertEqual(resp.failure_reason, FailureCode.MISSING_API_KEY)
        self.assertEqual(len(resp.vectors), 2)

    def test_embed_batch_success(self):
        vecs = [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]
        _inject_openai(_make_fake_openai(vectors_per_call=vecs))
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingBatchRequest
        resp = b.embed_batch(EmbeddingBatchRequest(texts=["a", "b", "c"]))
        self.assertFalse(resp.degraded)
        self.assertEqual(len(resp.vectors), 3)
        self.assertEqual(resp.dimensions, 1536)
        self.assertEqual(resp.provider, "openai")

    # -----------------------------------------------------------------------
    # Exception / error mapping
    # -----------------------------------------------------------------------

    def test_rate_limit_maps_correctly(self):
        fake = _make_fake_openai()
        exc = fake.RateLimitError("rate limit")
        _inject_openai(_make_fake_openai(raise_exc=exc))
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingRequest
        from memory_lab.providers.failure import FailureCode
        resp = b.embed_text(EmbeddingRequest(text="hello"))
        self.assertTrue(resp.degraded)
        self.assertEqual(resp.failure_reason, FailureCode.RATE_LIMITED)

    def test_timeout_maps_correctly(self):
        fake = _make_fake_openai()
        exc = fake.APITimeoutError("timeout")
        _inject_openai(_make_fake_openai(raise_exc=exc))
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingRequest
        from memory_lab.providers.failure import FailureCode
        resp = b.embed_text(EmbeddingRequest(text="hello"))
        self.assertTrue(resp.degraded)
        self.assertEqual(resp.failure_reason, FailureCode.TIMEOUT)

    def test_provider_http_error_maps_correctly(self):
        fake = _make_fake_openai()
        exc = fake.APIStatusError("500")
        _inject_openai(_make_fake_openai(raise_exc=exc))
        os.environ["OPENAI_API_KEY"] = "sk-test-fake"
        b = _get_backend()
        from memory_lab.providers.embedding_backend import EmbeddingRequest
        from memory_lab.providers.failure import FailureCode
        resp = b.embed_text(EmbeddingRequest(text="hello"))
        self.assertTrue(resp.degraded)
        self.assertEqual(resp.failure_reason, FailureCode.PROVIDER_HTTP_ERROR)

    # -----------------------------------------------------------------------
    # Top-level import safety
    # -----------------------------------------------------------------------

    def test_no_top_level_import_side_effect(self):
        """Module must be importable even when openai is absent."""
        sys.modules.pop("memory_lab.providers.openai_embedding", None)
        _remove_openai()
        # Should not raise
        try:
            from memory_lab.providers import openai_embedding  # noqa: F401
        except ImportError as e:
            self.fail(f"Importing openai_embedding raised ImportError: {e}")


if __name__ == "__main__":
    unittest.main()
