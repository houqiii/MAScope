import hashlib
import json
import re


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def dependency_edges(reference):
    units = reference["requirements"]
    ids = [u["id"] for u in units]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Reference must have unique, nonempty requirement IDs")
    parents = {u["id"]: u.get("depends_on", []) for u in units}
    for target, predecessors in parents.items():
        if len(predecessors) != len(set(predecessors)) or any(
            p not in parents or p == target for p in predecessors
        ):
            raise ValueError("Invalid or duplicate dependency edge")
    remaining = set(ids)
    while remaining:
        ready = {u for u in remaining if not (set(parents[u]) & remaining)}
        if not ready:
            raise ValueError("Dependency graph contains a cycle")
        remaining -= ready
    edges = [{"from": p, "to": u["id"]} for u in units for p in u.get("depends_on", [])]
    cell = reference.get("cell", "")
    if cell.startswith("C1") and edges:
        raise ValueError("C1 must have an empty dependency graph")
    if cell.startswith(("C2", "C3")) and not edges:
        raise ValueError("C2/C3 must have a nonempty dependency graph")
    return edges


def validate_terms(groups, allow_empty=False):
    if not isinstance(groups, list) or (not groups and not allow_empty):
        raise ValueError("Missing preregistered terms: supply nonempty variant groups")
    for variants in groups:
        if (
            not isinstance(variants, list)
            or not variants
            or any(not isinstance(s, str) or not s.strip() for s in variants)
        ):
            raise ValueError("Each term needs explicit nonempty surface variants")


def validate_reference(reference):
    edges = dependency_edges(reference)
    required = reference["required_experts"]
    if not required or len(required) != len(set(required)):
        raise ValueError("Required experts must be unique and nonempty")
    roles = reference.get("expert_roles", [[x] for x in required])
    if len(roles) != len(required) or any(
        not r
        or len(r) != len(set(r))
        or any(not isinstance(x, str) or not x for x in r)
        for r in roles
    ):
        raise ValueError("Invalid equivalent-expertise roles")
    units = {u["id"]: u for u in reference["requirements"]}
    for unit in units.values():
        alternatives = unit.get("acceptance")
        if not isinstance(alternatives, list) or not alternatives:
            raise ValueError(
                "Missing acceptance rules; this reference is not ready for deterministic evaluation"
            )
        if not unit.get("satisfying_agents") or not set(
            unit["satisfying_agents"]
        ).issubset({x for role in roles for x in role}):
            raise ValueError("Unit expertise is not represented by a required role")
        for alternative in alternatives:
            refs = alternative.get("evidence_ids")
            if (
                not isinstance(refs, list)
                or not refs
                or not set(refs).issubset(unit["acceptable_evidence"])
            ):
                raise ValueError("Acceptance rule must name accepted evidence")
            if any(re.fullmatch(r"MS-[0-9A-HJKMNP-TV-Z]{12}", x) is None for x in refs):
                raise ValueError("Schema 2.0 requires benchmark MS- source identifiers")
            validate_terms(alternative.get("terms"))
    for edge in edges:
        validate_terms(units[edge["to"]].get("objective_terms"))
        validate_terms(units[edge["from"]].get("constraint_terms"))
    for unit in units.values():
        bindings = unit.get("dependency_terms")
        if bindings is None:
            continue
        if set(bindings) != set(unit.get("depends_on", [])):
            raise ValueError("Bound-term endpoints disagree with the dependency graph")
        for parent, groups in bindings.items():
            validate_terms(groups)
            for group in groups:
                if not any(
                    set(group).issubset(variants)
                    for variants in units[parent]["constraint_terms"]
                ):
                    raise ValueError("Predecessor constraints omit a bound-term group")
                if any(
                    not any(set(group).issubset(variants) for variants in alt["terms"])
                    for alt in unit["acceptance"]
                ):
                    raise ValueError("Acceptance alternative omits a bound-term group")
    return edges


def expert_hits(reference, recruited):
    roles = reference.get("expert_roles", [[x] for x in reference["required_experts"]])
    matched = {}

    def assign(role, visited):
        for agent in sorted(set(roles[role]) & recruited):
            if agent in visited:
                continue
            visited.add(agent)
            if agent not in matched or assign(matched[agent], visited):
                matched[agent] = role
                return True
        return False

    return sum(assign(i, set()) for i in range(len(roles)))


def validate_families(references, complete=True):
    from collections import Counter, defaultdict

    families = defaultdict(list)
    for row in references:
        families[row["family_id"]].append(row)
    if len({r["task_id"] for r in references}) != len(references):
        raise ValueError("Duplicate task ID")
    for family, rows in families.items():
        if complete and not 3 <= len(rows) <= 7:
            raise ValueError(f"Family {family} must contain 3–7 queries")
        signatures = {
            fingerprint(
                {
                    "requirements": sorted(r["requirements"], key=lambda u: u["id"]),
                    "required_experts": sorted(r["required_experts"]),
                    "expert_roles": r.get("expert_roles"),
                    "cell": r["cell"],
                }
            )
            for r in rows
        }
        if len(signatures) != 1:
            raise ValueError(
                f"Family {family} must share units, experts and dependency graph"
            )
    return {
        "query_count": len(references),
        "family_count": len(families),
        "family_size_distribution": dict(
            sorted(Counter(len(v) for v in families.values()).items())
        ),
        "dependency_edge_count": sum(len(dependency_edges(r)) for r in references),
    }


def validate_release(references, dataset):
    inventory = validate_families(references)
    expected = {
        "query_count": 2766,
        "family_count": 499,
        "dependency_edge_count": 3664,
        "family_size_distribution": {3: 26, 4: 56, 5: 147, 6: 161, 7: 109},
    }
    for name, count in expected.items():
        if inventory[name] != count:
            raise ValueError(
                f"Release {name}: expected {count}, found {inventory[name]}"
            )
    dataset.verify()
    if len(dataset.profiles()) != 51:
        raise ValueError("Release requires 51 site agents")
    if {r["task_id"] for r in references} != {t.task_id for t in dataset}:
        raise ValueError("Runtime and reference query sets disagree")
    from collections import Counter

    cells = Counter(r["cell"] for r in references)
    if cells != dict(
        zip(
            [f"C{c}S{s}" for c in range(1, 4) for s in range(1, 4)],
            [454, 390, 292, 394, 314, 236, 296, 236, 154],
        )
    ):
        raise ValueError("Release taxonomy counts disagree")
    if sum(len(r["required_experts"]) for r in references) != 11018:
        raise ValueError("Release requires 11,018 expertise assignments")
    checked = set()
    for row in references:
        validate_reference(row)
        if dataset.task(row["task_id"]).family_id != row["family_id"]:
            raise ValueError(
                "Runtime must carry the matching family ID for every query"
            )
        for unit in row["requirements"]:
            for parent in unit.get("depends_on", []):
                validate_terms(unit.get("dependency_terms", {}).get(parent))
            for source in unit["acceptable_evidence"]:
                owners = tuple(unit["satisfying_agents"])
                if (source, owners) in checked:
                    continue
                found = False
                for owner in owners:
                    try:
                        dataset.corpus(owner).fetch(source)
                        found = True
                    except KeyError:
                        pass
                if not found:
                    raise ValueError(
                        "Accepted evidence missing from the owning experts' corpora"
                    )
                checked.add((source, owners))
    return inventory
