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
    for query in result["checks"][0]["queries"]:
        positions = query["ranks"][0]
        assert min(positions["rank_without"]) > 8
        assert min(positions["rank_with"]) <= 8
        assert positions["passed"]


def test_reach_gate_rejects_easy_query_in_any_family_member(tmp_path):
    from mascope.construction import DependencyCertificationError

    units, corpora = candidates(tmp_path)
    with pytest.raises(DependencyCertificationError, match="reach") as failure:
        certify_dependencies(["request symptoms", "blue_token"], units, corpora)
    queries = failure.value.details["queries"]
    assert len(queries) == 2
    assert queries[0]["ranks"][0]["passed"]
    assert not queries[1]["ranks"][0]["passed"]
    assert min(queries[1]["ranks"][0]["rank_without"]) == 1


@pytest.mark.parametrize("term,kind", [
    ("i.e", "component"), ("e.g.", "configuration_key"),
    ("https://example.com/reference", "component"), ("0.01", "quantity"),
])
def test_bound_term_types_reject_generic_language_links_and_unitless_numbers(term, kind):
    from mascope.construction import validate_bound_term

    with pytest.raises(ValueError):
        validate_bound_term([term], kind)


def test_explicit_quantity_surface_variants_remain_allowed():
    from mascope.construction import validate_bound_term

    validate_bound_term(["30 seconds", "thirty seconds"], "quantity")
    validate_bound_term(["ROS"], "component")
    validate_bound_term(["SPI1.begin"], "configuration_key")


def test_query_battery_preserves_findings_without_blank_duplicate_probes():
    from mascope.construction import query_battery

    assert query_battery("One. Two.", "Goal") == ["One. Two.", "One.", "Two.", "Goal"]
    battery = query_battery("Question", "Goal", ["First", "Second"])
    assert battery == [
        "Question", "Question First", "Question Second", "Question First Second",
        "Goal", "Goal First", "Goal Second", "Goal First Second",
    ]


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


@pytest.mark.parametrize("equivalent_text,passed", [("ready", False), ("ready 30 ms", True)])
def test_predecessor_equivalents_must_all_supply_binding(tmp_path, equivalent_text, passed):
    import json

    from mascope.dataset import Corpus

    units, corpora = candidates(tmp_path)
    evidence = "MS-000000000002"
    path = tmp_path / "a.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["text"] += " ready"
    rows.append({"evidence_id": evidence, "agent_id": "a", "title": "alternative", "text": equivalent_text})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    corpora["a"] = Corpus(path, "a")
    units[0]["acceptable_evidence"].append(evidence)
    units[0]["acceptance"] = [{"terms": [["ready"]]}]
    if passed:
        result = certify_dependencies(["request symptoms"], units, corpora)
        assert result["edges"] == [{"from": "a", "to": "b", "bound_terms": [["30 ms"]]}]
    else:
        with pytest.raises(ValueError, match="predecessor equivalent"):
            certify_dependencies(["request symptoms"], units, corpora)


def test_binding_audit_checks_each_predecessor_source():
    from mascope.construction import bind_terms

    units = [
        {"id": "a", "sources": [{"text": "limit 30 ms"}, {"text": "ready"}]},
        {"id": "b", "sources": [{"text": "response"}]},
    ]
    result = bind_terms("a", "b", [["30 ms"]], units, ["review symptoms"])
    assert result["checks"][0]["suppliers"] == ["a"]
    assert not result["checks"][0]["source_routes_supported"]
    assert not result["passed"]


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
    assert row["structure_matched"] and row["derived_structure"] == "C3"
    assert len(row["edge_measurements"]) == 3
    assert all(e["rank_without"] > 8 and e["rank_with"] <= 8 for e in row["edge_measurements"])
    for reference in references:
        reference["cell"] = "C2S1"
    row = recompute_families(Dataset(), references)[0]
    assert row["graph_matched"] and not row["structure_matched"]
    for reference in references:
        reference["cell"] = "C3S1"
    units[1]["depends_on"] = []
    for reference in references:
        reference["status"] = "certified"
    row = recompute_families(Dataset(), references)[0]
    assert not row["graph_matched"]
    assert not row["discovery_passed"]
    assert row["derived_structure"] == "C3"
    units[1]["depends_on"] = ["a"]
    units[0]["finding"] = "blue_token"
    row = recompute_families(Dataset(), references)[0]
    assert row["discovery_profile_passed"]
    assert not row["graph_matched"] and not row["discovery_passed"]
