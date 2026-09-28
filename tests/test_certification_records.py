import copy
import json

import pytest

from mascope.dataset import sha256
from mascope.deterministic import DeterministicEvaluator
from mascope.validation import compare_certification_records
from test_deterministic import reference


def measured():
    return {
        "task_id": "q", "from": "r1", "to": "r2",
        "bound_terms": [["30 ms", "30 milliseconds"]],
        "rank_without": 19, "rank_with": 3,
    }


def test_certification_records_must_match_recomputed_ranks_and_bindings():
    edge = measured()
    stored = copy.deepcopy(edge)
    stored["bound_terms"][0].reverse()
    result = compare_certification_records([{"edge_measurements": [edge]}], [stored])
    assert result[0]["passed"]


@pytest.mark.parametrize("field,value", [
    ("rank_with", 1), ("rank_without", 75), ("rank_with", True),
    ("bound_terms", [["unrelated"]]), ("bound_terms", ["30 ms"]),
])
def test_plausible_but_unmeasured_certificate_is_rejected(field, value):
    edge = measured()
    stored = {**edge, field: value}
    result = compare_certification_records([{"edge_measurements": [edge]}], [stored])
    assert not result[0]["passed"]
    assert field in result[0]["issues"]


def test_missing_duplicate_and_uncertified_edge_records_fail():
    edge = measured()
    for families, records, issue in [
        ([{"edge_measurements": [edge]}], [], "missing_or_duplicate_record"),
        ([{"edge_measurements": [edge]}], [edge, edge], "missing_or_duplicate_record"),
        ([{"graph_matched": False}], [edge], "not_recertified"),
    ]:
        result = compare_certification_records(families, records)
        assert not result[0]["passed"] and issue in result[0]["issues"]


def test_full_evaluator_refuses_missing_dependency_bindings(tmp_path):
    row = reference()
    (tmp_path / "references.jsonl").write_text(json.dumps(row) + "\n")
    manifest = {
        "schema_version": "2.0", "version": "test", "query_count": 1,
        "files": {"references.jsonl": sha256(tmp_path / "references.jsonl")},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="frozen bound-term"):
        DeterministicEvaluator(tmp_path)


def test_full_evaluator_accepts_complete_frozen_binding_maps(tmp_path):
    row = reference()
    for unit in row["requirements"][1:]:
        unit["dependency_terms"] = {"r1": [["blue route"]]}
        unit["acceptance"][0]["terms"].append(["blue route"])
    rows = [{**row, "task_id": f"q{i}"} for i in range(3)]
    (tmp_path / "references.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    manifest = {
        "schema_version": "2.0", "version": "test", "query_count": 3,
        "files": {"references.jsonl": sha256(tmp_path / "references.jsonl")},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert DeterministicEvaluator(tmp_path).inventory["dependency_edge_count"] == 6


def test_malformed_binding_map_is_a_validation_failure():
    from mascope.reference import validate_reference

    row = reference()
    row["requirements"][1]["dependency_terms"] = []
    with pytest.raises(ValueError, match="map predecessor"):
        validate_reference(row, require_bindings=True)


def test_binding_maps_must_preserve_the_certified_surface_variants(tmp_path):
    from mascope.dataset import Task
    from mascope.validation import recompute_families
    from test_construction import candidates

    units, corpora = candidates(tmp_path)
    group = ["30 ms", "30 milliseconds"]
    for unit in units:
        unit["acceptance"][0]["evidence_ids"] = unit["acceptable_evidence"]
        unit["objective_terms"] = [["request"]]
    units[0].update(depends_on=[], dependency_terms={}, constraint_terms=[group])
    units[1].update(depends_on=["a"], dependency_terms={"a": [group]}, constraint_terms=[])
    units[1]["acceptance"][0]["terms"][0] = group

    class Dataset:
        def profiles(self):
            return [{"agent_id": "a", "tags": []}, {"agent_id": "b", "tags": []}]

        def corpus(self, agent):
            return corpora[agent]

        def task(self, task_id):
            return Task(task_id, "request symptoms", "f")

    refs = [{
        "task_id": "q", "family_id": "f", "cell": "C2S1",
        "requirements": units, "required_experts": ["a", "b"],
    }]
    row = recompute_families(Dataset(), refs)[0]
    assert row["graph_matched"] and row["bindings_matched"]
    units[1]["dependency_terms"] = {"a": [["30 ms"]]}
    row = recompute_families(Dataset(), refs)[0]
    assert row["binding_rules_valid"] and row["graph_matched"]
    assert not row["bindings_matched"]
