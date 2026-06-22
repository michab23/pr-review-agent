# Agent 2: Reviewer — see spec/spec.md §3 for role, tools, system prompt, and reflection step
from agno.agent import Agent
from agno.models.litellm import LiteLLM

from src.models import ReviewFindings

REVIEWER_SYSTEM_PROMPT = """\
You are a senior code reviewer. You review pull requests against the team's coding standards.

Your job:
1. Read the diff carefully — only comment on what is actually in the diff
2. Retrieve relevant team standards using get_team_standards
3. For each issue found, cite the specific standard it violates
4. Do NOT invent file paths or function names — only reference what is in the diff
5. Be specific: "line 42 in auth.py uses MD5 for password hashing" not "security concerns exist"

Produce a ReviewFindings with severity levels: critical (must fix before merge), \
warning (should fix), suggestion (optional improvement).

If the diff is clean and meets standards, say so — an empty findings list with verdict \
"approve" is a valid and valued output.\
"""

# Model is overridden at runtime from PRClassification.model_to_use
reviewer_agent = Agent(
    name="reviewer",
    model=LiteLLM(id="anthropic/claude-sonnet-4-6"),
    response_model=ReviewFindings,
    instructions=REVIEWER_SYSTEM_PROMPT,
)
