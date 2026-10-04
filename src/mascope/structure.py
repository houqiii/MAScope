import json
from collections import Counter, defaultdict
from pathlib import Path

from .dataset import read_jsonl, sha256
from .reference import dependency_edges, validate_families


def verify_structure(runtime, annotations, spec=None):
    runtime, annotations = Path(runtime), Path(annotations)
    tasks = list(read_jsonl(runtime / "tasks.jsonl"))
    references = list(read_jsonl(annotations / "references.jsonl"))
    profiles = json.loads((runtime / "profiles.json").read_text())
    expected = json.loads(Path(spec).read_text()) if spec else {}
    checks = []

    def check(name, actual, target):
        checks.append(dict(check=name, actual=actual, expected=target,
                           status="PASS" if actual == target else "FAIL"))

    task_ids = [t["task_id"] for t in tasks]
    reference_ids = [r["task_id"] for r in references]
    check("unique_task_ids", len(set(task_ids)), len(task_ids))
    check("matching_task_ids", sorted(task_ids), sorted(reference_ids))
    check("nonempty_queries", sum(bool(t.get("query", "").strip()) for t in tasks), len(tasks))
    task_map = {t["task_id"]: t for t in tasks}
    check("task_family_membership", sum(task_map.get(r["task_id"], {}).get("family_id") == r["family_id"] for r in references), len(references))
    try:
        inventory = validate_families(references)
        check("shared_family_definitions_and_acyclic_graphs", True, True)
    except (ValueError, KeyError, TypeError) as error:
        check("shared_family_definitions_and_acyclic_graphs", str(error), True)
        inventory = {}
    sites = {p["agent_id"] for p in profiles}
    check("unique_site_agents", len(sites), len(profiles))
    check("site_agent_count", len(sites), 51)
    cells = defaultdict(lambda: dict(queries=0, families=set(), units=0, experts=Counter(), edges=0, pairs=0))
    sizes = defaultdict(int)
    depth_counts = Counter()
    invalid = []
    for r in references:
        units = r["requirements"]
        k = len(r["required_experts"])
        cell = r["cell"]
        bounds = {"S1": (2, 3), "S2": (4, 5), "S3": (6, 8)}.get(cell[2:])
        owners = {a for u in units for a in u["satisfying_agents"]}
        if not bounds or not bounds[0] <= k <= bounds[1] or len(units) != k or owners != set(r["required_experts"]) or not owners <= sites or any(len(u["satisfying_agents"]) != 1 for u in units):
            invalid.append(r["task_id"])
        c = cells[cell]
        c["queries"] += 1
        c["families"].add(r["family_id"])
        c["units"] += len(units)
        c["experts"][str(k)] += 1
        c["edges"] += sum(len(u.get("depends_on", [])) for u in units)
        c["pairs"] += k * (k - 1) if not cell.startswith("C1") else 0
        sizes[r["family_id"]] += 1
        try:
            edges = dependency_edges(r)
            depths = {}
            pending = {u["id"]: u.get("depends_on", []) for u in units}
            while pending:
                for uid, parents in list(pending.items()):
                    if all(p in depths for p in parents):
                        depths[uid] = max((depths[p] + 1 for p in parents), default=0)
                        del pending[uid]
            if edges:
                depth_counts[str(max(depths.values()))] += 1
        except (ValueError, KeyError, TypeError):
            pass
    check("expert_membership_and_size_bands", invalid, [])
    totals = dict(queries=len(tasks), families=len(sizes), required_units=sum(c["units"] for c in cells.values()), declared_edges=sum(c["edges"] for c in cells.values()))
    for key in ("queries", "families", "required_units"):
        if key in expected:
            check(key, totals[key], expected[key])
    edge_count = expected.get("declared_edges", expected.get("certified_edges"))
    if edge_count is not None:
        check("declared_edge_count", totals["declared_edges"], edge_count)
    if "family_sizes" in expected:
        check("family_size_distribution", {str(k): v for k, v in Counter(sizes.values()).items()}, expected["family_sizes"])
    if "cells" in expected:
        check("taxonomy_cells", sorted(cells), sorted(expected["cells"]))
        for cell, target in expected["cells"].items():
            c = cells[cell]
            for key in ("queries", "units"):
                check(f"{cell}.{key}", c[key], target[key])
            check(f"{cell}.families", len(c["families"]), target["families"])
            check(f"{cell}.experts_per_query", dict(c["experts"]), target["experts_per_query"])
    for field, measured in (("edges_per_cell", "edges"), ("candidate_pairs_per_cell", "pairs")):
        for cell, target in expected.get(field, {}).items():
            check(f"{cell}.{measured}", cells[cell][measured], target)
    depth_shares = {k: round(v * 100 / sum(depth_counts.values()), 1) for k, v in depth_counts.items()}
    if "graph_depth_share_over_queries" in expected:
        check("graph_depth_share_over_queries", depth_shares, expected["graph_depth_share_over_queries"])
    return dict(scope="structure", passed=sum(c["status"] == "PASS" for c in checks), failed=sum(c["status"] == "FAIL" for c in checks), totals=totals, inventory=inventory, checks=checks,
                inputs={str(p): sha256(p) for p in [runtime / "tasks.jsonl", runtime / "profiles.json", annotations / "references.jsonl"]})
