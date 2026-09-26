# LifeThread Security & Privacy Architecture

## 1. Overview

LifeThread implements defense-in-depth across every layer of the system. Operating as a persistent autonomous agent requires stringent security controls: safeguarding long-term user memories, preventing tenant cross-talk, protecting API keys, and sanitizing LLM reasoning tokens from user interfaces.

---

## 2. Authentication & Authorization

### 2.1 JWT Access & Refresh Tokens
- **Access Tokens:** Signed with HMAC-SHA256 (`HS256`) using `SECRET_KEY`. Access tokens carry a short TTL (default 30 minutes) and encode the user's UUID in the `sub` claim and a unique token identifier in `jti`.
- **Refresh Tokens:** Long-lived tokens (default 7 days) stored securely to permit token rotation without re-prompting for credentials.
- **Password Storage:** Uses bcrypt hashing with salted work factor to ensure passwords are never stored in plaintext.

### 2.2 Redis Token Denylist (`TokenDenylist`)
- Upon user logout or permission revocation, the token's `jti` is written to Redis with a TTL equal to the remaining lifespan of the token.
- `get_current_user` checks Redis on every authenticated request. Revoked tokens are immediately rejected with `401 Unauthorized`.

---

## 3. Strict Multi-Tenant Isolation

1. **Database Queries:**
   - Every read, write, update, and delete query in the application explicitly filters on `user_id`.
   - Goals, milestones, tasks, dependencies, plans, and memories are strictly segregated.
2. **Vector Similarity Isolation:**
   - `SemanticMemoryRetriever` filters memory candidates by `Memory.user_id == current_user.id` before computing vector distance metrics. Cross-tenant retrieval is architecturally prevented.
3. **Demo Data Segregation:**
   - Development and demonstration datasets are isolated under dedicated user `demo@lifethread.ai` with metadata tag `is_demo: True`.
   - Production systems disable all demo loading endpoints via `ALLOW_DEMO_DATA=False` and `ENVIRONMENT="production"`.

---

## 4. Chain-of-Thought (CoT) Defense (`CoTSanitizer`)

To prevent sensitive information leaks and mitigate prompt injection attacks:
- **Reasoning Token Stripping:** Private model reasoning tags (e.g. `<scratchpad>`, `<thought>`, `<hidden>`) are removed prior to logging, database storage, or frontend SSE transmission.
- **Secret Redaction:** High-entropy tokens, AWS access keys (`AKIA...`), JWT strings, and environment variables matching secret patterns are masked with `[REDACTED_SECRET]`.
- **Injection Sanitization:** Inbound user inputs are sanitized to prevent escape sequences in downstream prompt templates.

---

## 5. Security Audit Logging (`SecurityAuditService`)

All security-sensitive operations generate structured audit events recorded to `audit.log` and the database:
- `AUTHENTICATE_TOKEN` (success, expired, malformed, revoked)
- `USER_LOGIN` / `USER_REGISTER`
- `UNAUTHORIZED_ACCESS_ATTEMPT`
- `PERMISSION_DENIED`
- `MEMORY_STORED` / `MEMORY_DELETED`
- `DEMO_DATA_OPERATION`

Audit logs include timestamps, client IP addresses (or forwarded IPs), user IDs, requested resource URIs, and severity levels (`INFO`, `WARNING`, `CRITICAL`).

---

## 6. Network & Infrastructure Hardening

- **Security Headers Middleware:** Enforces `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy`.
- **CORS Policies:** Configured with an explicit whitelist of allowed origins; wildcard origins (`*`) are disallowed in production.
- **Rate Limiting:** Managed via `SlowAPI` to prevent brute-force login attempts and denial-of-service on computationally expensive LLM endpoints.
- **Container Isolation:** Production Dockerfiles run under an unprivileged `appuser` (UID 10001) with read-only root filesystems and minimal base images (`python:3.12-slim`).
