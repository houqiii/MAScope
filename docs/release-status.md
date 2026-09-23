# Release compatibility

Code and data are versioned separately. The code provides deterministic whole-graph evaluation; the existing data snapshot remains available for execution and explicit semantic evaluation.

| Component | Available state |
| --- | --- |
| Runtime data v1.1.0 | 2,766 queries, 499 families, 51 communities, 11,018 required expert assignments |
| Dependency annotations v1.1.0 | 4,290 annotated edges over 1,630 dependent queries |
| Semantic scorer | Whole-graph diagnostics using the existing claim and source annotations |
| Deterministic scorer | Implemented and tested; requires schema 2.0 annotations |
| Frozen schema 2.0 data | Not included in the current download |

The deterministic data contract requires per-unit acceptance terms and surface variants, assignment-objective terms, predecessor-constraint terms, and benchmark-minted `MS-` identifiers. These annotations cannot be recovered reliably by renaming fields or extracting words automatically from a claim. The current download contains source-grounded claims and `ev_` identifiers, not these frozen rules.

The manuscript describes 3,664 certified dependencies and solve-based construction checks. The currently distributed snapshot instead contains 4,290 annotated dependencies and does not include the corresponding certification runs. The code does not relabel those annotations as certified, remove edges to match a target count, or synthesize validation outcomes. Existing code and data therefore do not by themselves reproduce the manuscript's reported measurements.

To publish the deterministic snapshot, supply reviewed frozen rules, align the corpora and references under the same identifier map, and supply the recorded construction outcomes. `verify-references` checks the scoring contract and graph validity. `certify_dependencies` checks exhaustive supplied solve records against the certification thresholds; it does not run experiments or certify semantic validity by itself. Publish the resulting archives under a new data version, preserving v1.1.0.

Only the benchmark environment, evaluation and construction utilities are included in this repository. Evaluated methods, framework adapters, memory algorithms and experimental result files are not included.
