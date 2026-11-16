# ADR-0010: Server-side sessions with opaque cookies

- Status: Accepted · Date: 2026-11-14

## Context
After Steam OpenID verification we need a session (spec §27: secure session management, HttpOnly, Secure over HTTPS, SameSite, expiration). The options were a signed or encrypted stateless cookie (JWT, iron-session) or a server-side session.

## Decision
- A random 256-bit token goes in the `wdywtp_session` cookie (`HttpOnly`, `SameSite=Lax`, `Secure` whenever `PUBLIC_BASE_URL` is https, 30-day `Max-Age`).
- Only `sha256(token)` is stored, in `user_sessions` together with `expires_at`, `revoked_at` and `last_seen_at` (`last_seen_at` is updated at most every 5 minutes).
- Logout revokes the row. A daily task deletes expired and revoked sessions.
- Each login issues a fresh token, so session fixation is not possible.
- Unsafe API methods additionally require an `Origin` or `Referer` header from `PUBLIC_BASE_URL` (OriginCheckMiddleware) on top of `SameSite=Lax`.

## Consequences
- Sessions can be revoked immediately, and account deletion removes them all. A leaked database does not leak usable tokens.
- Each authenticated request costs one indexed lookup. That is fine at the target scale and could be cached in Redis later.
- `SameSite=Lax` is required, not `Strict`, because Steam returns the user with a top-level GET that must carry the OpenID state cookie.
