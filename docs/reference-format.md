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

## Construction

`source_identifier(key, community, post, unit_index)` derives a stable keyed identifier. Generate and retain the private construction key outside the release, check collisions, and apply the resulting identifier map consistently to corpus records and references.

`certify_group(queries, units, corpora)` certifies a candidate family using frozen acceptance and the runtime retriever. Units supply their frozen `objective` and `finding`, accepted sources, and `term_kinds` identifying specific quantities, configuration keys, versions or components. A general concept cannot supply a bound term.

Certification checks:

1. Each acceptance term absent from the public queries and downstream source context (question, title and accepted answer) has exactly one supplying unit.
2. Every downstream source and equivalent is outside the top eight for the query battery without that supplier, and reachable with its finding.
3. All family queries pass, the predecessor finding includes its bound terms, and the resulting graph is acyclic.

The battery contains the whole question, its sentences and the objective stripped of bound terms, plus combinations with other candidates' findings. The saved certificate contains the battery, top-eight positions, input hashes and corpus checksums. A missing source, ambiguous binding, failed reach check or cycle rejects the candidate. Local-solvability runs are separate from certification.

Certification also retains the full BM25 positions for every probe in `rank_without` and `rank_with`. A failed reach check raises `DependencyCertificationError`; its `details` records the edge, every family query, its probe battery and measured positions. General abbreviations and source links cannot serve as bound terms, and a quantity requires an explicit unit in its registered variants.

```bash
mascope verify-references --annotations "$MASCOPE_REFERENCES"
mascope verify-references --annotations "$MASCOPE_REFERENCES" --runtime data/runtime --release
```

The first command validates rules, checksums and families. The second additionally checks the complete release inventory, public family labels, expert ownership, and source IDs against the runtime. It does not replace the recorded certification and solvability checks.

`bind_terms(source_id, target_id, groups, units, queries)` checks literal supplier uniqueness and absence from queries. `reach(corpus, evidence_ids, query_group, predecessor_finding)` returns real ranks both with and without the predecessor and records a failed check without replacing ranks with target values. `certify_group` is the strict family gate and rejects a group if any check fails.

`certification/edges.jsonl` stores per-edge measurements. `certification/returns.jsonl` stores construction records and their provenance. Full verification derives family graphs from the current queries, frozen rules and runtime corpora and compares each saved binding and rank with its recomputed value. Missing, duplicate, unverified or inconsistent edge records fail verification. For multiple accepted passages, `rank_without` is the nearest best rank and `rank_with` is the farthest best rank across the passages. Every passage must pass the top-eight reach condition.

Full verification also checks each profile's corpus size and twelve most frequent tags against the retained records. Tag-frequency ties use alphabetical order. Every required unit must name at least one source identifier in its owning corpus.

C3 discovery is checked on the certified graph: the downstream expert must rank outside the query’s top required-expert count and within the top three for the predecessor finding. A profile-ranking match alone does not certify a dependency.

Verification also checks the structure label of every family. An empty graph yields C1; a nonempty graph that passes discovery across its queries yields C3; the remaining nonempty graphs yield C2.
