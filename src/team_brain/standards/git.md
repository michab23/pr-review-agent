# Git and PR Standards

## PR Size
- PRs must change ≤ 400 lines (additions + deletions) — split larger changes into sequential PRs
- Exception: auto-generated files (migrations, lock files) may exceed this limit but must be in a dedicated PR
- A PR that changes both business logic and test files is fine; a PR that changes three unrelated features is not

## Commit Messages
- Use imperative mood for the subject line: "Add login endpoint" not "Added login endpoint"
- Subject line must be ≤ 72 characters
- Leave a blank line between subject and body
- Body explains the *why*, not the *what* — the diff shows what changed
- Reference issue/ticket numbers in the body if applicable: "Closes #42"

## Branch Naming
- Feature branches: `feature/TICKET-short-description` (e.g., `feature/PROJ-42-add-auth`)
- Bug fix branches: `fix/TICKET-short-description` (e.g., `fix/PROJ-88-null-pointer-login`)
- Chore/infra branches: `chore/short-description` (e.g., `chore/upgrade-pydantic-v2`)
- No spaces or special characters in branch names

## Merge Strategy
- Rebase onto `main` before merging — no merge commits in the main branch history
- Squash trivial fix-up commits before requesting review
- Force-push to feature branches is allowed; never force-push to `main`

## PR Description
- Every PR must include: (1) what changed, (2) why it changed, (3) how to test it
- Link to any design doc, spec, or ticket that motivated the change
- Tag reviewers explicitly — do not leave PRs in limbo

## What Not to Commit
- Never commit `.env` files, secrets, or credentials — these must be in `.gitignore`
- Never commit generated files that can be reproduced (e.g., compiled binaries, `__pycache__/`)
- Never commit commented-out code — delete it (version control preserves history)
- Never commit `TODO` comments unless they reference a tracked ticket

## CI Gates
- PRs require at least one passing CI check before merge
- CI must run: linting (ruff), type checking (mypy or pyright), and unit tests
- Failing CI must be fixed before requesting review — do not merge with red CI
