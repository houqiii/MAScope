import concurrent.futures
import json
import threading

import pytest

from mascope import Completion, Dataset, Environment, run
from mascope.environment import BudgetExceeded


class Model:
    def complete(self, messages, max_tokens=4096, json_output=False):
        if json_output:
            return Completion(
                json.dumps(
                    {
                        "text": "The blue route reaches the destination.",
                        "evidence_ids": ["alpha:1:2"],
                    }
                ),
                20,
                10,
            )
        return Completion("A response", 20, 10)


def test_public_envelope_and_local_ownership(dataset):
    task = next(iter(dataset))
    assert set(vars(task)) == {"task_id", "query"}
    environment = Environment(dataset, task, Model())
    with pytest.raises(KeyError):
        environment.fetch("alpha", "beta:1:2")
    with pytest.raises(ValueError):
        environment.contribute("alpha", "Unsupported", ["alpha:1:2"])
    result = environment.ask("alpha", "blue route")
    assert result["evidence_ids"] == ["alpha:1:2"]
    assert environment.export()["usage"]["tokens"] == 30


def test_unmatched_query_does_not_return_arbitrary_evidence(dataset):
    assert dataset.corpus("alpha").search("zzzznotpresent") == []
    with pytest.raises(ValueError):
        dataset.corpus("alpha").search("route", 200)


def test_explicit_input_delivery_and_stable_event_order(dataset):
    environment = Environment(dataset, next(iter(dataset)), Model())
    artifact = environment.ask("alpha", "blue route")
    environment.send("alpha", "beta", "Use this finding", [artifact["artifact_id"]])
    assert environment.export()["events"][-1]["kind"] == "message"
    environment.submit("The route is blue.", [artifact["artifact_id"]])
    events = environment.export()["events"]
    assert [e["event_id"] for e in events] == [
        f"e{i + 1:06d}" for i in range(len(events))
    ]
    with pytest.raises(ValueError):
        environment.submit("Second answer")


def test_call_budget_and_failed_provider_usage(dataset):
    environment = Environment(dataset, next(iter(dataset)), Model(), call_budget=1)
    environment.complete([])
    with pytest.raises(BudgetExceeded):
        environment.complete([])
    assert environment.export()["usage"]["calls"] == 1

    class FailedModel:
        def complete(self, *args):
            raise RuntimeError("Unavailable")

    failed = Environment(dataset, next(iter(dataset)), FailedModel())
    with pytest.raises(RuntimeError):
        failed.complete([])
    assert failed.export()["usage"]["tokens"] is None
    assert failed.export()["usage"]["calls"] == 1


def test_parallel_calls_do_not_hold_runtime_lock(dataset):
    barrier = threading.Barrier(2)

    class ParallelModel:
        def complete(self, *args):
            barrier.wait(timeout=3)
            return Completion("Done", 2, 3)

    environment = Environment(dataset, next(iter(dataset)), ParallelModel())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: environment.complete([]), range(2)))
    assert results == ["Done", "Done"]
    assert environment.export()["usage"]["tokens"] == 10


def test_budget_overrun_records_actual_usage(dataset):
    environment = Environment(dataset, next(iter(dataset)), Model(), token_budget=5)
    with pytest.raises(BudgetExceeded):
        environment.complete([])
    assert environment.export()["usage"]["tokens"] == 30


def test_runner_error_retention_resume_and_reset(dataset, tmp_path):
    output = tmp_path / "runs"

    def broken(environment):
        environment.recruit("alpha")
        raise RuntimeError("Private implementation detail")

    rows = list(run(dataset, broken, Model(), output))
    assert len(rows) == 2 and all(r["status"] == "error" for r in rows)
    assert all(len(r["events"]) == 1 for r in rows)
    assert "Private implementation detail" not in json.dumps(rows)
    assert list(run(dataset, broken, Model(), output, resume=True)) == rows
    with pytest.raises(FileExistsError):
        list(run(dataset, broken, Model(), output))


def test_hidden_fields_rejected_and_manifest_verified(dataset):
    row = {"task_id": "one", "query": "Question", "required_experts": ["alpha"]}
    (dataset.root / "tasks.jsonl").write_text(json.dumps(row))
    with pytest.raises(ValueError):
        Dataset(dataset.root)
    dataset.manifest["files"] = {"profiles.json": "wrong"}
    with pytest.raises(ValueError):
        dataset.verify()


def test_inherited_evidence_requires_actual_input_delivery(dataset):
    environment = Environment(dataset, next(iter(dataset)), Model())
    artifact = environment.ask("alpha", "blue route")
    environment.send("alpha", "beta", "Use this", [artifact["artifact_id"]])
    with pytest.raises(ValueError):
        environment.contribute("beta", "The route is blue", ["alpha:1:2"])
    inherited = environment.ask("beta", "route limit", inputs=[artifact])
    assert inherited["evidence_ids"] == ["alpha:1:2"]
    work = [e for e in environment.export()["events"] if e["kind"] == "work_start"][-1]
    assert work["inputs"][0]["agent_id"] == "alpha"
    with pytest.raises(KeyError):
        environment.start_work("beta", "fabricated", inputs=[{"artifact_id": "fake"}])
