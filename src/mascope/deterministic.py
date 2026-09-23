import re
from pathlib import Path

from .dataset import read_json, read_jsonl, sha256
from .reference import expert_hits, fingerprint, query_stages, validate_reference

SCORER_VERSION = "string-full-graph-1"


def match_terms(text, groups):
    matches = []
    for variants in groups:
        variant = next((v for v in variants if v in text), None)
        if variant is None:
            return None
        matches.append({"variant": variant, "offset": text.index(variant)})
    return matches


def match_unit(text, unit, citations=(), allow_uncited=False):
    for alternative in unit["acceptance"]:
        terms = match_terms(text, alternative["terms"])
        ids = [x for x in alternative["evidence_ids"] if x in text or x in citations]
        if terms is not None and (ids or allow_uncited):
            return {"evidence_ids": ids, "terms": terms}
    return None


class DeterministicEvaluator:
    def __init__(self, annotations):
        self.root = Path(annotations).resolve()
        self.manifest = read_json(self.root / "manifest.json")
        if self.manifest.get("schema_version") != "2.0":
            raise ValueError(
                "Deterministic evaluation requires schema 2.0 references with frozen acceptance, objective and constraint terms. The v1.1.0 bundle supports only --scorer semantic."
            )
        files = self.manifest.get("files", {})
        if "references.jsonl" not in files:
            raise ValueError("Reference checksum is required")
        for name, expected in files.items():
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root) or sha256(path) != expected:
                raise ValueError("Evaluation reference integrity check failed")
        self.references = {}
        for row in read_jsonl(self.root / "references.jsonl"):
            if row["task_id"] in self.references:
                raise ValueError("Duplicate reference task")
            validate_reference(row)
            self.references[row["task_id"]] = row
        if len(self.references) != self.manifest["query_count"]:
            raise ValueError("Reference count disagrees with manifest")

    def evaluate(self, task, record):
        reference = self.references[task.task_id]
        if record["task_id"] != task.task_id or record.get(
            "dataset_version"
        ) != self.manifest.get("runtime_version", self.manifest["version"]):
            raise ValueError("Run and annotation versions or task IDs disagree")
        events = record["events"]
        if [e["event_id"] for e in events] != [
            f"e{i + 1:06d}" for i in range(len(events))
        ]:
            raise ValueError("Invalid trace event ordering")
        answer = (record.get("answer") or {}).get("text", "")
        finals = [e for e in events if e["kind"] == "final"]
        if (answer and (len(finals) != 1 or finals[0]["text"] != answer)) or (
            not answer and finals
        ):
            raise ValueError("Submitted answer disagrees with trace")
        final_index = events.index(finals[0]) if finals else len(events)
        if finals and final_index != len(events) - 1:
            raise ValueError("Trace contains events after submission")
        units = {u["id"]: u for u in reference["requirements"]}
        judgments = {key: match_unit(answer, unit) for key, unit in units.items()}
        recruited = {e["agent_id"] for e in events if e["kind"] == "recruit"}
        contributions = [
            (i, e) for i, e in enumerate(events) if e["kind"] == "contribution"
        ]
        known_ids = {x for u in units.values() for x in u["acceptable_evidence"]}

        def local_match(event, unit):
            citations = event.get("evidence_ids", [])
            uncited = (
                not citations
                and not any(x in event["text"] for x in known_ids)
                and not re.search(r"MS-[0-9A-Z]{12}|ev_[a-f0-9]+", event["text"])
            )
            return match_unit(event["text"], unit, citations, uncited)

        edges = []
        for edge in validate_reference(reference):
            predecessor, successor = units[edge["from"]], units[edge["to"]]
            best = {
                "from": edge["from"],
                "to": edge["to"],
                "stages": [False] * 5,
                "event_ids": [[] for _ in range(5)],
                "matches": {},
            }
            for i, finding in contributions:
                cited_predecessor = [
                    x
                    for x in predecessor["acceptable_evidence"]
                    if x in finding["text"] or x in finding.get("evidence_ids", [])
                ]
                finding_match = (
                    {"evidence_ids": cited_predecessor}
                    if cited_predecessor
                    else local_match(finding, predecessor)
                )
                if (
                    finding_match is None
                    or finding["agent_id"] not in predecessor["satisfying_agents"]
                ):
                    continue
                for expert in successor["satisfying_agents"]:
                    recruitment = [
                        (j, e)
                        for j, e in enumerate(events)
                        if e["kind"] == "recruit" and e["agent_id"] == expert
                    ]
                    if not recruitment:
                        continue
                    candidate = {
                        "from": edge["from"],
                        "to": edge["to"],
                        "stages": [True, False, False, False, False],
                        "event_ids": [
                            [finding["event_id"], recruitment[0][1]["event_id"]],
                            [],
                            [],
                            [],
                            [],
                        ],
                        "matches": {"finding": finding_match},
                    }
                    if sum(candidate["stages"]) > sum(best["stages"]):
                        best = candidate
                    for j, assignment in enumerate(events):
                        if (
                            j <= max(i, recruitment[0][0])
                            or assignment["kind"] != "work_start"
                            or assignment["agent_id"] != expert
                        ):
                            continue
                        objective = match_terms(
                            assignment["instruction"], successor["objective_terms"]
                        )
                        if objective is None:
                            continue
                        stages = [True, True, False, False, False]
                        locators = [
                            candidate["event_ids"][0],
                            [assignment["event_id"]],
                            [],
                            [],
                            [],
                        ]
                        matches = {"finding": finding_match, "objective": objective}
                        for carried in assignment.get("inputs", []):
                            if carried.get("artifact_id") != finding.get("artifact_id"):
                                continue
                            if any(
                                carried.get(k) != finding.get(k)
                                for k in ("text", "agent_id", "evidence_ids")
                            ):
                                raise ValueError(
                                    "Carried contribution disagrees with its original output"
                                )
                            constraints = match_terms(
                                carried["text"], predecessor["constraint_terms"]
                            )
                            cited = [
                                x
                                for x in predecessor["acceptable_evidence"]
                                if x in carried["text"]
                                or x in carried.get("evidence_ids", [])
                            ]
                            if constraints is not None and cited:
                                stages[2] = True
                                locators[2] = [
                                    assignment["event_id"],
                                    finding["event_id"],
                                ]
                                matches["constraints"] = constraints
                                matches["carried_evidence"] = cited
                                break
                        if stages[2]:
                            next_assignment = next(
                                (
                                    k
                                    for k in range(j + 1, len(events))
                                    if events[k]["kind"] == "work_start"
                                    and events[k]["agent_id"] == expert
                                ),
                                final_index,
                            )
                            for k, output in contributions:
                                if (
                                    not j < k < next_assignment
                                    or output["agent_id"] != expert
                                ):
                                    continue
                                local = local_match(output, successor)
                                if local is not None:
                                    stages[3] = True
                                    locators[3] = [output["event_id"]]
                                    matches["local_result"] = local
                                    if judgments[edge["to"]] is not None and finals:
                                        stages[4] = True
                                        locators[4] = [finals[0]["event_id"]]
                                    break
                        if sum(stages) > sum(best["stages"]):
                            best = {
                                **edge,
                                "stages": stages,
                                "event_ids": locators,
                                "matches": matches,
                            }
            edges.append(best)
        completed = record["status"] in {"completed", "budget_exhausted"} and bool(
            answer
        )
        covered = sum(v is not None for v in judgments.values()) if completed else 0
        return {
            "task_id": task.task_id,
            "dataset_version": record["dataset_version"],
            "reference_version": self.manifest["version"],
            "reference_sha256": fingerprint(reference),
            "scorer_version": SCORER_VERSION,
            "family_id": reference["family_id"],
            "instance_id": reference["instance_id"],
            "cell": reference["cell"],
            "success": int(completed and covered == len(units)),
            "evidence_coverage": covered / len(units),
            "expert_hits": expert_hits(reference, recruited),
            "required_experts": len(reference["required_experts"]),
            "recruited_experts": len(recruited),
            "stages": query_stages(edges),
            "edge_judgments": edges,
            "calls": record["usage"]["calls"],
            "tokens": record["usage"]["tokens"],
            "retrieval_calls": sum(e["kind"] in {"search", "fetch"} for e in events),
            "judgment": {"requirements": judgments},
        }
