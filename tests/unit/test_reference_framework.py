"""Hermetic tests — OpenCB Reference Framework v0.

The framework is the canonical consumer: manifest -> router -> executor ->
evidence package. Tests run against a fake tool registry (no DB, no HTTP) and
pin the ratified contracts: deterministic routing, budgets, no-repeat guard,
condition-named follow-ups, EP invariants, hub-match parity with the kernel.
"""

import pytest

from reference_framework.executor import execute
from reference_framework.hub_match import term_matches_hub
from reference_framework.manifest import load_manifest
from reference_framework.package_builder import build_package
from reference_framework.router import (
    MAX_CALLS_DIAGNOSE,
    PlanStep,
    RoutePlan,
    detect_intent,
    is_historical,
    route,
)

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]


# ---------------------------------------------------------------------------
# Manifest loader
# ---------------------------------------------------------------------------

def test_manifest_loads_all_tools_and_filters_routable():
    manifest = load_manifest()
    # 32 production-parity tools + CF-003 anchors + CF-002 decisions-by-content (public-only)
    assert len(manifest.tools) == 34
    routable = manifest.routable()
    assert "update_node_metadata" not in routable          # discouraged
    assert "list_graph_snapshot" not in routable           # alias
    assert "query_memory" in routable


def test_router_plans_only_name_manifest_tools():
    manifest = load_manifest()
    questions = [
        "what was decided recently?",
        "why did we switch the queue?",
        "what do we know about payments?",
        "which cache do we use now?",
        "how does checkout relate to caching?",
        "remember: decision: use Y",
        "is memory healthy?",
    ]
    for question in questions:
        for step in route(question).steps:
            assert step.tool in manifest.tools, f"{question!r} -> unknown tool {step.tool}"


# ---------------------------------------------------------------------------
# Router — taxonomy, priority, modifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,intent", [
    ("What was decided this week?", "latest_decisions"),
    ("Why did we choose RabbitMQ?", "explain_decision"),
    ("What do we know about webhooks?", "explain_topic"),
    ("Which message queue do we use now?", "verify_current_state"),
    ("How does checkout relate to caching?", "relationship_map"),
    ("Remember: decision: cap retries at 6", "save_memory"),
    ("Is memory healthy? any pending reviews?", "diagnose_system_state"),
    ("random text with no triggers at all", "explain_topic"),
])
def test_intent_taxonomy(question, intent):
    assert detect_intent(question.lower()) == intent


def test_priority_save_beats_reads():
    # contains both "remember" and "current" — writes are never accidental
    assert detect_intent("remember which queue is current") == "save_memory"


def test_historical_modifier_word_boundary():
    assert is_historical("what did we use previously?")
    assert not is_historical("prepare the beforehand-checklist")


def test_fallback_is_metadata_not_gap():
    plan = route("random text with no triggers at all")
    assert plan.intent == "explain_topic"
    assert plan.matched_by == "fallback"
    assert plan.notes == []          # ratified amendment: fallback itself is not a gap


def test_llm_preclassified_marker():
    plan = route("anything", preclassified_intent="latest_decisions")
    assert plan.matched_by == "llm_preclassified"
    assert plan.intent == "latest_decisions"


def test_every_conditional_step_names_its_trigger():
    for question in ("what was decided?", "why did we choose X?", "what about Y?",
                     "which do we use now?", "how do A and B relate?",
                     "remember this note", "is memory healthy?"):
        for step in route(question).steps[1:]:
            assert step.condition is not None or step.args or step.args_from, (
                f"follow-up without declared trigger/inputs: {step}"
            )
            assert step.reason, f"step without a reason: {step}"


# ---------------------------------------------------------------------------
# Hub match — kernel parity (ratified: HubTermGraph semantics verbatim)
# ---------------------------------------------------------------------------

def test_hub_match_parity_with_kernel():
    from memory_lab.graph.hub_term_graph import HubTermGraph

    hubs = {
        "h1": {"title": "Checkout Payments Domain", "aliases": ["checkout payments"]},
        "h2": {"title": "Session Caching Layer", "aliases": ["session cache"]},
    }
    kernel = HubTermGraph("postgresql://unused")
    kernel._hub_terms = {hid: {h["title"].lower(), *[a.lower() for a in h["aliases"]]}
                         for hid, h in hubs.items()}
    kernel._edges = []
    kernel._loaded_for = "ws"

    for term in ("payments", "session cache", "checkout payments domain", "caching", "xyz"):
        framework_says = {hid for hid, h in hubs.items() if term_matches_hub(term, h)}
        kernel_says = kernel._hubs_matching(term)
        assert framework_says == kernel_says, f"divergence on {term!r}"


# ---------------------------------------------------------------------------
# Executor — conditions, budget, no-repeat
# ---------------------------------------------------------------------------

class Registry(dict):
    """Callable registry that records calls."""

    def __init__(self, responses):
        super().__init__()
        self.calls = []
        for name, response in responses.items():
            self[name] = self._make(name, response)

    def _make(self, name, response):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            return response(kwargs) if callable(response) else response
        return call


_ANCHOR_RESPONSE = {"anchors": [
    {"content_id": "new-1", "supersedes_content_id": "old-1",
     "scope": "message-queue", "memory_type": "decision",
     "is_current": True, "current_state_scope": "message-queue",
     "quick_summary": "RabbitMQ is the message queue"},
], "count": 1, "scope": "message-queue"}


def _content_get_response(kwargs):
    if kwargs["content_id"] == "old-1":
        return {"content_id": "old-1", "is_current": False, "current_state_scope": "message-queue"}
    return {"content_id": "new-1", "is_current": True, "current_state_scope": "message-queue"}


def test_verify_current_state_chases_successor_via_anchor():
    registry = Registry({
        "memory_lab_retrieval_search": {"results": [
            {"content_id": "old-1", "text": "Decision: adopt Kafka…"},
            {"content_id": "new-1", "text": "Decision: switch to RabbitMQ…"},
        ]},
        "list_current_state_anchors": _ANCHOR_RESPONSE,
        "memory_lab_content_get": _content_get_response,
    })
    state = execute(route("which message queue do we use now?"), registry)
    called = [name for name, _ in registry.calls]
    assert called == ["memory_lab_retrieval_search", "memory_lab_content_get",
                      "list_current_state_anchors", "memory_lab_content_get"]
    assert registry.calls[2][1].get("scope") == "message-queue"
    package = build_package(state)["evidence_package"]
    statuses = {i["source"]["source_id"]: i["currency"]["status"]
                for i in package["items"] if i["kind"] == "content_record"}
    assert statuses == {"old-1": "superseded", "new-1": "current"}


def test_verify_current_state_finds_successor_retrieval_missed():
    # The exact case the v0 bounded probe could NOT handle (CF-003): retrieval
    # surfaces only the superseded item; the successor comes from the anchor.
    registry = Registry({
        "memory_lab_retrieval_search": {"results": [
            {"content_id": "old-1", "text": "Decision: adopt Kafka…"},
        ]},
        "list_current_state_anchors": _ANCHOR_RESPONSE,
        "memory_lab_content_get": _content_get_response,
    })
    state = execute(route("which message queue do we use now?"), registry)
    called = [name for name, _ in registry.calls]
    assert called == ["memory_lab_retrieval_search", "memory_lab_content_get",
                      "list_current_state_anchors", "memory_lab_content_get"]
    package = build_package(state)["evidence_package"]
    current_ids = {i["source"]["source_id"] for i in package["items"]
                   if i["currency"]["status"] == "current"}
    assert "new-1" in current_ids


_BY_CONTENT_HIT = {"decisions": [
    {"decision_id": "d-9", "title": "Adopt RabbitMQ", "decision_status": "active",
     "link_role": "source", "also_source": False},
], "count": 1, "content_id": "c-1"}

_BY_CONTENT_MISS = {"decisions": [], "count": 0, "content_id": "c-1"}


def test_explain_decision_referential_entry_beats_lexical():
    # CF-002: the content→decision join resolves the decision; the lexical
    # list_decisions fallback must NOT run.
    registry = Registry({
        "memory_lab_retrieval_search": {"results": [{"content_id": "c-1", "text": "queue decision…"}]},
        "list_decisions_for_content": _BY_CONTENT_HIT,
        "explain_decision": {"decision_id": "d-9", "title": "Adopt RabbitMQ",
                             "decision_reason": "ops simplicity"},
        "get_decision_lineage": {"decision_id": "d-9", "title": "Adopt RabbitMQ",
                                 "ancestors": [], "descendants": [], "depth": 0},
        "list_decisions": {"decisions": [], "count": 0},
    })
    state = execute(route("why did we choose the queue?"), registry)
    called = [name for name, _ in registry.calls]
    assert called == ["memory_lab_retrieval_search", "list_decisions_for_content",
                      "explain_decision", "get_decision_lineage"]
    assert registry.calls[2][1].get("decision_id") == "d-9"
    lexical = [t for t in state.trace if t.tool == "list_decisions"]
    assert lexical and lexical[0].outcome == "skipped"


def test_explain_decision_lexical_fallback_when_unlinked():
    registry = Registry({
        "memory_lab_retrieval_search": {"results": [{"content_id": "c-1", "text": "queue decision…"}]},
        "list_decisions_for_content": _BY_CONTENT_MISS,
        "list_decisions": {"decisions": [
            {"decision_id": "d-7", "title": "Switch queue to RabbitMQ", "decision_status": "active"},
        ], "count": 1},
        "explain_decision": {"decision_id": "d-7", "title": "Switch queue to RabbitMQ",
                             "decision_reason": "…"},
        "get_decision_lineage": {"decision_id": "d-7", "title": "Switch queue to RabbitMQ",
                                 "ancestors": [], "descendants": [], "depth": 0},
    })
    state = execute(route("why did we switch the queue?"), registry)
    called = [name for name, _ in registry.calls]
    assert called == ["memory_lab_retrieval_search", "list_decisions_for_content",
                      "list_decisions", "explain_decision", "get_decision_lineage"]
    assert registry.calls[3][1].get("decision_id") == "d-7"


def test_explain_topic_restored_3_3_followup():
    # CF-002 restores the §3.3 follow-up v0 dropped: evidence → decision → lineage.
    registry = Registry({
        "query_memory": {"answer": "RabbitMQ [ev_1]", "status": "ok", "confidence": 0.7,
                         "no_context": False, "citations": [{"evidence_id": "ev_1"}],
                         "evidence": [{"content_id": "c-1", "snippet": "Decision: RabbitMQ…",
                                       "is_current": True}],
                         "fallback": {"suggested": False}},
        "list_decisions_for_content": _BY_CONTENT_HIT,
        "get_decision_lineage": {"decision_id": "d-9", "title": "Adopt RabbitMQ",
                                 "ancestors": [{"decision_id": "d-1", "decision_status": "superseded"}],
                                 "descendants": [], "depth": 1},
        "memory_lab_retrieval_search": {"results": []},
    })
    state = execute(route("what do we know about queues?"), registry)
    called = [name for name, _ in registry.calls]
    assert called == ["query_memory", "list_decisions_for_content", "get_decision_lineage"]
    assert registry.calls[1][1].get("content_id") == "c-1"
    ep = build_package(state)["evidence_package"]
    linked = [i for i in ep["items"]
              if i["source"]["tool"] == "list_decisions_for_content"]
    assert linked and linked[0]["kind"] == "decision_record"
    assert linked[0]["authority"] == {"level": "curated", "human_gated": True}
    assert ep["lineage"], "restored follow-up must surface the lineage chain"


def test_explain_topic_unlinked_evidence_skips_lineage():
    registry = Registry({
        "query_memory": {"answer": "…", "status": "ok", "confidence": 0.7,
                         "no_context": False, "citations": [],
                         "evidence": [{"content_id": "c-1", "snippet": "note…"}],
                         "fallback": {"suggested": False}},
        "list_decisions_for_content": _BY_CONTENT_MISS,
        "get_decision_lineage": {"decision_id": "x"},
        "memory_lab_retrieval_search": {"results": []},
    })
    state = execute(route("what do we know about queues?"), registry)
    called = [name for name, _ in registry.calls]
    assert "get_decision_lineage" not in called
    lineage = [t for t in state.trace if t.tool == "get_decision_lineage"]
    assert lineage and lineage[0].outcome == "skipped" and lineage[0].condition == "DECISION_LINKED"


def test_historical_skips_successor_chase():
    registry = Registry({
        "memory_lab_retrieval_search": {"results": [{"content_id": "old-1", "text": "…"}]},
        "memory_lab_content_get": {"content_id": "old-1", "is_current": False},
    })
    state = execute(route("which queue did we use previously, the current one aside?"), registry)
    assert state.plan.historical is True
    assert [n for n, _ in registry.calls].count("memory_lab_content_get") == 1


def test_diagnose_stops_on_unhealthy_and_respects_budget():
    registry = Registry({
        "memory_lab_health": {"status": "unavailable", "reason": "database_url_not_configured"},
        "list_decision_conflicts": {"conflicts": []},
        "memory_lab_edge_list": {"edges": []},
        "list_hubs": {"hubs": []},
    })
    plan = route("is memory healthy?")
    assert plan.max_calls == MAX_CALLS_DIAGNOSE
    state = execute(plan, registry)
    assert [n for n, _ in registry.calls] == ["memory_lab_health"]
    skipped = [t for t in state.trace if t.outcome == "skipped"]
    assert len(skipped) == 3 and all(t.condition == "HEALTHY" for t in skipped)


def test_budget_enforced_and_declared_in_gaps():
    plan = RoutePlan(intent="x", matched_by="exact", historical=False, user_intent="q",
                     steps=[PlanStep("memory_lab_health", {"n": i}, reason="r") for i in range(8)],
                     max_calls=6)
    registry = Registry({"memory_lab_health": {"status": "ok"}})
    state = execute(plan, registry)
    assert state.calls_made == 6
    assert any("budget" in g for g in state.gaps)


def test_no_repeat_guard():
    plan = RoutePlan(intent="x", matched_by="exact", historical=False, user_intent="q",
                     steps=[PlanStep("memory_lab_health", reason="r"),
                            PlanStep("memory_lab_health", reason="r")])
    registry = Registry({"memory_lab_health": {"status": "ok"}})
    state = execute(plan, registry)
    assert len(registry.calls) == 1
    assert state.trace[1].outcome == "skipped"


def test_tool_error_becomes_degradation_never_raises():
    registry = Registry({"get_decision_timeline": {"ok": False, "error": {"status_code": 500}},
                         "list_decision_conflicts": {"conflicts": []}})
    state = execute(route("what was decided recently?"), registry)
    assert any(d["type"] == "tool_error" for d in state.degradations)


# ---------------------------------------------------------------------------
# CF-001/004 — manifest-driven shape extraction (response_shape v0.2)
# ---------------------------------------------------------------------------

def test_rows_for_locates_every_inventory_shape():
    from reference_framework.executor import _rows_for

    row = {"content_id": "c-1"}
    # keyed_list family
    assert _rows_for("list_current_state_anchors", {"anchors": [row], "count": 1}) == [row]
    assert _rows_for("memory_lab_edge_list", {"edges": [row], "count": 1}) == [row]
    assert _rows_for("list_decisions", {"decisions": [row], "count": 1}) == [row]
    assert _rows_for("list_hubs", {"hubs": [row], "count": 1}) == [row]
    assert _rows_for("memory_lab_retrieval_search", {"results": [row], "count": 1, "result_count": 1}) == [row]
    # answer_envelope: evidence rows
    assert _rows_for("query_memory", {"answer": "x", "evidence": [row]}) == [row]
    # status_buckets: flat view wins; bucket fallback still works (CF-001 as data)
    both = {"decisions": [row], "active": [{"content_id": "dup"}], "superseded": [], "total": 1, "count": 1}
    assert _rows_for("get_decision_timeline", both) == [row]
    buckets_only = {"active": [row], "superseded": [], "reversed": [], "draft": [], "total": 1}
    assert _rows_for("get_decision_timeline", buckets_only) == [row]
    # graph_snapshot: both row arrays
    snap = {"nodes": [row], "edges": [{"source_hub_id": "h1"}]}
    assert len(_rows_for("get_graph_snapshot", snap)) == 2
    # bare list tolerance for unknown tools (test registries)
    assert _rows_for("not_a_tool", [row]) == [row]


def test_classify_outcome_is_shape_driven():
    from reference_framework.executor import _classify_outcome

    assert _classify_outcome("list_decisions", {"ok": False, "error": {}}) == "error"
    assert _classify_outcome("list_decisions", {"decisions": [], "count": 0}) == "empty"
    assert _classify_outcome("get_decision_timeline",
                             {"decisions": [], "active": [], "superseded": [],
                              "reversed": [], "draft": [], "total": 0, "count": 0}) == "empty"
    assert _classify_outcome("memory_lab_content_get", {"content_id": "c-1"}) == "ok"
    # lineage_tree is NOT empty-detectable: an empty chain is a valid answer
    assert _classify_outcome("get_decision_lineage",
                             {"decision_id": "d-1", "ancestors": [], "descendants": [],
                              "depth": 0}) == "ok"


def test_response_shape_coherence_rejected_by_loader():
    from reference_framework.manifest import ManifestError, _parse_response_shape

    with pytest.raises(ManifestError):
        _parse_response_shape("t", None)                       # required in v0.2
    with pytest.raises(ManifestError):
        _parse_response_shape("t", {"kind": "surprise_list"})  # closed vocabulary
    with pytest.raises(ManifestError):
        _parse_response_shape("t", {"kind": "keyed_list", "rows_keys": ["a", "b"], "count_key": "count"})
    with pytest.raises(ManifestError):
        _parse_response_shape("t", {"kind": "record", "rows_keys": ["rows"]})
    shape = _parse_response_shape("t", {"kind": "keyed_list", "rows_keys": ["items"], "count_key": "count"})
    assert shape.rows_keys == ("items",)


def test_latest_decisions_mints_flat_timeline_without_duplicates():
    # CF-001 closed: the kernel's flat `decisions` view is minted directly;
    # bucket rows are the SAME rows and must not double-mint.
    rows = [
        {"decision_id": "d-2", "title": "Second", "decision_status": "active"},
        {"decision_id": "d-1", "title": "First", "decision_status": "superseded"},
    ]
    registry = Registry({
        "get_decision_timeline": {"decisions": rows, "count": 2, "total": 2,
                                  "active": [rows[0]], "superseded": [rows[1]],
                                  "reversed": [], "draft": []},
        "list_decision_conflicts": {"conflicts": []},
    })
    state = execute(route("what was decided recently?"), registry)
    ep = build_package(state)["evidence_package"]
    minted = [i["source"]["source_id"] for i in ep["items"] if i["kind"] == "decision_record"]
    assert minted == ["d-2", "d-1"]


# ---------------------------------------------------------------------------
# Evidence Package — invariants
# ---------------------------------------------------------------------------

def _topic_state(ask_response):
    registry = Registry({
        "query_memory": ask_response,
        "memory_lab_retrieval_search": {"results": []},
    })
    return execute(route("what do we know about queues?"), registry)


def test_derived_answer_cites_package_items_and_is_derived_authority():
    state = _topic_state({
        "answer": "Based only on retrieved workspace evidence: [ev_1] …",
        "status": "ok", "confidence": 0.7, "no_context": False,
        "citations": [{"evidence_id": "ev_1"}],
        "evidence": [{"content_id": "c1", "snippet": "Decision: switch to RabbitMQ…",
                      "is_current": True, "current_state_scope": "message-queue",
                      "result_trust": "high", "confidence": 0.61}],
        "fallback": {"suggested": False},
    })
    ep = build_package(state)["evidence_package"]
    answers = [i for i in ep["items"] if i["kind"] == "derived_answer"]
    assert len(answers) == 1
    answer = answers[0]
    assert answer["statement_kind"] == "tool_derived"
    assert answer["authority"] == {"level": "derived", "human_gated": False}
    item_ids = {i["item_id"] for i in ep["items"]}
    assert set(answer["derived_from"]) <= item_ids and answer["derived_from"]
    evidence = next(i for i in ep["items"] if i["kind"] == "content_evidence")
    assert evidence["currency"]["supersession_semantics"] == "unknown"
    assert evidence["trust"]["confidence_basis"] != "none reported"


def test_no_context_is_honest_empty_with_fallback_step():
    state = _topic_state({
        "answer": "Insufficient workspace evidence…", "status": "insufficient_evidence",
        "confidence": 0.0, "no_context": True, "citations": [], "evidence": [],
        "fallback": {"suggested": True},
    })
    ep = build_package(state)["evidence_package"]
    assert [i for i in ep["items"] if i["kind"] == "derived_answer"] == []
    fired = [t for t in ep["execution_trace"]
             if t["tool"] == "memory_lab_retrieval_search" and t.get("condition_fired")]
    assert fired, "fallback pointer must trigger raw retrieval"
    assert any(d["type"] == "empty_result" for d in ep["degradations"])


def test_truncation_declares_gap():
    rows = [{"content_id": f"c{i}", "text": f"evidence {i}"} for i in range(60)]
    registry = Registry({
        "query_memory": {"answer": "", "status": "insufficient_evidence", "no_context": True,
                         "citations": [], "evidence": [], "confidence": 0.0,
                         "fallback": {"suggested": True}},
        "memory_lab_retrieval_search": {"results": rows},
    })
    state = execute(route("what do we know about everything?"), registry)
    ep = build_package(state)["evidence_package"]
    assert len(ep["items"]) == 50
    assert any("truncated: 10 items omitted due to max_items=50" in g for g in ep["gaps"])


def test_pure_write_emits_trace_only_package():
    registry = Registry({
        "create_decision_memory": {"decision_id": "d1", "decision_status": "active"},
    })
    state = execute(route("record decision: cap webhook retries at 6"), registry)
    ep = build_package(state)["evidence_package"]
    assert ep["items"] == []                       # receipts are not evidence (EP vote 4)
    assert ep["execution_trace"], "trace must exist even for pure writes"
    assert ep["intent"]["intent_name"] == "save_memory"


def test_conflicts_never_resolved():
    registry = Registry({
        "get_decision_timeline": {"decisions": [
            {"decision_id": "d1", "title": "A", "decision_status": "conflicted"}]},
        "list_decision_conflicts": {"conflicts": [{"candidate_id": "cc1", "severity": "high"}]},
    })
    state = execute(route("what was decided recently?"), registry)
    ep = build_package(state)["evidence_package"]
    assert ep["conflicts"], "conflicted timeline must surface conflicts"
    assert all(c["resolution"] == "none" for c in ep["conflicts"])


def test_intent_block_carries_matched_by_and_historical():
    registry = Registry({
        "query_memory": {"answer": "", "status": "insufficient_evidence", "no_context": True,
                         "citations": [], "evidence": [], "confidence": 0.0,
                         "fallback": {"suggested": False}},
    })
    state = execute(route("tell me about what happened previously with queues"), registry)
    ep = build_package(state)["evidence_package"]
    assert ep["intent"]["historical"] is True
    assert ep["intent"]["matched_by"] in ("exact", "fallback")
    assert ep["intent"]["user_intent"].startswith("tell me about")
