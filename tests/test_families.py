import copy

import pytest
from test_deterministic import reference

from mascope.cli import parser
from mascope.reference import validate_families


def family(size):
    return [{**copy.deepcopy(reference()), "task_id": f"q{i}"} for i in range(size)]


@pytest.mark.parametrize("size", [3, 4, 5, 6, 7])
def test_all_supported_family_sizes(size):
    report = validate_families(family(size))
    assert report["family_size_distribution"] == {size: 1}
    assert report["dependency_edge_count"] == 2 * size


@pytest.mark.parametrize("size", [2, 8])
def test_family_size_is_not_a_fixed_pair(size):
    with pytest.raises(ValueError, match="3–7"):
        validate_families(family(size))


def test_family_cannot_mix_unit_sets():
    rows = family(3)
    rows[1]["requirements"][1]["depends_on"] = []
    with pytest.raises(ValueError, match="share units"):
        validate_families(rows)


def test_explicit_subset_retains_consistency_check():
    assert validate_families(family(1), complete=False)["query_count"] == 1


def test_evaluate_has_no_model_parameters():
    p = parser()
    args = [
        "evaluate",
        "--runtime",
        "r",
        "--annotations",
        "a",
        "--runs",
        "t",
        "--out",
        "o",
    ]
    assert p.parse_args(args).command == "evaluate"
    assert p.parse_args(args).scorer == "deterministic"
    assert p.parse_args(args).judge_model is None
    assert (
        p.parse_args(args + ["--scorer", "semantic", "--judge-model", "legacy"]).scorer
        == "semantic"
    )
