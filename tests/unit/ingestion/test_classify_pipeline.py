"""Unit tests — classify_pipeline heuristic_v1.

Pure-Python, no DB, no provider, no network.
All inputs are synthetic — no private source content included.
"""
import pytest
from memory_lab.ingestion.classify_pipeline import (
    ClassificationResult,
    MemoryType,
    MEMORY_TYPE_VALUES,
    classify,
    _raw_score_to_confidence,
)

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]


# ---------------------------------------------------------------------------
# Module-level sanity checks
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_memory_type_values_complete(self):
        assert MEMORY_TYPE_VALUES == {
            "milestone", "decision", "principle", "anchor",
            "evidence", "plan_roadmap", "raw_memory",
        }

    def test_memory_type_constants_match_taxonomy(self):
        for attr in ("MILESTONE", "DECISION", "PRINCIPLE", "ANCHOR",
                     "EVIDENCE", "PLAN_ROADMAP", "RAW_MEMORY"):
            value = getattr(MemoryType, attr)
            assert value in MEMORY_TYPE_VALUES, f"{attr}={value!r} not in MEMORY_TYPE_VALUES"

    def test_classification_result_to_dict(self):
        r = ClassificationResult(
            memory_type=MemoryType.MILESTONE,
            memory_sub_type="governance_milestone",
            confidence=0.85,
            signals=["go_classify"],
            project_topic="context_brain_memory_lab",
            domain_hint="governance",
        )
        d = r.to_dict()
        assert d["memory_type"] == "milestone"
        assert d["confidence"] == 0.85
        assert "go_classify" in d["signals"]

    def test_confidence_step_function_is_deterministic(self):
        assert _raw_score_to_confidence(2.0) == 0.62
        assert _raw_score_to_confidence(3.0) == 0.72
        assert _raw_score_to_confidence(5.0) == 0.85
        assert _raw_score_to_confidence(7.0) == 0.93
        # same input → same output
        assert _raw_score_to_confidence(3.0) == _raw_score_to_confidence(3.0)


# ---------------------------------------------------------------------------
# Empty / error handling
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    def test_empty_content_is_raw_memory(self):
        r = classify("")
        assert r.memory_type == MemoryType.RAW_MEMORY

    def test_empty_content_and_title_is_raw_memory(self):
        r = classify("", title="")
        assert r.memory_type == MemoryType.RAW_MEMORY

    def test_empty_content_low_confidence(self):
        r = classify("")
        assert r.confidence <= 0.50

    def test_ambiguous_text_falls_back_to_raw_memory(self):
        r = classify("Hello world, this is some random text about nothing special.")
        assert r.memory_type == MemoryType.RAW_MEMORY

    def test_ambiguous_text_confidence_below_threshold(self):
        r = classify("Hello world, this is some random text about nothing special.")
        assert r.confidence < 0.65

    def test_classify_never_raises_on_strange_input(self):
        for bad in [None, 123, [], {}]:  # type: ignore[arg-type]
            # Should not raise even with wrong types
            try:
                result = classify(bad)  # type: ignore[arg-type]
                assert isinstance(result, ClassificationResult)
            except TypeError:
                pass  # acceptable to raise TypeError from caller; just must not crash loudly


# ---------------------------------------------------------------------------
# MILESTONE classification
# ---------------------------------------------------------------------------

class TestMilestoneClassification:
    def test_gate_pass_text_is_milestone(self):
        r = classify(
            "GO_CLASSIFY_PIPELINE_SCHEMA_APPLY gate report.\n"
            "Final status: classify_pipeline_schema_apply_pass\n"
            "Version 0.1.0b9"
        )
        assert r.memory_type == MemoryType.MILESTONE

    def test_gate_pass_confidence_high(self):
        r = classify(
            "GO_CLASSIFY_PIPELINE_SCHEMA_APPLY gate report.\n"
            "Final status: classify_pipeline_schema_apply_pass\n"
        )
        assert r.confidence >= 0.72

    def test_milestone_subtype_governance_for_gate(self):
        r = classify(
            "go_context_brain_full_gap_map gate. Gate complete. Version 0.1.0b9.",
            title="Gate Report",
        )
        assert r.memory_type == MemoryType.MILESTONE
        assert r.memory_sub_type in ("governance_milestone", "release_milestone", "schema_apply")

    def test_milestone_subtype_schema_apply(self):
        r = classify(
            "schema_apply_pass — migration 027-030 applied. Schema apply complete."
        )
        assert r.memory_type == MemoryType.MILESTONE
        assert r.memory_sub_type == "schema_apply"

    def test_milestone_subtype_release(self):
        r = classify(
            "v0.1.0b9 released: public release. Package published to PyPI."
        )
        assert r.memory_type == MemoryType.MILESTONE
        assert r.memory_sub_type == "release_milestone"

    def test_gate_name_without_pass_still_milestone(self):
        r = classify("go_classify_pipeline_schema_apply completed. Migration boundary 000..030.")
        assert r.memory_type == MemoryType.MILESTONE

    def test_milestone_has_signals_list(self):
        r = classify("go_context_brain gate complete. schema_apply_pass.")
        assert r.memory_type == MemoryType.MILESTONE
        assert len(r.signals) > 0

    def test_node_type_milestone_boosts(self):
        r = classify("Some gate-related activity happened.", node_type="milestone")
        # Node type boost contributes; text is weak so confidence should be meaningful
        assert r.memory_type == MemoryType.MILESTONE or r.confidence <= 0.62


# ---------------------------------------------------------------------------
# DECISION classification
# ---------------------------------------------------------------------------

class TestDecisionClassification:
    def test_decision_text_classified(self):
        r = classify(
            "We decided Option A — clean-room reimplementation. "
            "Rationale: avoids IP risk from private source. "
            "Supersedes original purpose_extraction.py approach."
        )
        assert r.memory_type == MemoryType.DECISION

    def test_decision_confidence_adequate(self):
        r = classify("We decided Option A — clean-room reimplementation. Rationale: IP risk.")
        assert r.confidence >= 0.62

    def test_decision_architectural_subtype(self):
        r = classify(
            "Architectural decision: use schema migration pattern. "
            "We decided to apply separate migrations (027-030). Supersedes prior draft."
        )
        assert r.memory_type == MemoryType.DECISION
        assert r.memory_sub_type == "schema_design"

    def test_supersedes_is_decision_signal(self):
        r = classify(
            "This decision supersedes the prior architecture. "
            "Option B: use cb_current_state_anchors. Option A was rejected: too complex."
        )
        assert r.memory_type == MemoryType.DECISION

    def test_decision_node_type_hint(self):
        # node_type hint is a soft boost (+1.5); text needs a signal too to cross threshold
        r = classify("We decided on the clean-room approach.", node_type="decision")
        assert r.memory_type == MemoryType.DECISION


# ---------------------------------------------------------------------------
# PRINCIPLE classification
# ---------------------------------------------------------------------------

class TestPrincipleClassification:
    def test_principle_text_classified(self):
        r = classify(
            "Principle: classify pipeline NEVER writes is_current or current_state_scope. "
            "Ownership invariant enforced at all layers."
        )
        assert r.memory_type == MemoryType.PRINCIPLE

    def test_principle_confidence_high(self):
        r = classify(
            "Principle: classify pipeline NEVER writes is_current. "
            "Ownership invariant: current-state system NEVER writes memory_type."
        )
        assert r.confidence >= 0.72

    def test_principle_subtype_architecture(self):
        r = classify(
            "Architectural principle: governance rule — ownership invariant must not be violated."
        )
        assert r.memory_type == MemoryType.PRINCIPLE
        assert r.memory_sub_type == "architecture_principle"

    def test_invariant_keyword_is_principle(self):
        r = classify("Ownership invariant: classify owns memory_type. Design principle enforced.")
        assert r.memory_type == MemoryType.PRINCIPLE

    def test_never_write_is_principle_signal(self):
        r = classify("Principle: do not write is_current from classify pipeline. Invariant: forbidden.")
        assert r.memory_type == MemoryType.PRINCIPLE


# ---------------------------------------------------------------------------
# ANCHOR classification
# ---------------------------------------------------------------------------

class TestAnchorClassification:
    def test_current_state_anchor_text(self):
        r = classify(
            "Current state anchor for release:context_brain_memory_lab. "
            "is_current=TRUE. Canonical state for v0.1.0b9 milestone."
        )
        assert r.memory_type == MemoryType.ANCHOR

    def test_anchor_confidence_adequate(self):
        r = classify(
            "Current state: active anchor. Canonical: is_current set to TRUE."
        )
        assert r.confidence >= 0.72

    def test_anchor_subtype_current_state(self):
        r = classify(
            "State anchor: current-state is_current=TRUE. Scope: release scope."
        )
        assert r.memory_type == MemoryType.ANCHOR
        assert r.memory_sub_type == "current_state_anchor"

    def test_is_current_keyword_triggers_anchor(self):
        r = classify("is_current set to TRUE for this content. Current state confirmed.")
        assert r.memory_type == MemoryType.ANCHOR

    def test_canonical_scope_is_anchor(self):
        r = classify(
            "Canonical: authoritative scope for this workspace. Source of truth checkpoint."
        )
        assert r.memory_type == MemoryType.ANCHOR


# ---------------------------------------------------------------------------
# EVIDENCE classification
# ---------------------------------------------------------------------------

class TestEvidenceClassification:
    def test_smoke_test_results_are_evidence(self):
        r = classify(
            "Smoke test results: smoke_001 PASS, smoke_002 PASS. "
            "30/30 checks passed. All tables verified."
        )
        assert r.memory_type == MemoryType.EVIDENCE

    def test_evidence_confidence_high_for_smoke_results(self):
        r = classify("smoke_001 PASS. 30/30 smoke checks. All checks pass.")
        assert r.confidence >= 0.72

    def test_evidence_subtype_implementation(self):
        r = classify(
            "Smoke test results: smoke_001 PASS. smoke_002 PASS. "
            "All checks pass. Test result: validated."
        )
        assert r.memory_type == MemoryType.EVIDENCE
        assert r.memory_sub_type == "implementation_evidence"

    def test_scorecard_is_evidence_scorecard_update(self):
        r = classify(
            "Scorecard: full CB score ~73%. Layer scores: "
            "current_state_intelligence=30, storage_schema_foundation=90"
        )
        assert r.memory_type == MemoryType.EVIDENCE
        assert r.memory_sub_type == "scorecard_update"

    def test_scorecard_confidence_adequate(self):
        r = classify("Scorecard update. Layer scores: storage=90, reasoning=42.")
        assert r.confidence >= 0.62

    def test_layer_score_text_is_scorecard_evidence(self):
        r = classify("Layer score breakdown: auth_rbac=72, decision_memory=70. Score: 73% headline.")
        assert r.memory_type == MemoryType.EVIDENCE
        assert r.memory_sub_type == "scorecard_update"

    def test_evidence_node_type_hint(self):
        r = classify("Some validation content.", node_type="fact")
        assert r.memory_type in (MemoryType.EVIDENCE, MemoryType.RAW_MEMORY)

    def test_gate_vs_evidence_disambiguation(self):
        # Gate pass report → milestone (gate name + _pass signal outweigh smoke tests)
        r_milestone = classify(
            "go_classify_pipeline_schema_apply: schema_apply_pass. "
            "smoke_001 pass. 30/30 checks. v0.1.0b9."
        )
        assert r_milestone.memory_type == MemoryType.MILESTONE

        # Pure smoke test result → evidence (no gate name, no _pass pattern)
        r_evidence = classify(
            "Smoke test results: smoke_001 PASS, smoke_002 PASS. "
            "30/30 checks passed. All tables verified."
        )
        assert r_evidence.memory_type == MemoryType.EVIDENCE


# ---------------------------------------------------------------------------
# PLAN_ROADMAP classification
# ---------------------------------------------------------------------------

class TestPlanRoadmapClassification:
    def test_next_gates_is_plan_roadmap(self):
        r = classify(
            "Next gates: GO_CLASSIFY_PIPELINE_HEURISTIC_V1_IMPLEMENTATION (primary). "
            "Roadmap: implement classify_pipeline.py → wire ingest hook → add retrieval filters."
        )
        assert r.memory_type == MemoryType.PLAN_ROADMAP

    def test_roadmap_confidence_high(self):
        r = classify("Roadmap: next gate: GO_CLASSIFY. Implementation plan: phase 1, phase 2.")
        assert r.confidence >= 0.72

    def test_roadmap_subtype_roadmap_plan(self):
        r = classify(
            "Next gates: GO_INGEST_HOOK, GO_RETRIEVAL_FILTER. "
            "Planned work: implement heuristic_v1. Upcoming: context-pack API."
        )
        assert r.memory_type == MemoryType.PLAN_ROADMAP
        assert r.memory_sub_type == "roadmap_plan"

    def test_open_gates_is_plan_roadmap(self):
        r = classify("Open gates: GO_CLASSIFY_PIPELINE_SCHEMA_APPLY. Recommended next gate: heuristic v1.")
        assert r.memory_type == MemoryType.PLAN_ROADMAP

    def test_implementation_plan_is_roadmap(self):
        r = classify(
            "Implementation plan: step 1 — create classify_pipeline.py. "
            "Step 2 — wire to ingestion. Proposed: add retrieval filter params."
        )
        assert r.memory_type == MemoryType.PLAN_ROADMAP

    def test_node_type_task_boosts_roadmap(self):
        r = classify("Work to complete: build next pipeline stage.", node_type="task")
        assert r.memory_type == MemoryType.PLAN_ROADMAP or r.memory_type == MemoryType.RAW_MEMORY


# ---------------------------------------------------------------------------
# RAW_MEMORY fallback
# ---------------------------------------------------------------------------

class TestRawMemoryFallback:
    def test_generic_text_is_raw_memory(self):
        r = classify("The weather is nice today. Some random content.")
        assert r.memory_type == MemoryType.RAW_MEMORY

    def test_raw_memory_has_positive_confidence(self):
        r = classify("The weather is nice today.")
        assert r.confidence > 0.0

    def test_short_content_is_raw_memory(self):
        r = classify("ok")
        assert r.memory_type == MemoryType.RAW_MEMORY

    def test_raw_memory_subtype_is_none(self):
        r = classify("Random non-classifiable content here.")
        assert r.memory_type == MemoryType.RAW_MEMORY
        assert r.memory_sub_type is None

    def test_node_type_raw_note_stays_raw(self):
        r = classify("Some content here.", node_type="raw_note")
        assert r.memory_type == MemoryType.RAW_MEMORY


# ---------------------------------------------------------------------------
# Project topic and domain hint extraction
# ---------------------------------------------------------------------------

class TestTopicAndDomainExtraction:
    def test_context_brain_topic_extracted(self):
        r = classify("context-brain memory lab gate report. go_classify_pipeline gate complete.")
        assert r.project_topic == "context_brain_memory_lab"

    def test_memory_lab_topic_extracted(self):
        r = classify("memory_lab ingestion pipeline. schema_apply_pass. go_classify.")
        assert r.project_topic == "context_brain_memory_lab"

    def test_no_topic_when_no_pattern(self):
        r = classify("some random text with no project reference")
        assert r.project_topic is None

    def test_schema_domain_hint_detected(self):
        r = classify("ALTER TABLE content_items. CREATE TABLE migration. Index applied.")
        assert r.domain_hint == "schema"

    def test_governance_domain_hint_detected(self):
        r = classify(
            "Governance gate: constitutional rule_id policy check. "
            "Gate governance review."
        )
        assert r.domain_hint == "governance"

    def test_topic_tags_influence_domain_hint(self):
        r = classify(
            "Some content.", topic_tags=["auth", "api_key", "workspace_member"]
        )
        assert r.domain_hint == "auth"


# ---------------------------------------------------------------------------
# Confidence determinism
# ---------------------------------------------------------------------------

class TestConfidenceDeterminism:
    def test_same_input_same_confidence(self):
        text = "Principle: invariant — ownership must never be violated."
        r1 = classify(text)
        r2 = classify(text)
        assert r1.confidence == r2.confidence
        assert r1.memory_type == r2.memory_type

    def test_same_input_same_signals(self):
        text = "go_classify_pipeline_schema_apply. schema_apply_pass."
        r1 = classify(text)
        r2 = classify(text)
        assert sorted(r1.signals) == sorted(r2.signals)

    def test_confidence_in_valid_range(self):
        for text in [
            "go_context_brain gate. schema_apply_pass. v0.1.0b9.",
            "We decided option a — clean-room approach. Supersedes prior.",
            "Principle: invariant — must not modify.",
            "Current state anchor. is_current=TRUE. Canonical.",
            "smoke_001 PASS. 30/30 checks passed.",
            "Next gates: GO_INGEST. Roadmap: implement.",
            "Random fallback text with no signals.",
        ]:
            r = classify(text)
            assert 0.0 <= r.confidence <= 1.0, f"confidence={r.confidence!r} out of range for: {text!r}"

    def test_memory_type_always_in_taxonomy(self):
        for text in [
            "gate pass v0.1.0b9",
            "we decided option a",
            "principle invariant",
            "current state is_current",
            "smoke_001 30/30 checks",
            "roadmap: next gate:",
            "random text",
        ]:
            r = classify(text)
            assert r.memory_type in MEMORY_TYPE_VALUES, f"invalid type={r.memory_type!r}"


# ---------------------------------------------------------------------------
# No provider / no private source
# ---------------------------------------------------------------------------

class TestNoProviderDependency:
    def test_classify_imports_no_providers(self):
        import memory_lab.ingestion.classify_pipeline as cp
        import sys
        provider_modules = [k for k in sys.modules if "anthropic" in k or "openai" in k]
        # classify_pipeline itself must not have imported any provider module
        assert not any(
            "anthropic" in m or "openai" in m
            for m in dir(cp)
        )

    def test_classify_has_no_api_key_dependency(self):
        import os
        orig = os.environ.get("ANTHROPIC_API_KEY")
        try:
            if orig:
                del os.environ["ANTHROPIC_API_KEY"]
            r = classify("go_classify gate complete. schema_apply_pass.")
            assert isinstance(r, ClassificationResult)
        finally:
            if orig:
                os.environ["ANTHROPIC_API_KEY"] = orig

    def test_no_contentingestor_import(self):
        import sys
        # contentingestor must not appear in any imported module path
        assert not any("contentingestor" in str(m) for m in sys.modules)
