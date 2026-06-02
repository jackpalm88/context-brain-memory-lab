import psycopg2
import psycopg2.extras
from typing import Optional, Set


class AliasStore:
    """
    Psycopg2-based store for the cb_aliases table.
    Provides approved alias → canonical node resolution before graph BFS.
    Always wrap calls with run_in_threadpool in async context.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
            self._conn.autocommit = True
        return self._conn

    def get_canonical(self, term: str) -> Optional[str]:
        """Return the canonical graph node for term, or None if no approved alias exists."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT canonical FROM cb_aliases
                WHERE LOWER(term) = LOWER(%s) AND status = 'approved'
                ORDER BY confidence DESC
                LIMIT 1
                """,
                (term,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def resolve_terms(self, terms: Set[str]) -> Set[str]:
        """
        For each term, add its canonical node (if an approved alias exists).
        Returns the original set plus all resolved canonicals.
        """
        conn = self._get_conn()
        if not terms:
            return set(terms)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT term, canonical FROM cb_aliases
                WHERE LOWER(term) = ANY(%s) AND status = 'approved'
                """,
                ([t.lower() for t in terms],),
            )
            rows = cur.fetchall()
        resolved = set(terms)
        for _term, canonical in rows:
            resolved.add(canonical)
        return resolved
