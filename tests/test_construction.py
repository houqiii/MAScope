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
    with pytest.raises(ValueError, match="sources must be nonempty"):
        certify_dependencies(["request symptoms"], units, corpora)


def test_general_concept_cannot_be_a_bound_term(tmp_path):
    units, corpora = candidates(tmp_path)
    units[1]["term_kinds"] = {}
    with pytest.raises(ValueError, match="specific"):
        certify_dependencies(["request symptoms"], units, corpora)


def test_binding_requires_the_predecessor_finding_to_carry_the_term(tmp_path):
    units, corpora = candidates(tmp_path)
    units[0]["finding"] = "blue_token"
    with pytest.raises(ValueError, match="finding omits"):
        certify_dependencies(["request symptoms"], units, corpora)


def test_reach_records_failure_without_inventing_rank(tmp_path):
    from mascope.construction import reach

    units, corpora = candidates(tmp_path)
    result = reach(
        corpora["b"], ["MS-ZZZZZZZZZZZZ"], ["blue_token"], "30 ms blue_token"
    )
    assert result["rank_without"] == 1
    assert not result["passed"]


def test_downstream_question_is_visible_source_context(tmp_path):
    import json

    from mascope.dataset import Corpus

    units, corpora = candidates(tmp_path)
    path = tmp_path / "b.jsonl"
    rows = [json.loads(line) for line in path.open()]
    rows[0]["question"] = "This request already states 30 ms."
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    corpora["b"] = Corpus(path, "b")
    result = certify_dependencies(["request symptoms"], units, corpora)
    assert result["edges"] == []


def test_binding_rejects_term_present_in_downstream_question():
    from mascope.construction import bind_terms

    units = [
        {"id": "a", "sources": [{"text": "limit 30 ms"}]},
        {
            "id": "b",
            "sources": [{"question": "already known: 30 ms", "text": "response"}],
        },
    ]
    result = bind_terms("a", "b", [["30 ms"]], units, ["review symptoms"])
    assert not result["passed"]
    assert result["checks"][0]["suppliers"] == ["a", "b"]


def test_equivalent_source_must_support_each_local_acceptance_term(tmp_path):
    import json

    from mascope.dataset import Corpus

    units, corpora = candidates(tmp_path)
    evidence = "MS-000000000002"
    with (tmp_path / "b.jsonl").open("a") as stream:
        stream.write(json.dumps({"evidence_id": evidence, "agent_id": "b", "title": "blue_token", "text": "unrelated"}) + "\n")
    corpora["b"] = Corpus(tmp_path / "b.jsonl", "b")
    units[1]["acceptable_evidence"].append(evidence)
    with pytest.raises(ValueError, match="unsupported equivalent"):
        certify_dependencies(["request symptoms"], units, corpora)


def test_binding_audit_reads_runtime_not_embedded_reference_text(tmp_path):
    import json

    from mascope.validation import reference_source_texts

    (tmp_path / "corpora").mkdir()
    record = {"agent_id": "a", "evidence_id": "MS-000000000001",
              "title": "source", "question": "known 30 ms", "text": "actual finding"}
    (tmp_path / "corpora/a.jsonl").write_text(json.dumps(record) + "\n")
    reference = {"family_id": "f", "requirements": [{"id": "r1", "satisfying_agents": ["a"],
        "acceptable_evidence": [record["evidence_id"]], "sources": [{"text": "fabricated 99 ms"}]}]}
    result = reference_source_texts(tmp_path, [reference])
    assert "30 ms" in result["f", "r1"]
    assert "99 ms" not in result["f", "r1"]


def test_family_validation_recomputes_graph_similarity_and_discovery(tmp_path):
    from mascope.dataset import Task
    from mascope.validation import recompute_families

    units, corpora = candidates(tmp_path)
    units[0]["depends_on"] = []
    units[1]["depends_on"] = ["a"]

    class Dataset:
        def profiles(self):
            return [
                {"agent_id": "a", "tags": ["other"]},
                {"agent_id": "b", "tags": ["blue_token"]},
                {"agent_id": "c", "tags": ["request"]},
            ]

        def corpus(self, agent):
            return corpora[agent]

        def task(self, task_id):
            return Task(task_id, "request symptoms", "f")

    references = [
        {
            "task_id": f"q{i}",
            "family_id": "f",
            "cell": "C3S1",
            "requirements": units,
            "required_experts": ["a", "b"],
            "status": "uncertified",
        }
        for i in range(3)
    ]
    row = recompute_families(Dataset(), references)[0]
    assert row["graph_matched"] and row["discovery_passed"]
    assert row["similarity_pairs"] == row["similarity_violations"] == 3
    assert row["derived_edges"] == [("a", "b")]
    units[1]["depends_on"] = []
    for reference in references:
        reference["status"] = "certified"
    row = recompute_families(Dataset(), references)[0]
    assert not row["graph_matched"]
    assert not row["discovery_passed"]
    units[1]["depends_on"] = ["a"]
    units[0]["finding"] = "blue_token"
    row = recompute_families(Dataset(), references)[0]
    assert row["discovery_profile_passed"]
    assert not row["graph_matched"] and not row["discovery_passed"]
