from memory_lab.ingestion.ingestion_scoring import IngestionSignalInput, score_ingestion_signals


def strong_signals(**overrides):
    data = dict(extraction_confidence=0.9, domain_confidence=0.85, hub_confidence=0.8, tag_confidence=0.75, chunk_quality=0.9, chunk_composite=0.88, embedding_admin_ready=True, knn_ready=True, completeness_flags=("text", "domain", "hub", "tag"))
    data.update(overrides)
    return IngestionSignalInput(**data)


def test_deterministic_scoring_repeatability():
    signals = strong_signals(risk_flags=("minor_format_issue",))
    assert score_ingestion_signals(signals) == score_ingestion_signals(signals)


def test_scores_are_clamped_to_unit_range():
    summary = score_ingestion_signals(strong_signals(extraction_confidence=2.0, domain_confidence=-5.0, risk_flags=("a", "b", "c", "d", "e", "f", "g")))
    for value in (summary.score.quality, summary.score.risk, summary.score.completeness, summary.score.composite, summary.score.confidence):
        assert 0.0 <= value <= 1.0


def test_quality_risk_completeness_weights_behave_predictably():
    strong = score_ingestion_signals(strong_signals())
    weak = score_ingestion_signals(strong_signals(extraction_confidence=0.2, domain_confidence=0.2, hub_confidence=0.2, tag_confidence=0.2, chunk_quality=0.3, chunk_composite=0.3, completeness_flags=()))
    assert strong.score.quality > weak.score.quality
    assert strong.score.completeness > weak.score.completeness
    assert weak.score.risk > strong.score.risk


def test_low_classification_confidence_lowers_confidence_and_composite():
    strong = score_ingestion_signals(strong_signals())
    low = score_ingestion_signals(strong_signals(extraction_confidence=0.1, domain_confidence=0.1, hub_confidence=0.1, tag_confidence=0.1))
    assert low.score.confidence < strong.score.confidence
    assert low.score.composite < strong.score.composite
    assert "B21-C1-LOW-CLASSIFICATION-SIGNALS" in low.rule_ids


def test_risk_flags_reduce_composite_deterministically():
    clean = score_ingestion_signals(strong_signals())
    risky = score_ingestion_signals(strong_signals(risk_flags=("unsupported_source", "low_trust")))
    assert risky.score.risk > clean.score.risk
    assert risky.score.composite < clean.score.composite
    assert "B21-C1-RISK-FLAGS-REDUCE-COMPOSITE" in risky.rule_ids


def test_missing_signals_degrade_without_crashing():
    summary = score_ingestion_signals(IngestionSignalInput())
    assert summary.degraded is True
    assert summary.score.composite >= 0.0
    assert "B21-C1-MISSING-SIGNALS-DEGRADE-CONFIDENCE" in summary.rule_ids
    assert any("no semantic truth" in item for item in summary.limitations)
