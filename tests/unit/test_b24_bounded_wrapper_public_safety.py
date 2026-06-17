from pathlib import Path
WRAPPER_DIR=Path("memory_lab/wrappers")
FORBIDDEN_IMPORTS=("import requests","import httpx","import openai","import anthropic","import psycopg","import psycopg2","import asyncpg","import sqlalchemy","import pgvector","import chromadb","import qdrant","import pinecone","import weaviate","import socket","import subprocess","FastAPI","APIRouter","FastMCP")
FORBIDDEN_PATTERNS=("os.environ","DATABASE_URL","connect(","execute(","complete_json(","complete_text(","embed_text(","embed_batch(","search_memory(","ask_context_brain(","retrieve_context(","private_cb_search(")
MISLEADING=("production mcp ready","production gpt actions ready","full context brain ready","private context brain parity","live memory retrieval","live semantic search","queries your memory","searches context brain","provider-backed reasoning","real semantic extraction","db-backed retrieval","vector search","embeddings generated","production dlp","auth-ready production deployment")

def test_wrapper_modules_have_no_forbidden_imports_or_patterns():
    for path in WRAPPER_DIR.glob("*.py"):
        text=path.read_text()
        for item in FORBIDDEN_IMPORTS:
            assert item not in text, (path, item)
        for item in FORBIDDEN_PATTERNS:
            assert item not in text, (path, item)

def test_wrapper_wording_avoids_misleading_live_private_claims():
    text="\n".join(path.read_text() for path in WRAPPER_DIR.glob("*.py")).lower()
    for phrase in MISLEADING:
        assert phrase not in text
