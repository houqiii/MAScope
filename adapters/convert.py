import json
from copy import deepcopy
from pathlib import Path

from mascope.events import KINDS, export_events


def configurations():
    return [
        json.loads(path.read_text())
        for path in sorted(Path(__file__).parent.glob("*/config.json"))
    ]


HOOKS = {
    "AutoGen": ("speaker_selected", "speaker_prompt", "closing_summary", "termination"),
    "Magentic-One": (
        "ledger_specialist",
        "next_speaker",
        "progress_merge",
        "final_answer",
    ),
    "Flow": ("worker_allocated", "node_dispatched", "graph_merge", "last_node"),
    "CrewAI": (
        "member_delegated",
        "task_delegated",
        "manager_synthesis",
        "kickoff_result",
    ),
    "LangGraph": (
        "worker_handoff",
        "handoff_prompt",
        "supervisor_merge",
        "supervisor_answer",
    ),
    "Anemoi": ("thread_member", "plan_item", "consensus_vote", "answer_submission"),
    "AgentVerse": (
        "role_staffed",
        "action_decided",
        "evaluation_merge",
        "result_accepted",
    ),
    "MoA": (
        "first_layer_proposer",
        "layer_prompt",
        "aggregator_synthesis",
        "aggregator_output",
    ),
    "MAD": (
        "first_round_debater",
        "revision_prompt",
        "majority_vote",
        "selected_answer",
    ),
    "GoA": ("node_sampled", "neighbor_prompt", "pooling", "pooled_response"),
    "AgentNet": ("route_target", "forwarded_task", "returned_merge", "agent_answer"),
    "SelfOrg": (
        "initial_responder",
        "predecessor_prompt",
        "centroid_selection",
        "selected_response",
    ),
}


class LogAdapter:
    def __init__(self, method):
        configs = configurations()
        config = next(
            (c for c in configs if method in {c["method"], c["display"]}), None
        )
        if config is None or config["display"] not in HOOKS:
            raise ValueError("Unknown multi-agent adapter")
        self.config = config
        self.hooks = dict(
            zip(HOOKS[config["display"]], ("recruit", "assign", "aggregate", "submit"))
        )

    def convert(self, records):
        result = []
        recruited = set()
        submitted = False
        expanded = []
        for original in records:
            if original.get("hook") == "coordinator_turn":
                if "aggregate" in original:
                    expanded.append({"kind": "aggregate", **original["aggregate"]})
                expanded.extend(
                    {"kind": "assign", **item}
                    for item in original.get("assignments", [])
                )
            else:
                expanded.append(original)
        records = []
        for event in expanded:
            kind = self.hooks.get(
                event.get("hook", event.get("kind")), event.get("kind")
            )
            recipients = event.get("to", event.get("agent_ids"))
            if kind == "assign" and isinstance(recipients, list):
                for recipient in recipients:
                    item = deepcopy(event)
                    item.pop("agent_ids", None)
                    item.update(to=recipient, agent_id=recipient)
                    records.append(item)
            else:
                records.append(event)
        for original in records:
            if submitted:
                raise ValueError("Events after submission")
            event = deepcopy(original)
            native = event.pop("hook", event.get("kind"))
            kind = self.hooks.get(native, native)
            if kind not in KINDS:
                raise ValueError("Unknown log hook: " + str(native))
            event["kind"] = kind
            event["source_hook"] = native
            if kind in {"recruit", "assign", "local_output"}:
                agent = event.get("agent_id", event.get("to"))
                if not isinstance(agent, str) or not agent:
                    raise ValueError("Log hook needs a concrete receiving agent_id")
                event["agent_id"] = agent
                if agent not in recruited:
                    recruited.add(agent)
                    if kind != "recruit" and self.config["display"] in {
                        "AutoGen",
                        "CrewAI",
                        "LangGraph",
                        "MoA",
                        "MAD",
                        "SelfOrg",
                    }:
                        result.append(
                            {
                                "kind": "recruit",
                                "agent_id": agent,
                                "source_hook": native,
                            }
                        )
                elif kind == "recruit":
                    continue
            if kind == "assign":
                if not isinstance(event.get("instruction"), str) or not isinstance(
                    event.get("carried_units"), list
                ):
                    raise ValueError(
                        "Assignments require the actual instruction and all visible carried_units"
                    )
                event.setdefault("inputs", [])
            if kind == "local_output":
                if not isinstance(event.get("text"), str) or not isinstance(
                    event.get("evidence_ids"), list
                ):
                    raise ValueError("Local output requires text and evidence_ids")
                event.setdefault("artifact_id", f"a{len(result) + 1:06d}")
            if kind == "submit":
                if not isinstance(event.get("text"), str) or not event["text"].strip():
                    raise ValueError("Submission requires answer text")
                submitted = True
            result.append(event)
        for i, event in enumerate(result, 1):
            if event.get("event_id"):
                event["source_event_id"] = event["event_id"]
            event["event_id"] = f"e{i:06d}"
        return export_events(result)


def adapt(method, records):
    return LogAdapter(method).convert(records)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert supplied method logs into MAScope events"
    )
    parser.add_argument("--method", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = Path(args.input)
    records = [
        json.loads(line) for line in source.read_text().splitlines() if line.strip()
    ]
    events = adapt(args.method, records)
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    )


if __name__ == "__main__":
    main()
