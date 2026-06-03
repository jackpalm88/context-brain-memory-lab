"""FakeLLMBackend and FakeEmbeddingBackend for deterministic unit tests.
No network. No real provider imports. Intended for tests only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from .failure import FailureCode
from .llm_backend import LLMBackend, LLMRequest, LLMResponse
from .embedding_backend import (
    EmbeddingBackend, EmbeddingRequest, EmbeddingBatchRequest,
    EmbeddingResponse, EmbeddingBatchResponse,
)


@dataclass
class FakeLLMBackend(LLMBackend):
    preset_response: LLMResponse | None = None
    preset_failure: FailureCode | None = None
    preset_json: dict[str, Any] | None = None
    invalid_json_text: str | None = None
    schema_mismatch_json: dict[str, Any] | None = None

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def is_configured(self) -> bool:
        return True

    def complete_text(self, request: LLMRequest) -> LLMResponse:
        if self.preset_failure:
            return LLMResponse(degraded=True, failure_reason=self.preset_failure, provider="fake")
        if self.preset_response:
            return self.preset_response
        return LLMResponse(text="fake_text", provider="fake")

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        if self.preset_failure:
            return LLMResponse(degraded=True, failure_reason=self.preset_failure, provider="fake")
        if self.invalid_json_text is not None:
            return LLMResponse(degraded=True, failure_reason=FailureCode.INVALID_JSON, provider="fake")
        if self.schema_mismatch_json is not None:
            return LLMResponse(degraded=True, failure_reason=FailureCode.SCHEMA_VALIDATION_FAILED, provider="fake")
        if self.preset_json is not None:
            return LLMResponse(json_data=self.preset_json, provider="fake")
        return LLMResponse(json_data={}, provider="fake")

    def classify(self, request: LLMRequest, labels: list[str]) -> LLMResponse:
        if self.preset_failure:
            return LLMResponse(degraded=True, failure_reason=self.preset_failure, provider="fake")
        return LLMResponse(text=labels[0] if labels else "", provider="fake")

    def summarize(self, request: LLMRequest) -> LLMResponse:
        if self.preset_failure:
            return LLMResponse(degraded=True, failure_reason=self.preset_failure, provider="fake")
        return LLMResponse(text="fake_summary", provider="fake")


@dataclass
class FakeEmbeddingBackend(EmbeddingBackend):
    dimensions: int = 4
    preset_vector: list[float] | None = None
    preset_failure: FailureCode | None = None

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def vector_dimensions(self) -> int:
        return self.dimensions

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if self.preset_failure:
            return EmbeddingResponse(
                degraded=True, failure_reason=self.preset_failure, provider="fake"
            )
        v = self.preset_vector or [0.1] * self.dimensions
        return EmbeddingResponse(vector=v, dimensions=self.dimensions, provider="fake")

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        if self.preset_failure:
            return EmbeddingBatchResponse(
                vectors=[[] for _ in request.texts],
                degraded=True,
                failure_reason=self.preset_failure,
                provider="fake",
            )
        v = self.preset_vector or [0.1] * self.dimensions
        return EmbeddingBatchResponse(
            vectors=[list(v) for _ in request.texts],
            dimensions=self.dimensions,
            provider="fake",
        )
