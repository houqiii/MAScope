import pytest

from mascope.construction import certify_dependencies, source_identifier


def test_private_source_ids_are_stable_and_keyed():
    first = source_identifier(b"a" * 32, "site", 42, 0)
    assert len(first) == 15 and first.startswith("MS-")
    assert first == source_identifier(b"a" * 32, "site", 42, 0)
    assert first != source_identifier(b"b" * 32, "site", 42, 0)
    assert first != source_identifier(b"a" * 32, "site", 42, 1)
    with pytest.raises(ValueError):
        source_identifier(b"", "site", 42, 0)


def candidates(tmp_path):
    import json

    from mascope.dataset import Corpus

    a = {
        "evidence_id": "MS-000000000001",
        "agent_id": "a",
        "title": "source",
        "text": "30 ms blue_token",
    }
    b = {
        "evidence_id": "MS-ZZZZZZZZZZZZ",
        "agent_id": "b",
        "title": "blue_token",
        "text": "done",
    }
    (tmp_path / "a.jsonl").write_text(json.dumps(a) + "\n")
    distractors = [
        {
            "evidence_id": f"d{i}",
            "agent_id": "b",
            "title": "request",
            "text": "symptoms review",
        }
        for i in range(12)
    ]
    (tmp_path / "b.jsonl").write_text(
        "\n".join(json.dumps(r) for r in [b, *distractors]) + "\n"
    )
    units = [
        {
            "id": "a",
            "satisfying_agents": ["a"],
            "acceptable_evidence": [a["evidence_id"]],
            "acceptance": [{"terms": [["30 ms"]]}],
            "objective": "review request",
            "finding": "30 ms blue_token",
        },
        {
            "id": "b",
            "satisfying_agents": ["b"],
            "acceptable_evidence": [b["evidence_id"]],
            "acceptance": [{"terms": [["30 ms"], ["done"]]}],
            "term_kinds": {"30 ms": "quantity"},
            "objective": "review request 30 ms",
            "finding": "done",
        },
    ]
    return units, {
        agent: Corpus(tmp_path / (agent + ".jsonl"), agent) for agent in ["a", "b"]
    }


def test_binding_and_reach_use_frozen_text_and_bm25(tmp_path):
    units, corpora = candidates(tmp_path)
    result = certify_dependencies(
        ["request symptoms", "review symptoms"], units, corpora
    )
    assert result["edges"] == [{"from": "a", "to": "b", "bound_terms": [["30 ms"]]}]
    assert len(result["checks"][0]["queries"]) == 2
    assert result["candidate_pairs"] == 2
    assert result["corpus_sha256"]["a"]


def test_reach_gate_rejects_easy_query_in_any_family_member(tmp_path):
    units, corpora = candidates(tmp_path)
    with pytest.raises(ValueError, match="reach"):
        certify_dependencies(["request symptoms", "blue_token"], units, corpora)


def test_unbound_or_ambiguous_reference_cannot_be_certified(tmp_path):
    units, corpora = candidates(tmp_path)
    units[0]["acceptable_evidence"] = []
    units[0]["term_kinds"] = {"30 ms": "quantity"}
    with pytest.raises(ValueError, match="one supplier"):
        certify_dependencies(["request symptoms"], units, corpora)


def test_general_concept_cannot_be_a_bound_term(tmp_path):
    units, corpora = candidates(tmp_path)
    units[1]["term_kinds"] = {}
    with pytest.raises(ValueError, match="specific"):
        certify_dependencies(["request symptoms"], units, corpora)


def test_reach_records_failure_without_inventing_rank(tmp_path):
    from mascope.construction import reach

    units, corpora = candidates(tmp_path)
    result = reach(
        corpora["b"], ["MS-ZZZZZZZZZZZZ"], ["blue_token"], "30 ms blue_token"
    )
    assert result["rank_without"] == 1
    assert not result["passed"]
