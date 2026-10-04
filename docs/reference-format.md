# Frozen references

Evaluation consumes `manifest.json` and `references.jsonl` from a separate directory. Keep the reference directory outside evaluated methods' inputs. Source identifiers and term variants are frozen before execution.

## Manifest

```json
{
  "schema_version": "2.0",
  "version": "FROZEN_REFERENCE_VERSION",
  "runtime_version": "MATCHING_RUNTIME_VERSION",
  "query_count": 2766,
  "family_count": 499,
  "dependency_edge_count": 3664,
  "files": {"references.jsonl": "SHA256_OF_REFERENCES"}
}
```

Counts are checked against the records. Complete reference sets require 3–7 queries per family. A deliberately exported subset must declare `"scope": "subset"`; it retains all family identifiers and still undergoes within-family consistency checks. A subset cannot pass full-release validation.

## Per-query fields

| Field | Content |
| --- | --- |
| `task_id`, `family_id`, `cell` | Query identity, family membership and taxonomy cell |
| `required_experts` | One primary agent ID per required role |
| `expert_roles` | Optional alternative agent IDs for each role |
| `requirements` | Information units, their sources, acceptance and dependencies |

Family members must share the units, required experts, accepted sources, term rules, taxonomy and dependency graph. A query is identified by its own `task_id`. Public `tasks.jsonl` records may carry `family_id` for partitioning; it is checked against reference membership during evaluation.

Each unit contains `id`, `claim`, `satisfying_agents`, `depends_on`, `acceptable_evidence`, `sources`, and `acceptance`. Dependencies are the complete set of predecessors, not a selected edge. C1 has an empty graph; C2 and C3 have at least one edge. Unknown units, duplicate edges and cycles are rejected.

## Literal rules

Each acceptance alternative lists source identifiers and AND-connected term groups; variants within a group are OR-connected. For example:

```json
{
  "acceptance": [{
    "evidence_ids": ["MS-0123456789AB"],
    "terms": [["30 s", "30 seconds"], ["read timeout"]]
  }],
  "objective_terms": [["check timeout", "review timeout"]],
  "constraint_terms": [["certificate verification", "TLS verification"]],
  "dependency_terms": {"r1": [["30 s", "30 seconds"]]}
}
```

The fragment illustrates the format, not a released task. A successor requires nonempty objective terms. A predecessor requires nonempty constraint groups. `dependency_terms` maps each incoming predecessor to the certified bound terms used in bypass diagnosis. Complete reference packages must supply this map for every dependent unit; the evaluator rejects a package that omits it. Each bound-term group must occur in every successor acceptance alternative and in the predecessor’s constraint groups. Binding endpoints must match the dependency graph.

An accepted source identifier has prefix `MS-` and twelve Crockford base-32 characters. Identifiers and literal variants are checked exactly; the evaluator never generates or extends acceptance rules. Equivalent source routes must be recorded explicitly and preserve the certified dependency graph.

## Validation

```bash
mascope verify-references --annotations "$MASCOPE_REFERENCES"
mascope verify-references --annotations "$MASCOPE_REFERENCES" --runtime data/runtime --release
```

The first command validates rules, checksums and family consistency. The second also checks the complete release inventory, public family labels, expert ownership and source identifiers against the runtime.
