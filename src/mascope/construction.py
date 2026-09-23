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


def certify_dependencies(unit_ids, full_results, withheld_results):
    if not unit_ids or len(unit_ids) != len(set(unit_ids)):
        raise ValueError("Expected unique nonempty unit IDs")
    if set(full_results) != set(unit_ids):
        raise ValueError("Every unit needs a full-context solve record")
    expected = {
        (source, target)
        for source in unit_ids
        for target in unit_ids
        if source != target
    }
    if set(withheld_results) != expected:
        raise ValueError("Every ordered candidate pair needs a withholding record")

    def successes(values):
        if (
            not isinstance(values, list)
            or len(values) != 10
            or any(type(v) is not bool for v in values)
        ):
            raise ValueError("Each condition needs ten boolean solve outcomes")
        return sum(values)

    full = {u: successes(v) for u, v in full_results.items()}
    withheld = {pair: successes(v) for pair, v in withheld_results.items()}
    edges = [
        (source, target)
        for source, target in sorted(expected)
        if full[target] >= 8 and withheld[(source, target)] <= 1
    ]
    reference = {
        "requirements": [
            {"id": u, "depends_on": [s for s, t in edges if t == u]} for u in unit_ids
        ]
    }
    dependency_edges(reference)
    return {
        "edges": [{"from": s, "to": t} for s, t in edges],
        "candidate_pairs": len(expected),
        "certified_pairs": len(edges),
    }
