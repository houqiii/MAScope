import copy
import json

import pytest

from mascope.verification import verify_paper


@pytest.mark.parametrize("evidence,expected", [
    ([], 2),
    (["MS-000000000001"], 2),
    (["MS-000000000002"], 4),
])
def test_source_coverage_requires_nonempty_owned_evidence(dataset, tmp_path, evidence, expected):
    profiles = dataset.profiles()
    for profile in profiles:
        profile["tags"] = []
    (dataset.root / "profiles.json").write_text(json.dumps(profiles))
    units = []
    for key, agent, ids, finding in [
        ("r1", "alpha", ["MS-000000000001"], "blue route"),
        ("r2", "beta", evidence, "five units"),
    ]:
        units.append({
            "id": key, "claim": finding, "objective": finding, "finding": finding,
            "satisfying_agents": [agent], "depends_on": [], "dependency_terms": {},
            "constraint_terms": [], "objective_terms": [], "acceptable_evidence": ids,
            "acceptance": [{"evidence_ids": ids, "terms": [[finding]]}],
        })
    root = tmp_path / "references"
    root.mkdir()
    refs = [{
        "task_id": task.task_id, "family_id": "f", "cell": "C1S1",
        "required_experts": ["alpha", "beta"], "requirements": copy.deepcopy(units),
    } for task in dataset]
    (root / "references.jsonl").write_text("".join(json.dumps(r) + "\n" for r in refs))
    (root / "manifest.json").write_text(json.dumps({"files": {}}))
    spec = {
        "queries": 2, "families": 1, "required_units": 4,
        "runtime": {"experts": 2, "corpus_cap_pairs": 20000},
        "family_sizes": {"2": 1}, "cells": {}, "dependent_queries": 0,
        "certified_edges": 0, "edges_per_cell": {}, "candidate_pairs_per_cell": {},
        "graph_depth_share_over_queries": {},
        "expert_discovery": {"C1_families": 1, "C2_families": 0, "C3_families": 0},
        "local_solvability": {"occurrences": 2},
    }
    paper = tmp_path / "paper.json"
    paper.write_text(json.dumps(spec))
    report = verify_paper(dataset.root, root, paper, tmp_path / "report.json")
    check = next(c for c in report["checks"] if c["check"] == "reference_sources_in_runtime")
    assert check["actual"] == expected
    assert check["status"] == ("PASS" if expected == 4 else "FAIL")
    counts = next(c for c in report["checks"] if c["check"] == "profile_corpus_counts")
    tags = next(c for c in report["checks"] if c["check"] == "profile_top_tags")
    assert counts["actual"] == tags["actual"] == ["alpha", "beta"]
    assert counts["status"] == tags["status"] == "FAIL"
    for profile in profiles:
        profile["corpus_size"] = 1
        profile["tags"] = ["route"]
    (dataset.root / "profiles.json").write_text(json.dumps(profiles))
    verified = verify_paper(dataset.root, root, paper, tmp_path / "verified.json")
    assert all(c["status"] == "PASS" for c in verified["checks"]
               if c["check"] in {"profile_corpus_counts", "profile_top_tags"})
