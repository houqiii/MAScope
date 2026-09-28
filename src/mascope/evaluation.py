from collections import defaultdict

from .deterministic import DeterministicEvaluator as Evaluator

__all__ = ["Evaluator", "aggregate"]


def aggregate(rows, include_groups=True):
    rows = list(rows)
    if not rows or len({r["task_id"] for r in rows}) != len(rows):
        raise ValueError("Expected nonempty unique task results")

    identities = {
        (r.get("scorer_version", "legacy"), r.get("dataset_version")) for r in rows
    }
    if len(identities) != 1:
        raise ValueError("Cannot combine different scorer or dataset versions")

    def ratio(n, d):
        return 100 * n / d if d else None

    dependent = [r for r in rows if r["edge_judgments"]]
    edges = [e for r in dependent for e in r["edge_judgments"]]
    decided = []
    for edge in edges:
        stages = edge["stages"]
        if edge.get("status") == "undecided":
            if not edge.get("reason"):
                raise ValueError("Undecided edges require an audit reason")
            continue
        if len(stages) != 5 or any(type(x) is not bool for x in stages):
            raise ValueError("Expected five boolean decisions per edge")
        if any(stages[i] and not stages[i - 1] for i in range(1, 5)):
            raise ValueError("Dependency stages must be nested")
        decided.append(edge)
    for row in rows:
        keys = [(e["from"], e["to"]) for e in row["edge_judgments"]]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate edge judgment")
    counts = [sum(e["stages"][i] for e in decided) for i in range(5)]
    bypass = [e.get("bypass", {}) for e in edges]
    unknown_bypass = sum(
        b.get("retrieved", False) and b.get("bypassed") is None for b in bypass
    )
    known_tokens = [r["tokens"] for r in rows if r["tokens"] is not None]
    result = {
        "n": len(rows),
        "cap_hit_share": ratio(sum(r.get("cap_hit", False) for r in rows), len(rows)),
        "families": len({r["family_id"] for r in rows}),
        "success": ratio(sum(r["success"] for r in rows), len(rows)),
        "evidence_coverage": 100
        * sum(r["evidence_coverage"] for r in rows)
        / len(rows),
        "expert_recall": 100
        * sum(r["expert_hits"] / r["required_experts"] for r in rows)
        / len(rows),
        "expert_precision": 100
        * sum(
            r["expert_hits"] / r["recruited_experts"] if r["recruited_experts"] else 0
            for r in rows
        )
        / len(rows),
        "task_orchestration": ratio(counts[1], counts[0]),
        "information_transfer": ratio(counts[2], counts[1]),
        "local_solve": ratio(counts[3], counts[2]),
        "result_integration": ratio(counts[4], counts[3]),
        "dependency_survival": ratio(counts[4], counts[0]),
        "dependency_counts": counts,
        "dependency_unit": "edge",
        "dependency_edges": len(edges),
        "decided_edges": len(decided),
        "undecided_edges": len(edges) - len(decided),
        "not_ready_edges": sum(not e["stages"][0] for e in decided),
        "dependent_queries": len(dependent),
        "bypass": {
            "retrieved_edges": sum(b.get("retrieved", False) for b in bypass),
            "bypassed_edges": sum(b.get("bypassed") is True for b in bypass),
            "unknown_edges": unknown_bypass + sum("bypass" not in e for e in edges),
            "rate": ratio(sum(b.get("bypassed") is True for b in bypass), len(edges))
            if not unknown_bypass and all("bypass" in e for e in edges)
            else None,
        },
        "mean_calls": sum(r["calls"] for r in rows) / len(rows),
        "mean_tokens": sum(known_tokens) / len(rows)
        if len(known_tokens) == len(rows)
        else None,
        "runs_with_unknown_tokens": len(rows) - len(known_tokens),
    }
    parallel = [r for r in rows if r["cell"].startswith("C1")]
    dep = [r for r in rows if r["cell"].startswith(("C2", "C3"))]
    p = sum(r["success"] for r in parallel) / len(parallel) if parallel else 0
    d = sum(r["success"] for r in dep) / len(dep) if dep else 0
    result["dependency_success_drop"] = 100 * (p - d) / p if p and dep else None
    if include_groups:
        for label, key in (
            ("by_cell", lambda r: r["cell"]),
            ("by_structure", lambda r: r["cell"][:2]),
            ("by_scale", lambda r: r["cell"][2:]),
        ):
            groups = defaultdict(list)
            for row in rows:
                groups[key(row)].append(row)
            result[label] = {
                name: aggregate(group, include_groups=False)
                for name, group in sorted(groups.items())
            }
    return result
