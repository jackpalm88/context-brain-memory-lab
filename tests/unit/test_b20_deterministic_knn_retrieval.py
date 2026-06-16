"""B20 deterministic in-memory KNN retrieval tests."""

from memory_lab.retrieval.knn import (
    KNN_RETRIEVAL_MODE,
    DeterministicKnnRetriever,
    KnnQuery,
    KnnVectorItem,
    make_deterministic_knn_retriever,
    rank_by_cosine_similarity,
)


def item(item_id, vector, **overrides):
    data = {"item_id": item_id, "vector": vector}
    data.update(overrides)
    return KnnVectorItem(**data)


def test_factory_returns_deterministic_retriever():
    retriever = make_deterministic_knn_retriever()
    assert isinstance(retriever, DeterministicKnnRetriever)
    assert retriever.mode == KNN_RETRIEVAL_MODE


def test_cosine_similarity_ranking_over_supplied_synthetic_vectors():
    summary = rank_by_cosine_similarity(
        KnnQuery(vector=(1.0, 0.0), top_k=3, query_id="q1"),
        [item("aligned", (1.0, 0.0)), item("diagonal", (0.5, 0.5)), item("opposite", (-1.0, 0.0))],
    )
    assert tuple(result.item_id for result in summary.results) == ("aligned", "diagonal", "opposite")
    assert summary.results[0].score == 1.0
    assert summary.results[0].rank == 1
    assert summary.results[0].reason == "cosine_similarity_over_supplied_vectors"
    assert "no provider-backed semantic retrieval" in summary.non_claims


def test_stable_deterministic_tie_breaks_by_item_id():
    summary = rank_by_cosine_similarity(
        (1.0, 0.0),
        [item("b", (1.0, 0.0)), item("a", (1.0, 0.0)), item("c", (1.0, 0.0))],
    )
    assert tuple(result.item_id for result in summary.results) == ("a", "b", "c")


def test_top_k_bounds_are_applied():
    summary = rank_by_cosine_similarity(
        (1.0, 0.0),
        [item(str(i), (1.0, 0.0)) for i in range(5)],
        top_k=2,
    )
    assert len(summary.results) == 2
    zero = rank_by_cosine_similarity((1.0, 0.0), [item("x", (1.0, 0.0))], top_k=0)
    assert len(zero.results) == 1


def test_missing_vectors_are_skipped_with_warnings():
    summary = rank_by_cosine_similarity((1.0, 0.0), [item("missing", None), item("valid", (1.0, 0.0))])
    assert tuple(result.item_id for result in summary.results) == ("valid",)
    assert summary.skipped_count == 1
    assert "KNN_ITEM_VECTOR_MISSING_OR_INVALID" in summary.warnings
    assert summary.degraded is True


def test_zero_vector_handling_degrades_safely():
    summary = rank_by_cosine_similarity((1.0, 0.0), [item("zero", (0.0, 0.0)), item("valid", (1.0, 0.0))])
    assert tuple(result.item_id for result in summary.results) == ("valid", "zero")
    assert summary.results[1].score == 0.0
    assert "KNN_ZERO_VECTOR_DEGRADED" in summary.warnings
    assert summary.degraded is True


def test_dimension_mismatch_handling_skips_candidate():
    summary = rank_by_cosine_similarity((1.0, 0.0), [item("bad", (1.0, 0.0, 0.0)), item("ok", (1.0, 0.0))])
    assert tuple(result.item_id for result in summary.results) == ("ok",)
    assert summary.skipped_count == 1
    assert "KNN_DIMENSION_MISMATCH" in summary.warnings


def test_non_numeric_vector_values_rejected_or_degraded():
    summary = rank_by_cosine_similarity((1.0, 0.0), [item("bad", ("not-a-number", 0.0)), item("ok", (0.5, 0.5))])
    assert tuple(result.item_id for result in summary.results) == ("ok",)
    assert summary.skipped_count == 1
    assert "KNN_ITEM_VECTOR_MISSING_OR_INVALID" in summary.warnings


def test_empty_corpus_returns_unavailable_degraded_state():
    summary = rank_by_cosine_similarity(KnnQuery(vector=(1.0, 0.0), query_id="empty"), [])
    assert summary.results == ()
    assert summary.unavailable is True
    assert summary.degraded is True
    assert "KNN_CORPUS_EMPTY" in summary.warnings


def test_invalid_query_returns_unavailable_degraded_state():
    summary = rank_by_cosine_similarity(KnnQuery(vector=None, query_id="invalid"), [item("x", (1.0, 0.0))])
    assert summary.results == ()
    assert summary.unavailable is True
    assert summary.skipped_count == 1
    assert "KNN_QUERY_VECTOR_INVALID" in summary.warnings


def test_result_shape_includes_required_contract_fields():
    summary = rank_by_cosine_similarity((1.0, 0.0), [{"id": "mapping-item", "vector": [1, 0], "limitations": ("supplied fixture",)}])
    result = summary.results[0]
    assert result.item_id == "mapping-item"
    assert isinstance(result.score, float)
    assert result.rank == 1
    assert result.reason
    assert "supplied fixture" in result.limitations
    assert "no database access" in result.non_claims
