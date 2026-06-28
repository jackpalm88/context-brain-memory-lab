"""M10.3 — optional semantic enrichment (provider-neutral).

Produces topic/metadata annotations (topic_tags / meta_tags). The provider is
an implementation detail behind LLMBackend; with no configured provider it
falls back to a deterministic keyword extractor so the save path stays
deterministic and always succeeds. Never raises.
"""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-0000000000a1"
NEW = "00000000-0000-0000-0000-0000000000d2"


# ---- pure annotation logic ----

def test_sanitize_tags_drops_url_junk_short_and_dedupes():
    from memory_lab.ingestion.semantic_enrichment import sanitize_tags
    out = sanitize_tags(["Alpha", "alpha", "ab", "http://x.com", "linkedin", "Context Brain", "good_tag"])
    assert "alpha" in out
    assert out.count("alpha") == 1            # dedupe
    assert "ab" not in out                    # too short
    assert "context_brain" in out             # spaces -> underscores
    assert all("http" not in t and "." not in t for t in out)
    assert "linkedin" not in out              # junk


def test_split_topic_meta_and_limits():
    from memory_lab.ingestion.semantic_enrichment import _split_topic_meta, MAX_TOPIC_TAGS, MAX_META_TAGS
    tags = ["governance", "milestone", "audit", "release", "context", "brain", "memory",
            "alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
    topic, meta = _split_topic_meta(tags)
    assert len(topic) <= MAX_TOPIC_TAGS
    assert len(meta) <= MAX_META_TAGS
    assert "governance" in meta
    assert "context" in topic
    assert "governance" not in topic


def test_empty_content_yields_empty_mode():
    from memory_lab.ingestion.semantic_enrichment import annotate
    res = annotate("   ")
    assert res.mode == "empty"
    assert res.topic_tags == [] and res.meta_tags == []


# ---- deterministic fallback (no key) ----

def test_fallback_no_key_is_deterministic():
    from memory_lab.ingestion.semantic_enrichment import annotate
    from memory_lab.providers.noop import NoopLLMBackend
    body = "context brain memory milestone governance audit alpha beta gamma delta"
    r1 = annotate(body, llm_backend=NoopLLMBackend())
    r2 = annotate(body, llm_backend=NoopLLMBackend())
    assert r1.mode == "fallback"
    assert r1.topic_tags == r2.topic_tags and r1.meta_tags == r2.meta_tags
    assert "context" in r1.topic_tags
    assert "governance" in r1.meta_tags


def test_no_provider_call_when_backend_not_configured():
    from memory_lab.ingestion.semantic_enrichment import annotate
    spy = MagicMock()
    spy.is_configured = False
    annotate("context brain memory milestone alpha beta", llm_backend=spy)
    spy.complete_json.assert_not_called()


# ---- configured provider path ----

def test_fake_llm_configured_produces_enriched_annotations():
    from memory_lab.ingestion.semantic_enrichment import annotate
    from memory_lab.providers.fake import FakeLLMBackend
    backend = FakeLLMBackend()
    backend.preset_json = {"tags": ["alpha_topic", "governance", "http://junk.com", "ab", "milestone", "beta_topic"]}
    res = annotate("some content body", llm_backend=backend)
    assert res.mode == "enriched"
    assert "governance" in res.meta_tags
    assert "alpha_topic" in res.topic_tags
    assert all("http" not in t for t in res.topic_tags + res.meta_tags)


def test_degraded_llm_falls_back():
    from memory_lab.ingestion.semantic_enrichment import annotate
    from memory_lab.providers.fake import FakeLLMBackend
    from memory_lab.providers.failure import FailureCode
    backend = FakeLLMBackend()
    backend.preset_failure = FailureCode.TIMEOUT
    res = annotate("context brain memory milestone governance alpha beta", llm_backend=backend)
    assert res.mode == "fallback"
    assert res.topic_tags or res.meta_tags


def test_annotate_never_raises_on_bad_backend():
    from memory_lab.ingestion.semantic_enrichment import annotate
    boom = MagicMock()
    boom.is_configured = True
    boom.complete_json.side_effect = RuntimeError("kaboom")
    res = annotate("context brain memory alpha beta milestone", llm_backend=boom)
    assert res.mode == "fallback"


# ---- wiring into create_content_minimal ----

def _make_adapter():
    from memory_lab.api.services.api_adapter import ApiAdapter
    return ApiAdapter("postgresql://fake/fake")


class WiringCursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return {"content_id": NEW}


class WiringConn:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        pass


def _persist_event():
    ev = MagicMock()
    ev.scores.composite = 0.9
    ev.scores.quality = 0.9
    ev.scores.relevance = 0.9
    ev.scores.novelty = 0.9
    ev.circuit_open = False
    ev.fallback_reason = ""
    return ev


def test_new_content_writes_tags_and_response_exposes_them():
    from memory_lab.governance.tier_router import TierDecision
    adapter = _make_adapter()
    cur = WiringCursor()
    tier = TierDecision(tier="persistent", reason="ok", rule_id="T", should_persist=True)
    with patch.object(adapter, "_conn", lambda: WiringConn(cur)), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=_persist_event()), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=tier), \
         patch.object(adapter, "_run_classify_and_write", return_value={}):
        resp = adapter.create_content_minimal(
            content="context brain memory milestone governance alpha beta gamma", workspace_id=WS
        )
    sql = " || ".join(s for s, _ in cur.executed)
    assert "topic_tags" in sql
    assert "topic_tags" in resp and "meta_tags" in resp
    assert resp["created"] is True


def test_enrichment_failure_never_blocks_save():
    from memory_lab.governance.tier_router import TierDecision
    adapter = _make_adapter()
    cur = WiringCursor()
    tier = TierDecision(tier="persistent", reason="ok", rule_id="T", should_persist=True)
    with patch.object(adapter, "_conn", lambda: WiringConn(cur)), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=_persist_event()), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=tier), \
         patch.object(adapter, "_run_classify_and_write", return_value={}), \
         patch("memory_lab.api.services.api_adapter.annotate", side_effect=RuntimeError("boom")):
        resp = adapter.create_content_minimal(content="hello body text", workspace_id=WS)
    assert resp["created"] is True
    assert resp["persisted"] is True
