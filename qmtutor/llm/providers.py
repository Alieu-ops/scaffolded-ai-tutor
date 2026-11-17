"""
Provider-neutral LLM gateway.

The tutor only ever calls `provider.generate(system, messages, schema)` and
gets back a validated Pydantic object or a ProviderError. Which model answers
(local Ollama, a cloud API, or a fake in tests) is a configuration choice, so
the same tutoring rules can be compared across models fairly.

Ollama is the runtime (it downloads and serves open models locally); the
MODEL is a separate choice (e.g. llama3.2:3b); the TUTOR POLICY is neither:
it lives in domain/scaffold_policy.py. Keeping these three apart is a key
design point.

Failures are typed. A timeout, a missing model or malformed output never
becomes invented feedback; the calling service shows safe approved text.
"""

from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

import requests
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """code: 'unavailable', 'timeout', 'model_missing', 'invalid_output', 'auth', 'http_error'."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, system: str, messages: list[dict], schema: type[T]) -> T: ...


class OllamaProvider:
    """Local model through Ollama's /api/chat with JSON-schema structured output."""
    name = "ollama"

    def __init__(self, model: str, url: str = "http://localhost:11434", temperature: float = 0.2,
                 timeout_seconds: int = 120, max_tokens: int = 700):
        self.model = model
        self.url = url.rstrip("/") + "/api/chat"
        self.temperature = temperature
        self.timeout = timeout_seconds
        self.max_tokens = max_tokens

    def generate(self, system: str, messages: list[dict], schema: type[T]) -> T:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": False,
            "format": schema.model_json_schema(),   # Ollama constrains output to this JSON shape
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
        }
        try:
            response = requests.post(self.url, json=payload, timeout=self.timeout)
        except requests.ConnectionError:
            raise ProviderError("unavailable", "The local model server (Ollama) is not running.")
        except requests.Timeout:
            raise ProviderError("timeout", "The model took too long to reply.")
        if response.status_code == 404:
            raise ProviderError("model_missing", f"Model '{self.model}' is not installed (ollama pull {self.model}).")
        if response.status_code >= 400:
            raise ProviderError("http_error", f"Ollama returned HTTP {response.status_code}.")
        content = response.json().get("message", {}).get("content", "")
        return _validate(content, schema)


class AnthropicProvider:
    """
    Optional cloud provider (configuration only). Implemented but NOT live-tested
    in this build: no API key was available. Uses the same schemas: the JSON
    schema is given in the system prompt and the reply is validated by Pydantic.
    """
    name = "anthropic"

    def __init__(self, model: str, max_tokens: int = 1200):
        import anthropic   # imported lazily so Ollama-only installs do not need it
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()    # reads ANTHROPIC_API_KEY from the environment
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, system: str, messages: list[dict], schema: type[T]) -> T:
        instruction = (f"{system}\n\nReply with ONLY a JSON object matching this JSON schema, no other text:\n"
                       f"{json.dumps(schema.model_json_schema())}")
        try:
            response = self.client.messages.create(model=self.model, max_tokens=self.max_tokens,
                                                   system=instruction, messages=messages)
        except self._anthropic.AuthenticationError:
            raise ProviderError("auth", "The cloud API key is missing or wrong.")
        except self._anthropic.APIConnectionError:
            raise ProviderError("unavailable", "No connection to the cloud model.")
        except self._anthropic.APIStatusError as error:
            raise ProviderError("http_error", f"The cloud model returned HTTP {error.status_code}.")
        text = "".join(b.text for b in response.content if b.type == "text")
        return _validate(text, schema)


class FakeProvider:
    """
    Test double: returns scripted replies (Pydantic objects, dicts, raw strings
    or exceptions) in order, and records every call for assertions.
    """
    name = "fake"

    def __init__(self, replies: list | None = None, model: str = "fake-model"):
        self.replies = list(replies or [])
        self.model = model
        self.calls: list[dict] = []

    def generate(self, system: str, messages: list[dict], schema: type[T]) -> T:
        self.calls.append({"system": system, "messages": messages, "schema": schema.__name__})
        reply = self.replies.pop(0) if self.replies else {"message": "What is your first step?"}
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, BaseModel):
            return schema.model_validate(reply.model_dump())
        if isinstance(reply, dict):
            return _validate(json.dumps({**_defaults(schema), **reply}), schema)
        return _validate(str(reply), schema)


def _defaults(schema: type[BaseModel]) -> dict:
    """Minimal required fields so a FakeProvider dict like {'message': ...} fits other schemas too."""
    if schema.__name__ == "StudyReply":
        return {"explanation": "Here is an explanation."}
    if schema.__name__ == "ReasoningAssessment":
        return {"method_selection": 1, "mathematical_steps": 1, "conceptual_explanation": 1}
    return {}


def _validate(text: str, schema: type[T]) -> T:
    """Parse JSON (tolerating text around it) and validate. Raises ProviderError('invalid_output')."""
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    try:
        return schema.model_validate_json(match.group(0) if match else text)
    except (ValidationError, ValueError) as error:
        raise ProviderError("invalid_output", f"Model output did not match {schema.__name__}: {str(error)[:200]}")


def generate_with_retry(provider: LLMProvider, system: str, messages: list[dict], schema: type[T],
                        max_retries: int = 1) -> T:
    """Bounded retry for malformed output only. Other failures are raised at once."""
    for attempt in range(max_retries + 1):
        try:
            return provider.generate(system, messages, schema)
        except ProviderError as error:
            if error.code != "invalid_output" or attempt == max_retries:
                raise
    raise AssertionError("unreachable")


def make_provider(settings: dict) -> LLMProvider:
    """Build the provider named in config_v2.yaml (llm.provider)."""
    kind = settings["provider"]
    if kind == "ollama":
        return OllamaProvider(settings["ollama_model"], settings.get("ollama_url", "http://localhost:11434"),
                              settings.get("temperature", 0.2), settings.get("timeout_seconds", 120))
    if kind == "anthropic":
        return AnthropicProvider(settings["anthropic_model"])
    if kind == "fake":
        return FakeProvider()
    raise ValueError(f"Unknown LLM provider: {kind}")
