import copy
import json

import pytest

from mascope import Task
from mascope.dataset import sha256
from mascope.deterministic import DeterministicEvaluator
from mascope.evaluation import aggregate
from mascope.reference import dependency_edges, expert_hits
from mascope.report import summarize_runs


def reference():
    units = []
    for i, (agent, term) in enumerate(
        [("alpha", "blue route"), ("beta", "five units"), ("gamma", "TLS kept")], 1
    ):
        units.append(
            {
                "id": f"r{i}",
                "claim": term,
                "satisfying_agents": [agent],
                "depends_on": [] if i == 1 else ["r1"],
                "acceptable_evidence": [f"MS-00000000000{i}"],
                "acceptance": [
                    {"evidence_ids": [f"MS-00000000000{i}"], "terms": [[term]]}
                ],
                "objective_terms": [[f"check {term}"]],
                "constraint_terms": [[term]],
            }
        )
    return {
        "task_id": "task_a",
        "family_id": "f",
        "instance_id": "i",
        "cell": "C2S1",
        "required_experts": ["alpha", "beta", "gamma"],
        "requirements": units,
    }


def evaluator(tmp_path, ref=None):
    ref = ref or reference()
    (tmp_path / "references.jsonl").write_text(json.dumps(ref) + "\n")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "version": "test",
                "query_count": 1,
                "files": {"references.jsonl": sha256(tmp_path / "references.jsonl")},
            }
        )
    )
    return DeterministicEvaluator(tmp_path)


def record():
    events = [{"kind": "recruit", "agent_id": x} for x in ["alpha", "beta", "gamma"]]
    finding = {
        "kind": "contribution",
        "artifact_id": "a1",
        "agent_id": "alpha",
        "text": "blue route",
        "evidence_ids": ["MS-000000000001"],
    }
    events.append(finding)
    for i, agent, term in [(2, "beta", "five units"), (3, "gamma", "TLS kept")]:
        events.append(
            {
                "kind": "work_start",
                "agent_id": agent,
                "instruction": f"check {term}",
                "inputs": [copy.deepcopy(finding)],
            }
        )
        events.append(
            {
                "kind": "contribution",
                "artifact_id": f"a{i}",
                "agent_id": agent,
                "text": term,
                "evidence_ids": [f"MS-00000000000{i}"],
            }
        )
    answer = "blue route MS-000000000001; five units MS-000000000002; TLS kept MS-000000000003"
    events.append({"kind": "final", "text": answer})
    for i, event in enumerate(events, 1):
        event["event_id"] = f"e{i:06d}"
    return {
        "task_id": "task_a",
        "dataset_version": "test",
        "status": "completed",
        "answer": {"text": answer},
        "events": events,
        "usage": {"tokens": 15, "calls": 2},
    }


def score(ev, run=None):
    return ev.evaluate(
        Task("task_a", "Inspect route and constraints."), run or record()
    )


def set_answer(run, answer):
    run["answer"]["text"] = answer
    run["events"][-1]["text"] = answer


def test_deterministic_replay_and_exact_matches(tmp_path):
    ev = evaluator(tmp_path)
    first = score(ev)
    assert first == score(ev)
    assert first["success"] == first["evidence_coverage"] == 1
    assert first["stages"] == [True] * 5
    assert len(first["edge_judgments"]) == 2
    assert first["judgment"]["requirements"]["r2"]["terms"] == [
        {"variant": "five units", "offset": 28}
    ]


def test_terms_without_source_or_source_without_terms_fail(tmp_path):
    ev = evaluator(tmp_path)
    for answer in [
        "blue route; five units; TLS kept",
        "MS-000000000001 MS-000000000002 MS-000000000003",
    ]:
        run = record()
        set_answer(run, answer)
        assert score(ev, run)["success"] == score(ev, run)["evidence_coverage"] == 0


def test_registered_variants_only(tmp_path):
    ref = reference()
    ref["requirements"][1]["acceptance"][0]["terms"][0].append("5 units")
    ev = evaluator(tmp_path, ref)
    run = record()
    set_answer(run, run["answer"]["text"].replace("five units", "5 units"))
    assert score(ev, run)["success"] == 1
    set_answer(run, run["answer"]["text"].replace("5 units", "FIVE UNITS"))
    assert score(ev, run)["success"] == 0


def test_query_stage_requires_every_edge_not_edge_average(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][6]["instruction"] = "unrelated work"
    row = score(ev, run)
    assert row["edge_judgments"][0]["stages"] == [True] * 5
    assert row["edge_judgments"][1]["stages"] == [True, False, False, False, False]
    assert row["stages"] == [True, False, False, False, False]
    assert aggregate([row])["task_orchestration"] == 0


def test_delivery_requires_real_carried_inputs(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][4]["inputs"] = []
    assert score(ev, run)["stages"] == [True, True, False, False, False]
    run = record()
    run["events"][4]["inputs"][0]["text"] = "invented"
    with pytest.raises(ValueError, match="Carried"):
        score(ev, run)


def test_local_result_must_follow_assignment_and_precede_next(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][5]["agent_id"] = "gamma"
    assert score(ev, run)["stages"] == [True, True, True, False, False]


def test_final_integration_loss_is_distinct_from_local_solve(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    set_answer(run, "blue route MS-000000000001; TLS kept MS-000000000003")
    row = score(ev, run)
    assert row["stages"] == [True, True, True, True, False]
    assert row["success"] == 0
    assert row["evidence_coverage"] == pytest.approx(2 / 3)


def test_term_only_local_output_and_wrong_identifier(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][5]["evidence_ids"] = []
    assert score(ev, run)["stages"] == [True] * 5
    run["events"][5]["evidence_ids"] = ["wrong"]
    assert score(ev, run)["stages"][3] is False


def test_schema_fails_closed_without_annotations(tmp_path):
    ref = reference()
    del ref["requirements"][0]["acceptance"]
    with pytest.raises(ValueError, match="Missing acceptance"):
        evaluator(tmp_path, ref)
    (tmp_path / "manifest.json").write_text('{"schema_version":"1.0"}')
    with pytest.raises(ValueError, match="schema 2.0"):
        DeterministicEvaluator(tmp_path)


@pytest.mark.parametrize("problem", ["cycle", "duplicate", "missing", "parallel"])
def test_invalid_graph_rejected(problem):
    ref = reference()
    if problem == "cycle":
        ref["requirements"][0]["depends_on"] = ["r2"]
    if problem == "duplicate":
        ref["requirements"][1]["depends_on"] = ["r1", "r1"]
    if problem == "missing":
        ref["requirements"][1]["depends_on"] = ["missing"]
    if problem == "parallel":
        ref["cell"] = "C1S1"
    with pytest.raises(ValueError):
        dependency_edges(ref)


def test_equivalent_experts_do_not_double_credit_one_agent():
    ref = reference()
    ref["expert_roles"] = [["alpha", "alt"], ["beta", "alt"], ["gamma"]]
    assert expert_hits(ref, {"alt"}) == 1
    assert expert_hits(ref, {"alpha", "alt"}) == 2
    assert expert_hits(ref, {"alpha", "beta", "alt", "gamma"}) == 3


def test_budget_exhaustion_scores_existing_answer(tmp_path):
    run = record()
    run["status"] = "budget_exhausted"
    assert score(evaluator(tmp_path), run)["success"] == 1


def test_different_scorers_and_references_cannot_be_pooled(tmp_path):
    row = score(evaluator(tmp_path))
    other = {**row, "scorer_version": "semantic-full-graph-2"}
    with pytest.raises(ValueError):
        summarize_runs([[row], [other]])
    other = {**row, "reference_sha256": "changed"}
    with pytest.raises(ValueError):
        summarize_runs([[row], [other]])
