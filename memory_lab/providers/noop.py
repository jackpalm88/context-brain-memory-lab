from .failure import FailureCode
from .llm_backend import LLMBackend, LLMRequest, LLMResponse
from .embedding_backend import (
    EmbeddingBackend, EmbeddingRequest, EmbeddingBatchRequest,
    EmbeddingResponse, EmbeddingBatchResponse,
)


class NoopLLMBackend(LLMBackend):
    """LLM stub for LLM_PROVIDER=none.
    All methods: degraded=True, failure_reason=NOT_CONFIGURED.
    No network. No fake semantic content. Never raises."""

    @property
    def provider_name(self) -> str:
        return "none"

    @property
    def is_configured(self) -> bool:
        return False

    def _nc(self) -> LLMResponse:
        return LLMResponse(
            degraded=True,
            failure_reason=FailureCode.NOT_CONFIGURED,
            provider="none",
        )

    def complete_text(self, request: LLMRequest) -> LLMResponse:
        return self._nc()

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        return self._nc()

    def classify(self, request: LLMRequest, labels: list[str]) -> LLMResponse:
        return self._nc()

    def summarize(self, request: LLMRequest) -> LLMResponse:
        return self._nc()


class NoopEmbeddingBackend(EmbeddingBackend):
    """Embedding stub for EMBEDDING_PROVIDER=none."""

    @property
    def provider_name(self) -> str:
        return "none"

    @property
    def is_configured(self) -> bool:
        return False

    @property
    def vector_dimensions(self) -> int:
        return 0

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            degraded=True,
            failure_reason=FailureCode.NOT_CONFIGURED,
            provider="none",
        )

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        return EmbeddingBatchResponse(
            vectors=[[] for _ in request.texts],
            degraded=True,
            failure_reason=FailureCode.NOT_CONFIGURED,
            provider="none",
        )
