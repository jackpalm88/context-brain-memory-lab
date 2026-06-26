#!/usr/bin/env python3
"""M5 live end-to-end smoke for Context Brain Memory Lab (OPT-IN, real providers).

Proves the full real engine works end-to-end against a real DB + real provider keys:
  A) real OpenAI embedding call
  B) real Anthropic LLM call
  C) ingest synthetic content with real embeddings -> pgvector KNN retrieval ranks the
     semantically-correct item #1 (not recency)
  D) reasoning answer over freshly-ingested evidence using the real provider

This is NOT part of the hermetic deterministic gate. It needs live credentials and a
pgvector-capable Postgres, so it lives in scripts/ and is run manually.

Required environment (never logged):
  DATABASE_URL       postgresql DSN to a THROWAWAY pgvector Postgres (schema gets migrated)
  OPENAI_API_KEY     real OpenAI key (embeddings)
  ANTHROPIC_API_KEY  real Anthropic key (reasoning)
Optional:
  OPENAI_EMBEDDING_MODEL, ANTHROPIC_DEFAULT_MODEL

Throwaway DB example (the password is ephemeral and supplied only via DATABASE_URL):
  CN=cbml_m5 ; docker run -d --name $CN -e POSTGRES_PASSWORD=$(openssl rand -hex 12) \
      -e POSTGRES_DB=cbml_test -p 127.0.0.1::5432 pgvector/pgvector:pg16

Secrets are never printed; the DSN is masked in all output. Exit 0 = PASS, 2 = SKIP.
"""
from __future__ import annotations

import glob
import os
import pathlib
import sys
import uuid


def _mask_dsn(dsn: str) -> str:
    """Return the DSN with any credentials stripped (host/port/db only)."""
    try:
        scheme, rest = dsn.split("://", 1)
        hostpart = rest.split("@", 1)[1] if "@" in rest else rest
        return f"{scheme}://***:***@{hostpart}"
    except Exception:
        return "***"


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        print(f"SKIP: {name} not set - M5 live smoke is opt-in and needs live credentials.")
        sys.exit(2)
    return value


def main() -> int:
    dsn = _require_env("DATABASE_URL")
    _require_env("OPENAI_API_KEY")
    _require_env("ANTHROPIC_API_KEY")
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    print(f"M5 live smoke | DB={_mask_dsn(dsn)} | repo={repo_root}")

    import psycopg2

    from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
    from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend
    from memory_lab.persistence.results import ContentPersistenceRecord
    from memory_lab.providers.anthropic import AnthropicLLMBackend
    from memory_lab.providers.embedding_backend import EmbeddingRequest
    from memory_lab.providers.llm_backend import LLMRequest
    from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend
    from memory_lab.reasoning.models import ReasoningRequest
    from memory_lab.reasoning.service import answer_for_request

    # Migrate the throwaway DB to the full schema.
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    for path in sorted(glob.glob(str(repo_root / "migrations" / "*.sql"))):
        with conn.cursor() as cur:
            cur.execute(pathlib.Path(path).read_text(encoding="utf-8"))
    conn.close()
    print("migrations applied")

    # A) real OpenAI embedding
    emb = OpenAIEmbeddingBackend()
    assert emb.is_configured, "OpenAI backend not configured (missing key or sdk)"
    er = emb.embed_text(EmbeddingRequest(text="The capital of France is Paris."))
    assert er.is_ok and len(er.vector) > 0 and not er.degraded, "real OpenAI embedding failed"
    print(f"A. PASS real OpenAI embedding | dims={len(er.vector)} degraded={er.degraded}")

    # B) real Anthropic completion
    llm = AnthropicLLMBackend()
    assert llm.is_configured, "Anthropic backend not configured (missing key or sdk)"
    lr = llm.summarize(LLMRequest(
        prompt="Reply with the single word: pong",
        system="Answer with one word only.",
        max_tokens=10,
        temperature=0.0,
    ))
    assert not lr.degraded and (lr.text or "").strip(), "real Anthropic call failed/degraded"
    print(f"B. PASS real Anthropic | degraded={lr.degraded} text={(lr.text or '')[:40]!r}")

    # C) ingest with real embeddings -> pgvector KNN ranks the semantic match #1
    workspace_id = str(uuid.uuid4())
    backend = PostgresPersistenceBackend(
        dsn, embedding_backend=OpenAIEmbeddingBackend(), vector_embeddings_enabled=True
    )

    def _record(text: str) -> ContentPersistenceRecord:
        return ContentPersistenceRecord(
            content_id=str(uuid.uuid4()), workspace_id=workspace_id,
            text=text, title=text[:40], metadata={"m5": "live"},
        )

    paris = _record("The capital of France is Paris, a major European city on the Seine.")
    photo = _record("Photosynthesis is how plants convert sunlight into chemical energy.")
    saved_paris = backend.put_content_record(paris)
    saved_photo = backend.put_content_record(photo)
    assert saved_paris.ok and saved_photo.ok, "persistence put_content_record failed"
    assert saved_paris.metadata.uses_embeddings and saved_paris.metadata.uses_vector_db, \
        "real embeddings were not stored to the vector db"

    adapter = RetrievalAdapter(
        dsn, embedding_backend=OpenAIEmbeddingBackend(), pgvector_retrieval_enabled=True
    )
    results = adapter.search("Which city is the capital of France?", workspace_id=workspace_id, graph_boost=0.0)
    assert results and results[0]["retrieval_mode"] == "pgvector_knn", "retrieval not in pgvector_knn mode"
    assert results[0]["content_id"] == paris.content_id, "vector KNN did not rank the semantic match #1"
    print(f"C. PASS pgvector KNN | mode={results[0]['retrieval_mode']} top_is_semantic_match=True")

    # D) reasoning answer over freshly-ingested evidence using the real provider
    req = ReasoningRequest(workspace_id=workspace_id, query="What is the capital of France?",
                           enable_provider_synthesis=True)
    ans = answer_for_request(database_url=dsn, request=req, workspace_id=workspace_id,
                             provider_synthesis_enabled=True)
    assert ans.provider_metadata.attempted, "provider synthesis was not attempted"
    assert (ans.answer_candidate or "").strip(), "empty answer candidate"
    print(f"D. PASS grounded answer | mode={ans.mode} provider={ans.provider_metadata.provider} "
          f"evidence_refs={len(ans.evidence_refs)} degraded_reason={ans.degraded_reason}")
    print(f"   answer: {(ans.answer_candidate or '')[:160]!r}")

    print("\nM5 LIVE E2E: PASS - real OpenAI embeddings + real Anthropic + pgvector KNN + grounded answer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
