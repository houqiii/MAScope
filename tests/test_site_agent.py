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
