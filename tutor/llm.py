"""
Module 4: connection to the language model (LLM).

The rest of the app only calls `llm.chat(system_prompt, messages)`.
Which model answers is decided by config.yaml:

    provider: anthropic  -> Claude, over the internet (needs an API key)
    provider: ollama     -> a small open model running on this laptop,
                            works offline once downloaded

Both study arms use the SAME object created here, so they always use the
same model and settings; only the system prompt differs.

`messages` is the conversation so far, a list like:
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
"""

import requests


class LLMError(Exception):
    """A problem talking to the model, with a message a person can act on."""


class AnthropicLLM:
    def __init__(self, settings):
        import anthropic  # imported here so Ollama users don't need it
        self.anthropic = anthropic
        # The API key is read from the ANTHROPIC_API_KEY environment
        # variable automatically. It is never written in the code.
        self.client = anthropic.Anthropic()
        self.model = settings["anthropic_model"]
        self.max_tokens = settings["max_tokens"]
        self.effort = settings["effort"]

    def chat(self, system_prompt, messages):
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
                # How hard the model thinks before answering. "low" keeps
                # replies fast, which matters in a chat with a student.
                output_config={"effort": self.effort},
            )
        except self.anthropic.AuthenticationError:
            raise LLMError("The API key is wrong. Check ANTHROPIC_API_KEY (see README).")
        except TypeError as e:
            # The SDK raises TypeError when it finds no API key at all.
            if "authentication" in str(e).lower():
                raise LLMError("No API key found. Set ANTHROPIC_API_KEY (see README).")
            raise
        except self.anthropic.RateLimitError:
            raise LLMError("Too many requests to the model. Wait a minute and try again.")
        except self.anthropic.APIConnectionError:
            raise LLMError("No internet connection to the model. Check the internet, "
                           "or switch to provider: ollama in config.yaml.")
        except self.anthropic.APIStatusError as e:
            raise LLMError(f"The model service returned an error ({e.status_code}).")

        # The model may decline for safety reasons; show a neutral message.
        if response.stop_reason == "refusal":
            return "Sorry, I can't help with that. Let's go back to the question."

        # The reply is a list of blocks; keep only the text ones.
        return "".join(b.text for b in response.content if b.type == "text").strip()


class OllamaLLM:
    """
    Talks to Ollama, a free program that runs open models on the laptop.
    Ollama must be installed and running (see README).
    """

    def __init__(self, settings):
        self.model = settings["ollama_model"]
        self.url = settings["ollama_url"].rstrip("/") + "/api/chat"
        self.temperature = settings["ollama_temperature"]
        self.max_tokens = settings["max_tokens"]

    def chat(self, system_prompt, messages):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
        }
        try:
            response = requests.post(self.url, json=payload, timeout=300)
        except requests.ConnectionError:
            raise LLMError("Ollama is not running. Start the Ollama app, then try again.")
        if response.status_code == 404:
            raise LLMError(f"Model '{self.model}' is not downloaded. Run: ollama pull {self.model}")
        response.raise_for_status()
        return response.json()["message"]["content"].strip()


def make_llm(config):
    """Create the model connection chosen in config.yaml."""
    settings = config["llm"]
    if settings["provider"] == "anthropic":
        return AnthropicLLM(settings)
    if settings["provider"] == "ollama":
        return OllamaLLM(settings)
    raise ValueError(f"Unknown llm provider: {settings['provider']}")
