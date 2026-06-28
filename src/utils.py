import os

from langfuse import get_client
from openinference.instrumentation.agno import AgnoInstrumentor

from src.guardrails.validators import OutputValidator

_instrumented = False

extract_json = OutputValidator.extract_json


def configure_model_backend() -> None:
    """Apply USE_LITELLM_PROXY toggle. Call once after load_dotenv(), before any agent runs."""
    if os.getenv("USE_LITELLM_PROXY", "false").lower() in ("1", "true", "yes"):
        proxy_url = os.environ.get("LITELLM_PROXY_URL", "")
        proxy_key = os.environ.get("LITELLM_PROXY_KEY", "")
        if proxy_url:
            os.environ["ANTHROPIC_BASE_URL"] = proxy_url
        if proxy_key:
            os.environ["ANTHROPIC_API_KEY"] = proxy_key
    else:
        os.environ.pop("ANTHROPIC_BASE_URL", None)


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
