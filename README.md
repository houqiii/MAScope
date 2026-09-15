# MAScope

A benchmark environment for multi-agent collaboration across 51 specialist communities.

MAScope provides 2,766 tasks, private member knowledge, source-linked contributions, execution traces and outcome-and-process evaluation. Bring your own agent system through a Python entrypoint.

## Installation

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Data

Data is distributed separately from the code. Set `MASCOPE_DATA_URL` to the directory containing the versioned release archives, then download and verify:

```bash
mascope download --base-url "$MASCOPE_DATA_URL" --dest data
mascope verify --runtime data/runtime
```

The downloader verifies the release's SHA-256 checksums before installation. `--component runtime` installs tasks, public profiles and member corpora. `--component evaluator` installs the independent evaluation references.

Public source posts can also be fetched directly from the Stack Exchange API:

```bash
mascope fetch-sources --manifest data/runtime/sources.json --dest data/source-posts
```

This command resumes completed records, respects API backoff and keeps source attribution. API responses reflect currently available post revisions. The versioned archives provide the fixed benchmark snapshot. See [Data](docs/data.md).

## Tasks

Tasks combine a collaboration structure with a required expertise scale.

| Structure | 2 experts | 4–5 experts | 6 experts | Total |
| --- | ---: | ---: | ---: | ---: |
| Parallel composition | 454 | 390 | 292 | 1,136 |
| Sequential dependence | 394 | 314 | 236 | 944 |
| Expert discovery | 296 | 236 | 154 | 686 |
| Total | 1,144 | 940 | 682 | 2,766 |

The tasks span 499 families and 10,152 required expertise assignments. Each task exposes a natural-language query and an opaque identifier. Evaluation references are loaded only by the evaluator.

```bash
mascope list --runtime data/runtime
```

## Connect an agent

Implement a callable that accepts an `Environment`. It can inspect public profiles, recruit specialists, request their work, exchange contributions and submit an answer. The environment records events and accounts for model calls.

```python
from mascope import Environment

def solve(environment: Environment):
    raise NotImplementedError
```

Replace the function body with your agent implementation and make its module importable. The [integration guide](docs/integration.md) describes every runtime operation and the model interface.

Configure an OpenAI-compatible chat-completions endpoint through `OPENAI_BASE_URL` and `OPENAI_API_KEY`. Select the model explicitly:

```bash
mascope run \
  --runtime data/runtime \
  --agent my_agent:solve \
  --model "$MODEL" \
  --out results/run
```

Use `--task-ids` for a subset and `--resume` to retain completed run files. Each task starts with a fresh member state.

## Evaluate

```bash
mascope evaluate \
  --runtime data/runtime \
  --annotations data/evaluator \
  --runs results/run \
  --judge-model "$JUDGE_MODEL" \
  --out results/evaluation
```

The evaluator returns task success, information coverage, expert coverage, selection precision, task coordination, information transfer, result integration, model calls and token consumption. It saves the semantic judgments and trace locators alongside the aggregate metrics. Judge costs are recorded separately. See [Evaluation](docs/evaluation.md).

## Development

```bash
python -m pip install -e '.[dev]'
python3 -m pytest -q
```

## License

The code is MIT licensed. Stack Exchange content retains its applicable [CC BY-SA license](https://stackoverflow.com/help/licensing), source URLs and contributor attribution. Source content and benchmark data are distributed separately from the software license.
