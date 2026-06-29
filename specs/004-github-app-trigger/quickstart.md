# Quickstart: GitHub App Integration

**Feature**: `010-github-app-trigger`  
**Date**: 2026-06-27

---

## Prerequisites

- Python 3.11+, `uv` installed
- An existing GitHub account with permission to create GitHub Apps
- `ngrok` (or equivalent) for local webhook testing
- `.env` file with existing variables (ANTHROPIC_API_KEY, GITHUB_TOKEN, LANGFUSE_*)

---

## Step 1: Create the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set:
   - **App name**: `pr-review-agent` (or any name)
   - **Homepage URL**: your repo URL
   - **Webhook URL**: `https://<your-ngrok-url>/webhook` (fill in Step 3)
   - **Webhook secret**: generate a random string (save as `GITHUB_WEBHOOK_SECRET`)
3. Set **Permissions**:
   - Repository permissions → **Pull requests**: Read & write
   - Repository permissions → **Metadata**: Read-only
4. Subscribe to events: ✓ **Pull request**
5. Set **Where can this GitHub App be installed?**: `Only on this account` (for dev)
6. Click **Create GitHub App**
7. Note the **App ID** (save as `GITHUB_APP_ID`)
8. Generate a **Private key** → download the `.pem` file
9. Save the PEM contents as `GITHUB_APP_PRIVATE_KEY` in `.env` (or load from file)

---

## Step 2: Install the App on a Repository

1. In the GitHub App settings → **Install App** → choose your repository
2. After installation, note the **Installation ID** from the URL:
   `https://github.com/settings/installations/<INSTALLATION_ID>`
   (Only needed for verification; the webhook payload includes `installation.id` automatically)

---

## Step 3: Start ngrok (local development)

```bash
ngrok http 8080
```

Copy the `https://xxxx.ngrok-free.dev` URL from the **Forwarding** line and update your GitHub App's **Webhook URL** to:
`https://xxxx.ngrok-free.dev/webhook`

> Note: the free ngrok URL changes every time you restart ngrok — remember to update the GitHub App webhook URL each session.

---

## Step 4: Add environment variables

Add to your `.env`:

```bash
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
...your key contents...
-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=your-random-secret-here
```

---

## Step 5: Install new dependencies

```bash
uv add fastapi uvicorn
```

---

## Step 6: Start the webhook server

```bash
uv run python -m src.webhook
```

The server starts on port 8080 by default. You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

Override the port with the `PORT` env var if needed:
```bash
PORT=9000 uv run python -m src.webhook
```

> The MCP Team Brain server runs on port 8000 — the webhook server defaults to 8080 to avoid the conflict.

---

## Step 7: Open a Pull Request

Create a non-draft PR on the configured repository. Within seconds you should see:
1. A "🤖 AI review in progress…" comment on the PR
2. Terminal output showing the 3-agent pipeline running
3. The final review comment posted to the PR (HITL gate is skipped in this path)

---

## Verifying webhook delivery

Check GitHub App settings → **Advanced** → **Recent Deliveries** to see webhook delivery status and response bodies.

---

## Running the CLI pipeline (unchanged)

The existing CLI path is unaffected:

```bash
uv run python -m src.pipeline https://github.com/owner/repo/pull/42
```

This still shows the HITL approval gate.

---

## Production deployment

The webhook server is a standard ASGI app; deploy with any Python hosting:

- **Fly.io**: `fly launch` with a `Dockerfile`
- **Railway / Render**: point to `src.webhook.server:app`
- **Cloud Run / Lambda**: containerize the FastAPI app

Set the same env vars in your hosting environment's secret manager. Update the GitHub App **Webhook URL** to the production URL.
