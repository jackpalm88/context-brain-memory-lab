from memory_lab.graph.alias_hygiene import AliasHygieneService, normalize_entity_name


def test_duplicate_alias_candidates_are_report_only():
    report = AliasHygieneService().generate_candidates(["Context Brain", "context brain", "D.O.M.A", "DOMA"])
    assert report.candidate_count >= 1
    assert all(candidate.requires_human_review for candidate in report.candidates)
    assert all(candidate.mutation_allowed is False for candidate in report.candidates)
    assert "ALIAS_CANDIDATE_REVIEW_REQUIRED" in {w.code for w in report.warnings}


def test_alias_candidates_do_not_mutate_input_labels():
    labels = ["Rīga", "Riga"]
    before = list(labels)
    report = AliasHygieneService().generate_candidates(labels)
    assert labels == before
    assert report.candidate_count == 1
    assert report.candidates[0].candidate_type == "alias_or_multilingual_variant"


def test_normalize_entity_name_is_deterministic():
    values = [normalize_entity_name("  Rīga--Context_Brain!! ") for _ in range(3)]
    assert values == ["riga context brain", "riga context brain", "riga context brain"]


def test_no_candidates_returns_limitation_not_mutation():
    report = AliasHygieneService().generate_candidates(["alpha", "beta"])
    assert report.candidate_count == 0
    assert report.candidates == []
    assert "no_alias_candidates_detected_from_provided_labels" in report.limitations
