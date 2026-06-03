"""T1-T8: EmbeddingBackend contract via noop + fake."""
from memory_lab.providers.noop import NoopEmbeddingBackend
from memory_lab.providers.fake import FakeEmbeddingBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.embedding_backend import (
    EmbeddingRequest, EmbeddingBatchRequest,
    EmbeddingResponse, EmbeddingBatchResponse,
)


def test_noop_not_configured():
    b = NoopEmbeddingBackend()
    r = b.embed_text(EmbeddingRequest(text="hi"))
    assert r.failure_reason == FailureCode.NOT_CONFIGURED


def test_fake_emb_success_is_ok():
    b = FakeEmbeddingBackend(dimensions=4)
    r = b.embed_text(EmbeddingRequest(text="hi"))
    assert r.is_ok is True


def test_fake_emb_timeout_is_not_ok():
    b = FakeEmbeddingBackend(preset_failure=FailureCode.TIMEOUT)
    r = b.embed_text(EmbeddingRequest(text="hi"))
    assert r.is_ok is False


def test_fake_batch_no_partial_failure_on_success():
    b = FakeEmbeddingBackend()
    r = b.embed_batch(EmbeddingBatchRequest(texts=["a", "b"]))
    assert r.partial_failure is False


def test_fake_batch_preset_failure_degraded():
    b = FakeEmbeddingBackend(preset_failure=FailureCode.PROVIDER_HTTP_ERROR)
    r = b.embed_batch(EmbeddingBatchRequest(texts=["a"]))
    assert r.degraded is True


def test_batch_response_degraded_not_ok():
    r = EmbeddingBatchResponse(degraded=True)
    assert r.is_ok is False


def test_embedding_response_empty_vector_not_ok():
    r = EmbeddingResponse(vector=[], degraded=False)
    assert r.is_ok is False


def test_embedding_response_non_empty_ok():
    r = EmbeddingResponse(vector=[0.1, 0.2], dimensions=2, degraded=False)
    assert r.is_ok is True
