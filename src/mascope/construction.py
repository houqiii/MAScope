import hashlib
import hmac
import json

from .reference import dependency_edges

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def source_identifier(key, community, post, unit_index):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Use a private construction key of at least 32 bytes")
    payload = json.dumps(
        [community, str(post), unit_index], separators=(",", ":")
    ).encode()
    number = (
        int.from_bytes(hmac.new(key, payload, hashlib.sha256).digest()[:8], "big") >> 4
    )
    return "MS-" + "".join(
        ALPHABET[(number >> shift) & 31] for shift in range(55, -1, -5)
    )


def _source_text(source):
    return " ".join(source.get(field, "") for field in ("title", "question", "text"))


def certify_dependencies(queries, units, corpora):
    from .reference import fingerprint, validate_terms

    if not queries or any(not isinstance(q, str) or not q.strip() for q in queries):
        raise ValueError("Supply all nonempty queries of the candidate family")
    ids = [u["id"] for u in units]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Expected unique nonempty unit IDs")
    source_texts = {}
    passages = {}
    for unit in units:
        if not unit.get("acceptable_evidence"):
            raise ValueError("Accepted sources must be nonempty")
        passages[unit["id"]] = [
            (agent, corpora[agent].fetch(evidence))
            for agent in unit["satisfying_agents"]
            for evidence in unit["acceptable_evidence"]
            if evidence in _corpus_ids(corpora[agent])
        ]
        if {r["evidence_id"] for _, r in passages[unit["id"]]} != set(
            unit["acceptable_evidence"]
        ):
            raise ValueError("Accepted sources must exist in their owning corpora")
        source_texts[unit["id"]] = "\n".join(
            _source_text(r) for _, r in passages[unit["id"]]
        )
        if not unit.get("finding") or not unit.get("objective"):
            raise ValueError("Freeze a finding and objective for every candidate unit")
    edges, checks = [], []
    for target in units:
        bindings = {}
        alternatives = target.get("acceptance", [])
        if not alternatives:
            raise ValueError("Freeze acceptance before certifying dependencies")
        for alternative in alternatives:
            validate_terms(alternative["terms"])
            evidence_ids = alternative.get(
                "evidence_ids", target["acceptable_evidence"]
            )
            if not evidence_ids or not set(evidence_ids).issubset(
                target["acceptable_evidence"]
            ):
                raise ValueError("Acceptance route must name accepted sources")
            alternative_bindings = {}
            route_passages = [
                _source_text(passage)
                for _, passage in passages[target["id"]]
                if passage["evidence_id"] in evidence_ids
            ]
            for variants in alternative["terms"]:
                support = [any(v in text for v in variants) for text in route_passages]
                if any(support) and not all(support):
                    raise ValueError(
                        "Return group to composition: acceptance route has "
                        "unsupported equivalent evidence"
                    )
                if all(support):
                    continue
                visible = [any(v in q for v in variants) for q in queries]
                if all(visible):
                    continue
                if any(visible):
                    raise ValueError(
                        "Return group to composition: a family query reveals a bound term"
                    )
                kind = target.get("term_kinds", {}).get(variants[0])
                if kind not in {
                    "quantity",
                    "configuration_key",
                    "version",
                    "component",
                }:
                    raise ValueError(
                        "Return group to composition: bound term lacks a specific registered type"
                    )
                suppliers = [
                    u["id"]
                    for u in units
                    if u != target and any(v in source_texts[u["id"]] for v in variants)
                ]
                if len(suppliers) != 1:
                    raise ValueError(
                        "Return group to composition: bound term must have exactly one supplier"
                    )
                alternative_bindings.setdefault(suppliers[0], []).append(variants)
            if bindings and bindings != alternative_bindings:
                raise ValueError(
                    "Return group to composition: acceptance alternatives imply different bindings"
                )
            if alternative is alternatives[0]:
                bindings = alternative_bindings
            elif bindings != alternative_bindings:
                raise ValueError(
                    "Return group to composition: acceptance alternatives imply different bindings"
                )
        for parent, groups in sorted(bindings.items()):
            source = next(u for u in units if u["id"] == parent)
            if any(not any(v in source["finding"] for v in group) for group in groups):
                raise ValueError(
                    "Return group to composition: predecessor finding omits a bound term"
                )
            objective = target["objective"]
            for group in bindings.values():
                for variants in group:
                    for variant in sorted(variants, key=len, reverse=True):
                        objective = objective.replace(variant, " ")
            other_findings = [
                u["finding"] for u in units if u["id"] not in {parent, target["id"]}
            ]
            query_checks = []
            for query in queries:
                import re

                base = [query, *re.split(r"(?<=[.!?])\s+", query), objective]
                battery = list(
                    dict.fromkeys(
                        text
                        for q in base
                        for text in [
                            q,
                            *(q + " " + f for f in other_findings),
                            q + " " + " ".join(other_findings),
                        ]
                    )
                )
                ranks = []
                for agent, passage in passages[target["id"]]:
                    without, with_finding = [], []
                    for text in battery:
                        for phrase, result in [
                            (text, without),
                            (text + " " + source["finding"], with_finding),
                        ]:
                            retrieved = [
                                r["evidence_id"]
                                for r in corpora[agent].search(phrase, 8)
                            ]
                            result.append(
                                retrieved.index(passage["evidence_id"]) + 1
                                if passage["evidence_id"] in retrieved
                                else None
                            )
                    if any(rank is not None for rank in without) or not any(
                        rank is not None for rank in with_finding
                    ):
                        raise ValueError(
                            "Return group to composition: dependency fails the retrieval reach check"
                        )
                    ranks.append(
                        {
                            "agent_id": agent,
                            "evidence_id": passage["evidence_id"],
                            "without": without,
                            "with": with_finding,
                        }
                    )
                query_checks.append(
                    {"query": query, "battery": battery, "ranks": ranks}
                )
            edges.append({"from": parent, "to": target["id"], "bound_terms": groups})
            checks.append({"from": parent, "to": target["id"], "queries": query_checks})
    graph = {
        "requirements": [
            {"id": key, "depends_on": [e["from"] for e in edges if e["to"] == key]}
            for key in ids
        ]
    }
    dependency_edges(graph)
    return {
        "edges": edges,
        "candidate_pairs": len(ids) * (len(ids) - 1),
        "certified_pairs": len(edges),
        "checks": checks,
        "input_sha256": fingerprint({"queries": queries, "units": units}),
        "corpus_sha256": {
            agent: _corpus_hash(corpus) for agent, corpus in corpora.items()
        },
        "retriever": "bm25-k1=0.9-b=0.4",
    }


def _corpus_ids(corpus):
    corpus._load()
    return corpus._offsets


def _corpus_hash(corpus):
    from .dataset import sha256

    return sha256(corpus.path)


def bind_terms(source_id, target_id, groups, units, queries):
    from .reference import validate_terms

    validate_terms(groups)
    lookup = {u["id"]: u for u in units}
    if source_id == target_id or source_id not in lookup or target_id not in lookup:
        raise ValueError("Invalid binding endpoints")
    sources = {
        key: "\n".join(_source_text(s) for s in unit["sources"])
        for key, unit in lookup.items()
    }
    checks = []
    for variants in groups:
        suppliers = sorted(
            key for key, text in sources.items() if any(v in text for v in variants)
        )
        visible = any(v in query for v in variants for query in queries)
        checks.append(
            {
                "variants": variants,
                "suppliers": suppliers,
                "visible_in_query": visible,
                "passed": suppliers == [source_id] and not visible,
            }
        )
    return {
        "from": source_id,
        "to": target_id,
        "bound_terms": groups,
        "checks": checks,
        "passed": bool(checks) and all(c["passed"] for c in checks),
    }


def reach(corpus, evidence_ids, query_group, predecessor_finding):
    if not query_group or not evidence_ids:
        raise ValueError("Reach needs a nonempty query group and accepted passages")
    records = []
    for evidence in evidence_ids:
        without = [corpus.rank(q, [evidence])[evidence] for q in query_group]
        with_finding = [
            corpus.rank(q + " " + predecessor_finding, [evidence])[evidence]
            for q in query_group
        ]
        records.append(
            {
                "evidence_id": evidence,
                "rank_without": min(without),
                "rank_with": min(with_finding),
            }
        )
    return {
        "rank_without": min(r["rank_without"] for r in records),
        "rank_with": max(r["rank_with"] for r in records),
        "passages": records,
        "passed": all(r["rank_without"] > 8 and r["rank_with"] <= 8 for r in records),
        "corpus_sha256": _corpus_hash(corpus),
        "query_group": list(query_group),
    }


def certify_group(queries, units, corpora):
    return certify_dependencies(queries, units, corpora)
