import pytest

from mascope.evaluation import aggregate


def test_query_macro_averaging_and_conditional_denominators():
    first = {
        "task_id": "a",
        "family_id": "family_a",
        "cell": "C2S1",
        "success": 1,
        "evidence_coverage": 1,
        "expert_hits": 2,
        "required_experts": 2,
        "recruited_experts": 4,
        "edge_judgments": [
            {"from": "a", "to": "b", "stages": [True, True, True, True, False]}
        ],
        "calls": 3,
        "tokens": 100,
    }
    second = {
        **first,
        "task_id": "b",
        "family_id": "family_b",
        "success": 0,
        "expert_hits": 1,
        "required_experts": 6,
        "recruited_experts": 1,
        "evidence_coverage": 0,
        "edge_judgments": [{"from": "a", "to": "b", "stages": [False] * 5}],
        "tokens": None,
    }
    result = aggregate([first, second])
    assert result["expert_recall"] == pytest.approx(100 * (1 + 1 / 6) / 2)
    assert result["expert_precision"] == 75
    assert result["success"] == 50
    assert result["task_orchestration"] == 100
    assert result["result_integration"] == 0
    assert result["mean_tokens"] is None
    assert result["runs_with_unknown_tokens"] == 1
    assert aggregate([second])["task_orchestration"] is None


def test_duplicate_results_are_not_double_counted():
    with pytest.raises(ValueError):
        aggregate([{"task_id": "same"}, {"task_id": "same"}])
