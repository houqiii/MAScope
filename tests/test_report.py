import copy
import json

import pytest

from mascope.evaluation import aggregate
from mascope.report import summarize_directories, summarize_runs


def rows():
    base = {
        "task_id": "task_a",
        "dataset_version": "1.1.0",
        "family_id": "family_a",
        "instance_id": "instance_a",
        "cell": "C2S1",
        "success": 1,
        "evidence_coverage": 1,
        "expert_hits": 2,
        "required_experts": 2,
        "recruited_experts": 3,
        "edge_judgments": [{"from": "a", "to": "b", "stages": [True] * 5}],
        "calls": 4,
        "tokens": 100,
    }
    return [
        base,
        {
            **base,
            "task_id": "task_b",
            "cell": "C3S3",
            "success": 0,
            "edge_judgments": [
                {"from": "a", "to": "b", "stages": [True, True, True, False, False]}
            ],
            "tokens": 300,
        },
    ]


def test_survival_factors_and_grouped_metrics():
    summary = aggregate(rows())
    product = 1
    for field in (
        "task_orchestration",
        "information_transfer",
        "local_solve",
        "result_integration",
    ):
        product *= summary[field] / 100
    assert summary["dependency_survival"] == pytest.approx(product * 100)
    assert summary["local_solve"] == 50
    assert summary["by_scale"]["S1"]["success"] == 100
    assert summary["by_structure"]["C3"]["result_integration"] is None


def test_repeat_statistics_are_across_runs():
    first = rows()
    second = copy.deepcopy(first)
    second[1]["success"] = 1
    result = summarize_runs([first, second])
    assert result["queries_per_run"] == 2
    assert result["metrics"]["success"]["mean"] == 75
    assert result["metrics"]["success"]["std"] == pytest.approx(35.3553390593)
    assert result["by_scale"]["S1"]["success"]["std"] == 0


@pytest.mark.parametrize(
    "change", ["task", "version", "family", "missing", "duplicate"]
)
def test_incomparable_runs_rejected(change):
    first = rows()
    second = copy.deepcopy(first)
    if change == "task":
        second.pop()
    if change == "version":
        second[0]["dataset_version"] = "1.0.0"
    if change == "family":
        second[0]["family_id"] = "different"
    if change == "missing":
        second[0].pop("dataset_version")
    if change == "duplicate":
        second.append(second[0])
    with pytest.raises(ValueError):
        summarize_runs([first, second])


def test_unknown_usage_not_silently_excluded():
    first = rows()
    second = copy.deepcopy(first)
    second[0]["tokens"] = None
    result = summarize_runs([first, second])
    assert result["metrics"]["mean_tokens"]["mean"] is None
    assert result["metrics"]["mean_tokens"]["values"] == [200, None]
    assert summarize_runs([first])["metrics"]["success"]["std"] is None


def test_duplicate_directory_rejected(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_directories([tmp_path, tmp_path])


def test_directories_use_completed_selection_not_stale_files(tmp_path):
    selected = rows()
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "task_ids": [r["task_id"] for r in selected],
                "n": 2,
                "dataset_version": "1.1.0",
            }
        )
    )
    for row in selected:
        (tmp_path / (row["task_id"] + ".json")).write_text(json.dumps(row))
    (tmp_path / "task_stale.json").write_text("{}")
    assert summarize_directories([tmp_path])["queries_per_run"] == 2
    (tmp_path / "task_a.failed.json").write_text("{}")
    with pytest.raises(ValueError, match="failed judgments"):
        summarize_directories([tmp_path])
