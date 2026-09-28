import importlib
import json
from pathlib import Path

from .environment import BudgetExceeded, Environment


def load_agent(entrypoint):
    module, name = entrypoint.rsplit(":", 1)
    agent = getattr(importlib.import_module(module), name)
    if not callable(agent):
        raise TypeError("Agent entrypoint must be callable")
    return agent


def run(
    dataset,
    agent,
    model,
    output,
    task_ids=None,
    token_budget=2000000,
    call_budget=256,
    resume=False,
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    tasks = (
        [dataset.task(x) for x in task_ids] if task_ids is not None else list(dataset)
    )
    if len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError("Duplicate task selection")
    for task in tasks:
        if not task.task_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Task ID cannot be used as an output filename")
        path = output / (task.task_id + ".json")
        if path.exists():
            if not resume:
                raise FileExistsError(path.name)
            previous = json.loads(path.read_text())
            expected_model = getattr(model, "model", type(model).__name__)
            if (
                previous.get("task_id") != task.task_id
                or previous.get("dataset_version") != dataset.manifest["version"]
                or previous.get("model") != expected_model
                or previous.get("runtime_version") != "2.0.0"
                or previous.get("decoding", {}) != getattr(model, "decoding", {})
                or previous.get("budget")
                != {"tokens": token_budget, "calls": call_budget}
            ):
                raise ValueError(
                    "Existing output has a different task or run configuration"
                )
            yield previous
            continue
        environment = Environment(dataset, task, model, token_budget, call_budget)
        try:
            result = agent(environment)
            if environment.export()["cap_hit"]:
                raise BudgetExceeded("Task budget exhausted")
            if environment.export()["answer"] is None and isinstance(result, str):
                environment.submit(result)
            if environment.export()["answer"] is None:
                raise ValueError("Agent did not submit an answer")
            record = environment.export()
        except BudgetExceeded:
            environment.submit_at_cap()
            record = environment.export("budget_exhausted", "BudgetExceeded")
        except Exception as exc:
            record = environment.export("error", type(exc).__name__)
        record["dataset_version"] = dataset.manifest["version"]
        pending = path.with_suffix(".tmp")
        pending.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        pending.replace(path)
        yield record
