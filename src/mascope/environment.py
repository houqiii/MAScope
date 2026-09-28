import re
from copy import deepcopy
from importlib.resources import files
from threading import Condition, RLock

from .context import content_text
from .dataset import Task
from .events import export_events
from .model import ResponseError

ANSWER_FORMAT = (
    files("mascope").joinpath("prompts/answer_format.txt").read_text().strip()
)


class BudgetExceeded(RuntimeError):
    pass


class Environment:
    def __init__(self, dataset, task, model, token_budget=2000000, call_budget=256):
        if token_budget < 1 or call_budget < 1:
            raise ValueError("Budgets must be positive")
        self.task = Task(
            task.task_id, task.query + "\n\n" + ANSWER_FORMAT, task.family_id
        )
        self._dataset = dataset
        self._model = model
        self._token_budget = token_budget
        self._call_budget = call_budget
        self._events = []
        self._members = set()
        self._artifacts = {}
        self._fetched = {}
        self._received = {}
        self._inbox = {}
        self._answer = None
        self._held_answer = None
        self.execution_mode = "multi_agent"
        self._tokens = 0
        self._calls = 0
        self._unknown_usage = 0
        self._lock = RLock()
        self._pending = Condition(self._lock)
        self._active_calls = 0
        self._exhausted = False

    def _check_open(self):
        if self._exhausted:
            raise BudgetExceeded("Task budget exhausted")
        if self._answer is not None:
            raise ValueError("Final answer already submitted")

    def profiles(self):
        return self._dataset.profiles()

    def _event(self, kind, **payload):
        with self._lock:
            event = {
                "event_id": f"e{len(self._events) + 1:06d}",
                "kind": kind,
                **deepcopy(payload),
            }
            self._events.append(event)
            return event["event_id"]

    def recruit(self, agent_id):
        with self._lock:
            self._check_open()
            self._dataset.corpus(agent_id)
            if agent_id not in self._members:
                self._members.add(agent_id)
                self._event("recruit", agent_id=agent_id)

    @staticmethod
    def _passages(records):
        return [
            {
                "evidence_id": row["evidence_id"],
                "title": (
                    row["title"] + "\n" + row["question"]
                    if row.get("question")
                    else row["title"]
                ),
                "text": row["text"],
            }
            for row in records
        ]

    def _retrieval_usage(self, retrieve_event):
        self._event(
            "usage",
            call=retrieve_event,
            call_type="retrieval",
            prompt_tokens=0,
            completion_tokens=0,
        )

    def search(self, agent_id, query, limit=8):
        self.recruit(agent_id)
        records = self._passages(self._dataset.corpus(agent_id).search(query, limit))
        with self._lock:
            self._check_open()
            self._fetched.setdefault(agent_id, set()).update(
                r["evidence_id"] for r in records
            )
            event = self._event(
                "search",
                agent_id=agent_id,
                query=query,
                evidence_ids=[r["evidence_id"] for r in records],
                records=records,
            )
            self._retrieval_usage(event)
        return records

    def fetch(self, agent_id, evidence_id):
        self.recruit(agent_id)
        record = self._passages([self._dataset.corpus(agent_id).fetch(evidence_id)])[0]
        with self._lock:
            self._check_open()
            self._fetched.setdefault(agent_id, set()).add(evidence_id)
            event = self._event(
                "fetch", agent_id=agent_id, evidence_id=evidence_id, records=[record]
            )
            self._retrieval_usage(event)
        return record

    def complete(
        self,
        messages,
        phase="planning",
        agent_id=None,
        max_tokens=4096,
        json_output=False,
        tools=None,
    ):
        if phase not in {"planning", "members", "synthesis", "memory"}:
            raise ValueError("Unknown model-call phase")
        if agent_id is not None:
            self.recruit(agent_id)
        with self._lock:
            self._check_open()
            if self._calls >= self._call_budget or self._tokens >= self._token_budget:
                self._exhausted = True
                raise BudgetExceeded("Task budget exhausted")
            self._calls += 1
            self._active_calls += 1
            call_id = self._event(
                "model_start", phase=phase, agent_id=agent_id, messages=messages
            )
            output_limit = min(max_tokens, 4096, self._token_budget - self._tokens)
        try:
            reply = (
                self._model.complete(messages, output_limit, json_output)
                if tools is None
                else self._model.complete(
                    messages, output_limit, json_output, tools=tools
                )
            )
            input_tokens, output_tokens = reply.input_tokens, reply.output_tokens
            reply_text = reply.text
            reply_message = getattr(reply, "message", {})
        except Exception as exc:
            with self._lock:
                counts = exc.usage if isinstance(exc, ResponseError) else {}
                if counts:
                    self._tokens += counts["input_tokens"] + counts["output_tokens"]
                else:
                    self._unknown_usage += 1
                self._event(
                    "model_error",
                    call_id=call_id,
                    phase=phase,
                    error_type=type(exc).__name__,
                    **counts,
                )
                self._active_calls -= 1
                self._pending.notify_all()
                if self._calls >= self._call_budget or self._tokens >= self._token_budget:
                    self._exhausted = True
                    raise BudgetExceeded("Task budget exhausted") from exc
            raise
        with self._lock:
            self._tokens += input_tokens + output_tokens
            self._event(
                "model_end",
                call_id=call_id,
                phase=phase,
                agent_id=agent_id,
                text=reply_text,
                tool_calls=reply_message.get("tool_calls", []),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            self._active_calls -= 1
            self._pending.notify_all()
            if self._calls >= self._call_budget or self._tokens >= self._token_budget:
                self._exhausted = True
                raise BudgetExceeded("Task budget exhausted")
            return reply_text if tools is None else reply_message

    def send(self, sender, recipient, text, artifact_ids=()):
        if sender != "controller" and sender not in self._members:
            raise ValueError("Sender has not been recruited")
        if recipient != "controller":
            self.recruit(recipient)
        with self._lock:
            self._check_open()
            attachments = [deepcopy(self._artifacts[a]) for a in artifact_ids]
            payload = {"text": text, "attachments": attachments}
            event_id = self._event(
                "message",
                sender=sender,
                recipient=recipient,
                artifact_ids=list(artifact_ids),
                delivery="queued",
                **payload,
            )
            self._inbox.setdefault(recipient, []).append(
                {"event_id": event_id, **payload}
            )

    def contribute(self, agent_id, text, evidence_ids=()):
        self.recruit(agent_id)
        evidence_ids = list(dict.fromkeys(evidence_ids))
        available = self._fetched.get(agent_id, set()) | self._received.get(
            agent_id, set()
        )
        if not set(evidence_ids).issubset(available):
            raise ValueError("Contribution cites evidence not retrieved or received")
        with self._lock:
            self._check_open()
            artifact_id = f"a{len(self._artifacts) + 1:06d}"
            artifact = {
                "artifact_id": artifact_id,
                "agent_id": agent_id,
                "text": text,
                "evidence_ids": evidence_ids,
            }
            event_id = self._event("contribution", **artifact)
            self._artifacts[artifact_id] = {**artifact, "event_id": event_id}
            return deepcopy(self._artifacts[artifact_id])

    def start_work(self, agent_id, instruction, inputs=(), carried_units=()):
        self.recruit(agent_id)
        with self._lock:
            self._check_open()
            contributions = []
            for item in inputs:
                artifact_id = item if isinstance(item, str) else item["artifact_id"]
                contributions.append(deepcopy(self._artifacts[artifact_id]))
            context = deepcopy(
                [*contributions, *self._inbox.get(agent_id, []), *carried_units]
            )
            self._event(
                "work_start",
                agent_id=agent_id,
                instruction=instruction,
                inputs=contributions,
                carried_units=context,
            )
            self._received.setdefault(agent_id, set()).update(
                re.findall(
                    r"\bMS-[0-9A-Z]{12}\b",
                    content_text({"instruction": instruction, "carried_units": context}),
                )
            )
        return context

    def ask(self, agent_id, instruction, inputs=(), top_k=8):
        from .site_agent import specialist

        if top_k != 8:
            raise ValueError("The reference expert retrieves up to 8 passages")
        return specialist(self, agent_id, instruction, inputs)

    def record_memory(self, module, operation, items, recipients=()):
        recipients = list(recipients)
        with self._lock:
            self._check_open()
            if operation == "read":
                for recipient in recipients:
                    if recipient != "controller":
                        self._dataset.corpus(recipient)
            event_id = self._event(
                "memory",
                module=module,
                operation=operation,
                items=items,
                recipients=recipients,
            )
            if operation == "read":
                for recipient in recipients:
                    self._inbox.setdefault(recipient, []).append(
                        {"event_id": event_id, "content": deepcopy(items)}
                    )
                    self._received.setdefault(recipient, set()).update(
                        re.findall(r"\bMS-[0-9A-Z]{12}\b", content_text(items))
                    )
            return event_id

    def record_aggregate(self, text, artifact_ids=(), actor="controller"):
        with self._lock:
            self._check_open()
            if not set(artifact_ids).issubset(self._artifacts):
                raise ValueError("Unknown supporting contribution")
            return self._event(
                "aggregate",
                actor=actor,
                inputs=[deepcopy(self._artifacts[a]) for a in artifact_ids],
                output=text,
            )

    def hold_answer(self, text):
        if not isinstance(text, str):
            raise ValueError("Held answer must be text")
        with self._lock:
            self._check_open()
            self._held_answer = text

    def submit_at_cap(self):
        with self._pending:
            self._exhausted = True
            self._pending.wait_for(lambda: self._active_calls == 0)
            if self._answer is None:
                text = self._held_answer or ""
                self._answer = {"text": text, "artifact_ids": []}
                self._event("final", **self._answer, reason="budget_exhausted")

    def submit(self, text, artifact_ids=()):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Final answer must be nonempty text")
        with self._pending:
            self._pending.wait_for(lambda: self._active_calls == 0)
            self._check_open()
            if not set(artifact_ids).issubset(self._artifacts):
                raise ValueError("Unknown supporting contribution")
            self._answer = {"text": text, "artifact_ids": list(artifact_ids)}
            self._event("final", **self._answer)

    def export(self, status="completed", error_type=None):
        with self._lock:
            phases = {}
            for event in self._events:
                if (
                    event["kind"] in {"model_end", "model_error"}
                    and "input_tokens" in event
                ):
                    phase = phases.setdefault(
                        event["phase"], {"input_tokens": 0, "output_tokens": 0}
                    )
                    phase["input_tokens"] += event["input_tokens"]
                    phase["output_tokens"] += event["output_tokens"]
            return deepcopy(
                {
                    "schema_version": "1.0",
                    "task_id": self.task.task_id,
                    "status": status,
                    "error_type": error_type,
                    "model": getattr(self._model, "model", type(self._model).__name__),
                    "decoding": getattr(self._model, "decoding", {}),
                    "runtime_version": "2.0.0",
                    "execution_mode": self.execution_mode,
                    "answer": self._answer,
                    "events": export_events(self._events),
                    "cap_hit": status == "budget_exhausted"
                    or self._calls >= self._call_budget
                    or self._tokens >= self._token_budget,
                    "usage": {
                        "retrieval_calls": sum(
                            e["kind"] in {"search", "fetch", "retrieve"}
                            for e in self._events
                        ),
                        "calls": self._calls,
                        "tokens": self._tokens if not self._unknown_usage else None,
                        "known_tokens": self._tokens,
                        "calls_with_unknown_usage": self._unknown_usage,
                        "phases": phases,
                    },
                    "budget": {
                        "tokens": self._token_budget,
                        "calls": self._call_budget,
                    },
                }
            )
