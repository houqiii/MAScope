import json
from io import BytesIO

import pytest

from mascope import Completion, OpenAICompatible


@pytest.mark.parametrize(
    "mode", ["valid", "missing_usage", "truncated", "missing_content"]
)
def test_provider_response_and_request_contract(monkeypatch, mode):
    seen = []

    def request(req, timeout):
        seen.append(json.loads(req.data))
        row = {
            "choices": [{"finish_reason": "stop", "message": {"content": "Result"}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 4},
        }
        if mode == "missing_usage":
            del row["usage"]
        elif mode == "truncated":
            row["choices"][0]["finish_reason"] = "length"
        elif mode == "missing_content":
            row["choices"][0]["message"]["content"] = None
        return BytesIO(json.dumps(row).encode())

    monkeypatch.setattr("urllib.request.urlopen", request)
    model = OpenAICompatible("example", "https://example.org/v1", "test-only")
    if mode == "valid":
        assert model.complete(
            [{"role": "user", "content": "Question"}], 90, True
        ) == Completion("Result", 13, 4)
        assert seen[0]["response_format"] == {"type": "json_object"}
        assert seen[0]["max_tokens"] == 90
        assert "temperature" not in seen[0]
        assert "top_p" not in seen[0]
        assert "seed" not in seen[0]
        assert seen[0]["reasoning_effort"] == "high"
    else:
        with pytest.raises(RuntimeError):
            model.complete([])


@pytest.mark.parametrize("count", [-1, True, 1.2])
def test_invalid_usage_rejected(count):
    with pytest.raises(ValueError):
        Completion("result", count, 1)


def test_truncated_response_retains_reported_cost(dataset):
    from mascope.environment import Environment
    from mascope.model import ResponseError

    class Truncated:
        def complete(self, *args):
            raise ResponseError("Truncated", {"input_tokens": 20, "output_tokens": 40})

    environment = Environment(dataset, next(iter(dataset)), Truncated())
    with pytest.raises(ResponseError):
        environment.complete([])
    usage = environment.export()["usage"]
    assert usage["tokens"] == 60
    assert usage["calls_with_unknown_usage"] == 0
    assert usage["phases"]["planning"] == {"input_tokens": 20, "output_tokens": 40}


def test_native_tool_calls_preserve_usage(monkeypatch):
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "retrieve", "arguments": '{"query":"route"}'},
            }
        ],
    }

    def response(request, timeout):
        assert json.loads(request.data)["tools"][0]["function"]["name"] == "retrieve"
        return BytesIO(
            json.dumps(
                {
                    "choices": [{"finish_reason": "tool_calls", "message": message}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                }
            ).encode()
        )

    monkeypatch.setattr("urllib.request.urlopen", response)
    result = OpenAICompatible("example", api_key="fixture").complete(
        [], tools=[{"type": "function", "function": {"name": "retrieve"}}]
    )
    assert result.message == message and result.input_tokens == 10


def test_all_phases_share_default_decoding_and_resume_checks_effort(
    dataset, tmp_path, monkeypatch
):
    from mascope.runner import run

    requests = []

    def response(request, timeout):
        requests.append(json.loads(request.data))
        return BytesIO(json.dumps({
            "choices": [{"finish_reason": "stop", "message": {"content": "result"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }).encode())

    def agent(env):
        for phase in ("planning", "members", "synthesis", "memory"):
            env.complete([], phase=phase)
        env.submit("result")

    monkeypatch.setattr("urllib.request.urlopen", response)
    model = OpenAICompatible("example", api_key="fixture")
    result = next(run(dataset, agent, model, tmp_path, task_ids=["task_one"]))
    assert result["status"] == "completed"
    assert result["decoding"] == {"reasoning_effort": "high"}
    assert result["usage"]["tokens"] == 48
    assert len(requests) == 4
    for request in requests:
        assert request["reasoning_effort"] == "high"
        assert request["max_tokens"] == 4096
        assert not {"temperature", "top_p", "seed"} & request.keys()
    model = OpenAICompatible("example", api_key="fixture", reasoning_effort="low")
    with pytest.raises(ValueError, match="different task or run configuration"):
        next(run(dataset, agent, model, tmp_path, task_ids=["task_one"], resume=True))


def test_explicit_alternative_decoding_is_retained():
    model = OpenAICompatible(
        "example", api_key="fixture", temperature=0.3, top_p=0.95,
        seed=7, reasoning_effort=None,
    )
    assert model.decoding == {"temperature": 0.3, "top_p": 0.95, "seed": 7}
