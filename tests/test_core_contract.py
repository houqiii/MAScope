import ast
import json
from pathlib import Path

import pytest

from mascope import Dataset, run
from mascope.dataset import sha256
from mascope.deterministic import DeterministicEvaluator
from mascope.evaluation import aggregate
from mascope.model import ToolCompletion


def test_core_has_no_adapter_imports_or_framework_registration():
    root = Path(__file__).parents[1]
    assert not (root / "src/mascope/adapters").exists()
    assert len(list((root / "adapters").glob("*/config.json"))) == 12
    for path in (root / "src/mascope").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "adapter" not in (node.module or "").lower()
            elif isinstance(node, ast.Import):
                assert all("adapter" not in alias.name.lower() for alias in node.names)


class FixtureModel:
    def complete(self, messages, max_tokens, json_output, tools):
        if "expert agent for site01," in messages[0]["content"]:
            assert "30 ms" in messages[1]["content"]
            assert "MS-000000000001" in messages[1]["content"]
        if messages[-1]["role"] != "tool":
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "retrieve-1",
                        "type": "function",
                        "function": {
                            "name": "retrieve",
                            "arguments": '{"query":"check finding"}',
                        },
                    }
                ],
            }
        else:
            result = (
                "30 ms [MS-000000000001]"
                if "expert agent for site00," in messages[0]["content"]
                else "complete with 30 ms [MS-000000000002]"
            )
            message = {"role": "assistant", "content": result}
        return ToolCompletion(message, 12, 8)


@pytest.mark.parametrize("delivery", ["inputs", "message", "memory"])
def test_51_agent_query_handoff_and_offline_edge_evaluation(tmp_path, monkeypatch, delivery):
    runtime = tmp_path / "runtime"
    (runtime / "corpora").mkdir(parents=True)
    profiles = [
        {"agent_id": f"site{i:02}", "expertise": f"domain {i}", "tags": [f"topic{i}"]}
        for i in range(51)
    ]
    (runtime / "profiles.json").write_text(json.dumps(profiles))
    tasks = [
        {
            "task_id": f"q{i}",
            "query": f"Investigate symptom {i} and review limit.",
            "family_id": "f",
        }
        for i in range(3)
    ]
    (runtime / "tasks.jsonl").write_text("".join(json.dumps(q) + "\n" for q in tasks))
    for i, p in enumerate(profiles, 1):
        record = {
            "agent_id": p["agent_id"],
            "evidence_id": f"MS-{i:012d}",
            "title": "Check finding",
            "text": "30 ms" if i == 1 else "complete",
            "tags": [],
        }
        (runtime / "corpora" / (p["agent_id"] + ".jsonl")).write_text(
            json.dumps(record) + "\n"
        )
    (runtime / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "fixture",
                "query_count": 3,
                "agent_count": 51,
                "files": {},
            }
        )
    )
    dataset = Dataset(runtime)
    assert len(dataset.profiles()) == 51
    for p in profiles:
        assert (
            dataset.corpus(p["agent_id"]).search("finding")[0]["agent_id"]
            == p["agent_id"]
        )
    with pytest.raises(KeyError):
        dataset.corpus("site00").fetch("MS-000000000002")

    def fixture_work(env):
        upstream = env.ask("site00", "check finding")
        inputs = []
        if delivery == "inputs":
            inputs = [upstream]
        elif delivery == "message":
            env.send("site00", "site01", "Review this limit", [upstream["artifact_id"]])
        else:
            env.record_memory("board", "read", [upstream], recipients=["site01"])
        downstream = env.ask("site01", "review limit", inputs=inputs)
        return upstream["text"] + "\n" + downstream["text"]

    record = next(
        run(dataset, fixture_work, FixtureModel(), tmp_path / "runs", task_ids=["q0"])
    )
    units = [
        {
            "id": "u1",
            "claim": "30 ms",
            "satisfying_agents": ["site00"],
            "depends_on": [],
            "acceptable_evidence": ["MS-000000000001"],
            "acceptance": [{"evidence_ids": ["MS-000000000001"], "terms": [["30 ms"]]}],
            "constraint_terms": [["30 ms"]],
        },
        {
            "id": "u2",
            "claim": "complete with 30 ms",
            "satisfying_agents": ["site01"],
            "depends_on": ["u1"],
            "acceptable_evidence": ["MS-000000000002"],
            "acceptance": [
                {
                    "evidence_ids": ["MS-000000000002"],
                    "terms": [["complete"], ["30 ms"]],
                }
            ],
            "objective_terms": [["review"], ["limit"]],
            "dependency_terms": {"u1": [["30 ms"]]},
        },
    ]
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    refs = evaluation / "references.jsonl"
    refs.write_text(
        "".join(
            json.dumps(
                {
                    "task_id": t["task_id"],
                    "family_id": "f",
                    "cell": "C2S1",
                    "required_experts": ["site00", "site01"],
                    "requirements": units,
                }
            )
            + "\n"
            for t in tasks
        )
    )
    (evaluation / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "version": "fixture",
                "query_count": 3,
                "family_count": 1,
                "dependency_edge_count": 3,
                "files": {"references.jsonl": sha256(refs)},
            }
        )
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: pytest.fail("Scoring contacted a model"),
    )
    row = DeterministicEvaluator(evaluation).evaluate(dataset.task("q0"), record)
    summary = aggregate([row])
    assert row["answered"] == 1 and row["graph_carried"] is True
    assert summary["dependency_counts"] == [1, 1, 1, 1, 1]
    assert summary["expert_recall"] == summary["expert_precision"] == 100
    assert record["usage"]["calls"] == 4 and record["usage"]["retrieval_calls"] == 2
    assert summary["bypass"]["bypassed_edges"] == 0
