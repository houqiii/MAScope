# Integration

## Entry point

An agent is a Python callable `solve(environment)` that returns a final-answer string or calls `environment.submit(text, artifact_ids)`. Its planning, routing, communication and stopping rules belong to the caller.

`Environment.task` contains only `task_id` and `query`. `Environment.profiles()` returns member identifiers, names, expertise descriptions and tags.

## Member operations

| Operation | Result |
| --- | --- |
| `recruit(agent_id)` | Registers a participating specialist |
| `ask(agent_id, instruction, inputs=(), top_k=5)` | Retrieves local evidence, executes one specialist turn and returns a contribution |
| `start_work(agent_id, instruction, inputs=())` | Records an assignment and returns the supplied colleague contributions for custom execution |
| `search(agent_id, query, limit=5)` | Retrieves up to 20 records from that member's corpus |
| `fetch(agent_id, evidence_id)` | Reads one record owned by that member |
| `contribute(agent_id, text, evidence_ids=())` | Records a local contribution and validates its evidence ownership |
| `send(sender, recipient, text, artifact_ids=())` | Records a message between recruited members or the controller |
| `complete(messages, phase="planning", agent_id=None)` | Calls the configured model and records its input, output and usage |
| `submit(text, artifact_ids=())` | Records the final answer and its supporting contributions |

`ask` accepts contribution IDs or previously returned contribution objects in `inputs`. These inputs are delivered to the receiving member and recorded verbatim. `send` records a communication event; the caller controls when the recipient acts and which messages it receives. Pass the required contributions through `ask(inputs=...)` or include the message contents in the next `complete` call.

`search` uses deterministic inverse-document-frequency term matching with extra weight for tags. It returns no records for a query with no lexical matches. Each record contains an evidence identifier, title, tags, text and source URL. Search never exposes another member's corpus.

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

The default limits are 2,000,000 tokens and 256 model calls per task. Call admission checks remaining budget; token usage is checked again after each response. A response or concurrent batch that exceeds the token limit makes the run fail and retains the measured cost. Configure limits with `--token-budget` and `--call-budget`.

Each run is written atomically as one JSON file. The record contains the dataset version, model identifier, task ID, answer, ordered events, configured budgets, status and usage. Exceptions produce an error record; they do not remove the task from evaluation.

## Reference separation

The runtime archive contains the public task envelope and member resources. The evaluator archive contains requirements, source alternatives, task-family metadata and dependency annotations. Agent code should use only the runtime API. The local Python interface defines an information-access contract; process or container isolation must be supplied by deployments running untrusted agent implementations.
