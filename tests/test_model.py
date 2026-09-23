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
        assert seen[0]["temperature"] == 0.3
        assert seen[0]["top_p"] == 0.95
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
