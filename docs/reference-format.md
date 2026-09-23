# Frozen reference format

The deterministic evaluator consumes a separate directory containing `manifest.json` and `references.jsonl`. Keep it inaccessible to evaluated methods.

## Manifest

```json
{
  "schema_version": "2.0",
  "version": "YOUR_FROZEN_REFERENCE_VERSION",
  "runtime_version": "MATCHING_RUNTIME_DATA_VERSION",
  "query_count": 2766,
  "files": {"references.jsonl": "SHA256_OF_REFERENCES"}
}
```

The reference version identifies the annotation revision. The runtime version must match run records. Every output includes a hash of the exact reference used for that query.

## Per-query fields

| Field | Content |
| --- | --- |
| `task_id`, `family_id`, `instance_id`, `formulation`, `cell` | Task identity and partition metadata |
| `required_experts` | One primary member ID per required expert role |
| `expert_roles` | Optional list of alternative member IDs per role; defaults to singleton primary IDs |
| `requirements` | Nonempty list of information units |

Each information unit contains `id`, `claim`, `satisfying_agents`, `depends_on`, `acceptable_evidence`, `sources`, and `acceptance`. The complete graph is derived from `depends_on`; C1 has no edges and C2/C3 have at least one. Unknown predecessors, duplicate edges and cycles are rejected.

`acceptance` is a nonempty list of alternatives, each with `evidence_ids` and `terms`. An alternative requires one of its source identifiers and one variant from every term group. This illustrative fragment is a format example, not a benchmark annotation:

```json
{
  "acceptance": [{
    "evidence_ids": ["MS-0123456789AB"],
    "terms": [["30 s", "30 seconds"], ["read timeout"]]
  }],
  "objective_terms": [["check timeout", "review timeout"]],
  "constraint_terms": [["certificate verification", "TLS verification"]]
}
```

A successor needs nonempty `objective_terms`; a predecessor needs explicit `constraint_terms` (which may be an empty list if none are required). Surface variants are authored and frozen before execution. Neither the evaluator nor a model expands them at scoring time. Equivalent source alternatives are listed explicitly; all graph edges remain necessary under those alternatives.

## Construction utilities

`mascope.construction.source_identifier(key, community, post, unit_index)` produces `MS-` plus twelve Crockford base-32 characters using HMAC-SHA256. Generate the private key once, store it outside the release, check the resulting identifier map for collisions, and apply the same map to corpora and references. Do not mix identifiers from different releases.

`mascope.construction.certify_dependencies(unit_ids, full_results, withheld_results)` consumes ten boolean solve outcomes for each unit with all candidate findings supplied and ten for every ordered candidate-pair withholding condition. It retains a candidate edge when full-context success is at least 8/10 and withheld success is at most 1/10, then validates acyclicity. Preserve the underlying prompts, outputs, scorer decisions and execution metadata outside the runtime bundle; the boolean counts alone are not a substitute for that provenance.

```bash
mascope verify-references --annotations /path/to/frozen-references
```

This command validates annotation structure and checksums. It does not establish local solvability or causal necessity without the corresponding experiments.
