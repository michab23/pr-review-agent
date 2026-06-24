# Testing Standards

## Framework
- Use `pytest` as the test framework — no `unittest.TestCase` classes unless integrating with legacy code
- Test files must be named `test_<module>.py`
- Test functions must be named `test_<function_name>_<scenario>` (e.g., `test_validate_diff_strips_injection`)
- Use `pytest.fixture` for shared setup — no `setUp` / `tearDown` methods

## Coverage
- Minimum 80% line coverage on business logic modules (`src/agents/`, `src/tools/`, `src/models.py`)
- Coverage gates enforced in CI via `pytest --cov=src --cov-fail-under=80`
- Coverage is a floor, not a goal — do not write trivial tests to inflate the number

## Test Isolation
- External API calls (GitHub, LangFuse, Anthropic) must be mocked in unit tests
- Use `pytest-mock` or `unittest.mock.patch` for mocking — never make real network calls in unit tests
- Integration tests (real API calls) must be marked `@pytest.mark.integration` and skipped in default CI
- Each test must be independent — no shared mutable state between tests

## Assertions
- Each test should have one logical assertion (or a minimal, tightly related set)
- Prefer specific assertions: `assert result.risk_level == RiskLevel.HIGH` over `assert result is not None`
- For complex object equality, use Pydantic's `.model_dump()` for readable diffs on failure

## Parametrize
- Use `@pytest.mark.parametrize` for testing multiple input/output pairs
- Parametrized tests must have descriptive IDs: `@pytest.mark.parametrize("url,expected", [...], ids=["valid_pr", "invalid_url"])`

## Eval Tests (LLM Evaluation)
- Evaluation tests that call real LLMs are in `evals/` (not `tests/`)
- Run with: `uv run pytest evals/ -v -m "not integration"` for cost-free structural checks
- Run with: `uv run pytest evals/ -v` for full LLM evaluation (costs money — run before demo only)
- Eval tests must log cost and latency alongside pass/fail

## What to Test
- Test happy paths AND error paths (invalid URL, oversized diff, missing env var)
- Test boundary conditions (diff exactly at 100KB limit, empty findings list, confidence=0.0)
- Do NOT test internal implementation details — test observable behavior (inputs → outputs)
- Pydantic model validation rules must have explicit tests
