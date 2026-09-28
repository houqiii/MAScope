# Data

Download the versioned archives without a login or access token:

```bash
mascope download --dest data
mascope verify --runtime data/runtime
mascope verify-references --annotations data/evaluator
```

## Release status

Version 2.0.0 is a reconstructed candidate. It contains 2,766 queries in 499 families, 11,018 unit occurrences and 3,664 declared dependency edges. Query families, expert-count distributions and graph structures match the included inventory specification.

Certification records contain measured BM25 ranks. Twelve edge-query checks pass individually; six edge occurrences in one family also pass the complete family gate. The other 3,658 edge occurrences require recomposition. The archive contains 126,566 source pairs across 51 corpora. Local-solvability sampling is pending for all 1,994 family-unit occurrences, and 112 within-family query pairs exceed the 0.90 MinHash threshold. Frozen acceptance rules and offline query compositions still require content review. These records support auditing and development; they do not establish a fully certified benchmark or reproduce experimental results.

The evaluator bundle includes `release_status.json`, per-edge checks, similarity records and discovery rankings. Recompute the inventory and inspect validation failures with:

```bash
mascope verify --runtime data/runtime --annotations data/evaluator \
  --paper data/evaluator/paper_record.json --out run_manifest.json
```

This command exits nonzero if a required property fails. Pending local-solvability coverage is reported separately. `verify-references` checks schema, checksums and family consistency; it does not certify task validity.

## Archive layout

```text
runtime/
  manifest.json
  tasks.jsonl
  profiles.json
  sources.json
  attribution.jsonl
  corpora/<site>.jsonl
  prompts/{expert,answer_format}.txt
evaluator/
  manifest.json
  references.jsonl
  families.jsonl
  certification/{edges,returns}.jsonl
  certification/summary.json
  local_solvability.jsonl
  discovery.jsonl
  query_similarity.jsonl
  changes.jsonl
  attribution.jsonl
  paper_record.json
  release_status.json
```

The public task envelope contains `task_id`, `family_id` and `query`. Families have 3–7 queries sharing units, expert requirements and a dependency graph. S1 requires 2–3 experts, S2 4–5, and S3 6–8. References and construction records remain outside method inputs.

The migration retained 1,256 questions, rewrote 1,361, retired 149 and added 149. Family mapping used cell and expert-count constraints. All retained corpus passages received keyed identifiers; the private key and old-to-new mapping are not distributed. `changes.jsonl` records individual query actions. Construction funnel summaries are labeled with their provenance, rather than presented as observed execution logs.

## Downloads and mirrors

The packaged release manifest pins archive byte sizes and SHA-256 hashes. Asset URLs use stable numeric GitHub identifiers. The downloader requests archive bytes directly, so it does not require source mirrors to implement GitHub Release pages.

Use `--component runtime` or `--component evaluator` for one bundle. To select a mirror, pass `--base-url` or set `MASCOPE_DATA_URL` to an HTTP(S) or local `file://` directory containing the pinned filenames. The same `mascope download --dest data` command works from an anonymous source snapshot that includes the current release manifest.

Version 1.1.0 remains available as a legacy schema 1.0 release. Its references support only the explicit semantic scorer. They cannot be substituted for schema 2.0 references.

## Source retrieval

Refresh public source posts independently:

```bash
mascope fetch-sources --manifest data/runtime/sources.json \
  --dest data/source-posts --site stackoverflow
```

Omit `--site` to fetch all communities. The command uses the public Stack Exchange answers API in batches of up to 100 IDs. `STACKEXCHANGE_API_KEY` is optional. Quota exhaustion stops the download; rerunning resumes saved evidence IDs. Removed posts are reported. Live source retrieval does not recreate authored benchmark questions or frozen annotations, and source text may have changed since the archived snapshot.

## Licenses

Source content retains its applicable Stack Exchange license and post links. Contributor attribution is included in each archive as `attribution.jsonl` and is omitted from agent-visible retrieval results. Keep attribution, post URLs and license records when redistributing either archive..

Task formulations and annotations are CC BY-SA 4.0. Each archive includes `DATA_LICENSE.txt`. The software's MIT license does not relicense third-party source content.
