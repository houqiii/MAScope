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
        validate_terms(units[edge["from"]].get("constraint_terms"), allow_empty=True)
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


def query_stages(edge_judgments):
    return (
        [all(edge["stages"][i] for edge in edge_judgments) for i in range(5)]
        if edge_judgments
        else None
    )
