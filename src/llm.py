"""Claude API wrapper — one place to call the model, with tiered model selection.

Tiers (master plan §14): cheap extraction/scoring -> Haiku, quality writing -> Sonnet,
premium -> Opus. Keeps cost low without losing quality on the parts that matter.
"""
from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from . import config

_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=config.get_api_key())
    return _client


def complete(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.0,
) -> str:
    """Single-turn completion. Returns the text."""
    model = model or config.MODEL_SMART
    msg = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system or "You are a precise assistant. Follow instructions exactly.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")


def complete_json(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2000,
) -> Any:
    """Completion that must return JSON. Strips code fences and parses."""
    sys = (system + "\n\n" if system else "") + (
        "Respond with ONLY valid JSON. No prose, no markdown fences."
    )
    raw = complete(prompt, system=sys, model=model, max_tokens=max_tokens, temperature=0.0)
    return _parse_json(raw)


def _parse_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # last resort: grab the outermost {...} or [...]
        for open_c, close_c in (("{", "}"), ("[", "]")):
            i, j = text.find(open_c), text.rfind(close_c)
            if i != -1 and j != -1 and j > i:
                return json.loads(text[i : j + 1])
        raise
