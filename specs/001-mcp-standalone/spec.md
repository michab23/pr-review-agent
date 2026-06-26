# Feature Specification: MCP Server Standalone Mode

**Feature Branch**: `001-mcp-standalone`

**Created**: 2026-06-25

**Status**: Draft

**Input**: User description: "I'd like to separate mcp to be run in standalone terminal with separate command from running the pipeline, so the mcp is always up and running"

## Goal

Separate the Team Brain MCP server into a standalone, long-lived process with its own dedicated startup command. The pipeline connects to the already-running server rather than spawning a new subprocess for each review run.

## Success Criteria

- A developer can start the MCP server with a single dedicated command, independently of the pipeline
- The pipeline connects to an already-running server without spawning a subprocess per run
- The MCP server stays available across multiple consecutive pipeline runs without restart
- A developer unfamiliar with the project can be up and running (server + pipeline) in under 2 minutes following the documented steps

## Constraints

- Must use the existing FastMCP library already in the codebase
- Python 3.11+ / uv environment maintained
- The existing fallback path (direct file read) must remain active when the server is unreachable

---

## User Scenarios & Testing

### User Story 1 - Start Server Once, Review Many PRs (Priority: P1)

A developer opens a terminal, starts the MCP server with a single command, and leaves it running. They then run the pipeline against several different PRs in another terminal — each review run connects to the persistent server without delay or setup.

**Why this priority**: This is the core ask — removing the per-run subprocess overhead and enabling the server to be always available.

**Independent Test**: Run the server start command once. In a second terminal, invoke the pipeline twice against different PRs. Both runs complete successfully and both used the running server (not the fallback).

**Acceptance Scenarios**:

1. **Given** the server is not running, **When** a developer runs the dedicated server start command, **Then** the server starts and indicates it is ready to accept connections
2. **Given** the server is running, **When** the pipeline is invoked, **Then** the pipeline completes the review using the running server without spawning a new subprocess
3. **Given** the server is running, **When** the pipeline is invoked a second time, **Then** it connects to the same already-running server instance successfully

---

### User Story 2 - Graceful Fallback When Server Is Down (Priority: P2)

A developer runs the pipeline without first starting the server. The pipeline falls back to reading standards files directly and completes the review — with a visible warning that the server was not reachable.

**Why this priority**: Prevents hard failures during development or CI runs where the server is not pre-started. Fallback already exists; it must remain functional.

**Independent Test**: With the server stopped, run the pipeline. Verify the review completes (using the fallback), and a warning about the unreachable server is printed.

**Acceptance Scenarios**:

1. **Given** the server is not running, **When** the pipeline is invoked, **Then** the pipeline falls back to direct file reads and prints a warning
2. **Given** the server was running and then stopped mid-session, **When** the pipeline is invoked, **Then** the pipeline falls back gracefully without an unhandled exception

---

### User Story 3 - Clear Developer Onboarding (Priority: P3)

A developer reading the README can understand, in under 2 minutes, how to start the MCP server and then run the pipeline against it — with each in its own terminal.

**Why this priority**: Reduces friction for new contributors and for demo presenters.

**Independent Test**: Follow only the README instructions, with no prior knowledge of the project. Verify the server starts and the pipeline produces a review.

**Acceptance Scenarios**:

1. **Given** a fresh checkout, **When** a developer follows the documented server start command, **Then** the server starts without additional configuration
2. **Given** the server is running, **When** a developer follows the documented pipeline command, **Then** the pipeline connects to the server and completes a review

---

### Edge Cases

- What happens when the server port is already in use when starting?
- What happens when the pipeline cannot reach the server address (wrong host/port configured)?
- What happens when the server is restarted while the pipeline is mid-run?

---

## Requirements

### Functional Requirements

- **FR-001**: The system MUST provide a dedicated command to start the MCP server as a standalone process
- **FR-002**: The MCP server MUST accept connections from the pipeline without requiring a restart between runs
- **FR-003**: The pipeline MUST connect to the already-running server rather than spawning a new subprocess per invocation
- **FR-004**: The pipeline MUST fall back to direct file reads when the server is not reachable, and MUST display a warning to the user
- **FR-005**: The server startup command MUST be documented in the project README
- **FR-006**: The pipeline MUST be configurable to point to a non-default server address without code changes (e.g., via environment variable)

### Key Entities

- **MCP Server**: The Team Brain standards server process that exposes the `get_team_standards` tool; transitions from ephemeral (spawned per call) to persistent (long-lived, always-on)
- **Pipeline Client**: The component within the review pipeline that calls `get_team_standards`; transitions from stdio subprocess spawner to network client

---

## Assumptions

- The MCP server will run on the same machine as the pipeline during development and demo; remote hosting is out of scope for this feature
- A single server instance serving one client at a time is sufficient; concurrent multi-user scenarios are out of scope
- The existing `_fetch_direct` fallback in `src/tools/team_brain.py` is considered sufficient for the fallback path; no new fallback logic is needed
- Default server address (host and port) will be `localhost` and a standard port; developers can override via environment variable
- No authentication is required for the server connection in this initial version
