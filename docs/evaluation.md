# Evaluation

MAScope evaluates final answers and collaboration traces using frozen source identifiers and literal term variants. No model participates in acceptance or stage decisions. Every result records the dataset version, reference version, reference hash and scorer version.

```bash
mascope verify-references --annotations data/evaluator
mascope evaluate \
  --runtime data/runtime \
  --annotations data/evaluator \
  --runs results/run-1 \
  --out results/eval-1
```

The evaluator requires schema 2.0 [frozen references](reference-format.md). Missing rules, inconsistent families or invalid checksums stop evaluation. See [Data](data.md#evaluation-inputs) for archive contents.

## Acceptance and coverage

For unit u of query q, b(q,u) is one if the answer contains an accepted exact source identifier and at least one registered variant from each required term group. Alternatives are checked independently: an identifier from one alternative cannot be combined with terms from another. Matching is literal and case-sensitive. Case, inflection and quantity variants must be listed before execution; no paraphrases are inferred while scoring.

- Query success is one exactly when every required unit passes b(q,u).
- Query evidence coverage is the fraction of its units that pass the same predicate.
- Aggregate success and coverage are arithmetic means over queries.

A failed query can therefore retain partial coverage. Acceptance checks specified content and provenance; it does not judge the reasoning that connects the contributions. Match records retain source identifiers, matched variants and character offsets.

## Expert selection

Let Rq be the required expert roles and Aq the distinct recruited agents for query q.

| Metric | Definition |
| --- | --- |
| Expert recall | (100 / N) × Σq matched roles(q) / \|Rq\| |
| Expert precision | (100 / N) × Σq matched roles(q) / \|Aq\| |

Both are **query-macro averages**. Precision is zero when no agent is recruited. Equivalent experts are alternatives for one role; maximum one-to-one matching prevents duplicate credit. High recall from recruiting the entire pool does not imply high precision. Neither selection metric enters the dependency-stage denominators.

## Dependency stages

Every edge ui → uj in `requirements[].depends_on` is scored independently. The complete benchmark specification contains 3,664 edge occurrences over 1,630 dependent queries. The scorer uses the actual graph in each validated reference, rather than a hard-coded edge count or a selected representative edge.

| Stage | Predicate on one edge |
| --- | --- |
| 1 · Ready | The team holds ui's finding and has recruited an expert for uj |
| 2 · Task orchestration | A later assignment to that expert contains uj's registered objective terms |
| 3 · Information transfer | All context visible to the recipient contains ui's identifier and required constraint terms |
| 4 · Local solve | The assigned expert produces uj with accepted identifier and preregistered terms |
| 5 · Result integration | The final answer contains uj's accepted identifier and terms |

A root unit is held after its owning expert retrieves its source. A unit with predecessors becomes available to subsequent work only after its incoming dependencies pass local solve. This prevents an upstream failure being charged again to successors that never became ready. Final integration is not required to make a local finding available to later work.

Assignments are `assign` events, local outputs are `local_output` events, and submission is a `submit` event. The earlier `work_start`, `contribution` and `final` names are accepted as input aliases. A group assignment identifies its recipients in `agent_ids`; it is evaluated for each eligible recipient. Carried artifacts must match previously recorded contributions. An output belongs to the interval after its assignment and before the expert's next assignment. Repeated attempts retain the deepest valid progression; readiness propagates from the earliest valid local result.

An uncited local output may match its preregistered terms when they uniquely identify the relevant unit. A wrong citation does not receive this fallback, and final acceptance always requires identifiers. An uncited output that remains ambiguous after matching is marked `undecided`, with a reason. Undecided edges are reported separately and excluded from both sides of the conditional ratios. Invalid or incomplete trace records are not silently converted to failures.

## Edge aggregation

Let nk count **decided edges**, across evaluated queries, that reach stage k.

| Output field | Value |
| --- | --- |
| `task_orchestration` | 100 × n2 / n1 |
| `information_transfer` | 100 × n3 / n2 |
| `local_solve` | 100 × n4 / n3 |
| `result_integration` | 100 × n5 / n4 |
| `dependency_survival` | 100 × n5 / n1 |

An edge contributes to a stage's denominator only after reaching the preceding stage. Two ready edges with one assigned produce 50% orchestration, even if they belong to the same query. No all-edges-per-query conjunction is applied. The four conditional rates multiply to dependency survival when all denominators are nonzero. A zero denominator produces `null`.

Reports include `dependency_counts` (n1–n5), `dependency_edges`, `decided_edges`, `undecided_edges`, `not_ready_edges`, and `dependent_queries`. C1 has no edges and does not enter process denominators. Results are also grouped by taxonomy cell, task structure and expertise scale. Expert and outcome metrics remain query averages within each group.

## Bypass diagnostics

At the first retrieval returning uj or an accepted equivalent to its owning expert, inspect previously received messages, assignments, passages and explicit shared-memory reads. Queued messages count only once included in readable assignment context; unread memory writes do not count. The edge is bypassed if neither ui's identifier nor any registered bound term was present. The expert's own generated text does not count as received content.

Each `edge_judgments[].bypass` records retrieval, the first retrieval event and the bypass decision. Missing bound-term annotations or incomplete passage logs yield an unknown decision rather than a presumed bypass. A later valid handoff can still make a previously bypassed edge pass the stage predicates.

## Costs and repeated runs

Provider-reported input and output tokens are counted once across planning, members, synthesis and memory. Retrieval calls are recorded separately; retrieved text is included in token usage when supplied to a model. Reaching either budget cap submits the latest answer retained with `hold_answer`, or an empty answer if none was retained, and preserves the measured trace without adding synthesis. In-flight call usage is recorded before cap submission. If token usage is unknown for any selected query, aggregate `mean_tokens` is `null`.

```bash
mascope summarize \
  --evaluations results/eval-1 results/eval-2 results/eval-3 results/eval-4 results/eval-5 \
  --out results/summary.json
```

Each repetition must use identical task IDs, dataset, scorer and reference hashes. Metrics are computed independently per repetition, then summarized by their mean and sample standard deviation. Missing or failed evaluations cannot be silently excluded. Hold out whole families when tuning and preserve family groups when resampling.

## Additional diagnostics

`cap_hit_share` counts queries reaching either the token cap or the model-call cap. The `by_scale.S3.cap_hit_share` field reports the S3 subset. `bypass.rate` uses all evaluated dependency edges as its denominator; it is null if the trace or annotations leave any bypass decision unknown.

Use `mascope evaluate ... --identifier-free` to rescore the same runs with the identifier requirement removed from final acceptance. The output includes strict success, identifier-free success, the gain in percentage points, and each rule's `dependency_success_drop`: 100 × (success on C1 − success on C2∪C3) / success on C1. A zero C1 success rate gives null. Local stage rules remain unchanged.

Per-query outputs `answered` and `graph_carried` describe final acceptance and whether all edges in a nonempty dependency graph reach stage 5. They do not supply stage-rate denominators.

## Legacy scoring

Schema 1.0 data can be evaluated explicitly with `--scorer semantic --judge-model MODEL`. This optional legacy mode calls a model and is not the deterministic benchmark protocol. The default scorer never contacts a model and rejects `--judge-model`.
