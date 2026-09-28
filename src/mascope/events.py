from copy import deepcopy

KINDS = {
    "recruit",
    "assign",
    "message",
    "retrieve",
    "local_output",
    "aggregate",
    "memory",
    "submit",
    "usage",
}
ALIASES = {
    "work_start": "assign",
    "contribution": "local_output",
    "final": "submit",
    "search": "retrieve",
    "fetch": "retrieve",
    "model_start": "usage",
    "model_end": "usage",
    "model_error": "usage",
    "work_end": "usage",
}


def export_events(events):
    result = []
    for original in events:
        event = deepcopy(original)
        kind = event["kind"]
        if kind in ALIASES:
            event["native_kind"] = kind
            event["kind"] = ALIASES[kind]
        if event["kind"] == "recruit":
            event.setdefault("agent", event.get("agent_id"))
        if event["kind"] == "retrieve":
            event.setdefault("agent", event.get("agent_id"))
            event.setdefault(
                "returned_identifiers",
                event.get("evidence_ids", [event.get("evidence_id")]),
            )
        if event["kind"] == "local_output":
            event.setdefault("agent", event.get("agent_id"))
            event.setdefault("content", event.get("text", ""))
            event.setdefault("cited_identifiers", event.get("evidence_ids", []))
        if event["kind"] == "message":
            event.setdefault("from", event.get("sender"))
            event.setdefault("to", event.get("recipient"))
            event.setdefault("content", event.get("text", ""))
        if event["kind"] == "usage" and kind in {"model_end", "model_error"}:
            event.setdefault("call", event.get("call_id"))
            event.setdefault("call_type", "model")
            event.setdefault("prompt_tokens", event.get("input_tokens"))
            event.setdefault("completion_tokens", event.get("output_tokens"))
        if event["kind"] == "assign":
            event.setdefault("task_text", event.get("instruction", ""))
            event.setdefault("carried_units", event.get("inputs", []))
            event.setdefault("from", "controller")
            event.setdefault("to", event.get("agent_ids", event.get("agent_id")))
        if event["kind"] == "submit":
            event.setdefault("answer", event.get("text", ""))
        result.append(event)
    return result


def normalize_events(events):
    result = []
    for original in events:
        event = deepcopy(original)
        kind = event["kind"]
        if kind == "assign":
            event.update(
                kind="work_start",
                instruction=event.get("instruction", event.get("task_text", "")),
            )
            recipient = event.get("to", event.get("agent_id"))
            if isinstance(recipient, list):
                event.setdefault("agent_ids", recipient)
            else:
                event.setdefault("agent_id", recipient)
            event.setdefault("inputs", [])
        elif kind == "local_output":
            event.update(
                kind="contribution", text=event.get("text", event.get("content", ""))
            )
            event.setdefault("agent_id", event.get("agent"))
            event.setdefault("artifact_id", event["event_id"])
            event.setdefault("evidence_ids", event.get("cited_identifiers", []))
        elif kind == "retrieve":
            event["kind"] = event.get("native_kind", "search")
            event.setdefault("agent_id", event.get("agent"))
            event.setdefault("evidence_ids", event.get("returned_identifiers", []))
        elif kind == "submit":
            event.update(kind="final", text=event.get("text", event.get("answer", "")))
        elif kind == "usage" and event.get("native_kind"):
            event["kind"] = event["native_kind"]
        elif kind == "message":
            event.setdefault("recipient", event.get("to"))
            event.setdefault("sender", event.get("from"))
            event.setdefault("text", event.get("content", ""))
        if kind == "recruit":
            event.setdefault("agent_id", event.get("agent"))
        result.append(event)
    return result
