"""LLM provider chain: Groq first, free fallbacks after it, so one outage never stops an episode.

Every candidate speaks the OpenAI chat-completions format. The caller builds one payload;
this module tries each candidate in order and returns the first usable response. Local
validators in the callers (fact check, script writer) stay the final authority, so a
fallback model can never relax a safety gate.

Order:
1. Groq, primary model (NEWSFLOW_GROQ_MODEL, default openai/gpt-oss-120b).
2. Groq, fallback models (NEWSFLOW_GROQ_FALLBACK_MODELS, comma separated, default
   openai/gpt-oss-20b). Same key, separate model limits.
3. Optional providers, used only when their key exists: CEREBRAS_API_KEY (gpt-oss-120b),
   GEMINI_API_KEY (gemini-2.5-flash), OPENROUTER_API_KEY (a ":free" model). Model ids are
   overridable with NEWSFLOW_CEREBRAS_MODEL, NEWSFLOW_GEMINI_MODEL, NEWSFLOW_OPENROUTER_MODEL.
Set NEWSFLOW_LLM_PROVIDERS (comma separated, e.g. "cerebras,groq") to force the order.
"""
from __future__ import annotations

import os

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GROQ_FALLBACK_MODELS = "openai/gpt-oss-20b"
PROVIDERS = {
    "cerebras": ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions",
                 "NEWSFLOW_CEREBRAS_MODEL", "gpt-oss-120b"),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "NEWSFLOW_GEMINI_MODEL", "gemini-2.5-flash"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions",
                   "NEWSFLOW_OPENROUTER_MODEL", "openai/gpt-oss-120b:free"),
}
# Fields only Groq understands. They are dropped for other providers.
GROQ_ONLY_FIELDS = ("tool_choice",)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def candidates(primary_model: str | None = None, groq_key: str | None = None) -> list[dict]:
    """Ordered usable candidates: {name, url, key, model, groq}. Providers without a key are skipped."""
    groq_key = (groq_key if groq_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
    primary = (primary_model or os.getenv("NEWSFLOW_GROQ_MODEL", "") or DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    groq_models = [primary]
    for model in _csv(os.getenv("NEWSFLOW_GROQ_FALLBACK_MODELS", DEFAULT_GROQ_FALLBACK_MODELS)):
        if model not in groq_models:
            groq_models.append(model)
    groups: dict[str, list[dict]] = {}
    if groq_key:
        groups["groq"] = [
            {"name": f"groq:{model}", "url": GROQ_URL, "key": groq_key, "model": model, "groq": True}
            for model in groq_models
        ]
    for name, (key_env, url, model_env, default_model) in PROVIDERS.items():
        key = os.getenv(key_env, "").strip()
        if key:
            model = os.getenv(model_env, "").strip() or default_model
            groups[name] = [{"name": f"{name}:{model}", "url": url, "key": key, "model": model, "groq": False}]
    forced = [name for name in _csv(os.getenv("NEWSFLOW_LLM_PROVIDERS", "")) if name in groups]
    order = forced + [name for name in ("groq", *PROVIDERS) if name in groups and name not in forced]
    return [item for name in order for item in groups[name]]


def available() -> bool:
    return bool(candidates())


def _payload_for(payload: dict, candidate: dict) -> dict:
    result = dict(payload)
    result["model"] = candidate["model"]
    if not candidate["groq"]:
        for field in GROQ_ONLY_FIELDS:
            result.pop(field, None)
        fmt = result.get("response_format")
        # Strict json_schema is only relied on for Groq. Elsewhere use plain JSON mode;
        # the caller's local validator still checks the result.
        if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
            result["response_format"] = {"type": "json_object"}
    return result


def chat(payload: dict, service: str, post=None, primary_model: str | None = None,
         groq_key: str | None = None, stop_on: tuple = ()) -> tuple[dict, str]:
    """Send the payload down the chain. Returns (response, candidate name). Raises RuntimeError if all fail.

    stop_on: error substrings that end the chain at once, so the caller can run its own retry
    (the fact checker retries a strict-JSON failure in plain JSON mode before trying other models).
    """
    if post is None:
        from newsflow.fact_check import _post_json as post
    chain = candidates(primary_model, groq_key)
    if not chain:
        raise RuntimeError(f"{service}: no LLM provider key is configured")
    errors = []
    for candidate in chain:
        try:
            response = post(candidate["url"], _payload_for(payload, candidate), candidate["key"], f"{service} [{candidate['name']}]")
            choices = response.get("choices") if isinstance(response, dict) else None
            if not choices or not isinstance((choices[0] or {}).get("message", {}).get("content"), str):
                raise RuntimeError(f"{service} [{candidate['name']}] returned no message content")
            if len(chain) > 1:
                print(f"[LLM] {service} answered by {candidate['name']}")
            return response, candidate["name"]
        except RuntimeError as exc:
            if any(marker in str(exc).casefold() for marker in stop_on):
                raise
            errors.append(str(exc)[:240])
            print(f"[LLM] {service} candidate {candidate['name']} failed: {str(exc)[:160]}")
    raise RuntimeError(f"{service}: all LLM providers failed: " + " | ".join(errors))
