import re
from pathlib import Path

from .context import content_text
from .dataset import read_json, read_jsonl, sha256
from .events import normalize_events
from .reference import expert_hits, fingerprint, validate_families, validate_reference

SCORER_VERSION = "string-edge-3"


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


def _recipients(event):
    return event.get("agent_ids", [event.get("agent_id")])


def _retrieved(event):
    return event.get("evidence_ids", [event.get("evidence_id")])


def _content(event):
    return content_text(event)


class DeterministicEvaluator:
    def __init__(self, annotations, identifier_free=False):
        self.identifier_free = identifier_free
        self.root = Path(annotations).resolve()
        self.manifest = read_json(self.root / "manifest.json")
        if self.manifest.get("schema_version") != "2.0":
            raise ValueError(
                "Deterministic evaluation requires schema 2.0 frozen source identifiers and term rules"
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
            validate_reference(row, require_bindings=self.manifest.get("scope") != "subset")
            self.references[row["task_id"]] = row
        if len(self.references) != self.manifest["query_count"]:
            raise ValueError("Reference count disagrees with manifest")
        self.inventory = validate_families(
            list(self.references.values()),
            complete=self.manifest.get("scope") != "subset",
        )
        for name in ("family_count", "dependency_edge_count"):
            if name in self.manifest and self.manifest[name] != self.inventory[name]:
                raise ValueError(f"Reference {name} disagrees with manifest")

    def evaluate(self, task, record):
        reference = self.references[task.task_id]
        if record["task_id"] != task.task_id or record.get(
            "dataset_version"
        ) != self.manifest.get("runtime_version", self.manifest["version"]):
            raise ValueError("Run and annotation versions or task IDs disagree")
        if task.family_id is not None and task.family_id != reference["family_id"]:
            raise ValueError("Public and reference family IDs disagree")
        events = normalize_events(record["events"])
        if [e["event_id"] for e in events] != [
            f"e{i + 1:06d}" for i in range(len(events))
        ]:
            raise ValueError("Invalid trace event ordering")
        answer = (record.get("answer") or {}).get("text", "")
        finals = [e for e in events if e["kind"] == "final"]
        if (answer and (len(finals) != 1 or finals[0]["text"] != answer)) or (
            record.get("answer") is None and finals
        ):
            raise ValueError("Submitted answer disagrees with trace")
        if finals and events[-1] != finals[0]:
            raise ValueError("Trace contains events after submission")
        for event in events:
            if event["kind"] == "work_start":
                if (
                    not isinstance(event.get("instruction"), str)
                    or not isinstance(event.get("inputs"), list)
                    or not _recipients(event)
                    or any(not isinstance(a, str) or not a for a in _recipients(event))
                ):
                    raise ValueError("Incomplete assignment record")
            if event["kind"] == "contribution":
                if (
                    not isinstance(event.get("text"), str)
                    or not isinstance(event.get("evidence_ids"), list)
                    or not event.get("artifact_id")
                    or not event.get("agent_id")
                ):
                    raise ValueError("Incomplete local output record")
        units = {u["id"]: u for u in reference["requirements"]}
        judgments = {
            key: match_unit(answer, unit, allow_uncited=self.identifier_free)
            for key, unit in units.items()
        }
        recruits = {}
        artifacts = {}

        def check_artifacts(value):
            if isinstance(value, list):
                for item in value:
                    check_artifacts(item)
            elif isinstance(value, dict):
                if "artifact_id" in value:
                    original = artifacts.get(value["artifact_id"])
                    if original is None or any(
                        value.get(k) != original.get(k)
                        for k in ("text", "agent_id", "evidence_ids")
                    ):
                        raise ValueError(
                            "Carried contribution disagrees with its original output"
                        )
                for key in ("inputs", "carried_units", "attachments", "content"):
                    check_artifacts(value.get(key))

        for i, event in enumerate(events):
            if event["kind"] == "recruit":
                recruits.setdefault(event["agent_id"], i)
            if event["kind"] == "contribution":
                if event["artifact_id"] in artifacts:
                    raise ValueError("Duplicate contribution identifier")
                artifacts[event["artifact_id"]] = event
            if event["kind"] == "work_start" and any(
                not isinstance(item, dict) or "artifact_id" not in item
                for item in event["inputs"]
            ):
                raise ValueError("Carried inputs must identify original contributions")
            if event["kind"] in {"work_start", "message"}:
                check_artifacts(event)
            elif event["kind"] == "memory" and event.get("operation") == "read":
                check_artifacts(event.get("items"))

        def local_match(event, unit):
            citations = event.get("evidence_ids", [])
            uncited = not citations and not re.search(
                r"MS-[0-9A-Z]{12}|ev_[a-f0-9]+", event["text"]
            )
            match = match_unit(event["text"], unit, citations, uncited)
            candidates = [
                u
                for u in units.values()
                if event["agent_id"] in u["satisfying_agents"]
                and match_unit(event["text"], u, citations, uncited) is not None
            ]
            return match, uncited and len(candidates) > 1

        ready = {}
        undecided_units = set()
        edges = []
        pending = set(units)
        while pending:
            for key in sorted(pending):
                unit = units[key]
                if any(p in pending for p in unit.get("depends_on", [])):
                    continue
                if not unit.get("depends_on"):
                    ready[key] = next(
                        (
                            i
                            for i, e in enumerate(events)
                            if e["kind"] in {"search", "fetch"}
                            and e.get("agent_id") in unit["satisfying_agents"]
                            and set(_retrieved(e)) & set(unit["acceptable_evidence"])
                        ),
                        None,
                    )
                else:
                    incoming = []
                    for parent in unit["depends_on"]:
                        edge = self._edge(
                            parent,
                            key,
                            ready[parent],
                            units,
                            events,
                            recruits,
                            judgments,
                            local_match,
                        )
                        if parent in undecided_units:
                            edge.update(
                                status="undecided",
                                reason="Predecessor readiness depends on an undecided local output",
                            )
                        edges.append(edge)
                        incoming.append(edge)
                    if any(e["status"] == "undecided" for e in incoming):
                        undecided_units.add(key)
                    solved = [e.get("local_index") for e in incoming]
                    ready[key] = (
                        max(solved) if all(x is not None for x in solved) else None
                    )
                pending.remove(key)
                break
        for edge in edges:
            edge.pop("local_index", None)
            edge["bypass"] = self._bypass(
                edge, units, events, record.get("execution_mode") == "single_agent"
            )
        completed = record["status"] in {"completed", "budget_exhausted"} and bool(
            answer
        )
        covered = sum(v is not None for v in judgments.values()) if completed else 0
        return {
            "task_id": task.task_id,
            "dataset_version": record["dataset_version"],
            "reference_version": self.manifest["version"],
            "reference_sha256": fingerprint(reference),
            "scorer_version": SCORER_VERSION
            + ("-identifier-free" if self.identifier_free else ""),
            "answered": int(completed and covered == len(units)),
            "graph_carried": bool(edges)
            and all(e["status"] == "decided" and e["stages"][4] for e in edges),
            "cap_hit": bool(
                record.get("cap_hit", record["status"] == "budget_exhausted")
            ),
            "family_id": reference["family_id"],
            "cell": reference["cell"],
            "success": int(completed and covered == len(units)),
            "evidence_coverage": covered / len(units),
            "expert_hits": expert_hits(reference, set(recruits)),
            "required_experts": len(reference["required_experts"]),
            "recruited_experts": len(recruits),
            "edge_judgments": edges,
            "calls": record["usage"]["calls"],
            "tokens": record["usage"]["tokens"],
            "retrieval_calls": sum(e["kind"] in {"search", "fetch"} for e in events),
            "judgment": {"requirements": judgments},
        }

    def _edge(
        self,
        parent,
        child,
        finding_index,
        units,
        events,
        recruits,
        judgments,
        local_match,
    ):
        predecessor, successor = units[parent], units[child]
        best = {
            "from": parent,
            "to": child,
            "stages": [False] * 5,
            "event_ids": [[] for _ in range(5)],
            "status": "decided",
            "matches": {},
        }
        if finding_index is None:
            return best
        ambiguous = False
        local_indices = []
        for expert in successor["satisfying_agents"]:
            if expert not in recruits:
                continue
            first = [
                events[finding_index]["event_id"],
                events[recruits[expert]]["event_id"],
            ]
            if not best["stages"][0]:
                best["stages"][0], best["event_ids"][0] = True, first
            for j, assignment in enumerate(events):
                if (
                    j <= max(finding_index, recruits[expert])
                    or assignment["kind"] != "work_start"
                    or expert not in _recipients(assignment)
                ):
                    continue
                objective = match_terms(
                    assignment["instruction"], successor["objective_terms"]
                )
                if objective is None:
                    continue
                stages, locators = (
                    [True, True, False, False, False],
                    [first, [assignment["event_id"]], [], [], []],
                )
                content = _content(assignment)
                constraints = match_terms(content, predecessor["constraint_terms"])
                cited = [x for x in predecessor["acceptable_evidence"] if x in content]
                matches = {"objective": objective}
                if constraints is not None and cited:
                    stages[2], locators[2] = True, [assignment["event_id"]]
                    matches.update(constraints=constraints, carried_evidence=cited)
                    stop = next(
                        (
                            k
                            for k in range(j + 1, len(events))
                            if events[k]["kind"] == "work_start"
                            and expert in _recipients(events[k])
                        ),
                        len(events),
                    )
                    for k in range(j + 1, stop):
                        output = events[k]
                        if (
                            output["kind"] != "contribution"
                            or output["agent_id"] != expert
                        ):
                            continue
                        local, uncertain = local_match(output, successor)
                        ambiguous |= local is not None and uncertain
                        if local is None or uncertain:
                            continue
                        stages[3], locators[3] = True, [output["event_id"]]
                        local_indices.append(k)
                        matches["local_result"] = local
                        if judgments[child] is not None:
                            stages[4], locators[4] = True, [events[-1]["event_id"]]
                        break
                if sum(stages) > sum(best["stages"]):
                    best.update(stages=stages, event_ids=locators, matches=matches)
        if local_indices:
            best["local_index"] = min(local_indices)
        elif ambiguous:
            best.update(
                status="undecided",
                reason="Uncited local output matches multiple eligible units",
            )
        return best

    def _bypass(self, edge, units, events, single_agent=False):
        predecessor, successor = units[edge["from"]], units[edge["to"]]
        groups = successor.get("dependency_terms", {}).get(edge["from"])
        for i, event in enumerate(events):
            if (
                event["kind"] not in {"search", "fetch"}
                or (
                    event.get("agent_id") not in successor["satisfying_agents"]
                    and not (
                        single_agent
                        and event.get("agent_id") == "controller"
                        and event.get("site") in successor["satisfying_agents"]
                    )
                )
                or not set(_retrieved(event)) & set(successor["acceptable_evidence"])
            ):
                continue
            received, complete = [], True
            for earlier in events[:i]:
                if (
                    earlier["kind"] == "message"
                    and event["agent_id"] in (
                        earlier["recipient"]
                        if isinstance(earlier.get("recipient"), list)
                        else [earlier.get("recipient")]
                    )
                    and earlier.get("delivery") != "queued"
                ) or (
                    earlier["kind"] == "work_start"
                    and event["agent_id"] in _recipients(earlier)
                ):
                    received.append(_content(earlier))
                if (
                    earlier["kind"] == "memory"
                    and earlier.get("operation") == "read"
                    and event["agent_id"] in earlier.get("recipients", [])
                ):
                    received.append(content_text(earlier.get("items", [])))
                if (
                    earlier["kind"] in {"search", "fetch"}
                    and earlier.get("agent_id") == event["agent_id"]
                ):
                    received.extend(x for x in _retrieved(earlier) if x)
                    received.append(_content(earlier))
                    complete &= "records" in earlier
            text = "\n".join(received)
            present = any(x in text for x in predecessor["acceptable_evidence"]) or any(
                v in text for group in (groups or []) for v in group
            )
            bypassed = (
                False if present else True if complete and groups is not None else None
            )
            return {
                "retrieved": True,
                "event_id": event["event_id"],
                "bypassed": bypassed,
            }
        return {"retrieved": False, "bypassed": False}
