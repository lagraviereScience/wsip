/**
 * Server-side session access (Data Access Layer). Reads the HttpOnly session
 * cookie and asks the backend who the user is. Request-time only: callers must
 * render behind a <Suspense> boundary (Cache Components).
 *
 * `cookies()` is deliberately awaited OUTSIDE any try/catch: during prerendering
 * Next.js interrupts it on purpose, and swallowing that would bake signed-out
 * content into the static shell.
 */
import "server-only";

import { cookies } from "next/headers";
import { unstable_rethrow } from "next/navigation";
import { cache } from "react";

import type { Me } from "@/lib/api/types";

const BACKEND = process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000";
const COOKIE = process.env.SESSION_COOKIE_NAME ?? "wdywtp_session";

async function sessionToken(): Promise<string | undefined> {
  return (await cookies()).get(COOKIE)?.value;
}

export async function backendFetch(path: string): Promise<Response | null> {
  const token = await sessionToken();
  if (!token) return null;
  return fetch(`${BACKEND}${path}`, {
    headers: { Cookie: `${COOKIE}=${token}`, Accept: "application/json" },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
}

/** Public (no session) backend request, e.g. the taxonomy. */
export async function publicBackendFetch(path: string): Promise<Response> {
  return fetch(`${BACKEND}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
}

/**
 * The signed-in user, or null when signed out (or the session expired).
 *
 * Memoised per request with React's `cache`: a page's components all ask for the
 * user, and without it each asked the backend again (3–4 `/api/me` calls per page,
 * found in the Stage 6 load test).
 */
export const getCurrentUser = cache(fetchCurrentUser);

async function fetchCurrentUser(): Promise<Me | null> {
  const token = await sessionToken();
  if (!token) return null;
  let res: Response;
  try {
    res = await fetch(`${BACKEND}/api/me`, {
      headers: { Cookie: `${COOKIE}=${token}`, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
  } catch (err) {
    // Next aborts in-flight fetches when a prerender or partial prefetch ends;
    // that is not an outage and must not be read as "signed out".
    unstable_rethrow(err);
    // Backend unreachable: degrade to the signed-out preview rather than crash the page.
    console.error("session lookup failed", err);
    return null;
  }
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`/api/me returned ${res.status}`);
  return (await res.json()) as Me;
}
