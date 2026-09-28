import concurrent.futures
import json
import threading

import pytest

from mascope import Completion, Dataset, Environment, run
from mascope.environment import BudgetExceeded


class Model:
    def complete(self, messages, max_tokens=4096, json_output=False, tools=None):
        if tools is not None:
            from mascope.model import ToolCompletion

            if messages[-1]["role"] != "tool":
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "lookup",
                            "type": "function",
                            "function": {
                                "name": "retrieve",
                                "arguments": '{"query":"route"}',
                            },
                        }
                    ],
                }
            else:
                message = {
                    "role": "assistant",
                    "content": "The blue route reaches the destination. [MS-000000000001]",
                }
            return ToolCompletion(message, 20, 10)
        if json_output:
            return Completion(
                json.dumps(
                    {
                        "text": "The blue route reaches the destination.",
                        "evidence_ids": ["MS-000000000001"],
                    }
                ),
                20,
                10,
            )
        return Completion("A response", 20, 10)


def test_public_envelope_and_local_ownership(dataset):
    task = next(iter(dataset))
    assert set(vars(task)) == {"task_id", "query", "family_id"}
    environment = Environment(dataset, task, Model())
    with pytest.raises(KeyError):
        environment.fetch("alpha", "MS-000000000002")
    with pytest.raises(ValueError):
        environment.contribute("alpha", "Unsupported", ["MS-000000000001"])
    result = environment.ask("alpha", "blue route")
    assert result["evidence_ids"] == ["MS-000000000001"]
    assert environment.export()["usage"]["tokens"] == 60


def test_bm25_zero_score_ties_are_stable(dataset):
    assert [
        r["evidence_id"] for r in dataset.corpus("alpha").search("zzzznotpresent")
    ] == ["MS-000000000001"]
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
        environment.contribute("beta", "The route is blue", ["MS-000000000001"])
    inherited = environment.ask("beta", "route limit", inputs=[artifact])
    assert inherited["evidence_ids"] == ["MS-000000000001"]
    work = [e for e in environment.export()["events"] if e["kind"] == "assign"][-1]
    assert work["inputs"][0]["agent_id"] == "alpha"
    with pytest.raises(KeyError):
        environment.start_work("beta", "fabricated", inputs=[{"artifact_id": "fake"}])


def test_retrieval_limit_matches_environment(dataset):
    import pytest

    with pytest.raises(ValueError, match="between 1 and 8"):
        dataset.corpus("alpha").search("route", limit=9)


def test_bm25_ranking_matches_independent_formula_and_ignores_tags(tmp_path):
    import math
    import re
    from collections import Counter

    from mascope.dataset import Corpus

    rows = [
        {
            "evidence_id": "a",
            "agent_id": "site",
            "title": "route",
            "text": "route route slow",
            "tags": [],
        },
        {
            "evidence_id": "b",
            "agent_id": "site",
            "title": "route",
            "text": "fast",
            "tags": [],
        },
        {
            "evidence_id": "c",
            "agent_id": "site",
            "title": "misc",
            "text": "slow other other other other",
            "tags": ["route", "route"],
        },
    ]
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    corpus = Corpus(path, "site")
    terms = [
        Counter(
            re.findall(r"[a-z0-9_+#.-]{2,}", (r["title"] + " " + r["text"]).lower())
        )
        for r in rows
    ]
    avg = sum(sum(c.values()) for c in terms) / len(terms)
    score = {}
    for row, c in zip(rows, terms):
        total = 0
        for term in ["route", "slow"]:
            df = sum(term in other for other in terms)
            tf = c[term]
            total += (
                math.log(1 + (3 - df + 0.5) / (df + 0.5))
                * tf
                * 1.9
                / (tf + 0.9 * (0.6 + 0.4 * sum(c.values()) / avg))
            )
        score[row["evidence_id"]] = total
    expected = sorted(score, key=lambda key: (-score[key], key))
    assert [r["evidence_id"] for r in corpus.search("route slow")] == expected
    assert [r["evidence_id"] for r in corpus.search("ROUTE slow route")] == expected


def test_family_metadata_is_preserved_without_prompt_injection(dataset):
    from mascope import Task

    task = Task("q", "Question", "family_a")
    environment = Environment(dataset, task, Model())
    assert environment.task.family_id == "family_a"
    assert "family_a" not in environment.task.query


def test_cap_submits_only_the_answer_the_method_already_holds(dataset, tmp_path):
    def agent(env):
        env.hold_answer("partial result")
        env.complete([])
        env.complete([])

    record = next(
        run(
            dataset,
            agent,
            Model(),
            tmp_path / "cap",
            task_ids=["task_one"],
            call_budget=1,
        )
    )
    assert record["status"] == "budget_exhausted"
    assert record["answer"]["text"] == "partial result"
    assert record["events"][-1]["kind"] == "submit"
    assert record["usage"]["calls"] == 1
