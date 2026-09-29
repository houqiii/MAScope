# Integration

## Entry point

An agent is a Python callable `solve(environment)` that returns a final-answer string or calls `environment.submit(text, artifact_ids)`. Its planning, routing, communication and stopping rules belong to the caller.

`Environment.task` contains `task_id`, `query` and optional `family_id` metadata. The same answer-format sentence is appended to every query, asking for the identifiers of supporting passages. `Environment.profiles()` returns member identifiers, names, expertise descriptions and tags.

## Member operations

| Operation | Result |
| --- | --- |
| `recruit(agent_id)` | Registers a participating specialist |
| `ask(agent_id, instruction, inputs=(), top_k=8)` | Runs the frozen expert prompt with a retrieval tool loop and returns a contribution |
| `start_work(agent_id, instruction, inputs=(), carried_units=())` | Records an assignment and returns its complete visible context for custom execution |
| `search(agent_id, query, limit=8)` | Retrieves at most 8 records from that member's corpus |
| `fetch(agent_id, evidence_id)` | Reads one record owned by that member |
| `contribute(agent_id, text, evidence_ids=())` | Records a local contribution and validates its evidence ownership |
| `send(sender, recipient, text, artifact_ids=())` | Queues a message and resolved contribution attachments for the recipient |
| `complete(messages, phase="planning", agent_id=None)` | Calls the configured model and records its input, output and usage |
| `submit(text, artifact_ids=())` | Records the final answer and its supporting contributions |
| `export()` | Returns the dataset version, submitted answer, event trace and usage for evaluation |

`ask` accepts contribution IDs or previously returned contribution objects in `inputs`. These inputs are delivered to the receiving member and recorded verbatim. `send` queues the message text and resolved attachments for the addressed recipient. Its next `start_work` or `ask` receives these messages alongside explicit inputs and carried content. Queued messages have `delivery="queued"`; they count as read context when included in an assignment. The caller controls when the recipient works. Other recipients’ messages are not included.

`search` ranks question and accepted-answer text using BM25 (k1 = 0.9, b = 0.4), returning the top eight by default. Text is lowercased and tokenized with `[a-z0-9_+#.-]{2,}`; each distinct query term contributes once. Ties, including zero-score ties, are ordered by evidence identifier. Tags do not receive extra weight. The dataset record retains source metadata. Environment retrieval exposes the identifier, question and accepted-answer text. Search never exposes another member's corpus.

## Custom specialist execution

Use `start_work` to obtain the assigned inputs, `search` or `fetch` to access a specialist's records, `complete(phase="members", agent_id=...)` to execute its model call with those inputs, and `contribute` to register its result. Citations must refer to records retrieved by that member or delivered in colleague contributions. The trace preserves the original retrieval and subsequent delivery events.

Keep retrieved records in the owning member's execution context. Planning and synthesis receive public profiles and member contributions; they do not read local corpora directly. Route all execution-model calls through `complete` so that the trace and cost report remain complete.

Call `complete` for planning, member work, synthesis and memory operations, with the corresponding `phase`. Provider responses must include input and output token counts. A custom model object implements:

```python
from mascope import Completion

class Model:
    def complete(self, messages, max_tokens=4096, json_output=False) -> Completion:
        raise NotImplementedError
```

The runtime supports concurrent member calls. Shared trace identifiers and usage accounting are synchronized. A failed provider call is counted, and unavailable usage remains unknown. The runtime does not silently retry or substitute another model.

## Budgets and output

The default limits are 2,000,000 tokens and 256 model calls per task. Call admission checks remaining budget; token usage is checked again after each response. Reaching either limit stops execution at the response boundary and retains the measured cost, including in-flight calls. No further work or answer replacement is allowed after the cap. Budget exhaustion is recorded separately; any already submitted answer is scored as it stands. Configure limits with `--token-budget` and `--call-budget`.

Each run is written atomically as one JSON file. The record contains the dataset version, model identifier, task ID, answer, ordered events, configured budgets, status and usage. Exceptions produce an error record; they do not remove the task from evaluation.

## Reference separation

The runtime archive contains the public task envelope and member resources. The evaluator archive contains requirements, source alternatives, dependency annotations and frozen acceptance terms. Family membership may also be exposed as public partition metadata. Agent code should use only the runtime API. The local Python interface defines an information-access contract; process or container isolation must be supplied by deployments running untrusted agent implementations.

## Reproducible execution

The default transport requests temperature 0.3 and top-p 0.95. `--seed` is forwarded when supplied; provider support and reproducibility remain provider-dependent. Run records retain decoding settings and runtime version, and resume rejects changed settings. Retrieval calls are counted separately; their text enters token accounting when supplied to a model. The local runtime does not enforce a process security boundary.

## Canonical events and visible inputs

Exported traces use `recruit`, `assign`, `message`, `retrieve`, `local_output`, `aggregate`, `memory`, `submit`, and `usage`. An assignment's `carried_units` contains all content actually readable when work begins: delivered messages, supplied peer outputs, and the shared thread or board included in that prompt. A message existing elsewhere in a log does not establish delivery. Use `record_aggregate(text, artifact_ids, actor)` and `record_memory(module, operation, items, recipients=())` for those events and `complete` for their model costs. An explicit memory `read` supplies the recorded items to the named recipients and their next work context. A `write` does not deliver content, and an empty recipient list does not broadcast it. Custom execution must pass the full context returned by `start_work` into its member prompt.

`ask` uses the frozen `prompts/expert.txt` and the `retrieve(query)` tool scoped to the selected site. Tool calls, outputs and provider usage are retained. The benchmark supplies no single-agent or multi-agent method implementation.

Retrieval returns only the identifier, question and accepted-answer text to the caller. Attribution and licensing records remain in the data archives. Twelve optional [log adapters](../adapters/README.md) are provided outside the installed package. They convert caller-supplied logs after execution; the environment never imports them.

At a budget cap the runner submits the latest answer explicitly retained by `hold_answer(text)`, or an empty answer when none exists. It does not call a synthesis model after the cap. Retrieval operations have their own usage events; their text contributes tokens when it is sent to a model.
