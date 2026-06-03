from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .failure import FailureCode


@dataclass
class LLMRequest:
    prompt: str
    system: str | None = None
    max_tokens: int = 512
    temperature: float = 0.0
    timeout_s: float = 10.0
    expected_schema: dict[str, Any] | None = None


@dataclass
class LLMResponse:
    text: str = ""
    json_data: dict[str, Any] | None = None
    provider: str = "none"
    model: str = ""
    degraded: bool = False
    failure_reason: FailureCode | None = None

    @property
    def is_ok(self) -> bool:
        return not self.degraded


class LLMBackend(ABC):
    """Abstract base for LLM provider adapters.

    Contract:
    - Never raises outside the adapter boundary.
    - degraded=True with failure_reason set on any non-happy path.
    - complete_json: json_data populated OR degraded=True (never partial).
    - classify: text = one of labels OR degraded=True.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def complete_text(self, request: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    def complete_json(self, request: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    def classify(self, request: LLMRequest, labels: list[str]) -> LLMResponse: ...

    @abstractmethod
    def summarize(self, request: LLMRequest) -> LLMResponse: ...
