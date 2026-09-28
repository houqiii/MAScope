from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .construction import _source_text, certify_group
from .dataset import read_jsonl
from .pipeline import minhash, profile_ranks
from .reference import validate_reference


def compare_certification_records(recomputed, records):
    actual = defaultdict(list)
    for record in records:
        actual[record["task_id"], record["from"], record["to"]].append(record)
    expected = {
        (record["task_id"], record["from"], record["to"]): record
        for family in recomputed
        for record in family.get("edge_measurements", [])
    }
    results = []
    for key in sorted(set(actual) | set(expected)):
        measured = expected.get(key)
        stored = actual.get(key, [])
        issues = []
        if measured is None:
            issues.append("not_recertified")
        if len(stored) != 1:
            issues.append("missing_or_duplicate_record")
        if measured is not None and len(stored) == 1:
            for field in ("bound_terms", "rank_without", "rank_with"):
                value, target = stored[0].get(field), measured[field]
                if field == "bound_terms":
                    valid = isinstance(value, list) and all(
                        isinstance(group, list) and all(isinstance(v, str) for v in group)
                        for group in value
                    )
                    same = valid and sorted(map(sorted, value)) == sorted(map(sorted, target))
                else:
                    same = type(value) is int and value == target
                if not same:
                    issues.append(field)
        results.append({
            "task_id": key[0], "from": key[1], "to": key[2],
            "passed": not issues, "issues": issues,
        })
    return results


def reference_source_texts(runtime, references):
    needed = defaultdict(set)
    for reference in references:
        for unit in reference["requirements"]:
            for agent in unit["satisfying_agents"]:
                needed[agent].update(unit["acceptable_evidence"])
    sources = {}
    for agent, ids in needed.items():
        for source in read_jsonl(Path(runtime) / "corpora" / (agent + ".jsonl")):
            if source["evidence_id"] in ids and source["agent_id"] == agent:
                sources[agent, source["evidence_id"]] = _source_text(source)
    return {
        (reference["family_id"], unit["id"]): "\n".join(
            sources[agent, evidence]
            for agent in unit["satisfying_agents"]
            for evidence in unit["acceptable_evidence"]
            if (agent, evidence) in sources
        )
        for reference in references
        for unit in reference["requirements"]
    }


def recompute_families(dataset, references):
    families = defaultdict(list)
    for row in references:
        families[row["family_id"]].append(row)
    profiles = dataset.profiles()
    rows = []
    for family_id, group in families.items():
        reference = group[0]
        units = reference["requirements"]
        queries = [dataset.task(r["task_id"]).query for r in group]
        signatures = [minhash(q) for q in queries]
        similarities = [
            sum(x == y for x, y in zip(a, b)) / 128
            for a, b in combinations(signatures, 2)
        ]
        declared = sorted((p, u["id"]) for u in units for p in u.get("depends_on", []))
        lookup = {u["id"]: u for u in units}
        discovery = []
        for query in queries:
            initial = profile_ranks(query, profiles)
            found = False
            for parent, child in declared:
                after = profile_ranks(lookup[parent]["finding"], profiles)
                found |= any(
                    initial[a] > len(reference["required_experts"]) and after[a] <= 3
                    for a in lookup[child]["satisfying_agents"]
                )
            discovery.append(found)
        row = {
            "family_id": family_id,
            "cell": reference["cell"],
            "query_count": len(group),
            "declared_edges": declared,
            "similarity_pairs": len(similarities),
            "similarity_violations": sum(s >= 0.90 for s in similarities),
            "discovery_profile_passed": bool(declared) and all(discovery),
        }
        try:
            for member in group:
                validate_reference(member, require_bindings=True)
            row["binding_rules_valid"] = True
        except (ValueError, KeyError) as error:
            row.update(binding_rules_valid=False, binding_rule_error=str(error))
        try:
            certificate = certify_group(
                queries,
                units,
                {a: dataset.corpus(a) for u in units for a in u["satisfying_agents"]},
            )
            derived = sorted((e["from"], e["to"]) for e in certificate["edges"])
            row.update(
                derived_edges=derived,
                graph_matched=derived == declared,
                input_sha256=certificate["input_sha256"],
                corpus_sha256=certificate["corpus_sha256"],
            )
            bindings = {(e["from"], e["to"]): e["bound_terms"] for e in certificate["edges"]}
            recorded = {
                (parent, unit["id"]): groups
                for unit in units
                for parent, groups in (unit.get("dependency_terms") or {}).items()
            } if row["binding_rules_valid"] else {}
            row["bindings_matched"] = row["binding_rules_valid"] and (
                set(recorded) == set(bindings)
                and all(
                    sorted(map(sorted, recorded[edge])) == sorted(map(sorted, groups))
                    for edge, groups in bindings.items()
                )
            )
            row["edge_measurements"] = [
                {
                    "task_id": member["task_id"],
                    "from": edge["from"], "to": edge["to"],
                    "bound_terms": bindings[edge["from"], edge["to"]],
                    "rank_without": min(min(p["rank_without"]) for p in query["ranks"]),
                    "rank_with": max(min(p["rank_with"]) for p in query["ranks"]),
                }
                for edge in certificate["checks"]
                for member, query in zip(group, edge["queries"])
            ]
            derived_discovery = []
            for query in queries:
                initial = profile_ranks(query, profiles)
                derived_discovery.append(any(
                    initial[agent] > len(reference["required_experts"])
                    and profile_ranks(lookup[parent]["finding"], profiles)[agent] <= 3
                    for parent, child in derived
                    for agent in lookup[child]["satisfying_agents"]
                ))
            row["derived_structure"] = (
                "C1" if not derived else "C3" if all(derived_discovery) else "C2"
            )
            row["structure_matched"] = reference["cell"].startswith(row["derived_structure"])
        except (ValueError, KeyError) as error:
            row.update(graph_matched=False, bindings_matched=False, structure_matched=False, error=str(error))
            if getattr(error, "details", None) is not None:
                row["failure_measurement"] = error.details
        row["discovery_passed"] = row["discovery_profile_passed"] and row["graph_matched"]
        rows.append(row)
    return rows
