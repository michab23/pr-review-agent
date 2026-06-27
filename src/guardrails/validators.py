"""
Input/output validators for the PR review pipeline.

Input guardrails protect the system from malformed or malicious PR content.
Output guardrails protect users by enforcing schema and bounds on LLM output.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

MAX_DIFF_BYTES = 102_400  # 100 KB
_TRUNCATION_MARKER = "\n\n[diff truncated — exceeds 100 KB]"

_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"system prompt",
    r"you are now",
]

# Known-safe path segments that may follow /pull/<number>
_ALLOWED_PR_SUFFIXES = frozenset({"files", "commits"})


class ValidationError(ValueError):
    """Raised when input or output validation fails."""


class InputValidator:
    """Validate pipeline inputs before they reach any agent or LLM."""

    @staticmethod
    def validate_pr_url(url: str) -> tuple[str, int]:
        """Strictly validate a GitHub PR URL; return (repo_name, pr_number).

        Rejects trailing garbage, unknown path suffixes, whitespace, and
        control characters. Accepted forms:
          https://github.com/<owner>/<repo>/pull/<number>
          https://github.com/<owner>/<repo>/pull/<number>/files
          https://github.com/<owner>/<repo>/pull/<number>/commits
        Query strings and fragments are ignored (urlparse strips them).
        """
        if not url or not isinstance(url, str):
            raise ValidationError("PR URL must be a non-empty string")

        url = url.strip()

        # Reject embedded whitespace or control characters anywhere in the URL.
        if re.search(r"[\x00-\x20\x7f]", url):
            raise ValidationError(
                "Invalid GitHub PR URL: contains whitespace or control characters"
            )

        try:
            parsed = urlparse(url)
        except Exception as exc:
            raise ValidationError(f"Invalid GitHub PR URL: {exc}") from exc

        if parsed.scheme != "https" or parsed.netloc != "github.com":
            raise ValidationError(f"Invalid GitHub PR URL: {url!r}")

        # Path must be exactly: /<owner>/<repo>/pull/<number>[/(files|commits)]
        segments = [s for s in parsed.path.split("/") if s]
        if len(segments) < 4 or len(segments) > 5:
            raise ValidationError(f"Invalid GitHub PR URL: {url!r}")

        owner, repo, pull_kw, pr_num_str = segments[:4]
        trailing = segments[4] if len(segments) == 5 else None

        if not owner or not repo or pull_kw != "pull" or not pr_num_str.isdigit():
            raise ValidationError(f"Invalid GitHub PR URL: {url!r}")

        if trailing is not None and trailing not in _ALLOWED_PR_SUFFIXES:
            raise ValidationError(f"Invalid GitHub PR URL: {url!r}")

        return f"{owner}/{repo}", int(pr_num_str)

    @staticmethod
    def scrub_diff(diff: str) -> str:
        """Strip prompt injection patterns and truncate diff to 100 KB."""
        cleaned = diff
        for pattern in _INJECTION_PATTERNS:
            cleaned = re.sub(pattern, "[REDACTED]", cleaned, flags=re.IGNORECASE)
        diff_bytes = cleaned.encode()
        if len(diff_bytes) > MAX_DIFF_BYTES:
            keep = MAX_DIFF_BYTES - len(_TRUNCATION_MARKER.encode("utf-8"))
            cleaned = diff_bytes[:keep].decode("utf-8", errors="ignore") + _TRUNCATION_MARKER
        return cleaned


class OutputValidator:
    """Validate and sanitize LLM output before it passes to the next pipeline stage."""

    @staticmethod
    def extract_json(text: str) -> str:
        """Extract the outermost JSON object from LLM output, handling markdown fences."""
        text = re.sub(r"^```(?:json)?\s*\n(.*)\n```\s*$", r"\1", text.strip(), flags=re.DOTALL)
        text = text.strip()
        start = text.find("{")
        if start == -1:
            raise ValidationError(f"No JSON object found in LLM output: {text[:200]!r}")
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError as e:
            raise ValidationError(
                f"Failed to parse JSON from LLM output: {e}. "
                f"Text prefix: {text[start:start + 200]!r}"
            ) from e
        return json.dumps(obj)

    @staticmethod
    def clamp_confidence(result: dict[str, Any]) -> dict[str, Any]:
        """Clamp the confidence field to [0.0, 1.0]."""
        score = result.get("confidence", 0.0)
        if not isinstance(score, int | float):
            score = 0.0
        result["confidence"] = max(0.0, min(1.0, float(score)))
        return result
