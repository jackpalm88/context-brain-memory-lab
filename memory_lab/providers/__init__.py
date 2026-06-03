"""memory_lab.providers — provider abstraction layer.

Public surface (base interfaces + noop/fake only):
    from memory_lab.providers import (
        FailureCode,
        LLMRequest, LLMResponse, LLMBackend,
        EmbeddingRequest, EmbeddingBatchRequest,
        EmbeddingResponse, EmbeddingBatchResponse, EmbeddingBackend,
        NoopLLMBackend, NoopEmbeddingBackend,
        FakeLLMBackend, FakeEmbeddingBackend,
        ProviderConfig,
    )

No real provider adapters in this module.
"""
from .failure import FailureCode
from .llm_backend import LLMRequest, LLMResponse, LLMBackend
from .embedding_backend import (
    EmbeddingRequest, EmbeddingBatchRequest,
    EmbeddingResponse, EmbeddingBatchResponse, EmbeddingBackend,
)
from .noop import NoopLLMBackend, NoopEmbeddingBackend
from .fake import FakeLLMBackend, FakeEmbeddingBackend
from .config import ProviderConfig

__all__ = [
    "FailureCode",
    "LLMRequest", "LLMResponse", "LLMBackend",
    "EmbeddingRequest", "EmbeddingBatchRequest",
    "EmbeddingResponse", "EmbeddingBatchResponse", "EmbeddingBackend",
    "NoopLLMBackend", "NoopEmbeddingBackend",
    "FakeLLMBackend", "FakeEmbeddingBackend",
    "ProviderConfig",
]
