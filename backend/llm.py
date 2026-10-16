"""Thin wrapper over an OpenAI-compatible API, used for all LLM/VLM calls.

Provider: Google Gemini directly when GEMINI_API_KEY is set, otherwise OpenRouter
(ACCESSFLOW_OPENROUTER_API_KEY).
"""

import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
DEFAULT_MODEL = "google/gemini-3.1-flash-lite"

MODEL_EDGES = os.environ.get("LLM_MODEL_EDGES") or DEFAULT_MODEL
MODEL_SUMMARY = os.environ.get("LLM_MODEL_SUMMARY") or DEFAULT_MODEL

_client: Optional[OpenAI] = None


def using_gemini() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def is_configured() -> bool:
    """True when a key for either provider is set."""
    return using_gemini() or bool(os.environ.get("ACCESSFLOW_OPENROUTER_API_KEY"))


def _model_name(model: str) -> str:
    # OpenRouter slugs are "google/<model>"; Google's own API wants just "<model>".
    if using_gemini() and model.startswith("google/"):
        return model[len("google/"):]
    return model


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if using_gemini():
            _client = OpenAI(base_url=GEMINI_BASE_URL, api_key=os.environ["GEMINI_API_KEY"])
        else:
            api_key = os.environ.get("ACCESSFLOW_OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "Set GEMINI_API_KEY or ACCESSFLOW_OPENROUTER_API_KEY to use the AI model."
                )
            _client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    return _client


def _image_data_url(image_path: str) -> str:
    path = Path(image_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def complete(
    prompt: str,
    *,
    model: str,
    image_path: Optional[str] = None,
    json_mode: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    retries: int = 3,
    retry_delay: float = 5.0,
) -> str:
    """Send one user message (optionally with an image) and return the reply text."""
    content = []
    if image_path:
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(image_path)}})
    content.append({"type": "text", "text": prompt})

    kwargs = {"model": _model_name(model), "messages": [{"role": "user", "content": content}]}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = get_client().chat.completions.create(**kwargs)
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:  # network / rate limit / provider errors
            last_err = e
            if attempt < retries:
                time.sleep(retry_delay * attempt)
    raise RuntimeError(f"LLM call failed after {retries} attempts: {str(last_err)[:500]}")
