import os
from langfuse import get_client


def setup_langfuse_tracing() -> None:
    """Initialise LangFuse SDK from env vars. Call once in __main__ before any agent runs."""
    required = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing LangFuse env vars: {', '.join(missing)}")
    get_client()
