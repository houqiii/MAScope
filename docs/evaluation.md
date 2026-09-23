# Evaluation

MAScope reports outcome, expert selection, progress along the complete dependency graph, and execution cost. Every score records its dataset version, scorer version and reference hash. Results produced with different contracts must not be pooled.

## Deterministic evaluation

```bash
mascope verify-references --annotations /path/to/frozen-references
mascope evaluate \
  --runtime data/runtime \
  --annotations /path/to/frozen-references \
  --runs results/run-1 \
  --out results/eval-1
```

The default scorer makes no model calls. It requires schema 2.0 references with frozen source identifiers and term variants. It never infers missing terms, substitutes a model judge, or turns an invalid annotation into a failed task. The currently downloadable v1.1.0 annotations predate this contract; see [Release compatibility](release-status.md).

Each unit has one or more acceptance alternatives. An alternative requires at least one of its exact source identifiers and at least one registered surface variant from **every** term group. The identifier and terms must occur in the submitted answer. Matching is literal and case-sensitive: case, inflection and quantity variants must be listed explicitly. Alternatives are evaluated independently; terms from one cannot be combined with the identifier of another. Match records contain the accepted identifier and the exact matched terms and offsets. Unregistered paraphrases are misses.

## Outcome and expert selection

| Field | Definition |
| --- | --- |
| `success` | Percentage of queries for which every required unit passes acceptance |
| `evidence_coverage` | Mean percentage of accepted units per query |
| `expert_recall` | Mean, over queries, of matched required expert roles / required roles |
| `expert_precision` | Mean, over queries, of matched required expert roles / distinct recruited agents |
| `mean_calls` | Mean attempted model calls per query |
| `mean_tokens` | Mean input plus output tokens across all model-call phases |

Success and coverage use the **same unit predicate**. A failed query can have positive coverage. Recall and precision are macro averages across queries, not ratios of pooled expert counts. Recruiting nobody gives zero selection precision. Equivalent experts are represented as alternatives for a required role; a maximum one-to-one matching prevents one agent receiving credit for multiple roles or several equivalents receiving repeated credit for one role.

Per-task `evidence_coverage` is a fraction; aggregate rates are percentages. Empty conditional denominators produce `null`.

## The full dependency graph

All edges in `requirements[].depends_on` are evaluated. No representative edge is selected. Each edge has five nested stages:

| Stage | Trace predicate |
| --- | --- |
| Ready | A predecessor local output is available and an eligible downstream expert has been recruited |
| Task orchestration | A later assignment to that expert contains the successor's registered objective terms |
| Information transfer | That assignment carries the predecessor output, its accepted identifier and constraint terms |
| Local solve | The assigned expert subsequently produces the successor result with accepted source and terms |
| Result integration | The final answer contains the successor identifier and terms |

The native runtime records assignments as `work_start`, local outputs as `contribution`, and submission as `final`. A message alone is not an assignment or delivered input. Carried artifacts are checked against the original contribution. Local outputs belong to the interval after their assignment and before the next assignment to that expert. Repeated attempts are allowed: the deepest valid execution of an edge is retained. A local output without citations can match by its registered terms; an output with an incorrect citation does not receive this fallback. Final answers always require identifiers.

A query reaches stage k only if **every edge** reaches stage k. Let n1 through n5 count queries reaching the five stages:

| Field | Ratio |
| --- | --- |
| `task_orchestration` | 100 × n2 / n1 |
| `information_transfer` | 100 × n3 / n2 |
| `local_solve` | 100 × n4 / n3 |
| `result_integration` | 100 × n5 / n4 |
| `dependency_survival` | 100 × n5 / n1 |

The four conditional rates multiply to dependency survival when their denominators are nonzero. Edge-level decisions and event locators remain in `edge_judgments`; aggregation uses query-level stages. C1 has an empty graph and does not enter process-rate denominators. Reports also group results by taxonomy cell, structure and expertise scale.

## Costs and failures

All model calls, including controller, member, synthesis and memory calls, go through `complete`. Provider-reported input and output usage is counted once. Retrieval calls are counted separately in the run record; retrieved text passed to a model is charged through that model's input tokens. No estimated retrieval-token surcharge is added. Deployments with separately billed retrieval must supply their accounting policy alongside the run.

Budget exhaustion retains any answer already submitted and its measured trajectory; no additional synthesis call is inserted. Other runtime errors score as unsuccessful while retaining their trace. Failed calls with missing provider usage leave token cost unknown. If any selected task has unknown usage, aggregate `mean_tokens` is `null`.

## Semantic evaluation of the existing data snapshot

```bash
mascope evaluate \
  --runtime data/runtime --annotations data/evaluator \
  --runs results/run-1 --scorer semantic \
  --judge-model "$JUDGE_MODEL" --out results/semantic-eval-1
```

This explicit compatibility mode uses source/trace validation and a configurable content judge for v1.1.0 references. It checks **every annotated edge**, but its outcome predicate and content decisions differ from deterministic acceptance. Correct unsupported content can satisfy a semantic outcome requirement without increasing supported coverage. Its results are marked `semantic-full-graph-2` and are not interchangeable with deterministic results or the earlier single-edge scorer.

The judge must return every unit and every edge exactly once, five nested stage decisions per edge, and real event locators for positive stages. Invalid judgments receive validation feedback, at most three attempts; exhausted attempts produce `.failed.json` and stop evaluation. Judge usage is saved separately from execution cost.

## Repeated runs

```bash
mascope summarize \
  --evaluations results/eval-1 results/eval-2 results/eval-3 results/eval-4 results/eval-5 \
  --out results/summary.json
```

Each repetition must use the same task set, dataset, scorer and reference hashes. Metrics are computed separately per repetition, then summarized by their mean and sample standard deviation. One repetition has no estimated standard deviation. Missing runs or failed judgments are not silently removed. Keep both formulations of each base instance and all instances of a family together when making development splits or resampling tasks.
