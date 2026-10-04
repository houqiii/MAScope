import copy
import json

import pytest

from mascope.structure import verify_structure


def make_data(tmp_path, mutate=None):
    runtime = tmp_path / "runtime"
    annotations = tmp_path / "evaluator"
    runtime.mkdir()
    annotations.mkdir()
    profiles = [{"agent_id": f"site{i}"} for i in range(51)]
    tasks = [dict(task_id=f"t{i}", family_id="f1", query=f"Scenario {i}") for i in range(3)]
    units = [dict(id="r1", satisfying_agents=["site0"], depends_on=[]), dict(id="r2", satisfying_agents=["site1"], depends_on=["r1"])]
    refs = [dict(task_id=t["task_id"], family_id="f1", cell="C2S1", required_experts=["site0", "site1"], requirements=copy.deepcopy(units)) for t in tasks]
    if mutate:
        mutate(tasks, refs)
    (runtime / "profiles.json").write_text(json.dumps(profiles))
    (runtime / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (annotations / "references.jsonl").write_text("".join(json.dumps(r) + "\n" for r in refs))
    return runtime, annotations


def test_structure_counts_declared_edges_without_certification(tmp_path):
    runtime, annotations = make_data(tmp_path)
    report = verify_structure(runtime, annotations)
    assert report["failed"] == 0
    assert report["scope"] == "structure"
    assert report["totals"] == dict(queries=3, families=1, required_units=6, declared_edges=3)
    assert "certification" not in report


def test_cycle_cannot_pass_structure(tmp_path):
    def mutate(tasks, refs):
        for ref in refs:
            ref["requirements"][0]["depends_on"] = ["r2"]
    report = verify_structure(*make_data(tmp_path, mutate))
    assert report["failed"] > 0


def test_family_graph_drift_fails(tmp_path):
    def mutate(tasks, refs):
        refs[0]["requirements"][1]["depends_on"] = []
    report = verify_structure(*make_data(tmp_path, mutate))
    assert report["failed"] > 0


@pytest.mark.parametrize("edge_key", ["declared_edges", "certified_edges"])
def test_spec_counts_are_computed_not_copied(tmp_path, edge_key):
    runtime, annotations = make_data(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(dict(queries=4, families=1, required_units=6, **{edge_key: 4}, graph_depth_share_over_queries={"1": 100.0})))
    report = verify_structure(runtime, annotations, spec)
    assert report["failed"] == 2
    assert report["totals"]["queries"] == 3
    assert report["totals"]["declared_edges"] == 3


def test_task_membership_mismatch_fails(tmp_path):
    def mutate(tasks, refs):
        tasks[0]["family_id"] = "another"
    report = verify_structure(*make_data(tmp_path, mutate))
    assert report["failed"] > 0
