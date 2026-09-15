import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int

    def __post_init__(self):
        if any(
            type(v) is not int or v < 0 for v in (self.input_tokens, self.output_tokens)
        ):
            raise ValueError("Token usage must be nonnegative integers")


class ResponseError(RuntimeError):
    def __init__(self, message, usage):
        super().__init__(message)
        self.usage = usage


class OpenAICompatible:
    def __init__(self, model, base_url=None, api_key=None, timeout=180):
        self.model = model
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("Set OPENAI_API_KEY")

    def complete(self, messages, max_tokens=4096, json_output=False):
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Model request failed with HTTP {exc.code}") from None
        usage = data.get("usage", {})
        if "prompt_tokens" not in usage or "completion_tokens" not in usage:
            raise RuntimeError("Provider response did not include token usage")
        measured = Completion("", usage["prompt_tokens"], usage["completion_tokens"])
        counts = {
            "input_tokens": measured.input_tokens,
            "output_tokens": measured.output_tokens,
        }
        choices = data.get("choices", [])
        if not choices or choices[0].get("finish_reason") == "length":
            raise ResponseError("Missing or truncated model response", counts)
        text = choices[0]["message"].get("content")
        if not isinstance(text, str):
            raise ResponseError("Expected a text response", counts)
        return Completion(text, usage["prompt_tokens"], usage["completion_tokens"])
