from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .failure import FailureCode


@dataclass
class EmbeddingRequest:
    text: str
    timeout_s: float = 10.0


@dataclass
class EmbeddingBatchRequest:
    texts: list[str]
    timeout_s: float = 30.0


@dataclass
class EmbeddingResponse:
    vector: list[float] = field(default_factory=list)
    dimensions: int = 0
    provider: str = "none"
    degraded: bool = False
    failure_reason: FailureCode | None = None

    @property
    def is_ok(self) -> bool:
        return not self.degraded and len(self.vector) > 0


@dataclass
class EmbeddingBatchResponse:
    vectors: list[list[float]] = field(default_factory=list)
    dimensions: int = 0
    provider: str = "none"
    degraded: bool = False
    failure_reason: FailureCode | None = None
    partial_failure: bool = False

    @property
    def is_ok(self) -> bool:
        return not self.degraded and not self.partial_failure


class EmbeddingBackend(ABC):
    """Abstract base for embedding provider adapters.

    Contract:
    - Never raises outside the adapter boundary.
    - degraded=True when not configured or on any failure.
    - embed_batch: partial_failure=True if only some items fail.
    - pgvector storage/retrieval is outside this contract.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def is_configured(self) -> bool: ...

    @property
    @abstractmethod
    def vector_dimensions(self) -> int: ...

    @abstractmethod
    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    @abstractmethod
    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse: ...
