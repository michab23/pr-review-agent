# Security Standards

## Password Handling
- Never use MD5, SHA1, or SHA256 for password hashing — these are cryptographically broken for this purpose
- Use `bcrypt` or `argon2` with a work factor ≥ 12 for bcrypt, or default parameters for argon2
- Example: `bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))`
- Never store plaintext passwords or reversible encodings (base64, hex) in any database or log

## Secret Management
- Never hardcode secrets, API keys, tokens, or passwords in source code
- Load all credentials from environment variables via `python-dotenv` (`os.environ["KEY"]`, not `os.getenv("KEY")` with a fallback value that exposes the secret)
- Secrets must never appear in log output, LLM prompts, error messages, or trace payloads
- `.env` files must be in `.gitignore`; never commit `.env` to version control

## SQL and Query Safety
- Never concatenate user input into SQL strings: `f"SELECT * FROM users WHERE id = {user_id}"` is forbidden
- Use parameterized queries or an ORM for all database interactions
- Example (psycopg2): `cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))`
- Validate and type-check all query parameters before use

## JWT and Session Tokens
- Access tokens must have an expiry (`exp` claim) of ≤ 24 hours
- Refresh tokens must have an expiry of ≤ 30 days
- Never store JWTs in localStorage (use httpOnly cookies for web clients)
- Verify the `alg` header explicitly — reject tokens with `alg: none`

## Network and Transport
- Enforce HTTPS for all external API calls — reject plaintext HTTP
- Use `httpx` with default TLS verification; never pass `verify=False`
- Validate SSL certificates; do not suppress `InsecureRequestWarning`

## Input Validation
- Treat all external input (HTTP request bodies, PR diffs, file uploads, CLI args) as untrusted
- Validate and sanitize at the system boundary before any processing or LLM context injection
- Apply maximum size limits on all external inputs (e.g., diff ≤ 100KB, request body ≤ 10MB)
- Strip or escape prompt injection patterns before passing any external text to an LLM

## GitHub Token Scoping
- GitHub personal access tokens must use the minimum required scope
- For posting PR comments only: `pull_requests: write` is sufficient — do not use `repo` full scope
- Document required token scopes in the README
