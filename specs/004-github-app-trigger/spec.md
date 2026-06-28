# Feature Specification: GitHub Integration for Auto-Triggered PR Review

**Feature Branch**: `010-github-app-trigger`

**Created**: 2026-06-27

**Status**: Draft

**Input**: User description: "I'm checking the option to create github app (or any other solution giving me the functionality below) based on this pr-review-agent project, so the pipeline can be triggered automatically once pr created"

## Goal

Enable the PR review pipeline to start automatically whenever a pull request is created on a configured GitHub repository, eliminating the need for a developer to manually run the pipeline from the command line. Review results should be delivered back to the PR without requiring local environment setup.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Auto-Trigger Pipeline on PR Creation (Priority: P1)

A developer opens a new pull request on GitHub. Without any manual action, the PR review pipeline starts within seconds and processes the PR. The developer can see that a review is underway (e.g., a pending status check or a "Review in progress" comment) and eventually receives the structured review comment on their PR.

**Why this priority**: This is the entire value proposition of the feature — removing the manual invocation step. Nothing else matters if this core flow doesn't work.

**Independent Test**: Create a new PR in a configured repository and verify the pipeline starts automatically and produces a review comment, without any developer manually running a command.

**Acceptance Scenarios**:

1. **Given** the integration is installed on a repository, **When** a new pull request is created, **Then** the review pipeline starts within 60 seconds and a "review in progress" indicator appears on the PR
2. **Given** the pipeline has completed, **When** the review output is ready, **Then** a structured review comment is posted to the PR by an automated account
3. **Given** the pipeline fails or times out, **When** the error occurs, **Then** the PR receives a failure status or comment explaining what went wrong, rather than silently hanging

---

### User Story 2 - GitHub App Installation (Priority: P2)

A repository owner or organization admin installs the GitHub App on their repository (or across an organization). After installation, the app automatically registers the webhook needed to trigger reviews. The owner can uninstall the app at any time to stop automated reviews, with no residual configuration left behind.

**Why this priority**: The GitHub App installation is the gate that enables the entire automated flow. Without it, no webhooks fire. However, the core pipeline trigger (US1) can be validated with a hard-coded single-repo configuration first.

**Independent Test**: Install the GitHub App on a test repository, open a PR, and confirm the review fires. Then uninstall the app and confirm subsequent PRs on that repository no longer trigger reviews.

**Acceptance Scenarios**:

1. **Given** a repository owner installs the GitHub App, **When** the installation completes, **Then** subsequent pull requests on that repository trigger the review pipeline automatically
2. **Given** a repository owner uninstalls the GitHub App, **When** a new PR is created, **Then** no review pipeline is triggered and no comment is posted
3. **Given** the GitHub App is installed at the organization level, **When** a PR is opened in any repository in that org, **Then** the review pipeline is triggered for that repository

---

### User Story 3 - Repository Configuration Management (Priority: P3)

A repository owner or org admin configures which repositories participate in the automated review. They can add or remove repositories, and optionally set per-repository settings (e.g., which branches trigger a review).

**Why this priority**: Necessary for adoption and control, but the core trigger mechanism can be validated with a single hard-coded repository first.

**Independent Test**: Install the integration on one repository, confirm the pipeline runs there, then disable it on that repository and confirm the pipeline does not run on subsequent PRs.

**Acceptance Scenarios**:

1. **Given** the integration is installed on a repository, **When** the repo owner removes the installation, **Then** subsequent PRs on that repository no longer trigger the review pipeline
2. **Given** a multi-repo installation, **When** a PR is opened on one of the repositories, **Then** only the review for that specific repository runs

---

### Edge Cases

- What happens when the repository has no `ANTHROPIC_API_KEY` or other required credentials configured for the automated runner?
- How does the system handle a PR that is converted to draft after triggering the pipeline (i.e., the pipeline is already running when the PR is re-drafted)?
- What happens when the pipeline takes longer than GitHub's webhook delivery timeout (30 seconds)?
- Rapid successive pushes: when a new `synchronize` event arrives, the in-flight run for that PR is cancelled and a new run starts against the latest commit (FR-010).
- How does the system handle duplicate webhook deliveries (GitHub retries on failure)?
- What happens when the Team Brain MCP server is unavailable at trigger time?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST start the PR review pipeline automatically when a non-draft pull request is opened on a configured repository, without requiring any developer to manually invoke a command. The system MUST also trigger when a draft PR is converted to "ready for review," and when new commits are pushed to an already-open PR. Draft PRs opened as drafts MUST be skipped until that conversion occurs.
- **FR-002**: The system MUST authenticate GitHub webhook payloads to confirm they originate from GitHub (e.g., via webhook secret signature verification)
- **FR-003**: The system MUST post the structured review comment to the triggering PR immediately once the pipeline completes, with no approval step required
- **FR-004**: The system MUST post an interim PR comment ("🤖 AI review in progress…") immediately after the webhook is received and before the pipeline begins, to signal that a review is underway. The comment is posted using the GitHub App installation token. When the review completes, the interim comment is deleted and the full review comment is posted in its place.
- **FR-005**: The system MUST handle pipeline failures gracefully — the PR must receive a failure status or error comment rather than hanging indefinitely
- **FR-006**: The system MUST support configuration of which repositories trigger the pipeline, with at least single-repository granularity
- **FR-007**: The system MUST store required credentials (API keys, webhook secrets) outside the repository in a secrets management mechanism
- **FR-008**: The HITL approval gate MUST be bypassed for automated triggers — the pipeline posts the review comment directly to the PR without waiting for human input. The HITL gate is retained in the CLI invocation path (`src.pipeline` run manually) and is not removed from that code path.
- **FR-009**: The system MUST deduplicate webhook events so that retried deliveries do not trigger duplicate pipeline runs for the same PR
- **FR-010**: When a new `synchronize` event arrives for a PR that already has a pipeline run in progress, the system MUST cancel the in-flight run and start a new run against the latest commit. At most one pipeline run per PR is active at any time.

### Key Entities

- **Webhook Event**: A GitHub-delivered payload describing a PR lifecycle event (opened, reopened, synchronized); contains PR URL, repository, author, and metadata
- **Pipeline Run**: A single execution of the 3-agent review pipeline, associated with one PR and one webhook event
- **App Installation**: A GitHub App installation record scoping the automated review to a specific repository or organization; created when the owner installs the app, removed on uninstall

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A pull request created on a configured repository receives a review comment within 5 minutes of opening, with no manual action required from any developer
- **SC-002**: 100% of webhook payloads from GitHub are authenticated before the pipeline is invoked — unauthenticated requests are rejected
- **SC-003**: Pipeline failures surface on the PR within 2 minutes of the failure occurring, via a GitHub status check or comment
- **SC-004**: Duplicate webhook deliveries for the same PR event result in at most one pipeline run (idempotent processing)
- **SC-005**: Configuration changes (enabling/disabling a repository) take effect within 5 minutes without requiring a restart of the integration service

## Clarifications

### Session 2026-06-27

- Q: Which GitHub integration mechanism should the automated trigger use? → A: GitHub App (per-repo/org installation, JWT auth, status check support)
- Q: Should the pipeline run on GitHub pull requests opened as Draft? → A: Skip draft PRs; trigger only on non-draft `opened` events and on `ready_for_review` conversion
- Q: Should the pipeline re-run when new commits are pushed to an already-open PR? → A: Yes — trigger on `synchronize` events; each push produces a fresh review
- Q: When multiple commits are pushed rapidly, should the system cancel the in-flight review or let all runs complete? → A: Cancel in-flight run and restart with latest commit; at most one active run per PR at any time

## Assumptions

- The integration is implemented as a **GitHub App** (not a webhook+PAT or GitHub Actions workflow), supporting per-repository and organization-level installation with JWT-based authentication
- The existing `src.pipeline` module is the integration point — the automated trigger invokes the same pipeline code currently run manually, passing the PR URL as input
- The HITL approval gate is bypassed for all automated triggers; the pipeline posts the review comment directly without waiting for human confirmation (HITL remains in the CLI path only)
- The Team Brain MCP server will be running as a persistent service accessible to the automated runner, or the pipeline will fall back to the existing file-based standards as it already does
- Secrets (ANTHROPIC_API_KEY, GitHub App private key, webhook secrets) will be managed via environment variables in the hosting environment — no secrets in source code or repository
- Triggering events: `pull_request` with actions `opened` (non-draft only), `ready_for_review`, and `synchronize` (new commits pushed to an open PR); `reopened` is in scope but can be deferred
- "Configured repository" means a repository where the GitHub App is installed — the app does not apply globally to all repos by default
- The integration will run as a hosted service (not a GitHub Action that runs in the PR's own repository), to keep the pipeline environment separate from the repository under review
