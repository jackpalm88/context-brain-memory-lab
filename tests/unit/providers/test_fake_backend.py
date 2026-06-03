"""T1-T10: FakeLLMBackend and FakeEmbeddingBackend deterministic behavior."""
import pytest
from memory_lab.providers.fake import FakeLLMBackend, FakeEmbeddingBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.llm_backend import LLMRequest, LLMResponse
from memory_lab.providers.embedding_backend import EmbeddingRequest, EmbeddingBatchRequest


def test_fake_llm_is_configured():
    assert FakeLLMBackend().is_configured is True


def test_fake_llm_preset_json():
    b = FakeLLMBackend(preset_json={"quality": 0.8, "relevance": 0.7, "novelty": 0.5})
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.json_data == {"quality": 0.8, "relevance": 0.7, "novelty": 0.5}
    assert r.degraded is False


def test_fake_llm_preset_failure_complete_text():
    b = FakeLLMBackend(preset_failure=FailureCode.TIMEOUT)
    r = b.complete_text(LLMRequest(prompt="x"))
    assert r.degraded is True
    assert r.failure_reason == FailureCode.TIMEOUT


def test_fake_llm_preset_failure_complete_json():
    b = FakeLLMBackend(preset_failure=FailureCode.TIMEOUT)
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.degraded is True


def test_fake_llm_invalid_json_path():
    b = FakeLLMBackend(invalid_json_text="not-json{{{")
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.degraded is True
    assert r.failure_reason == FailureCode.INVALID_JSON


def test_fake_llm_schema_mismatch_path():
    b = FakeLLMBackend(schema_mismatch_json={"wrong_key": 1})
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.degraded is True
    assert r.failure_reason == FailureCode.SCHEMA_VALIDATION_FAILED


def test_fake_llm_classify_returns_first_label():
    b = FakeLLMBackend()
    r = b.classify(LLMRequest(prompt="x"), labels=["a", "b"])
    assert r.text == "a"


def test_fake_emb_dimensions():
    b = FakeEmbeddingBackend(dimensions=3)
    r = b.embed_text(EmbeddingRequest(text="hi"))
    assert r.dimensions == 3
    assert len(r.vector) == 3


def test_fake_emb_batch_length():
    b = FakeEmbeddingBackend()
    r = b.embed_batch(EmbeddingBatchRequest(texts=["x", "y"]))
    assert len(r.vectors) == 2


def test_fake_emb_preset_failure():
    b = FakeEmbeddingBackend(preset_failure=FailureCode.RATE_LIMITED)
    r = b.embed_batch(EmbeddingBatchRequest(texts=["x"]))
    assert r.degraded is True
    assert r.failure_reason == FailureCode.RATE_LIMITED
