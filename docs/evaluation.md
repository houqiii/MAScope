# Evaluation

## Inputs

Evaluation uses a runtime task, its recorded execution, and the matching version of the independent reference bundle. A complete evaluation expects one run for every task. Select a subset explicitly with `--task-ids`; missing run files are never silently dropped.

The reference defines necessary information units, accepted source alternatives, required specialists and a preregistered dependency for each sequential-dependence or expert-discovery task. The dependency is selected deterministically before agent execution. Equivalent expressions of the same base instance share the selected dependency.

## Metrics

All rates are percentages. A zero denominator produces `null`.

| Field | Definition |
| --- | --- |
| `success` | Fraction of tasks whose answer satisfies every necessary information unit and the overall task constraints |
| `information_coverage` | Mean fraction of necessary information units correctly expressed with accepted source support |
| `expert_coverage` | Required recruited specialists divided by all required specialist assignments |
| `selection_precision` | Required recruited specialists divided by all recruited specialists |
| `task_coordination` | Started successor work divided by dependencies whose predecessor finding and relevant expert were available |
| `information_transfer` | Successor work receiving usable evidence and constraints divided by started successor work |
| `result_integration` | Correct local results retained in the answer divided by produced correct local results |
| `mean_calls` | Mean number of attempted model calls per task |
| `mean_tokens` | Mean input plus output tokens across all execution phases |

Expert counts are micro-averaged over tasks. Process rates use the preregistered dependency from each dependent task. Information coverage is macro-averaged over tasks. The report includes the five cumulative dependency counts, dependent-task count and success by taxonomy cell.

## Semantic judgments

The judge receives the original task, required claims with accepted source text, the final answer, and the complete ordered execution trace. It determines whether requirements are satisfied and supported, whether global constraints hold, and which dependency stages were reached. The full prompt is `JUDGE_PROMPT` in `mascope.evaluation`.

Structured checks require all reference IDs exactly once, source support from retrieved and contributed evidence, five nested stage decisions, and real trace-event locators for positive stages. A fabricated citation or a citation with no supporting content does not count. Planning a step does not count as executing it. A message counts as usable input only when it reaches the actual executor's context.

Model judgments and their explanations are retained for inspection. Invalid responses receive explicit validation feedback, with at most three judge attempts per task. All attempts and their token usage are saved. Exhausted validation attempts stop evaluation and produce a `.failed.json` record rather than a negative task label. The caller selects the judge model explicitly and can compare judgments across models or replace the judge with a compatible adjudication service.

## Failures, costs and grouped analysis

Runtime errors count as unsuccessful tasks with zero final information coverage. Their available traces remain eligible for process inspection. Failed calls with unavailable provider usage keep token cost unknown; the aggregate token mean is `null` if any selected run has unknown usage. Evaluation-model token usage is stored separately from agent execution cost.

Task families and base-instance identifiers are provided in evaluation records. Use family-aware partitions when creating development sets or estimating uncertainty. The 2,766 task formulations comprise two expressions of each of 1,383 base instances; they are not 2,766 independent source problems.
