import collections
import json
import re
import statistics
from pathlib import Path

from .dataset import Dataset, read_json, read_jsonl, sha256
from .validation import recompute_families, reference_source_texts
from .reference import dependency_edges, fingerprint, validate_reference


def verify_paper(runtime, annotations, paper, output):
    dataset = Dataset(runtime)
    spec = read_json(paper)
    root = Path(annotations)
    refs = list(read_jsonl(root / "references.jsonl"))
    tasks = {t.task_id: t for t in dataset}
    families = collections.defaultdict(list)
    for row in refs:
        families[row["family_id"]].append(row)
    checks = []

    def check(name, actual, expected):
        checks.append(
            {
                "check": name,
                "actual": actual,
                "expected": expected,
                "status": "PASS" if actual == expected else "FAIL",
            }
        )

    check("queries", len(tasks), spec["queries"])
    check("references", len(refs), spec["queries"])
    check("query_identity", sorted(tasks), sorted(r["task_id"] for r in refs))
    check("families", len(families), spec["families"])
    check(
        "required_units",
        sum(len(r["requirements"]) for r in refs),
        spec["required_units"],
    )
    check("experts", len(dataset.profiles()), spec["runtime"]["experts"])
    check(
        "family_sizes",
        {
            str(k): v
            for k, v in sorted(collections.Counter(map(len, families.values())).items())
        },
        spec["family_sizes"],
    )
    check(
        "public_family_labels",
        sum(
            tasks[r["task_id"]].family_id == r["family_id"]
            for r in refs
            if r["task_id"] in tasks
        ),
        len(refs),
    )
    for cell, expected in spec["cells"].items():
        rows = [r for r in refs if r["cell"] == cell]
        check(cell + ".queries", len(rows), expected["queries"])
        check(
            cell + ".families",
            len({r["family_id"] for r in rows}),
            expected["families"],
        )
        check(
            cell + ".units",
            sum(len(r["requirements"]) for r in rows),
            expected["units"],
        )
        check(
            cell + ".experts_per_query",
            {
                str(k): v
                for k, v in sorted(
                    collections.Counter(
                        len(r["required_experts"]) for r in rows
                    ).items()
                )
            },
            expected["experts_per_query"],
        )
    invalid = []
    graphs = {}
    depths = []
    consistent = 0
    valid_rules = 0
    for family, rows in families.items():
        signatures = {
            fingerprint([r["cell"], r["required_experts"], r["requirements"]])
            for r in rows
        }
        consistent += len(signatures) == 1
        for r in rows:
            try:
                edges = dependency_edges(r)
                graphs[r["task_id"]] = edges
                if edges:
                    levels = {}
                    pending = {
                        u["id"]: u.get("depends_on", []) for u in r["requirements"]
                    }
                    while pending:
                        for key, parents in list(pending.items()):
                            if all(p in levels for p in parents):
                                levels[key] = max(
                                    (levels[p] + 1 for p in parents), default=0
                                )
                                del pending[key]
                    depths.append(max(levels.values()))
            except ValueError:
                invalid.append(r["task_id"])
            try:
                validate_reference(r)
                valid_rules += 1
            except (ValueError, KeyError):
                pass
    check("acyclic_graphs", len(invalid), 0)
    check("family_shared_units_graph", consistent, len(families))
    check("frozen_rule_records", valid_rules, len(refs))
    check(
        "dependent_queries",
        sum(bool(e) for e in graphs.values()),
        spec["dependent_queries"],
    )
    check("declared_edges", sum(map(len, graphs.values())), spec["certified_edges"])
    for cell, n in spec["edges_per_cell"].items():
        rows = [r for r in refs if r["cell"] == cell]
        check(cell + ".edges", sum(len(graphs.get(r["task_id"], [])) for r in rows), n)
        check(
            cell + ".candidate_pairs",
            sum(len(r["requirements"]) * (len(r["requirements"]) - 1) for r in rows),
            spec["candidate_pairs_per_cell"][cell],
        )
    actual_depth = (
        {
            str(k): round(100 * v / len(depths), 1)
            for k, v in sorted(collections.Counter(depths).items())
        }
        if depths
        else {}
    )
    check(
        "graph_depth_share_over_queries",
        actual_depth,
        spec["graph_depth_share_over_queries"],
    )
    for structure in ["C1", "C2", "C3"]:
        check(
            structure + ".families",
            sum(rows[0]["cell"].startswith(structure) for rows in families.values()),
            spec["expert_discovery"][structure + "_families"],
        )
    certpath = root / "certification/edges.jsonl"
    cert = list(read_jsonl(certpath)) if certpath.exists() else []
    expected_edges = {
        (r["task_id"], e["from"], e["to"])
        for r in refs
        for e in graphs.get(r["task_id"], [])
    }
    identities = [(r["task_id"], r["from"], r["to"]) for r in cert]
    check(
        "certificate_edge_coverage",
        len(set(identities) & expected_edges),
        len(expected_edges),
    )
    check("certificate_duplicates", len(identities) - len(set(identities)), 0)
    refmap = {r["task_id"]: r for r in refs}
    canonical_sources = reference_source_texts(runtime, refs)
    binding = 0
    reached = 0
    unreachable = 0
    for record in cert:
        ref = refmap.get(record["task_id"])
        if ref is None:
            continue
        units = {u["id"]: u for u in ref["requirements"]}
        if record["from"] not in units or record["to"] not in units:
            continue
        parent, child = units[record["from"]], units[record["to"]]
        groups = record.get("bound_terms", [])
        ok = bool(groups)
        for variants in groups:
            suppliers = [
                u["id"]
                for u in units.values()
                if any(
                    v in canonical_sources[ref["family_id"], u["id"]]
                    for v in variants
                )
            ]
            ok &= suppliers == [parent["id"]]
            ok &= all(
                not any(v in tasks[q["task_id"]].query for v in variants)
                for q in families[ref["family_id"]]
            )
            ok &= variants in child.get("acceptance", [{}])[0].get("terms", [])
            ok &= variants in parent.get("constraint_terms", [])
        ok &= len(groups) == record.get("requested_bound_count", len(groups))
        binding += ok
        reached += record.get("rank_with") is not None and record["rank_with"] <= 8
        unreachable += (
            record.get("rank_without") is not None and record["rank_without"] > 8
        )
    check("unique_bound_suppliers", binding, len(expected_edges))
    check("rank_with_top8", reached, len(expected_edges))
    check("rank_without_outside_top8", unreachable, len(expected_edges))
    recomputed = recompute_families(dataset, refs)
    check(
        "certified_family_graphs",
        sum(r["graph_matched"] for r in recomputed),
        len(families),
    )
    check(
        "certified_edges",
        sum(
            len(r["declared_edges"]) * r["query_count"]
            for r in recomputed
            if r["graph_matched"]
        ),
        spec["certified_edges"],
    )
    corpus_count = 0
    corpus_sizes = []
    complete_questions = 0
    corpus_ids = {}
    invalid_ids = 0
    over_cap = []
    for profile in dataset.profiles():
        agent = profile["agent_id"]
        count = 0
        for record in read_jsonl(Path(runtime) / "corpora" / (agent + ".jsonl")):
            count += 1
            complete_questions += (
                isinstance(record.get("question"), str)
                and len(record["question"].split()) >= 80
            )
            evidence = record["evidence_id"]
            invalid_ids += (
                re.fullmatch(r"MS-[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{12}", evidence)
                is None
                or evidence in corpus_ids
                or record["agent_id"] != agent
            )
            corpus_ids[evidence] = agent
        corpus_count += count
        corpus_sizes.append(count)
        if count > spec["runtime"]["corpus_cap_pairs"]:
            over_cap.append(agent)
    check("corpus_identifier_ownership", invalid_ids, 0)
    check("corpus_size_cap", over_cap, [])
    check("corpus_complete_questions", complete_questions, corpus_count)
    check("corpus_pairs", corpus_count, spec["runtime"].get("corpus_pairs", 766930))
    check(
        "corpus_median",
        statistics.median(corpus_sizes),
        spec["runtime"].get("corpus_median", 18271),
    )
    check(
        "corpus_minimum", min(corpus_sizes), spec["runtime"].get("corpus_minimum", 3247)
    )
    check(
        "corpora_at_cap",
        sum(n == spec["runtime"]["corpus_cap_pairs"] for n in corpus_sizes),
        spec["runtime"].get("corpora_at_cap", 23),
    )
    check(
        "reference_sources_in_runtime",
        sum(
            all(
                corpus_ids.get(e) in u["satisfying_agents"]
                for e in u["acceptable_evidence"]
            )
            for r in refs
            for u in r["requirements"]
        ),
        spec["required_units"],
    )
    similarity_path = root / "query_similarity.jsonl"
    similarities = list(read_jsonl(similarity_path)) if similarity_path.exists() else []
    check(
        "query_similarity_records",
        len(similarities),
        sum(len(g) * (len(g) - 1) // 2 for g in families.values()),
    )
    check(
        "query_similarity_below_threshold",
        sum(r["similarity_violations"] for r in recomputed),
        0,
    )
    discovery_path = root / "discovery.jsonl"
    discovery = list(read_jsonl(discovery_path)) if discovery_path.exists() else []
    check(
        "discovery_edge_coverage",
        len({(r["task_id"], r["from"], r["to"]) for r in discovery} & expected_edges),
        len(expected_edges),
    )
    check(
        "C3.discovery_profile_checks",
        sum(r["cell"].startswith("C3") and r["discovery_passed"] for r in recomputed),
        spec["expert_discovery"]["C3_families"],
    )
    check(
        "C3.discovery_verified_families",
        sum(
            r["cell"].startswith("C3") and r["graph_matched"] and r["discovery_passed"]
            for r in recomputed
        ),
        spec["expert_discovery"]["C3_families"],
    )
    solpath = root / "local_solvability.jsonl"
    solves = list(read_jsonl(solpath)) if solpath.exists() else []
    check(
        "unit_family_occurrences",
        sum(len(g[0]["requirements"]) for g in families.values()),
        spec["local_solvability"]["occurrences"],
    )
    coverage = {
        "recorded_units": len(solves),
        "evaluated_units": sum(len(r.get("samples", [])) == 10 for r in solves),
        "completed_samples": sum(len(r.get("samples", [])) for r in solves),
        "pending_units": sum(r.get("status") == "pending" for r in solves),
    }
    for component, base in [("runtime", Path(runtime)), ("evaluator", root)]:
        manifest = read_json(base / "manifest.json")
        bad = []
        for name, digest in manifest.get("files", {}).items():
            path = (base / name).resolve()
            if (
                not path.is_relative_to(base.resolve())
                or not path.is_file()
                or sha256(path) != digest
            ):
                bad.append(name)
        check(component + ".checksums", bad, [])
    report = {
        "paper_spec_sha256": sha256(paper),
        "runtime_version": dataset.manifest["version"],
        "passed": sum(c["status"] == "PASS" for c in checks),
        "failed": sum(c["status"] == "FAIL" for c in checks),
        "checks": checks,
        "corpus_pairs": corpus_count,
        "recomputed_families": recomputed,
        "local_solvability_coverage": coverage,
        "certification_summary": {
            "declared_edges": len(expected_edges),
            "records": len(cert),
            "bindings_passed": binding,
            "reach_with_passed": reached,
            "reach_without_passed": unreachable,
        },
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2))
    return report
