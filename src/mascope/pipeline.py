import hashlib
import random
from collections import Counter
from copy import deepcopy
from itertools import combinations

from .construction import certify_group
from .dataset import tokens
from .deterministic import match_unit
from .reference import fingerprint


def minhash(text, permutations=128, seed=20260927):
    words = tokens(text)
    shingles = {" ".join(words[i : i + 3]) for i in range(max(1, len(words) - 2))}
    hashes = [
        int.from_bytes(hashlib.sha256(s.encode()).digest()[:4], "big") for s in shingles
    ]
    generator = random.Random(seed)
    prime = 4294967291
    result = []
    for _ in range(permutations):
        a, b = generator.randrange(1, prime), generator.randrange(prime)
        result.append(min((a * h + b) % prime for h in hashes))
    return result


def profile_ranks(text, profiles):
    words = set(tokens(text))
    scores = {
        p["agent_id"]: sum(
            bool(words & set(tokens(tag.replace("-", " ")))) for tag in p["tags"]
        )
        for p in profiles
    }
    return {
        agent: i + 1
        for i, agent in enumerate(sorted(scores, key=lambda a: (-scores[a], a)))
    }


def assess_family(candidate, corpora, profiles, validation):
    queries = candidate["queries"]
    units = deepcopy(candidate["units"])
    checks = []

    def check(name, passed, details=None):
        checks.append({"check": name, "passed": bool(passed), "details": details})

    ids = [q["task_id"] for q in queries]
    experts = sorted({a for u in units for a in u["satisfying_agents"]})
    check("family_size", 3 <= len(queries) <= 7)
    check("unique_query_ids", len(ids) == len(set(ids)))
    check("multiple_communities", len(experts) >= 2)
    check("expert_scale", 2 <= len(experts) <= 8)
    check("unique_units", len({u["id"] for u in units}) == len(units))
    selections = validation.get("subsumption", [])
    pairs = {(a["id"], b["id"]) for a in units for b in units if a != b}
    selected = {(r["from"], r["to"]) for r in selections}
    check("subsumption_coverage", selected == pairs)
    check(
        "no_subsumed_unit",
        bool(selections)
        and all(r.get("accepted") is False and r.get("source_run") for r in selections),
    )
    for query in queries:
        text = query["query"]
        ranks = profile_ranks(text, profiles)
        check(
            query["task_id"] + ".surface_selection",
            not all(ranks.get(a, 10**9) <= len(experts) for a in experts),
        )
        reviews = validation.get("reviews", {}).get(query["task_id"], [])
        criteria = {
            "no_community_named",
            "observable_goal_and_symptoms",
            "no_corpus_unique_vocabulary",
            "all_units_required_without_naming",
        }
        independent = (
            len(reviews) >= 2
            and len({r.get("reviewer") for r in reviews}) == len(reviews)
            and all(r.get("reviewer") for r in reviews)
        )
        complete = independent and all(
            set(r.get("checklist", {})) == criteria
            and all(type(v) is bool for v in r["checklist"].values())
            for r in reviews
        )
        decision = False
        if complete:
            first, second = reviews[:2]
            if first["checklist"] == second["checklist"]:
                decision = all(first["checklist"].values())
            elif len(reviews) == 3:
                decision = all(reviews[2]["checklist"].values())
        check(query["task_id"] + ".composition_review", decision)
    signatures = {q["task_id"]: minhash(q["query"]) for q in queries}
    for a, b in combinations(queries, 2):
        similarity = (
            sum(
                x == y
                for x, y in zip(signatures[a["task_id"]], signatures[b["task_id"]])
            )
            / 128
        )
        check(
            "distinct_queries:" + a["task_id"] + ":" + b["task_id"],
            similarity < 0.90,
            similarity,
        )
    certificate = None
    try:
        certificate = certify_group([q["query"] for q in queries], units, corpora)
        check("dependency_certification", True)
    except (ValueError, KeyError) as error:
        check("dependency_certification", False, str(error))
    if certificate is None:
        return {
            "family_id": candidate["family_id"],
            "disposition": "return_to_composition",
            "checks": checks,
            "candidate_sha256": fingerprint(candidate),
        }
    lookup = {u["id"]: u for u in units}
    for u in units:
        u["depends_on"] = [
            e["from"] for e in certificate["edges"] if e["to"] == u["id"]
        ]
        u["dependency_terms"] = {
            e["from"]: e["bound_terms"]
            for e in certificate["edges"]
            if e["to"] == u["id"]
        }
    discovery = []
    for q in queries:
        qr = profile_ranks(q["query"], profiles)
        rows = []
        for edge in certificate["edges"]:
            ranks = profile_ranks(lookup[edge["from"]]["finding"], profiles)
            target = lookup[edge["to"]]["satisfying_agents"]
            rows.append(
                {
                    **edge,
                    "passed": any(
                        qr[a] > len(experts) and ranks[a] <= 3 for a in target
                    ),
                }
            )
        discovery.append({"task_id": q["task_id"], "edges": rows})
    structure = (
        "C1"
        if not certificate["edges"]
        else "C3"
        if all(any(e["passed"] for e in row["edges"]) for row in discovery)
        else "C2"
    )
    scale = "S1" if len(experts) <= 3 else "S2" if len(experts) <= 5 else "S3"
    for unit in units:
        samples = validation.get("local_solvability", {}).get(unit["id"], [])
        valid = len(samples) == 10 and all(
            set(r.get("predecessors", [])) == set(unit["depends_on"])
            and r.get("corpus_agent") in unit["satisfying_agents"]
            and isinstance(r.get("answer"), str)
            and r.get("source_run")
            for r in samples
        )
        successes = sum(
            match_unit(r.get("answer", ""), unit) is not None for r in samples
        )
        check(
            unit["id"] + ".local_solvability",
            valid and successes >= 6,
            {"samples": len(samples), "successes": successes},
        )
    for q in queries:
        record = validation.get("end_to_end", {}).get(q["task_id"], {})
        passed = (
            bool(record.get("source_run"))
            and record.get("corpora_reachable") is True
            and record.get("experts_inferred") is True
            and all(match_unit(record.get("answer", ""), u) is not None for u in units)
        )
        check(q["task_id"] + ".end_to_end", passed)
    ready = all(c["passed"] for c in checks)
    return {
        "family_id": candidate["family_id"],
        "disposition": "freeze" if ready else "revise",
        "checks": checks,
        "certificate": certificate,
        "discovery": discovery,
        "cell": structure + scale,
        "units": units,
        "candidate_sha256": fingerprint(candidate),
        "validation_sha256": fingerprint(validation),
    }


def freeze_family(candidate, assessment):
    if assessment.get("disposition") != "freeze" or not all(
        c["passed"] for c in assessment["checks"]
    ):
        raise ValueError("Family has not passed every construction gate")
    if assessment["candidate_sha256"] != fingerprint(candidate):
        raise ValueError("Candidate changed after validation")
    units = assessment["units"]
    experts = sorted({a for u in units for a in u["satisfying_agents"]})
    return [
        {
            "task_id": q["task_id"],
            "family_id": candidate["family_id"],
            "cell": assessment["cell"],
            "required_experts": experts,
            "requirements": deepcopy(units),
        }
        for q in candidate["queries"]
    ]


def release_gate(assessments, expected=None):
    records = list(assessments)
    if not records or any(r.get("disposition") != "freeze" for r in records):
        raise ValueError("Only frozen families may enter a release")
    if len({r["family_id"] for r in records}) != len(records):
        raise ValueError("Duplicate family")
    counts = dict(Counter(r["cell"] for r in records))
    if expected is not None and counts != expected:
        raise ValueError(
            "Certified release inventory differs from the requested inventory"
        )
    return {
        "families": len(records),
        "family_cells": counts,
        "assessment_hashes": [fingerprint(r) for r in records],
    }


def prepare_corpus(records, community, key, cap=20000, seed=20260301):
    from .construction import source_identifier

    if not 1 <= cap <= 20000:
        raise ValueError("Corpus cap must be between 1 and 20000")
    records = list(records)
    eligible = [
        r
        for r in records
        if r.get("accepted") is True
        and isinstance(r.get("question"), str)
        and len(r["question"].split()) >= 80
        and r.get("tags")
        and r.get("text")
    ]
    eligible.sort(key=lambda r: (-r["answer_score"], str(r["answer_id"])))
    kept, signatures, buckets = [], [], {}
    for record in eligible:
        sig = minhash(record["question"])
        bands = [
            (offset, tuple(sig[offset : offset + 10])) for offset in range(0, 128, 10)
        ]
        candidates = {index for band in bands for index in buckets.get(band, ())}
        if any(
            sum(a == b for a, b in zip(sig, signatures[index])) / 128 >= 0.90
            for index in candidates
        ):
            continue
        index = len(kept)
        kept.append(record)
        signatures.append(sig)
        for band in bands:
            buckets.setdefault(band, []).append(index)
    chosen = random.Random(seed).sample(kept, min(cap, len(kept)))
    rows, attribution = [], []
    for record in chosen:
        evidence = source_identifier(key, community, record["answer_id"], 0)
        row = {
            name: record[name]
            for name in (
                "question",
                "title",
                "text",
                "tags",
                "question_id",
                "answer_id",
                "source_url",
                "content_license",
                "creation_date",
                "revision_date",
                "question_creation_date",
                "question_revision_date",
                "question_license",
                "question_url",
                "source_snapshot",
                "accepted",
                "answer_score",
            )
            if name in record
        }
        row.update(agent_id=community, evidence_id=evidence)
        rows.append(row)
        attribution.append(
            {
                "evidence_id": evidence,
                **{
                    name: record[name]
                    for name in (
                        "attribution",
                        "question_attribution",
                        "source_url",
                        "content_license",
                        "question_license",
                        "question_url",
                        "revision_date",
                        "question_revision_date",
                    )
                    if name in record
                },
            }
        )
    tags = Counter(tag for row in rows for tag in row["tags"])
    top_tags = [
        tag for tag, _ in sorted(tags.items(), key=lambda p: (-p[1], p[0]))[:12]
    ]
    return {
        "records": sorted(rows, key=lambda r: r["evidence_id"]),
        "attribution": attribution,
        "profile_tags": top_tags,
        "counts": {
            "input": len(records),
            "eligible": len(eligible),
            "deduplicated": len(kept),
            "retained": len(rows),
        },
        "seed": seed,
    }
