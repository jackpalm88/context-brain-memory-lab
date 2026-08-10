"""Different AI. Same brain. — one client saves a decision, another recalls it.

Requires a running OpenCB API (README quickstart):

    docker compose up --build
    python examples/decision_recall_demo.py

No provider keys needed — this exercises only the deterministic core.
Uses the `requests` library (already a package dependency).
"""

from __future__ import annotations

import sys

import requests

API_URL = "http://127.0.0.1:8088"


def save_decision_as_client_a() -> str:
    """Client A: record a decision with its rationale."""
    resp = requests.post(
        f"{API_URL}/v1/content",
        json={
            "content": (
                "Architecture decision: we chose PostgreSQL with pgvector for "
                "OpenCB persistence because it keeps deterministic fallback "
                "retrieval and vector KNN in one operational store. Rationale: "
                "single backup path, mature tooling, and the deterministic core "
                "must work without embeddings. Alternatives considered: a "
                "dedicated vector database was rejected for the operational "
                "overhead of running a second stateful service in self-hosted "
                "setups."
            )
        },
        timeout=15,
    )
    resp.raise_for_status()
    save = resp.json()
    if not save.get("persisted"):
        raise RuntimeError(f"save was not persisted — governed floor rejected it: {save}")
    print(f"[client A] saved content_id={save['content_id']} tier={save['tier']}")
    return save["content_id"]


def ask_as_client_b(question: str) -> None:
    """Client B: a different session, asking a grounded question."""
    resp = requests.post(f"{API_URL}/v1/ask", json={"question": question}, timeout=15)
    resp.raise_for_status()
    answer = resp.json()
    print(f"\n[client B] question: {question}")
    print(f"[client B] status: {answer['status']}")
    print(f"[client B] answer: {answer['answer']}")
    if answer.get("citations"):
        print(f"[client B] cited content ids: {[c['content_id'] for c in answer['citations']]}")


def main() -> int:
    try:
        requests.get(f"{API_URL}/health", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        print(f"OpenCB API not reachable at {API_URL} — is `docker compose up` running?\n{exc}")
        return 1

    save_decision_as_client_a()
    ask_as_client_b("What database did we choose for persistence and why?")
    ask_as_client_b("What is our Kubernetes ingress strategy?")  # honest empty
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
