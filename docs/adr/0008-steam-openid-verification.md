# ADR-0008: Steam OpenID 2.0 verification without a third-party library

- Status: Accepted, implemented in Stage 2 (`app/integrations/steam/openid.py`, `app/services/auth.py`) · Date: 2026-11-14

## Context
Spec §27 asks for "an established, maintained OpenID library". No maintained Python OpenID 2.0 relying-party library exists (`python3-openid` is effectively abandoned, and Authlib does not support OpenID 2.0). Steam uses only a narrow slice of the protocol.

## Decision
Implement a small, heavily tested verifier in `app/integrations/steam/`:
1. Redirect to `https://steamcommunity.com/openid/login` with `openid.mode=checkid_setup`, identifier_select, and a `return_to` that carries a signed, single-use, short-lived state token. The state is also bound to an `HttpOnly` cookie (CSRF protection; OpenID 2.0 has no `state` parameter).
2. On return, validate `return_to` and `openid.op_endpoint` exactly, then validate `claimed_id` against `^https://steamcommunity\.com/openid/id/(\d{17})$`.
3. POST the signed fields back to Steam with `openid.mode=check_authentication` server-side and require `is_valid:true`.
4. Reject reused `openid.response_nonce` values (stored in Redis until they expire) and reused state tokens.
5. Extract SteamID64 only after all checks pass.

## Consequences
- This deviates from the spec's library requirement because no suitable library exists. It was approved by the product owner on 2026-11-14.
- The code is security-critical and needs its own test suite, including replayed, forged and tampered `claimed_id` and `return_to` cases.
