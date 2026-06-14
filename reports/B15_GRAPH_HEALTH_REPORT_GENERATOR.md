# B15 Graph Health Report Generator

Generated: 2026-06-14T11:44:10.994870+00:00Z

## Validation

- Report generator uses existing B15 service/models only
- No API wiring, no database dependency, no provider calls
- No graph mutation, no private CB access

## Scenarios

### healthy_connected_graph

- **status**: ok
- **health_score**: 100
- **component_scores**: {"topology_score": 25, "index_searchability_score": 30, "hub_recall_score": 25, "alias_hygiene_score": 10, "consistency_score": 10}
- **warnings count**: 0
- **findings count**: 0
- **alias candidates count**: 0
- **limitations**: ['no_alias_candidates_detected_from_provided_labels']

### missing_embedding_null_searchable

- **status**: degraded
- **health_score**: 35
- **component_scores**: {"topology_score": 10, "index_searchability_score": 5, "hub_recall_score": 0, "alias_hygiene_score": 10, "consistency_score": 10}
- **warnings count**: 2
- **findings count**: 0
- **alias candidates count**: 0
- **limitations**: ['no_alias_candidates_detected_from_provided_labels']

### hub_linked_not_searchable_or_retrieved

- **status**: degraded
- **health_score**: 40
- **component_scores**: {"topology_score": 10, "index_searchability_score": 10, "hub_recall_score": 0, "alias_hygiene_score": 10, "consistency_score": 10}
- **warnings count**: 2
- **findings count**: 2
- **alias candidates count**: 0
- **limitations**: ['no_alias_candidates_detected_from_provided_labels']

### alias_candidate_case

- **status**: degraded
- **health_score**: 57
- **component_scores**: {"topology_score": 10, "index_searchability_score": 30, "hub_recall_score": 0, "alias_hygiene_score": 7, "consistency_score": 10}
- **warnings count**: 1
- **findings count**: 0
- **alias candidates count**: 2
- **limitations**: []

### empty_graph

- **status**: limited
- **health_score**: 20
- **component_scores**: {"topology_score": 0, "index_searchability_score": 0, "hub_recall_score": 0, "alias_hygiene_score": 10, "consistency_score": 10}
- **warnings count**: 0
- **findings count**: 0
- **alias candidates count**: 0
- **limitations**: ['empty_graph_or_no_graph_data', 'no_content_index_state_provided', 'no_alias_candidates_detected_from_provided_labels']

## Scope Guard

- api_wiring: false
- report_generator: true
- pyproject_changes: false
- build_export: false
- provider_calls: false
- private_cb_access: false
- cb_write: false
- git_ops: false
