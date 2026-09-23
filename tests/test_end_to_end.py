import json

import pytest

from mascope import Completion, run
from mascope.dataset import sha256
from mascope.evaluation import Evaluator, aggregate


class Model:
    model = "test-model"

    def complete(self, messages, max_tokens=4096, json_output=False):
        return Completion("The route is available.", 11, 7)


class Judge:
    def complete(self, messages, max_tokens=8192, json_output=True):
        payload = json.loads(messages[-1]["content"])
        assert payload["query"]
        assert payload["requirements"][0]["sources"][0]["text"]
        return Completion(
            json.dumps(
                {
                    "constraints_satisfied": True,
                    "requirements": [
                        {
                            "id": "r1",
                            "satisfied": True,
                            "supported": False,
                            "evidence_ids": [],
                        }
                    ],
                    "dependencies": [],
                }
            ),
            30,
            20,
        )


def references(tmp_path, dataset):
    root = tmp_path / "evaluator"
    root.mkdir()
    task = next(iter(dataset))
    row = {
        "task_id": task.task_id,
        "family_id": "f1",
        "instance_id": "i1",
        "cell": "C1S1",
        "required_experts": ["alpha", "beta"],
        "requirements": [
            {
                "id": "r1",
                "claim": "The route is available.",
                "acceptable_evidence": ["alpha:1:2"],
                "sources": [{"text": "The blue route reaches the destination."}],
            }
        ],
        "dependencies": [],
    }
    path = root / "references.jsonl"
    path.write_text(json.dumps(row) + "\n")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "1.0.0",
                "query_count": 1,
                "files": {"references.jsonl": sha256(path)},
            }
        )
    )
    return root


def test_run_evaluate_and_keep_outcome_distinct_from_provenance(dataset, tmp_path):
    task = next(iter(dataset))

    def agent(environment):
        environment.recruit("alpha")
        return environment.complete(
            [{"role": "user", "content": environment.task.query}], phase="synthesis"
        )

    record = next(
        run(dataset, agent, Model(), tmp_path / "runs", task_ids=[task.task_id])
    )
    evaluator = Evaluator(references(tmp_path, dataset), Judge())
    row = evaluator.evaluate(task, record)
    assert row["success"] == 1
    assert row["evidence_coverage"] == 0
    assert row["tokens"] == 18
    report = aggregate([row])
    assert report["expert_recall"] == 50
    assert report["expert_precision"] == 100
    assert report["task_orchestration"] is None
    assert json.loads((tmp_path / "runs" / (task.task_id + ".json")).read_text())[
        "answer"
    ]["text"]


def test_annotation_integrity_and_version_mismatch(dataset, tmp_path):
    root = references(tmp_path, dataset)
    evaluator = Evaluator(root, Judge())
    task = next(iter(dataset))
    with pytest.raises(ValueError, match="versions"):
        evaluator.evaluate(task, {"task_id": task.task_id, "dataset_version": "other"})
    with (root / "references.jsonl").open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="integrity"):
        Evaluator(root, Judge())


def test_resume_rejects_changed_budget(dataset, tmp_path):
    task = next(iter(dataset))
    list(run(dataset, lambda e: "Answer", Model(), tmp_path, task_ids=[task.task_id]))
    with pytest.raises(ValueError, match="configuration"):
        list(
            run(
                dataset,
                lambda e: "Answer",
                Model(),
                tmp_path,
                task_ids=[task.task_id],
                call_budget=1,
                resume=True,
            )
        )


@pytest.mark.parametrize("recover", [True, False])
def test_judge_feedback_is_bounded_and_costed(dataset, tmp_path, recover):
    from mascope.evaluation import JudgeValidationError

    class RepairingJudge(Judge):
        def __init__(self):
            self.calls = 0

        def complete(self, messages, max_tokens=8192, json_output=True):
            self.calls += 1
            if self.calls > 1:
                assert "Validation error" in messages[-1]["content"]
            supported = not recover or self.calls == 1
            return Completion(
                json.dumps(
                    {
                        "constraints_satisfied": True,
                        "requirements": [
                            {
                                "id": "r1",
                                "satisfied": True,
                                "supported": supported,
                                "evidence_ids": ["alpha:1:2"] if supported else [],
                            }
                        ],
                        "dependencies": [],
                    }
                ),
                10,
                5,
            )

    task = next(iter(dataset))
    record = next(
        run(
            dataset,
            lambda e: "The route is blue.",
            Model(),
            tmp_path / "runs",
            task_ids=[task.task_id],
        )
    )
    judge = RepairingJudge()
    evaluator = Evaluator(references(tmp_path, dataset), judge)
    if recover:
        result = evaluator.evaluate(task, record)
        assert result["evidence_coverage"] == 0
        assert len(result["judge_attempts"]) == 2
        assert result["judge_usage"] == {"input_tokens": 20, "output_tokens": 10}
    else:
        with pytest.raises(JudgeValidationError) as error:
            evaluator.evaluate(task, record)
        assert judge.calls == len(error.value.attempts) == 3
        assert error.value.usage == {"input_tokens": 30, "output_tokens": 15}
