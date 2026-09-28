# Benchmark

MAScope studies whether specialist contributions survive the work needed to turn them into a complete answer. It separates the agent pool, the method that coordinates it, and the references used to evaluate the resulting trace.

## Expert environment

Each of the 51 agents represents a Stack Exchange community. Its public profile exposes its name, expertise and tags. Its local corpus contains source excerpts with provenance and licenses. All members use the same configured model; their accessible knowledge differs.

| Resource group | Communities |
| --- | ---: |
| Software & Web | 13 |
| Systems & Networks | 12 |
| Data & Computation | 10 |
| Hardware & Engineering | 7 |
| Natural & Spatial Sciences | 4 |
| Professional Practice | 5 |
| **Total** | **51** |

Recruitment makes a member available; it does not establish that the member performed useful work. A contribution carries both its content and the source identifiers it uses. Passing that contribution into a later assignment records the actual information available to its recipient.

## Task definition

A task consists of a public question and evaluator-side references:

| Component | Meaning | Visibility |
| --- | --- | --- |
| Question | User goal, observations and requested output | Method |
| Required units | Necessary claims, satisfying experts and accepted evidence alternatives | Evaluator |
| Dependency graph | Required predecessor–successor relationships | Evaluator |
| Acceptance criteria | Required content and constraints applied to the final answer | Evaluator |

The public task envelope carries the question, an opaque task identifier and family membership for partitioning. Structure, scale, required experts and dependency graphs remain evaluator-side. Family identifiers are metadata, not instructions appended to the question.

## Structure and scale

- **C1 · Parallel composition:** independent work can proceed separately and must be integrated into the answer.
- **C2 · Sequential dependence:** downstream work needs an earlier finding as its input or objective.
- **C3 · Clue-based expert discovery:** an earlier finding also identifies the expertise required for subsequent work.

S1 requires 2–3 experts, S2 requires 4–5, and S3 requires 6–8. These are task requirements, not recruitment budgets. The method can recruit any number of the available members.

![Resource pool and taxonomy](../assets/figures/taxonomy.png)

## Execution and evaluation

The method chooses members, assigns work, exchanges contributions and produces its final answer. The runtime records those decisions without prescribing a protocol. The evaluator checks task outcome, source support, recruitment and progress along every annotated dependency for each C2/C3 query.

![Execution and evaluation](../assets/figures/workflow.png)

The four collaboration capabilities are expert selection, task orchestration, information transfer and result integration. Local solve rate is reported separately to distinguish failure to produce a correct contribution from failure to retain it. Full formulas, source checks and judgment handling are in [Evaluation](evaluation.md).

## Families

A family contains 3–7 queries that share information units, required experts, collaboration structure and the complete dependency graph. Questions differ in the observable symptoms they surface and in their wording. Keep an entire family on one side of any development/evaluation split.

The benchmark specification comprises 499 families and 2,766 queries: 26 families of size 3, 56 of size 4, 147 of size 5, 161 of size 6, and 109 of size 7. The 1,630 dependent queries carry 3,664 declared edges. Their measured certification status is recorded separately in the [data release](data.md#release-status). These are per-query edge occurrences; shared family graphs are scored separately for every executed query.

Reference validation checks family sizes, shared annotations and graph structure. A selected evaluation subset may contain fewer members, but must retain the original family identifiers and references.

## Dependency certification

Edges are derived from frozen acceptance terms. A downstream term absent from the question and its own source must have a unique supplying unit. The downstream source and its recorded alternatives must also stay outside the top eight BM25 results under a fixed query battery, and become reachable when the predecessor finding is supplied. Certification checks every ordered candidate pair and every query in the family. Ambiguous bindings, failed reach checks and cycles return the candidate group for revision.

The runtime and certification use the same BM25 ranking, with k1 = 0.9 and b = 0.4. Local solvability is a separate construction check; solve outcomes do not determine the dependency graph.

See [Data](data.md) for archive contents and [Evaluation](evaluation.md) for scoring.
