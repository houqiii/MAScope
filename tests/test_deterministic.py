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
                "scope": "subset",
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
    events.append(
        {
            "kind": "search",
            "agent_id": "alpha",
            "evidence_ids": ["MS-000000000001"],
            "records": [{"evidence_id": "MS-000000000001", "text": "blue route"}],
        }
    )
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
    assert all(e["stages"] == [True] * 5 for e in first["edge_judgments"])
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


def test_aggregation_counts_edges_independently(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][7]["instruction"] = "unrelated work"
    row = score(ev, run)
    assert row["edge_judgments"][0]["stages"] == [True] * 5
    assert row["edge_judgments"][1]["stages"] == [True, False, False, False, False]
    assert aggregate([row])["task_orchestration"] == 50


def test_delivery_requires_real_carried_inputs(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][5]["inputs"] = []
    assert score(ev, run)["edge_judgments"][0]["stages"] == [
        True,
        True,
        False,
        False,
        False,
    ]
    run = record()
    run["events"][5]["inputs"][0]["text"] = "invented"
    with pytest.raises(ValueError, match="Carried"):
        score(ev, run)


def test_nested_visible_context_counts_but_metadata_does_not(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    work = run["events"][5]
    finding = work["inputs"].pop()
    work["carried_units"] = [{"text": "Use this finding", "attachments": [finding]}]
    assert score(ev, run)["edge_judgments"][0]["stages"] == [True] * 5
    work["carried_units"] = [{"content": [finding]}]
    assert score(ev, run)["edge_judgments"][0]["stages"] == [True] * 5
    work["carried_units"][0]["content"][0]["text"] = "altered blue route"
    with pytest.raises(ValueError, match="Carried"):
        score(ev, run)
    work["carried_units"] = [{"metadata": finding}]
    assert score(ev, run)["edge_judgments"][0]["stages"][2] is False


def test_frozen_bindings_must_agree_with_acceptance_and_transfer_constraints(tmp_path):
    from mascope.reference import validate_reference

    ref = reference()
    child = ref["requirements"][1]
    child["dependency_terms"] = {"r1": [["blue route"]]}
    with pytest.raises(ValueError, match="Acceptance alternative"):
        validate_reference(ref)
    child["acceptance"][0]["terms"].append(["blue route"])
    validate_reference(ref)
    ref["requirements"][0]["constraint_terms"] = [["unrelated"]]
    with pytest.raises(ValueError, match="Predecessor constraints"):
        validate_reference(ref)
    child["dependency_terms"] = {"r3": [["blue route"]]}
    with pytest.raises(ValueError, match="endpoints"):
        validate_reference(ref)


def test_local_result_must_follow_assignment_and_precede_next(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][6]["agent_id"] = "gamma"
    assert score(ev, run)["edge_judgments"][0]["stages"] == [
        True,
        True,
        True,
        False,
        False,
    ]


def test_final_integration_loss_is_distinct_from_local_solve(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    set_answer(run, "blue route MS-000000000001; TLS kept MS-000000000003")
    row = score(ev, run)
    assert row["edge_judgments"][0]["stages"] == [True, True, True, True, False]
    assert row["success"] == 0
    assert row["evidence_coverage"] == pytest.approx(2 / 3)


def test_term_only_local_output_and_wrong_identifier(tmp_path):
    ev = evaluator(tmp_path)
    run = record()
    run["events"][6]["evidence_ids"] = []
    assert score(ev, run)["edge_judgments"][0]["stages"] == [True] * 5
    run["events"][6]["evidence_ids"] = ["wrong"]
    assert score(ev, run)["edge_judgments"][0]["stages"][3] is False


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


def reorder(run):
    for i, event in enumerate(run["events"], 1):
        event["event_id"] = f"e{i:06d}"


def test_root_is_ready_on_retrieval_without_local_output(tmp_path):
    run = record()
    del run["events"][4]
    for event in run["events"]:
        if event["kind"] == "work_start":
            event["inputs"] = []
            event["instruction"] += "; blue route MS-000000000001"
    reorder(run)
    assert all(
        e["stages"] == [True] * 5
        for e in score(evaluator(tmp_path), run)["edge_judgments"]
    )


def test_unretrieved_root_cannot_be_ready(tmp_path):
    run = record()
    del run["events"][3]
    reorder(run)
    assert all(
        e["stages"] == [False] * 5
        for e in score(evaluator(tmp_path), run)["edge_judgments"]
    )


def test_upstream_failure_does_not_penalize_unready_successor(tmp_path):
    ref = reference()
    ref["requirements"][2]["depends_on"] = ["r2"]
    run = record()
    run["events"][5]["instruction"] = "unrelated work"
    row = score(evaluator(tmp_path, ref), run)
    edges = row["edge_judgments"]
    assert edges[0]["stages"] == [True, False, False, False, False]
    assert edges[1]["stages"] == [False] * 5
    result = aggregate([row])
    assert result["dependency_counts"] == [1, 0, 0, 0, 0]
    assert result["not_ready_edges"] == 1


def test_readiness_propagates_after_upstream_local_solve(tmp_path):
    ref = reference()
    ref["requirements"][2]["depends_on"] = ["r2"]
    run = record()
    run["events"][7]["inputs"] = [copy.deepcopy(run["events"][6])]
    row = score(evaluator(tmp_path, ref), run)
    assert all(e["stages"] == [True] * 5 for e in row["edge_judgments"])


def test_group_assignment_is_resolved_for_each_expert(tmp_path):
    run = record()
    run["events"][5]["agent_ids"] = ["beta", "gamma"]
    del run["events"][5]["agent_id"]
    run["events"][5]["instruction"] = "check five units and check TLS kept"
    del run["events"][7]
    reorder(run)
    assert all(
        e["stages"] == [True] * 5
        for e in score(evaluator(tmp_path), run)["edge_judgments"]
    )


def test_undecided_edges_leave_both_sides_of_all_ratios(tmp_path):
    row = score(evaluator(tmp_path))
    row["edge_judgments"][1].update(
        status="undecided",
        reason="ambiguous local output",
        stages=[True, True, True, False, False],
    )
    result = aggregate([row])
    assert result["dependency_counts"] == [1] * 5
    assert result["undecided_edges"] == 1
    assert result["dependency_survival"] == 100


def test_uncited_ambiguous_output_is_not_a_failure(tmp_path):
    ref = reference()
    ref["requirements"][2]["satisfying_agents"] = ["beta"]
    ref["requirements"][2]["acceptance"][0]["terms"] = [["five units"]]
    run = record()
    run["events"][6]["evidence_ids"] = []
    row = score(evaluator(tmp_path, ref), run)
    assert row["edge_judgments"][0]["status"] == "undecided"


def test_bypass_only_considers_received_content(tmp_path):
    ref = reference()
    ref["requirements"][1]["dependency_terms"] = {"r1": [["blue route"]]}
    ref["requirements"][1]["acceptance"][0]["terms"].append(["blue route"])
    run = record()
    run["events"].insert(
        3,
        {
            "kind": "contribution",
            "agent_id": "beta",
            "artifact_id": "b0",
            "text": "blue route",
            "evidence_ids": [],
        },
    )
    run["events"].insert(
        4,
        {
            "kind": "search",
            "agent_id": "beta",
            "evidence_ids": ["MS-000000000002"],
            "records": [],
        },
    )
    reorder(run)
    first = score(evaluator(tmp_path, ref), run)["edge_judgments"][0]
    assert first["bypass"]["bypassed"] is True
    run["events"].insert(
        4,
        {
            "kind": "message",
            "sender": "alpha",
            "recipient": "beta",
            "text": "blue route",
        },
    )
    reorder(run)
    assert (
        score(evaluator(tmp_path, ref), run)["edge_judgments"][0]["bypass"]["bypassed"]
        is False
    )


@pytest.mark.parametrize(
    "event, expected",
    [
        ({"kind": "memory", "operation": "read", "recipients": ["beta"],
          "items": [{"text": "blue route"}]}, False),
        ({"kind": "memory", "operation": "write", "recipients": ["beta"],
          "items": [{"text": "blue route"}]}, True),
        ({"kind": "memory", "operation": "read", "recipients": ["gamma"],
          "items": [{"text": "blue route"}]}, True),
        ({"kind": "message", "recipient": ["beta", "gamma"],
          "text": "Read this", "attachments": [{"text": "blue route"}]}, False),
        ({"kind": "message", "recipient": "beta", "delivery": "queued",
          "text": "blue route"}, True),
    ],
)
def test_bypass_uses_only_read_memory_and_delivered_messages(tmp_path, event, expected):
    ref = reference()
    ref["requirements"][1]["dependency_terms"] = {"r1": [["blue route"]]}
    ref["requirements"][1]["acceptance"][0]["terms"].append(["blue route"])
    run = record()
    run["events"][3:3] = [event, {
        "kind": "search", "agent_id": "beta",
        "evidence_ids": ["MS-000000000002"], "records": [],
    }]
    reorder(run)
    result = score(evaluator(tmp_path, ref), run)
    assert result["edge_judgments"][0]["bypass"]["bypassed"] is expected


def test_incomplete_assignment_is_an_error_not_a_failed_stage(tmp_path):
    run = record()
    del run["events"][5]["inputs"]
    with pytest.raises(ValueError, match="Incomplete assignment"):
        score(evaluator(tmp_path), run)


def test_successful_edge_cannot_hide_an_unassigned_edge_in_another_query(tmp_path):
    row = score(evaluator(tmp_path))
    other = copy.deepcopy(row)
    other["task_id"] = "task_b"
    other["edge_judgments"] = [other["edge_judgments"][0]]
    other["edge_judgments"][0]["stages"] = [True, False, False, False, False]
    report = aggregate([row, other])
    assert report["dependency_counts"] == [3, 2, 2, 2, 2]
    assert report["task_orchestration"] == pytest.approx(200 / 3)
    assert report["dependency_survival"] == pytest.approx(200 / 3)
