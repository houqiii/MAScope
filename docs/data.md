# Data

The fixed benchmark snapshot is available from the [v1.1.0 GitHub Release](https://github.com/houqiii/MAScope/releases/tag/v1.1.0).

```bash
export MASCOPE_DATA_URL="https://github.com/houqiii/MAScope/releases/download/v1.1.0"
mascope download --base-url "$MASCOPE_DATA_URL" --dest data
mascope verify --runtime data/runtime
```

## Release layout

The release manifest packaged with the software specifies archive filenames, byte sizes and SHA-256 checksums. Supply the directory that hosts these archives with `--base-url` or `MASCOPE_DATA_URL`. HTTP, HTTPS and local `file://` directories are supported.

```text
runtime/
  manifest.json
  tasks.jsonl
  profiles.json
  sources.json
  corpora/
evaluator/
  manifest.json
  references.jsonl
```

`tasks.jsonl` contains only opaque task identifiers and natural-language queries. Each base instance has two equivalent formulations. `profiles.json` contains public specialist descriptions. Each file in `corpora` belongs to one specialist and contains source-linked records. The evaluator bundle holds family membership, taxonomy labels, information requirements, accepted evidence and dependency graphs.

## Source retrieval

The runtime bundle includes a source manifest identifying each source answer and its community. Fetch current source records independently:

```bash
mascope fetch-sources \
  --manifest data/runtime/sources.json \
  --dest data/source-posts \
  --site stackoverflow
```

Omit `--site` to fetch all communities. The command uses the public [Stack Exchange answers API](https://api.stackexchange.com/docs/answers-by-ids) in batches of up to 100 IDs. Set `STACKEXCHANGE_API_KEY` if available. Quota exhaustion stops the download; rerunning resumes from saved evidence IDs. Missing or removed posts are reported rather than replaced.

Downloaded source records retain the answer owner's public attribution, source URL, available license metadata and revision timestamps. Source text may change over time. Live source retrieval therefore produces a current-source corpus; it does not reproduce the archived text byte-for-byte or create the benchmark's authored task annotations.

## Licenses

Source question-and-answer content retains the applicable Stack Exchange content license. License versions depend on contribution and revision dates; consult the [source licensing information](https://stackoverflow.com/help/licensing) and linked post histories. The original contributors remain credited through the source records and post links. Extracted excerpts are marked in the distributed source records.

The software MIT license does not relicense source content. Keep source attribution and license information when redistributing a corpus.

Task formulations and benchmark annotations are distributed under CC BY-SA 4.0. Each archive includes `DATA_LICENSE.txt`.

## Version 1.1.0

| Required experts per query | Queries |
| --- | ---: |
| 2 | 686 |
| 3 | 458 |
| 4 | 928 |
| 5 | 12 |
| 6 | 478 |
| 8 | 204 |
| **Total** | **2,766** |

The release contains 11,018 required expertise assignments. A total of 662 question formulations receive additional, source-grounded requirements: 458 S1 queries gain one specialist and 204 S3 queries gain two. The nine taxonomy-cell counts, 499 family identifiers, two formulations per base instance and existing dependency annotations are preserved. The remaining 2,104 questions are unchanged.

These are task and annotation revisions, not relabelings of existing runs. The 119 extended families were checked for source support and consistency: 111 received a separate model review, while eight were authored and inspected directly against the retrieved sources in the release preparation session. This is model-assisted validation, not a human annotation study. Source ownership, dependency graphs, paired annotations, counts and archive integrity are checked programmatically. Modified tasks require new method executions and evaluations.

Evidence identifiers are release-specific opaque strings. Source post identifiers, URLs and attribution remain available in the corpus and source manifest. Treat evidence identifiers as opaque when integrating a method.

## Reference schema

An evaluator record contains:

```text
task_id                 Public task identifier
family_id               Family grouping for partitions and resampling
instance_id             Base instance shared by two formulations
formulation             1 or 2
cell                    C1S1 through C3S3
required_experts        Required member identifiers
requirements[]
  id                    Information-unit identifier
  claim                 Required, verifiable content
  satisfying_agents     Specialists that can supply the unit
  depends_on            Predecessor unit identifiers
  acceptable_evidence   Accepted source identifiers
  sources               Reference excerpts and source URLs
dependency              Legacy selected edge; ignored by the whole-graph scorers
```

References are evaluator inputs and must not be fed into method planning or member retrieval. Dataset manifests record the release version, counts and file checksums; run records include the version used for execution.

## Evaluation inputs

The v1.1.0 bundle contains 4,290 annotated edges in `requirements[].depends_on` across 1,630 dependent queries. The whole-graph evaluator checks all of these edges using `--scorer semantic --judge-model MODEL`. Solve-based dependency-certification records are not included in this release.

Deterministic scoring accepts separately supplied schema 2.0 references containing frozen source identifiers, acceptance terms, surface variants, objective terms and constraint terms. These annotations are not part of the v1.1.0 download. See [Reference format](reference-format.md) for the schema and [Evaluation](evaluation.md) for commands and scoring definitions.
