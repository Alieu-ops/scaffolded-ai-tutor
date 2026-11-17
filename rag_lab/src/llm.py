"""
A small client for the LOCAL language model (Ollama), with a disk cache.

Plain language: Ollama runs the model on this laptop and listens at http://localhost:11434.
We send it a prompt and get text back. Nothing leaves the computer.

Why a cache: on this CPU each answer takes seconds. Evaluating hundreds of questions with
several methods would take hours if every run asked again. So every (model, task, input) is
answered once and saved in output/llm_cache.jsonl; later runs reuse the saved answer.
Changing the prompt text changes the cache key automatically (the prompt is part of it).

Settings: temperature 0 makes the model pick its most likely words, so the same input gives
(almost) the same output: steadier and less "creative", which is what we want here.
"""

from __future__ import annotations

import hashlib
import json
import re

import requests

from common import LAB

OLLAMA_URL = "http://localhost:11434/api/generate"
CACHE_FILE = LAB / "output" / "llm_cache.jsonl"
DEFAULT_MODEL = "llama3.2:3b"
TIMEOUT_SECONDS = 300

_cache: dict[str, str] | None = None


def _load_cache() -> dict[str, str]:
    global _cache
    if _cache is None:
        _cache = {}
        if CACHE_FILE.exists():
            for line in CACHE_FILE.open(encoding="utf-8"):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue      # a half-written line (run stopped mid-write): skip it; it is simply asked again
                _cache[record["key"]] = record["output"]
    return _cache


def generate(prompt: str, model: str = DEFAULT_MODEL, json_mode: bool = False, options: dict | None = None,
             schema: dict | None = None) -> str:
    """
    Send one prompt to the local model; return its text (from the cache when possible).
    options: extra Ollama settings, e.g. {"num_ctx": 8192} (how much text the model can read at
    once; the default is too small for 5 textbook passages) or {"num_predict": 600} (maximum
    answer length). Calls without options keep their old cache keys.
    schema: a JSON schema the reply MUST follow ("structured outputs"). Ollama then only lets the
    model write tokens that fit the schema, so a small model cannot produce a broken shape.
    """
    options = options or {}
    extra = f"\x00{json.dumps(options, sort_keys=True)}" if options else ""
    extra += f"\x00{json.dumps(schema, sort_keys=True)}" if schema else ""
    key = hashlib.sha1(f"{model}\x00{json_mode}\x00{prompt}{extra}".encode("utf-8")).hexdigest()
    cache = _load_cache()
    if key in cache:
        return cache[key]

    payload = {"model": model, "prompt": prompt, "stream": False,
               "options": {"temperature": 0, **options}, "think": False}     # think=False: no long hidden "reasoning"
    if schema:
        payload["format"] = schema                                  # valid JSON of exactly this shape
    elif json_mode:
        payload["format"] = "json"                                  # ask Ollama to return valid JSON
    response = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    if response.status_code == 400 and "think" in response.text.lower():
        payload.pop("think")                                        # model does not accept the setting
        response = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    text = response.json().get("response", "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # drop any visible reasoning

    cache[key] = text
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "model": model, "output": text}, ensure_ascii=False) + "\n")
    return text


def generate_json(prompt: str, model: str = DEFAULT_MODEL, options: dict | None = None,
                  schema: dict | None = None) -> dict:
    """Like generate(), but parse the reply as JSON. Returns {} if the model produced invalid JSON."""
    text = generate(prompt, model, json_mode=True, options=options, schema=schema)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def check_ollama(model: str) -> None:
    """Fail early with a clear message if Ollama is not running or the model is missing."""
    try:
        tags = requests.get("http://localhost:11434/api/tags", timeout=5).json()
    except requests.RequestException:
        raise SystemExit("Ollama is not running. Start the Ollama app (or run: ollama serve).")
    names = {m["name"] for m in tags.get("models", [])}
    if model not in names:
        raise SystemExit(f"Model {model} is not installed. Run: ollama pull {model}\nInstalled: {sorted(names)}")
