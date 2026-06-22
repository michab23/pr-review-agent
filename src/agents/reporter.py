# Agent 3: Reporter — see spec/spec.md §3 for role, HITL behavior, and comment format
from agno.agent import Agent
from agno.models.litellm import LiteLLM

REPORTER_SYSTEM_PROMPT = """\
You are a technical writer formatting a code review for a GitHub PR comment.

Given the review findings, produce a clear, structured markdown comment that:
1. Opens with a one-sentence verdict summary
2. Lists each finding with its severity, file, line range, issue, cited standard, and fix
3. Closes with run metadata (run ID, cost, LangFuse trace link)

Follow the comment template in spec/data-model.md exactly.\
"""

reporter_agent = Agent(
    name="reporter",
    model=LiteLLM(id="anthropic/claude-sonnet-4-6"),
    instructions=REPORTER_SYSTEM_PROMPT,
)
