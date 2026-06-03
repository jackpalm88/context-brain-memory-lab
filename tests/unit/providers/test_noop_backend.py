"""T1-T11: NoopLLMBackend and NoopEmbeddingBackend contract."""
import pytest
from memory_lab.providers.noop import NoopLLMBackend, NoopEmbeddingBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.llm_backend import LLMRequest
from memory_lab.providers.embedding_backend import EmbeddingRequest, EmbeddingBatchRequest


@pytest.fixture
def llm():
    return NoopLLMBackend()


@pytest.fixture
def emb():
    return NoopEmbeddingBackend()


def test_llm_provider_name(llm):
    assert llm.provider_name == "none"


def test_llm_is_configured_false(llm):
    assert llm.is_configured is False


def test_complete_text_degraded(llm):
    r = llm.complete_text(LLMRequest(prompt="x"))
    assert r.degraded is True
    assert r.failure_reason == FailureCode.NOT_CONFIGURED


def test_complete_json_degraded_no_json_data(llm):
    r = llm.complete_json(LLMRequest(prompt="x"))
    assert r.degraded is True
    assert r.json_data is None


def test_classify_degraded(llm):
    r = llm.classify(LLMRequest(prompt="x"), labels=["a", "b"])
    assert r.degraded is True


def test_summarize_degraded(llm):
    r = llm.summarize(LLMRequest(prompt="x"))
    assert r.degraded is True


def test_complete_json_no_fake_semantic_text(llm):
    r = llm.complete_json(LLMRequest(prompt="x"))
    assert r.text == ""


def test_emb_vector_dimensions_zero(emb):
    assert emb.vector_dimensions == 0


def test_embed_text_degraded_empty_vector(emb):
    r = emb.embed_text(EmbeddingRequest(text="hello"))
    assert r.degraded is True
    assert r.vector == []


def test_embed_batch_degraded_empty_vectors(emb):
    r = emb.embed_batch(EmbeddingBatchRequest(texts=["a", "b"]))
    assert r.degraded is True
    assert r.vectors == [[], []]


def test_none_raise(llm, emb):
    req = LLMRequest(prompt="test")
    ereq = EmbeddingRequest(text="test")
    breq = EmbeddingBatchRequest(texts=["x"])
    for fn in [
        lambda: llm.complete_text(req),
        lambda: llm.complete_json(req),
        lambda: llm.classify(req, []),
        lambda: llm.summarize(req),
        lambda: emb.embed_text(ereq),
        lambda: emb.embed_batch(breq),
    ]:
        fn()  # must not raise
