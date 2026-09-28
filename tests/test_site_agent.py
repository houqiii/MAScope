import json
import pytest
from mascope.environment import Environment
from mascope.model import ToolCompletion
from mascope.site_agent import prompt


class ToolModel:
    def __init__(self, single=False):
        self.single = single
        self.seen = []

    def complete(self, messages, max_tokens, json_output, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        if len(self.seen) == 1:
            args = {"query": "blue route"}
            if self.single:
                args["site"] = "alpha"
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {"name": "retrieve", "arguments": json.dumps(args)},
                    }
                ],
            }
        else:
            assert messages[-1]["role"] == "tool"
            assert "blue route" in messages[-1]["content"]
            message = {
                "role": "assistant",
                "content": "The blue route reaches the destination.",
            }
        return ToolCompletion(message, 10, 5)


def test_expert_prompt_and_private_corpus(dataset):
    model = ToolModel()
    env = Environment(dataset, next(iter(dataset)), model)
    result = env.ask("alpha", "Find the blue route")
    assert result["agent_id"] == "alpha"
    assert model.seen[0][0]["content"] == prompt("expert").replace(
        "<site>", "alpha"
    ).replace("<expertise scope>", "routing")
    retrieved = next(e for e in env.export()["events"] if e["kind"] == "retrieve")
    assert all(set(r) == {"evidence_id", "title", "text"} for r in retrieved["records"])
    with pytest.raises(ValueError):
        env.ask("alpha", "work", top_k=3)


def test_addressed_messages_and_memory_are_in_the_expert_prompt(dataset):
    model = ToolModel()
    env = Environment(dataset, next(iter(dataset)), model)
    env.send("controller", "alpha", "Use the upstream limit of 30 s")
    env.send("controller", "beta", "An unrelated private message")
    env.record_memory("board", "write", ["Unread board item"])
    env.record_memory("board", "read", ["Read board item"], recipients=["alpha"])
    env.ask("alpha", "Find the blue route")
    user = model.seen[0][1]["content"]
    assert "upstream limit of 30 s" in user and "Read board item" in user
    assert "Unread board item" not in user and "unrelated private" not in user
    work = next(e for e in env.export()["events"] if e["kind"] == "assign")
    assert json.loads(user.split("\n\n", 1)[1]) == work["carried_units"]
