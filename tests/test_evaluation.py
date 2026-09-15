import pytest

from mascope.evaluation import aggregate, validate_judgment


def sample():
    reference = {
        "requirements": [{"id": "r1", "acceptable_evidence": ["alpha:1:2"]}],
        "dependency": {"from": "r1", "to": "r2"},
    }
    events = [
        {"event_id": "e000001", "kind": "search", "evidence_ids": ["alpha:1:2"]},
        {"event_id": "e000002", "kind": "contribution", "evidence_ids": ["alpha:1:2"]},
    ]
    judgment = {
        "constraints_satisfied": True,
        "requirements": [
            {
                "id": "r1",
                "satisfied": True,
                "supported": True,
                "evidence_ids": ["alpha:1:2"],
            }
        ],
        "dependency": {
            "stages": [True, True, False, False, False],
            "event_ids": [["e000001"], ["e000002"], [], [], []],
        },
    }
    return reference, {"events": events}, judgment


def test_support_requires_retrieval_and_contribution():
    reference, record, judgment = sample()
    validate_judgment(judgment, reference, record)
    record["events"] = record["events"][:1]
    with pytest.raises(ValueError):
        validate_judgment(judgment, reference, record)


@pytest.mark.parametrize(
    "mutation",
    [
        "future_stage",
        "false_boolean",
        "fake_event",
        "missing_requirement",
        "duplicate_requirement",
        "fake_source",
    ],
)
def test_invalid_judgments_rejected(mutation):
    reference, record, judgment = sample()
    if mutation == "future_stage":
        judgment["dependency"]["stages"][4] = True
    elif mutation == "false_boolean":
        judgment["requirements"][0]["satisfied"] = "false"
    elif mutation == "fake_event":
        judgment["dependency"]["event_ids"][0] = ["e999999"]
    elif mutation == "missing_requirement":
        judgment["requirements"] = []
    elif mutation == "duplicate_requirement":
        judgment["requirements"] *= 2
    elif mutation == "fake_source":
        judgment["requirements"][0]["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError):
        validate_judgment(judgment, reference, record)


def test_micro_averaging_and_conditional_denominators():
    first = {
        "task_id": "a",
        "family_id": "family_a",
        "cell": "C2S1",
        "success": 1,
        "information_coverage": 1,
        "expert_hits": 2,
        "required_experts": 2,
        "recruited_experts": 4,
        "stages": [True, True, True, True, False],
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
        "information_coverage": 0,
        "stages": [False] * 5,
        "tokens": None,
    }
    result = aggregate([first, second])
    assert result["expert_coverage"] == 37.5
    assert result["selection_precision"] == 60
    assert result["success"] == 50
    assert result["task_coordination"] == 100
    assert result["result_integration"] == 0
    assert result["mean_tokens"] is None
    assert result["runs_with_unknown_tokens"] == 1
    assert aggregate([{**second, "stages": [False] * 5}])["task_coordination"] is None


def test_duplicate_results_are_not_double_counted():
    with pytest.raises(ValueError):
        aggregate([{"task_id": "same"}, {"task_id": "same"}])
