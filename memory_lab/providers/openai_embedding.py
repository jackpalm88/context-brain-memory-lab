"""
OpenAI EmbeddingBackend adapter — implements EmbeddingBackend.

Design constraints:
- Top-level module does NOT import `openai` -- safe to import when package absent.
- All `import openai` calls are deferred to _get_client().
- is_configured = True only if: openai importable AND OPENAI_API_KEY non-empty.
- Never raises outside the adapter boundary.
- No DB dependency.
- No consumer wiring.
"""
from __future__ import annotations

import logging
import os

from .failure import FailureCode
from .embedding_backend import (
    EmbeddingBackend,
    EmbeddingRequest,
    EmbeddingBatchRequest,
    EmbeddingResponse,
    EmbeddingBatchResponse,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 1536


class OpenAIEmbeddingBackend(EmbeddingBackend):
    """EmbeddingBackend adapter for the OpenAI embeddings API.

    Usage::

        backend = OpenAIEmbeddingBackend()
        resp = backend.embed_text(EmbeddingRequest(text="..."))
        if resp.degraded:
            # use fallback -- failure_reason indicates why
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def is_configured(self) -> bool:
        """True iff openai package importable AND OPENAI_API_KEY present."""
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        return bool(key)

    @property
    def vector_dimensions(self) -> int:
        return _DEFAULT_DIMENSIONS

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        """Return an OpenAI client, or (None, FailureCode) on any setup failure."""
        try:
            import openai as _openai
        except ImportError:
            return None, FailureCode.PROVIDER_IMPORT_MISSING
        key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not key:
            return None, FailureCode.MISSING_API_KEY
        try:
            return _openai.OpenAI(api_key=key), None
        except Exception as exc:
            logger.debug("[openai_embedding] client init error: %s", exc)
            return None, FailureCode.UNKNOWN_ERROR

    def _degraded_text(self, code: FailureCode) -> EmbeddingResponse:
        return EmbeddingResponse(
            vector=[],
            dimensions=0,
            provider=self.provider_name,
            degraded=True,
            failure_reason=code,
        )

    def _degraded_batch(self, code: FailureCode, n: int = 0, partial: bool = False) -> EmbeddingBatchResponse:
        return EmbeddingBatchResponse(
            vectors=[[] for _ in range(n)],
            dimensions=0,
            provider=self.provider_name,
            degraded=True,
            failure_reason=code,
            partial_failure=partial,
        )

    @staticmethod
    def _map_exception(exc: Exception) -> FailureCode:
        """Map an openai (or other) exception to a FailureCode."""
        cls_name = type(exc).__name__
        module = getattr(type(exc), "__module__", "") or ""

        if "openai" in module or cls_name.startswith("OpenAI"):
            if "RateLimitError" in cls_name:
                return FailureCode.RATE_LIMITED
            if "APITimeoutError" in cls_name or "Timeout" in cls_name:
                return FailureCode.TIMEOUT
            if "AuthenticationError" in cls_name:
                return FailureCode.MISSING_API_KEY
            if "APIStatusError" in cls_name or "APIConnectionError" in cls_name or "APIError" in cls_name:
                return FailureCode.PROVIDER_HTTP_ERROR
        return FailureCode.UNKNOWN_ERROR

    def _get_model(self) -> str:
        return (os.environ.get("OPENAI_EMBEDDING_MODEL") or _DEFAULT_MODEL).strip()

    # ------------------------------------------------------------------
    # EmbeddingBackend interface
    # ------------------------------------------------------------------

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed a single text string."""
        client, init_fail = self._get_client()
        if client is None:
            return self._degraded_text(init_fail)

        model = self._get_model()
        try:
            response = client.embeddings.create(model=model, input=request.text)
            vector = response.data[0].embedding
            if len(vector) != _DEFAULT_DIMENSIONS:
                logger.debug(
                    "[openai_embedding] dimension mismatch: got %d, expected %d",
                    len(vector), _DEFAULT_DIMENSIONS,
                )
                return self._degraded_text(FailureCode.DIMENSION_MISMATCH)
            return EmbeddingResponse(
                vector=vector,
                dimensions=len(vector),
                provider=self.provider_name,
                degraded=False,
            )
        except Exception as exc:
            code = self._map_exception(exc)
            logger.debug("[openai_embedding] embed_text failed (%s): %s", code, exc)
            return self._degraded_text(code)

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        """Embed a list of texts in one API call."""
        client, init_fail = self._get_client()
        if client is None:
            return self._degraded_batch(init_fail, n=len(request.texts))

        model = self._get_model()
        try:
            response = client.embeddings.create(model=model, input=request.texts)
            vectors = [item.embedding for item in response.data]

            # Check dimensions for each vector
            bad = [i for i, v in enumerate(vectors) if len(v) != _DEFAULT_DIMENSIONS]
            if bad:
                logger.debug("[openai_embedding] dimension mismatch on batch items: %s", bad)
                return self._degraded_batch(
                    FailureCode.DIMENSION_MISMATCH,
                    n=len(request.texts),
                    partial=True,
                )
            return EmbeddingBatchResponse(
                vectors=vectors,
                dimensions=_DEFAULT_DIMENSIONS,
                provider=self.provider_name,
                degraded=False,
                partial_failure=False,
            )
        except Exception as exc:
            code = self._map_exception(exc)
            logger.debug("[openai_embedding] embed_batch failed (%s): %s", code, exc)
            return self._degraded_batch(code, n=len(request.texts))
