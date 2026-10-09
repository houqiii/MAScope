# Data

## Dataset

| Field | Count |
| --- | ---: |
| Queries | 2,766 |
| Families | 499 |
| Required unit occurrences | 11,018 |
| Annotated dependency edges | 3,664 |
| Source pairs | 126,566 |

With the runtime and evaluator bundles under `data/`, verify archive integrity and reference formats:

```bash
mascope verify --runtime data/runtime
mascope verify-references --annotations data/evaluator
```

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
  local_solvability.jsonl
  discovery.jsonl
  attribution.jsonl
```

The public task envelope contains `task_id`, `family_id` and `query`. Families have 3–7 queries sharing units, expert requirements and a dependency graph. S1 requires 2–3 experts, S2 4–5, and S3 6–8. References and construction records remain outside method inputs.

Source identifiers are keyed and frozen with the data. Construction keys and identifier maps remain private.

## Loading archives

Use the runtime and evaluator archives together. Extract them into `data/runtime` and `data/evaluator`, respectively.

For archives hosted at an accessible HTTP(S) location or stored in a local directory, the downloader verifies their byte sizes and SHA-256 hashes against the bundled `release.json` manifest:

```bash
mascope download --base-url "$MASCOPE_DATA_URL" --dest data
```

Set `MASCOPE_DATA_URL` to the directory containing the filenames listed in the manifest. A local directory can be supplied as a `file://` URL. Use `--component runtime` or `--component evaluator` to load one bundle.

## Source retrieval

Refresh public source posts independently:

```bash
mascope fetch-sources --manifest data/runtime/sources.json \
  --dest data/source-posts --site stackoverflow
```

Omit `--site` to fetch all communities. The command uses the public Stack Exchange answers API in batches of up to 100 IDs. `STACKEXCHANGE_API_KEY` is optional. Quota exhaustion stops the download; rerunning resumes saved evidence IDs. Removed posts are reported. Live source retrieval does not recreate authored benchmark questions or frozen annotations, and source text may have changed since the archived snapshot.

## Licenses

Source content retains its applicable Stack Exchange license and post links. Contributor attribution is included in each archive as `attribution.jsonl` and is omitted from agent-visible retrieval results. Keep attribution, post URLs and license records when redistributing either archive.

Task formulations and annotations are CC BY-SA 4.0. Each archive includes `DATA_LICENSE.txt`. The software's MIT license does not relicense third-party source content.
