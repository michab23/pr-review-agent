# Agent 1: Analyzer — see spec/spec.md §3 for role, tools, system prompt, and risk routing table
from agno.agent import Agent
from agno.models.litellm import LiteLLM

ANALYZER_SYSTEM_PROMPT = """\
You are a PR risk classifier. Given a pull request diff and metadata, your job is to:
1. Identify the type(s) of change (feature, bug_fix, refactor, security, docs, config, dependency)
2. Assign a risk level: low (docs/config/trivial fixes), medium (features/refactors), \
high (security-sensitive/auth/payments/data migrations/dependency bumps)
3. List the specific files that drove your risk rating
4. Choose the review model: low→haiku, medium→sonnet, high→opus

Be conservative: when in doubt, rate higher.

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

analyzer_agent = Agent(
    name="analyzer",
    model=LiteLLM(id="anthropic/claude-haiku-4-5-20251001", top_p=None, temperature=1),
    instructions=ANALYZER_SYSTEM_PROMPT,
)


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
    return content.model_dump()


if __name__ == "__main__":
    import json
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(run_standalone(payload), indent=2))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
