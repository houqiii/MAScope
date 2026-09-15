import json

import pytest

from mascope import Dataset


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "runtime"
    (root / "corpora").mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "1.0.0",
                "query_count": 2,
                "agent_count": 2,
                "files": {},
            }
        )
    )
    (root / "tasks.jsonl").write_text(
        json.dumps(
            {"task_id": "task_one", "query": "Check the blue route and its limit."}
        )
        + "\n"
        + json.dumps({"task_id": "task_two", "query": "Check the red route."})
        + "\n"
    )
    (root / "profiles.json").write_text(
        json.dumps(
            [
                {"agent_id": "alpha", "expertise": "routing"},
                {"agent_id": "beta", "expertise": "limits"},
            ]
        )
    )
    for agent, text in [
        ("alpha", "The blue route reaches the destination."),
        ("beta", "The maximum load is five units."),
    ]:
        row = {
            "evidence_id": f"{agent}:1:2",
            "agent_id": agent,
            "title": "Route limit",
            "text": text,
            "tags": ["route"],
            "source_url": "https://example.org/source",
        }
        (root / "corpora" / (agent + ".jsonl")).write_text(json.dumps(row) + "\n")
    return Dataset(root)
