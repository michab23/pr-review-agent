import os

from langfuse import get_client
from openinference.instrumentation.agno import AgnoInstrumentor

from src.guardrails.validators import OutputValidator

_instrumented = False

extract_json = OutputValidator.extract_json


def setup_langfuse_tracing() -> None:
    """Initialise LangFuse SDK from env vars. Call once in __main__ before any agent runs."""
    global _instrumented
    if _instrumented:
        return
    required = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing LangFuse env vars: {', '.join(missing)}")
    get_client()
    AgnoInstrumentor().instrument()
    _instrumented = True
