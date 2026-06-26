import json
import os
import re

from langfuse import get_client
from openinference.instrumentation.agno import AgnoInstrumentor


def extract_json(text: str) -> str:
    """Extract the outermost JSON object from LLM output, handling markdown fences."""
    text = re.sub(r"^```(?:json)?\s*\n(.*)\n```\s*$", r"\1", text.strip(), flags=re.DOTALL)
    text = text.strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in LLM output: {text[:200]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse JSON from LLM output: {e}. "
            f"Text prefix: {text[start:start + 200]!r}"
        ) from e
    return json.dumps(obj)


def setup_langfuse_tracing() -> None:
    """Initialise LangFuse SDK from env vars. Call once in __main__ before any agent runs."""
    required = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing LangFuse env vars: {', '.join(missing)}")
    get_client()
    AgnoInstrumentor().instrument()
