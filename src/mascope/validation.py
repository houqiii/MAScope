from collections import defaultdict
from itertools import combinations

from .construction import certify_group
from .pipeline import minhash, profile_ranks


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
            "discovery_passed": bool(declared) and all(discovery),
        }
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
        except (ValueError, KeyError) as error:
            row.update(graph_matched=False, error=str(error))
        rows.append(row)
    return rows
