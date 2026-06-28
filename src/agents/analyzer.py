# Agent 1: Analyzer — see spec/spec.md §3 for role, tools, system prompt, and risk routing table
from agno.agent import Agent
from agno.models.litellm import LiteLLM
from langfuse import get_client, observe

ANALYZER_SYSTEM_PROMPT = """\
You are a PR risk classifier. Given a pull request diff and metadata, your job is to:
1. Identify the type(s) of change (feature, bug_fix, refactor, security, docs, config, dependency)
2. Assign a risk level. Default is MEDIUM — only deviate with strong reason:
   - low: Pure docs/comments (no code change), OR config-only changes with no new packages \
and no logic change — e.g. linter/formatter config, minor version bumps of EXISTING \
dependencies without CVEs. No new code paths, no new packages introduced.
   - medium: Everything else — bug fixes of any size, new features, refactors, dependency \
additions/upgrades without CVEs, behavioral changes, config value changes, missing auth or \
validation (reviewer catches these). When in doubt between low and medium, choose MEDIUM.
   - high: ONLY when code CONTAINS an active exploitable vulnerability: broken crypto \
(MD5/SHA1 for passwords, hardcoded secrets/tokens in source), SQL/command injection, XSS, \
or when implementing/modifying auth systems, payment flows, data migrations, or upgrading \
dependencies with known CVEs.
3. List the specific files that drove your risk rating
4. Choose the review model: low→haiku, medium→sonnet, high→opus

Examples:
- "Remove slice cap [:100] in pagination logic" → MEDIUM (behavioral code change)
- "Add httpx + retry decorator" → MEDIUM (new dependency + behavior change)
- "New feature endpoint (even if missing auth check)" → MEDIUM
- "Update README.md only" → LOW
- "Bump existing dep minor version + add linter config in pyproject.toml" → LOW (config-only, no new packages)
- "MD5 password hashing" → HIGH (broken crypto in code)
- "Hardcoded secret in source" → HIGH

Return ONLY a valid JSON object — no markdown fences, no prose:
{
  "risk_level": "low" | "medium" | "high",
  "change_types": ["feature" | "bug_fix" | "refactor" | "security" | "docs" | "config" | "dependency"],
  "risk_rationale": "<one sentence>",
  "model_to_use": "<litellm model id>",
  "files_of_concern": ["<filename>", ...]
}\
"""

# Risk → LiteLLM model ID routing (spec/data-model.md)
RISK_MODEL_MAP = {
    "low": "anthropic/claude-haiku-4-5-20251001",
    "medium": "anthropic/claude-sonnet-4-6",
    "high": "anthropic/claude-opus-4-8",
}

from src.models import PRClassification

analyzer_agent = Agent(
    name="analyzer",
    model=LiteLLM(id="anthropic/claude-haiku-4-5-20251001", top_p=None, temperature=1),
    instructions=ANALYZER_SYSTEM_PROMPT,
    output_schema=PRClassification,
)


@observe(name="analyzer")
def run_standalone(payload: dict) -> dict:
    """Run the Analyzer against a PRMetadata payload; return PRClassification dict."""
    import json
    from src.models import PRMetadata
    from src.utils import extract_json
    metadata = PRMetadata.model_validate(payload)
    result = analyzer_agent.run(str(metadata.model_dump()))
    content = result.content
    if isinstance(content, str):
        return json.loads(extract_json(content))
    if isinstance(content, dict):
        return content
    if hasattr(content, "model_dump"):
        return content.model_dump()
    raise TypeError(f"Unexpected analyzer output type: {type(content).__name__}")


if __name__ == "__main__":
    import json
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    from src.utils import configure_model_backend, setup_langfuse_tracing
    configure_model_backend()
    tracing_enabled = False
    try:
        setup_langfuse_tracing()
        tracing_enabled = True
    except RuntimeError:
        pass  # Langfuse env vars not set; run without tracing
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(run_standalone(payload), indent=2))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if tracing_enabled:
            get_client().flush()
