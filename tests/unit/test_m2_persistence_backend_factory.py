import builtins

from memory_lab.persistence.factory import build_persistence_backend
from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend
from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend


def test_empty_env_selects_in_memory_backend(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    backend = build_persistence_backend()
    assert isinstance(backend, InMemoryPersistenceBackend)


def test_blank_database_url_selects_in_memory_backend(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "   ")
    backend = build_persistence_backend()
    assert isinstance(backend, InMemoryPersistenceBackend)


def test_database_url_selects_postgres_backend(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/test")
    backend = build_persistence_backend()
    assert isinstance(backend, PostgresPersistenceBackend)
    assert backend.database_url == "postgresql://example/test"


def test_explicit_database_url_overrides_empty_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    backend = build_persistence_backend("postgresql://example/explicit")
    assert isinstance(backend, PostgresPersistenceBackend)
    assert backend.database_url == "postgresql://example/explicit"


def test_empty_env_path_does_not_import_psycopg2_or_open_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "psycopg2" or name.startswith("psycopg2."):
            raise AssertionError("empty-env persistence factory must not import psycopg2")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    backend = build_persistence_backend()
    assert isinstance(backend, InMemoryPersistenceBackend)


def test_postgres_backend_skeleton_fails_without_fake_success():
    backend = PostgresPersistenceBackend("postgresql://example/test")
    result = backend.get_content_record("ws1", "c1")
    assert result.ok is False
    assert result.error.code == "postgres_sql_persistence_not_implemented"
    assert result.metadata.requires_db is True
    assert result.metadata.live_backend_used is False
    assert "no fake/noop persistence" in result.error.message
