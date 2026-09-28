# Log adapters

This directory contains twelve independent method-to-event mappings and their configuration records. It is outside `src/mascope`, is not installed in the benchmark wheel, and is never loaded by the environment. Each named subdirectory contains a configuration and the four protocol-specific event mappings.

```bash
python adapters/convert.py --method LangGraph --input native-events.jsonl --out events.jsonl
```

The input contract uses instrumentation hooks with explicit payloads. The four hooks for each method map to recruitment, assignment, aggregation and submission:

| Method | Recruit | Assign | Aggregate | Submit |
| --- | --- | --- | --- | --- |
| AutoGen | speaker_selected | speaker_prompt | closing_summary | termination |
| Magentic-One | ledger_specialist | next_speaker | progress_merge | final_answer |
| Flow | worker_allocated | node_dispatched | graph_merge | last_node |
| CrewAI | member_delegated | task_delegated | manager_synthesis | kickoff_result |
| LangGraph | worker_handoff | handoff_prompt | supervisor_merge | supervisor_answer |
| Anemoi | thread_member | plan_item | consensus_vote | answer_submission |
| AgentVerse | role_staffed | action_decided | evaluation_merge | result_accepted |
| MoA | first_layer_proposer | layer_prompt | aggregator_synthesis | aggregator_output |
| MAD | first_round_debater | revision_prompt | majority_vote | selected_answer |
| GoA | node_sampled | neighbor_prompt | pooling | pooled_response |
| AgentNet | route_target | forwarded_task | returned_merge | agent_answer |
| SelfOrg | initial_responder | predecessor_prompt | centroid_selection | selected_response |

Each hook carries `hook` and its payload. Recruitment needs `agent_id`. Assignment needs `agent_id`, `instruction` and `carried_units`, including every piece of context visible to the recipient. Aggregation and submission carry `text`. Canonical retrieval, message, local-output, memory and usage events can be interleaved. For pool-registered methods, registration alone does not create recruitment events; the first recorded invocation does. Staffed methods require the native staffing event.

```python
records = [
    {
        "hook": "handoff_prompt",
        "agent_id": "serverfault",
        "instruction": "Check the timeout",
        "carried_units": ["Peer finding [MS-0123456789AB]: timeout 30 s"],
    },
    {"hook": "supervisor_answer", "text": "Final answer"},
]
```

The shipped tests verify these payload contracts and preservation of visible inputs for all twelve mappings. Bindings to particular framework-native logger versions remain pending; the hook names are MAScope instrumentation names, not claims about unmodified vendor log formats. Each method's `config.json` records this separately as `native_revision` and `fixture_verified`.

Configuration records specify GoA's eight slots with repeated experts allowed, MAD's two rounds and majority vote, SelfOrg's 51 agents/top-2/three-round limit, MoA's three layers, and disabled cross-query memory for AgentNet. These describe the adapter's intended execution context, not an included implementation of those algorithms.
