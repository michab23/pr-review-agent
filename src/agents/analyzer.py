# Agent 1: Analyzer — see spec/spec.md §3 for role, tools, system prompt, and risk routing table
from agno.agent import Agent
from agno.models.litellm import LiteLLM

from src.models import PRClassification

ANALYZER_SYSTEM_PROMPT = """\
You are a PR risk classifier. Given a pull request diff and metadata, your job is to:
1. Identify the type(s) of change (feature, bug_fix, refactor, security, docs, config, dependency)
2. Assign a risk level: low (docs/config/trivial fixes), medium (features/refactors), \
high (security-sensitive/auth/payments/data migrations/dependency bumps)
3. List the specific files that drove your risk rating
4. Choose the review model: low→haiku, medium→sonnet, high→opus

Return a valid PRClassification. Be conservative: when in doubt, rate higher.\
"""

# Risk → LiteLLM model ID routing (spec/data-model.md)
RISK_MODEL_MAP = {
    "low": "anthropic/claude-haiku-4-5-20251001",
    "medium": "anthropic/claude-sonnet-4-6",
    "high": "anthropic/claude-opus-4-8",
}

analyzer_agent = Agent(
    name="analyzer",
    model=LiteLLM(id="anthropic/claude-haiku-4-5-20251001", top_p=None),
    output_schema=PRClassification,
    instructions=ANALYZER_SYSTEM_PROMPT,
)
