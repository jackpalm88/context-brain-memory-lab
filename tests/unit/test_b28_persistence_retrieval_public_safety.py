from pathlib import Path

MODULE = Path("memory_lab/retrieval/persistence_handoff.py")
TEXT = MODULE.read_text()


def test_no_forbidden_runtime_access_or_imports_in_production_module():
    forbidden = tuple(
        "".join(parts)
        for parts in (
            ("DATABASE", "_", "URL"),
            ("os", ".", "environ"),
            ("psy", "copg"),
            ("sql", "alchemy"),
            ("req", "uests"),
            ("htt", "px"),
            ("url", "lib"),
            ("sock", "et"),
            ("open", "ai"),
            ("anth", "ropic"),
            ("Pro", "vider"),
            ("MCP", " ", "server"),
            ("Fast", "API"),
            ("API", "Router"),
            ("Dep", "ends"),
            ("mig", "rations"),
            ("ale", "mbic"),
        )
    )
    for pattern in forbidden:
        assert pattern not in TEXT


def test_no_backend_mutation_or_runtime_wiring_in_production_module():
    assert "put_content_record" not in TEXT
    assert "def get(" not in TEXT
    assert "def post(" not in TEXT
    assert "".join(("API", "Router")) not in TEXT


def test_model_index_terms_are_only_boundary_language():
    allowed_fragments = (
        "generate embeddings",
        "no_embedding_generation",
        "not_embedding_or_vector_retrieval",
        "uses_embeddings: bool = False",
        "uses_vector_db: bool = False",
        "no_vector_db_access",
        "use vector storage",
    )
    for line in TEXT.splitlines():
        lowered = line.lower()
        if "".join(("embed", "ding")) in lowered or "".join(("vec", "tor")) in lowered:
            assert any(fragment in line for fragment in allowed_fragments), line


def test_no_forbidden_affirmative_claims_in_production_module():
    forbidden_affirmative = tuple(
        "".join(parts)
        for parts in (
            ("production", " ", "ready"),
            ("production", " ", "retrieval"),
            ("live", " ", "memory", " ", "retrieval"),
            ("live", " ", "semantic", " ", "search"),
            ("searches", " ", "Context", " ", "Brain"),
            ("private", " ", "Context", " ", "Brain", " ", "parity"),
            ("Full", " ", "Context", " ", "Brain", " ", "ready"),
            ("DB-backed", " ", "retrieval"),
            ("DB-backed", " ", "production", " ", "persistence"),
            ("provider-backed", " ", "reasoning"),
            ("embeddings", " ", "generated"),
            ("vector", " ", "search"),
            ("MCP", " ", "production", " ", "ready"),
            ("GPT", " ", "Actions", " ", "production", " ", "ready"),
        )
    )
    for claim in forbidden_affirmative:
        assert claim not in TEXT


def test_required_negative_boundary_claims_are_present():
    required = (
        "not_live_memory_retrieval",
        "not_semantic_search",
        "not_db_backed_retrieval",
        "not_db_backed_production_persistence",
        "not_provider_backed_reasoning",
        "not_embedding_or_vector_retrieval",
        "not_private_context_brain_parity",
        "not_full_context_brain_parity",
        "not_api_or_mcp_runtime",
        "not_production_ready",
    )
    for claim in required:
        assert claim in TEXT
