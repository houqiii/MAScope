# Evaluation

## Inputs and outputs

Evaluation requires a task, its recorded execution and the matching reference bundle. The default command expects a run for every task. Use `--task-ids` to select a subset explicitly; missing files are never silently removed from the denominator.

Each output record contains task and family identifiers, the dataset version, taxonomy cell, outcome, expert counts, dependency-stage decisions, execution usage and the full semantic judgment. `summary.json` aggregates the selected records. Judge calls and tokens remain separate from agent execution cost.

## Outcome, coverage and selection

| Field | Definition |
| --- | --- |
| `success` | Percentage of queries whose final answer satisfies every required unit and the overall task constraints |
| `evidence_coverage` | Mean percentage of required units correctly expressed and supported by accepted, observed evidence |
| `expert_recall` | Required specialists recruited, divided by all required specialist assignments |
| `expert_precision` | Required specialists recruited, divided by all recruited specialists |
| `mean_calls` | Mean number of attempted model calls per query |
| `mean_tokens` | Mean input plus output tokens per query, across planning, members, synthesis and memory |

Expert counts are micro-averaged over queries. Evidence coverage is macro-averaged over queries. Correct content without observed source support can satisfy an outcome requirement without counting toward evidence coverage. Recruiting every member can raise recall while reducing precision.

Per-task `evidence_coverage` is a fraction in [0, 1]. Aggregate reports express all rates in percent. A zero denominator is `null`, not zero.

## Dependency stages and capabilities

Each C2/C3 task has one dependency selected before execution. Its five stages are cumulative:

| Stage | Required event |
| --- | --- |
| 1 · Ready | The predecessor finding is available and a relevant downstream expert is recruited |
| 2 · Assigned | The necessary follow-up work starts at that expert after the predecessor finding |
| 3 · Informed | The executor receives usable predecessor evidence and key constraints |
| 4 · Solved | The expert produces a correct local result |
| 5 · Adopted | That result survives into the final answer |

Let `n1` through `n5` count queries reaching each stage. Reports provide:

| Field | Ratio | Interpretation |
| --- | --- | --- |
| `task_orchestration` | `100 × n2 / n1` | Ready work becomes an actual assignment |
| `information_transfer` | `100 × n3 / n2` | Assignments receive the information they need |
| `local_solve` | `100 × n4 / n3` | Informed experts produce correct local results |
| `result_integration` | `100 × n5 / n4` | Correct local results reach the answer |
| `dependency_survival` | `100 × n5 / n1` | Ready dependencies survive the whole chain |

When denominators are nonzero, dependency survival equals the product of the four conditional rates after converting percentages to fractions. `local_solve` is the agent-side reference; expert selection and the other three conditional stages define the four collaboration capabilities.

The report includes `dependency_counts`, `dependent_queries`, and the same metrics grouped under `by_cell`, `by_structure` and `by_scale`. C1 tasks have no selected dependency and therefore have `null` conditional process rates.

## Source checks and semantic judgments

The supplied evaluator uses a configurable semantic judge for content correctness and dependency-stage decisions. It receives the question, reference claims with accepted source text, final answer and ordered trace. `JUDGE_PROMPT` in `mascope.evaluation` specifies the judgment contract.

Programmatic validation requires every reference requirement exactly once; accepted evidence that was both retrieved and contributed; five nested stage decisions; and real event locators for positive stages. A citation identifier alone does not establish semantic support. Planning a step does not count as executing it, and a recorded message counts as usable input only when it reaches the executor's context.

Full judgments and reasons are saved. Invalid responses receive validation feedback, with at most three judge attempts per task. Exhausted attempts produce a `.failed.json` record and stop evaluation rather than assigning a negative task label. The judge model is selected explicitly and can be replaced by a compatible adjudication service. Source/trace validation is deterministic; semantic assessments depend on the chosen judge and should be audited when comparing systems.

## Repeated runs

```bash
mascope summarize \
  --evaluations results/eval-1 results/eval-2 results/eval-3 results/eval-4 results/eval-5 \
  --out results/summary.json
```

The summarizer checks that repetitions use identical task references and dataset versions. It computes each metric separately per repetition, then reports its mean, sample standard deviation and individual values. Standard deviation is `null` for a single repetition. It does not pool repeated tasks into a larger apparent sample.

Use separate result directories for independent repetitions. Control method-specific random seeds inside the supplied method and record its configuration alongside the run. The runtime does not impose or claim deterministic sampling at the model provider.

## Failures and cost

Runtime errors count as unsuccessful tasks with zero final evidence coverage; their traces remain available for process inspection. Failed calls with unavailable provider usage leave token cost unknown. If any selected task has unknown usage, `mean_tokens` is `null`; repeated-run summaries preserve this rather than silently discarding incomplete observations.

Memory calls made through `complete(phase="memory")` count toward execution cost. This allows the same evaluator to compare a method with and without memory while keeping the task set and other execution settings fixed.

## Migration from 1.0

Metric names are now `evidence_coverage`, `expert_recall`, `expert_precision` and `task_orchestration`, replacing `information_coverage`, `expert_coverage`, `selection_precision` and `task_coordination`. Summaries additionally include local solve, dependency survival and complete structure/scale breakdowns. New evaluations include dataset-version metadata needed for repeated-run validation.
