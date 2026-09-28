import json
import re
from importlib.resources import files


def prompt(name):
    return files("mascope").joinpath("prompts", name + ".txt").read_text().strip()


def tool_schema():
    properties = {"query": {"type": "string"}}
    return [
        {
            "type": "function",
            "function": {
                "name": "retrieve",
                "description": "Retrieve up to eight passages from the permitted corpus.",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            },
        }
    ]


def loop(environment, messages, retrieve, agent_id=None):
    seen_calls = set()
    while True:
        response = environment.complete(
            messages,
            phase="members",
            agent_id=agent_id,
            tools=tool_schema(),
        )
        messages.append(response)
        calls = response.get("tool_calls", [])
        if not calls:
            text = response.get("content")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Tool loop ended without an answer")
            return text
        for call in calls:
            if call.get("id") in seen_calls or not isinstance(call.get("id"), str):
                raise ValueError("Tool call IDs must be unique nonempty strings")
            seen_calls.add(call["id"])
            function = call.get("function", {})
            arguments = json.loads(function.get("arguments", "{}"))
            expected = {"query"}
            if (
                function.get("name") != "retrieve"
                or set(arguments) != expected
                or any(
                    not isinstance(v, str) or not v.strip() for v in arguments.values()
                )
            ):
                raise ValueError("Invalid retrieval call")
            records = retrieve(**arguments)
            text = "\n\n".join(
                f"[{r['evidence_id']}] {r['title']} / {r['text']}" for r in records
            )
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": text}
            )


def specialist(environment, agent_id, instruction, inputs=()):
    context = environment.start_work(agent_id, instruction, inputs)
    profile = next(p for p in environment.profiles() if p["agent_id"] == agent_id)
    system = (
        prompt("expert")
        .replace("<site>", agent_id)
        .replace("<expertise scope>", profile.get("expertise", ""))
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": instruction + "\n\n" + json.dumps(context, ensure_ascii=False),
        },
    ]
    result = loop(
        environment,
        messages,
        lambda query: environment.search(agent_id, query),
        agent_id=agent_id,
    )
    ids = list(dict.fromkeys(re.findall(r"\bMS-[0-9A-Z]{12}\b", result)))
    return environment.contribute(agent_id, result, ids)
