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

Only the question and an opaque task identifier appear in the public task envelope. Family, structure, scale, required experts and dependency graphs remain in the evaluator bundle.

## Structure and scale

- **C1 · Parallel composition:** independent work can proceed separately and must be integrated into the answer.
- **C2 · Sequential dependence:** downstream work needs an earlier finding as its input or objective.
- **C3 · Clue-based expert discovery:** an earlier finding also identifies the expertise required for subsequent work.

S1 requires 2–3 experts, S2 requires 4–5, and S3 requires 6 or more. These are task requirements, not recruitment budgets. The method can recruit any number of the available members.

![Resource pool and taxonomy](../assets/figures/taxonomy.png)

## Execution and evaluation

The method chooses members, assigns work, exchanges contributions and produces its final answer. The runtime records those decisions without prescribing a protocol. The evaluator checks task outcome, source support, recruitment and progress along every annotated dependency for each C2/C3 query.

![Execution and evaluation](../assets/figures/workflow.png)

The four collaboration capabilities are expert selection, task orchestration, information transfer and result integration. Local solve rate is reported separately to distinguish failure to produce a correct contribution from failure to retain it. Full formulas, source checks and judgment handling are in [Evaluation](evaluation.md).

## Families and versions

The 2,766 questions contain two formulations of 1,383 base instances, grouped into 499 families. Keep all variants of a family together when making development and evaluation splits. Related formulations must not be treated as independent source problems when estimating task-level uncertainty.

Version 1.1.0 extends selected tasks and their supporting references to the 2–3 and 6–8 expertise ranges. Task and family identifiers remain stable, but modified questions and references require new runs. The runner and evaluator reject mismatched dataset versions. See [Data](data.md) for exact release statistics.

The runtime and evaluation contract are documented separately from data-release readiness. See [Release compatibility](release-status.md) for the available snapshot and frozen-reference requirements.
