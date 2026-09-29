import json

import pytest

from mascope import Completion, run
from mascope.dataset import sha256
from mascope.environment import Environment
from mascope.evaluation import Evaluator, aggregate


class Model:
    model = "test-model"

    def complete(self, messages, max_tokens=4096, json_output=False):
        return Completion("blue route MS-000000000001", 11, 7)


def references(tmp_path, dataset):
    root = tmp_path / "evaluator"
    root.mkdir()
    task = next(iter(dataset))
    row = {
        "task_id": task.task_id,
        "family_id": "f1",
        "cell": "C1S1",
        "required_experts": ["alpha", "beta"],
        "requirements": [
            {
                "id": "r1",
                "claim": "blue route",
                "satisfying_agents": ["alpha"],
                "depends_on": [],
                "acceptable_evidence": ["MS-000000000001"],
                "acceptance": [
                    {"evidence_ids": ["MS-000000000001"], "terms": [["blue route"]]}
                ],
            }
        ],
    }
    path = root / "references.jsonl"
    path.write_text(json.dumps(row) + "\n")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "scope": "subset",
                "version": "1.0.0",
                "query_count": 1,
                "files": {"references.jsonl": sha256(path)},
            }
        )
    )
    return root


def test_run_and_evaluate_without_model_access(dataset, tmp_path, monkeypatch):
    task = next(iter(dataset))

    def agent(environment):
        environment.recruit("alpha")
        return environment.complete(
            [{"role": "user", "content": environment.task.query}], phase="synthesis"
        )

    record = next(
        run(dataset, agent, Model(), tmp_path / "runs", task_ids=[task.task_id])
    )
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("Evaluation must be offline"),
    )
    row = Evaluator(references(tmp_path, dataset)).evaluate(task, record)
    assert row["success"] == row["evidence_coverage"] == 1
    assert row["tokens"] == 18
    report = aggregate([row])
    assert report["expert_recall"] == 50
    assert report["expert_precision"] == 100
    assert report["task_orchestration"] is None


def test_annotation_integrity_and_version_mismatch(dataset, tmp_path):
    root = references(tmp_path, dataset)
    evaluator = Evaluator(root)
    task = next(iter(dataset))
    with pytest.raises(ValueError, match="versions"):
        evaluator.evaluate(task, {"task_id": task.task_id, "dataset_version": "other"})
    with (root / "references.jsonl").open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="integrity"):
        Evaluator(root)


def test_environment_export_evaluates_without_runner(dataset, tmp_path):
    task = next(iter(dataset))
    environment = Environment(dataset, task, Model())
    environment.recruit("alpha")
    environment.submit("blue route MS-000000000001", [])
    record = environment.export()
    result = Evaluator(references(tmp_path, dataset)).evaluate(task, record)
    assert record["dataset_version"] == dataset.manifest["version"]
    assert result["success"] == 1
    assert result["calls"] == 0


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


def test_identifier_free_rescores_same_frozen_terms(dataset, tmp_path):
    task = next(iter(dataset))
    record = next(
        run(
            dataset,
            lambda e: "blue route",
            Model(),
            tmp_path / "runs",
            task_ids=[task.task_id],
        )
    )
    root = references(tmp_path, dataset)
    assert Evaluator(root).evaluate(task, record)["success"] == 0
    loose = Evaluator(root, identifier_free=True).evaluate(task, record)
    assert loose["success"] == 1
    assert (
        loose["reference_sha256"]
        == Evaluator(root).evaluate(task, record)["reference_sha256"]
    )
