"""PR1B/P3C minimal MCP tool handlers mapped to API-backed calls."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, List

from .client import MemoryLabApiClient, MemoryLabApiError


def _client() -> MemoryLabApiClient:
    return MemoryLabApiClient.from_env()


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return MemoryLabApiClient.redact_sensitive(value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _structured_api_error(exc: MemoryLabApiError) -> Dict[str, Any]:
    safe_body = _redact(exc.body)
    body_json: Any = None
    if safe_body:
        try:
            body_json = _redact(json.loads(safe_body))
        except ValueError:
            body_json = None
    return {
        "ok": False,
        "error": {
            "type": "memory_lab_api_error",
            "message": _redact(str(exc)),
            "method": exc.method,
            "url": _redact(exc.url),
            "status_code": exc.status_code,
            "body": safe_body,
            "body_json": body_json,
        },
    }


def _call_api(fn, *args, **kwargs) -> Dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except MemoryLabApiError as exc:
        return _structured_api_error(exc)


def memory_lab_health() -> Dict[str, Any]:
    """Check Memory Lab API liveness.

    Returns service status, name and version. Call first when a tool sequence
    fails unexpectedly to distinguish backend-down from request errors.
    """
    return _call_api(_client().health)


def memory_lab_content_create_id(content: Optional[str] = None, scope_hint: Optional[str] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Save one content item to workspace memory and return its content_id.

    The save is governed: content is scored and low-signal text is discarded
    (persisted=false, mode=governed_discarded) — write substantive prose, and use
    decision:/finding: vocabulary for decisions and findings. Exact duplicates
    dedup by content hash. scope_hint explicitly pins the current-state scope
    (recommended when saving decisions) instead of automatic scope resolution.
    Read the response: it reports tier, classification and conflict escalations.
    """
    return _call_api(_client().content_create_id, content=content, scope_hint=scope_hint, workspace_id=workspace_id)


def memory_lab_content_get(content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch one stored content item by content_id, including its quick_summary
    and stored fields. Use memory_lab_retrieval_search to find content by text."""
    return _call_api(_client().content_get, content_id=content_id, workspace_id=workspace_id)


def set_quick_summary(content_id: str, quick_summary: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Set or replace the short human-readable quick_summary of an existing
    content item. Good summaries make retrieval results scannable for agents."""
    return _call_api(
        _client().set_quick_summary,
        content_id=content_id,
        quick_summary=quick_summary,
        workspace_id=workspace_id,
    )


def update_node_metadata(content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Read-only node metadata reader (no mutation).

    NOTE: despite the production-parity name, this tool does NOT mutate. It returns the
    content node's metadata and marks the response read_only=true / mutation="none". A
    real metadata update would require a dedicated PATCH endpoint (not implemented).
    """
    result = _call_api(_client().update_node_metadata, content_id=content_id, workspace_id=workspace_id)
    if isinstance(result, dict) and result.get("ok") is not False:
        result.setdefault("read_only", True)
        result.setdefault("mutation", "none")
    return result


def classify_content_node(content_id: str, node_type: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Assign a semantic node_type to a content item from a fixed vocabulary.

    IMPORTANT (honest contract): this is a CALLER-SPECIFIED, DETERMINISTIC assignment --
    NOT automatic/AI classification and NOT provider-backed. The name matches the
    production tool for MCP parity. Allowed node types: decision, fact, hypothesis,
    question, playbook, concept, source, task, event, raw_note.
    """
    return _call_api(_client().set_node_type, content_id=content_id, node_type=node_type, workspace_id=workspace_id)


def memory_lab_hub_create(
    title: str,
    hub_type: Optional[str] = None,
    description: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a knowledge hub (type: topic, project, system or concept_cluster).

    Hubs organize related content; their titles/aliases/related_terms feed both
    retrieval corroboration and automatic current-state scope resolution, so a
    well-named hub keeps decisions on the same topic in one supersession chain.
    """
    return _call_api(_client().hub_create, title=title, hub_type=hub_type, description=description, workspace_id=workspace_id)


def memory_lab_hub_get(hub_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch one hub by hub_id: title, type, description, aliases, related_terms
    and status. Use list_hubs to discover hub ids."""
    return _call_api(_client().hub_get, hub_id=hub_id, workspace_id=workspace_id)


def memory_lab_hub_link_content(hub_id: str, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Link an existing content item to a hub. Manual hub links are a curation
    signal: linked content earns a fixed recall boost in ranked retrieval."""
    return _call_api(_client().hub_link_content, hub_id=hub_id, content_id=content_id, workspace_id=workspace_id)


def memory_lab_edge_create(
    source_hub_id: str,
    target_hub_id: str,
    edge_type: str,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a manual (human-curated) relationship edge between two hubs with
    the given edge_type. Machine-proposed edges arrive separately as status
    'inferred' and go through approve_inferred_edge / reject_inferred_edge."""
    return _call_api(
        _client().edge_create,
        source_hub_id=source_hub_id,
        target_hub_id=target_hub_id,
        edge_type=edge_type,
        workspace_id=workspace_id,
    )


def memory_lab_edge_get(edge_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch one hub-to-hub relationship edge by edge_id, including its type,
    status (manual/inferred/archived), note, reason and confidence."""
    return _call_api(_client().edge_get, edge_id=edge_id, workspace_id=workspace_id)


def memory_lab_edge_list(
    hub_id: Optional[str] = None,
    include_archived: Optional[bool] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """List hub-to-hub relationship edges, optionally restricted to one hub.
    include_archived=true also returns archived (soft-deleted) edges."""
    return _call_api(_client().edge_list, hub_id=hub_id, include_archived=include_archived, workspace_id=workspace_id)


def memory_lab_edge_archive(edge_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Archive (soft-delete) a hub-to-hub edge. Archived edges leave the active
    graph but remain readable for audit; use update_hub_edge to change fields."""
    return _call_api(_client().edge_archive, edge_id=edge_id, workspace_id=workspace_id)


def memory_lab_retrieval_search(
    query: str,
    limit: Optional[int] = None,
    debug: Optional[bool] = None,
    only_clean: Optional[bool] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Search raw Memory Lab retrieval evidence.

    Public analogue of Context Brain `search_raw_chunks`. Returns the structured
    retrieval envelope introduced in M11C-2, including normalized evidence results
    with provenance, retrieval/ranking reasons, hub/graph matches, knowledge paths,
    score components, and distance when available.

    Parameters:
    - query: required free-text query.
    - limit: optional result cap forwarded to `/v1/retrieval/search`.
    - debug: optional flag; when true, returns safe `debug_metadata.stage_metrics`
      for adapter_search, normalize, deterministic retrieval, pgvector, hub inclusion,
      graph expansion, dedup/filtering, and degraded reasons. When false/omitted,
      the normal response stays clean and omits `debug_metadata`.
    - only_clean: compatibility flag accepted by the public API; currently reported
      in debug `filters_applied` as an accepted no-op rather than a private clean/dirty
      filter.
    - workspace_id: optional workspace override for the API request context.

    Note: API-level `memory_type`/`memory_types` filters exist on
    `/v1/retrieval/search`, but this MCP wrapper does not forward them in M11C-2-4;
    adding MCP filter parameters is a future behavior/shape change, not docs polish.
    """
    return _call_api(
        _client().retrieval_search,
        query=query,
        limit=limit,
        debug=debug,
        only_clean=only_clean,
        workspace_id=workspace_id,
    )



_QUERY_MEMORY_NO_CONTEXT_STATUSES = {"insufficient_evidence", "unsupported_intent", "no_context"}


def _enrich_query_memory_result(result: Any) -> Any:
    """Guarantee the OPENCB-M11C §5.2 six signals on a successful query_memory result.

    Additive enrichment only: existing AskResponse fields are preserved and three derived
    signals are added — has_citations, no_context (distinct from an error), and a fallback
    pointer to the deeper raw-retrieval tool. Structured API errors pass through unchanged so
    an error stays distinguishable from a no-context outcome.
    """
    if not isinstance(result, dict) or result.get("ok") is False:
        return result

    citations = result.get("citations") or []
    has_citations = bool(citations)
    status = result.get("status")
    no_context = (not has_citations) or status in _QUERY_MEMORY_NO_CONTEXT_STATUSES
    try:
        low_confidence = float(result.get("confidence", 0.0)) < 0.5
    except (TypeError, ValueError):
        low_confidence = True

    enriched = dict(result)
    enriched["has_citations"] = has_citations
    enriched["no_context"] = bool(no_context)
    enriched["fallback"] = {
        "recommended_tool": "memory_lab_retrieval_search",
        "reason": (
            "For graph/hub-aware retrieval, or when confidence is low or no workspace evidence "
            "grounded the answer, use raw retrieval."
        ),
        "suggested": bool(no_context or low_confidence),
    }
    return enriched


def query_memory(
    query: str,
    enable_provider_synthesis: bool = False,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask a question answered strictly from workspace memory (evidence-grounded).

    Returns the /v1/ask envelope: answer, citations, claims, confidence,
    plus derived signals has_citations, no_context (distinct from an error) and a
    fallback pointer to memory_lab_retrieval_search for low-confidence outcomes.
    Superseded memories are demoted below the current decision of the same
    current-state scope unless the question asks about history.

    enable_provider_synthesis=true requests provider-backed rewording of the
    deterministic answer. It takes effect only when the deployment gate
    (MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED) is on and a provider is configured;
    otherwise the response reports mode="degraded" with failure_reason
    "provider_disabled" and the deterministic answer is retained. The provider may
    only reword — citations stay bounded to retrieved workspace evidence.
    """
    kwargs: Dict[str, Any] = {"query": query, "workspace_id": workspace_id}
    if enable_provider_synthesis:
        kwargs["enable_provider_synthesis"] = True
    return _enrich_query_memory_result(_call_api(_client().ask, **kwargs))


def list_hubs(status: str = "active", workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """List the workspace's hubs filtered by status ('active' default, or
    'archived'). The usual entry point for discovering hub ids and topics."""
    return _call_api(_client().hub_list, status=status, workspace_id=workspace_id)


def update_hub(
    hub_id: str,
    title: Optional[str] = None,
    hub_type: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    related_terms: Optional[List[str]] = None,
    status: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update hub fields; only supplied fields change. Investing in aliases and
    related_terms pays off directly: they drive retrieval corroboration,
    edge-inference quality and automatic current-state scope resolution."""
    return _call_api(
        _client().hub_update,
        hub_id=hub_id,
        title=title,
        hub_type=hub_type,
        description=description,
        aliases=aliases,
        related_terms=related_terms,
        status=status,
        workspace_id=workspace_id,
    )


def update_hub_edge(
    edge_id: str,
    edge_type: Optional[str] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a hub-to-hub edge's type, status, note, reason or confidence;
    only supplied fields change. Use memory_lab_edge_archive to retire an edge."""
    return _call_api(
        _client().edge_update,
        edge_id=edge_id,
        edge_type=edge_type,
        status=status,
        note=note,
        reason=reason,
        confidence=confidence,
        workspace_id=workspace_id,
    )


def approve_inferred_edge(
    source_hub_id: str,
    target_hub_id: str,
    edge_type: str,
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
    note: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Approve a machine-proposed (inferred) hub edge, promoting it into the
    curated graph. This is the human gate of edge inference: nothing an agent or
    job proposes becomes curated without this call. Optional reason/confidence/
    note are recorded on the approved edge."""
    return _call_api(
        _client().approve_inferred_edge,
        source_hub_id=source_hub_id,
        target_hub_id=target_hub_id,
        edge_type=edge_type,
        reason=reason,
        confidence=confidence,
        note=note,
        workspace_id=workspace_id,
    )


def reject_inferred_edge(
    source_hub_id: str,
    target_hub_id: str,
    edge_type: str,
    reason: Optional[str] = None,
    note: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reject a machine-proposed (inferred) hub edge. Rejections are durable:
    the edge-inference job never silently resurrects a rejected proposal."""
    return _call_api(
        _client().reject_inferred_edge,
        source_hub_id=source_hub_id,
        target_hub_id=target_hub_id,
        edge_type=edge_type,
        reason=reason,
        note=note,
        workspace_id=workspace_id,
    )


def save_and_link_to_hub(
    content: str,
    save_purpose: str,
    hub_id: str,
    content_url: Optional[str] = None,
    quick_summary: Optional[str] = None,
    scope_hint: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Save one content item and link it to a hub in a single call (the daily
    write-path shortcut). quick_summary is persisted after the save; scope_hint
    explicitly pins the current-state scope (recommended for decisions).

    Honest contract: save_purpose and content_url have no counterpart in the
    public minimal API — they are accepted for production tool-signature parity
    and reported back as unsupported when supplied.
    """
    return _call_api(
        _client().save_and_link_to_hub,
        content=content,
        hub_id=hub_id,
        quick_summary=quick_summary,
        save_purpose=save_purpose,
        content_url=content_url,
        scope_hint=scope_hint,
        workspace_id=workspace_id,
    )


def get_graph_snapshot(include_inferred: bool = True, include_curated: bool = True, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Full graph snapshot: hub nodes + relationship edges, filterable by edge class.

    PUBLIC IMPROVEMENT over production (where include_inferred is a documented no-op):
    include_inferred returns machine-generated relationships; include_curated returns
    human-curated relationships. Both default True (full graph, backward compatible);
    both False yields no edges. (Which concrete edge origins count as machine-generated
    is an internal implementation detail, intentionally not part of this contract.)
    """
    return _call_api(
        _client().graph_snapshot,
        include_inferred=include_inferred,
        include_curated=include_curated,
        workspace_id=workspace_id,
    )


def list_graph_snapshot(include_inferred: bool = True, include_curated: bool = True, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Flag-forwarding alias of get_graph_snapshot (production parity: spec-canonical name)."""
    return get_graph_snapshot(include_inferred=include_inferred, include_curated=include_curated, workspace_id=workspace_id)


def load_graph_node_full(content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Load one content node in full graph context: content fields plus its hub
    memberships and graph neighborhood. Heavier than memory_lab_content_get —
    use search_graph_preview first to find the right node."""
    return _call_api(_client().graph_node_full, content_id=content_id, workspace_id=workspace_id)


def search_graph_preview(
    query: str,
    node_type: Optional[str] = None,
    hub_id: Optional[str] = None,
    limit: int = 10,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Search graph nodes by free text with optional node_type / hub_id filters.
    Returns a lightweight preview list for navigation; follow up with
    load_graph_node_full for the complete node."""
    return _call_api(
        _client().graph_search_preview,
        query=query,
        node_type=node_type,
        hub_id=hub_id,
        limit=limit,
        workspace_id=workspace_id,
    )


def create_decision_memory(
    title: str,
    decision_reason: str,
    decision_context: Optional[str] = None,
    why_this_matters: Optional[str] = None,
    decision_status: str = "active",
    reversible: bool = True,
    source_content_ids: Optional[List[str]] = None,
    linked_hub_ids: Optional[List[str]] = None,
    supersedes_decision_id: Optional[str] = None,
    alternatives_considered: Optional[List[Dict[str, Any]]] = None,
    contradicting_evidence: Optional[str] = None,
    confidence_level: str = "medium",
    decision_tags: Optional[List[str]] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a first-class decision node with reason, context, alternatives,
    confidence_level and lineage. Prefer this over a plain content save for
    decisions the workspace must track: supersedes_decision_id builds an explicit
    supersession chain (the old decision is marked superseded automatically),
    and explain_decision / get_decision_lineage read it back."""
    payload: Dict[str, Any] = {
        "title": title,
        "decision_reason": decision_reason,
        "decision_status": decision_status,
        "reversible": reversible,
        "confidence_level": confidence_level,
    }
    if decision_context is not None:
        payload["decision_context"] = decision_context
    if why_this_matters is not None:
        payload["why_this_matters"] = why_this_matters
    if source_content_ids is not None:
        payload["source_content_ids"] = source_content_ids
    if linked_hub_ids is not None:
        payload["linked_hub_ids"] = linked_hub_ids
    if supersedes_decision_id is not None:
        payload["supersedes_decision_id"] = supersedes_decision_id
    if alternatives_considered is not None:
        payload["alternatives_considered"] = alternatives_considered
    if contradicting_evidence is not None:
        payload["contradicting_evidence"] = contradicting_evidence
    if decision_tags is not None:
        payload["decision_tags"] = decision_tags
    return _call_api(_client().decision_create, payload, workspace_id=workspace_id)


def explain_decision(decision_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch one decision with its full explainability envelope: reason, context,
    why_this_matters, alternatives considered, contradicting evidence,
    confidence_level, status and lineage summary."""
    return _call_api(_client().decision_get, decision_id, workspace_id=workspace_id)


def list_decisions(
    status: Optional[str] = None,
    hub_id: Optional[str] = None,
    limit: int = 20,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """List decision nodes, optionally filtered by status and/or linked hub.
    Use get_decision_timeline for a chronological view across the workspace."""
    return _call_api(_client().decision_list, status=status, hub_id=hub_id, limit=limit, workspace_id=workspace_id)


def update_decision_status(decision_id: str, decision_status: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Transition a decision's lifecycle status (e.g. active → superseded or
    deprecated). For replacing a decision with a new one, prefer
    create_decision_memory with supersedes_decision_id so lineage is preserved."""
    return _call_api(
        _client().decision_update_status,
        decision_id=decision_id,
        decision_status=decision_status,
        workspace_id=workspace_id,
    )


def get_decision_lineage(decision_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the supersession lineage of one decision: the ancestors it replaced
    and the descendants that replaced it, with statuses and timestamps."""
    return _call_api(_client().decision_lineage, decision_id, workspace_id=workspace_id)


def list_decision_conflicts(workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """List computed contradiction candidates between decisions. Read-only and
    non-arbitrating: it surfaces potential conflicts for a human to resolve,
    it never decides which side is true."""
    return _call_api(_client().decision_conflicts, workspace_id=workspace_id)


def get_decision_timeline(
    hub_id: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = 50,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Chronological timeline of the workspace's decisions, newest first,
    optionally filtered by hub or comma-separated tags. The fastest way to
    answer 'what has been decided here recently?'."""
    return _call_api(_client().decision_timeline, hub_id=hub_id, tags=tags, limit=limit, workspace_id=workspace_id)


APPROVED_TOOLS = {
    "memory_lab_health": memory_lab_health,
    "memory_lab_content_create_id": memory_lab_content_create_id,
    "memory_lab_content_get": memory_lab_content_get,
    "set_quick_summary": set_quick_summary,
    "update_node_metadata": update_node_metadata,
    "memory_lab_hub_create": memory_lab_hub_create,
    "memory_lab_hub_get": memory_lab_hub_get,
    "memory_lab_hub_link_content": memory_lab_hub_link_content,
    "memory_lab_edge_create": memory_lab_edge_create,
    "memory_lab_edge_get": memory_lab_edge_get,
    "memory_lab_edge_list": memory_lab_edge_list,
    "memory_lab_edge_archive": memory_lab_edge_archive,
    "memory_lab_retrieval_search": memory_lab_retrieval_search,

    "query_memory": query_memory,
    "list_hubs": list_hubs,
    "update_hub": update_hub,
    "update_hub_edge": update_hub_edge,
    "approve_inferred_edge": approve_inferred_edge,
    "reject_inferred_edge": reject_inferred_edge,
    "save_and_link_to_hub": save_and_link_to_hub,
    "get_graph_snapshot": get_graph_snapshot,
    "list_graph_snapshot": list_graph_snapshot,
    "load_graph_node_full": load_graph_node_full,
    "search_graph_preview": search_graph_preview,
    "create_decision_memory": create_decision_memory,
    "explain_decision": explain_decision,
    "list_decisions": list_decisions,
    "update_decision_status": update_decision_status,
    "get_decision_lineage": get_decision_lineage,
    "list_decision_conflicts": list_decision_conflicts,
    "get_decision_timeline": get_decision_timeline,
    "classify_content_node": classify_content_node,
}
