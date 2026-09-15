# Data

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

`tasks.jsonl` contains only opaque task identifiers and natural-language queries. Each base instance has two equivalent formulations. `profiles.json` contains public specialist descriptions. Each file in `corpora` belongs to one specialist and contains source-linked records. The evaluator bundle holds family membership, taxonomy labels, information requirements, accepted evidence and selected dependencies.

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
