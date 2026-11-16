"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { ApiSession } from "@/lib/api/types";

function when(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

/** The signed-in user's sessions, with "Sign out other devices". */
export function SessionsControl() {
  const [sessions, setSessions] = useState<ApiSession[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/sessions")
      .then((res) => (res.ok ? (res.json() as Promise<ApiSession[]>) : Promise.reject(res.status)))
      .then((data) => {
        if (!cancelled) setSessions(data);
      })
      .catch(() => {
        if (!cancelled) setMessage("Couldn't load your sessions.");
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  async function signOutOthers() {
    setMessage(null);
    try {
      const res = await fetch("/api/auth/logout-others", { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      const { revoked } = (await res.json()) as { revoked: number };
      setMessage(revoked ? `Signed out ${revoked} other session${revoked > 1 ? "s" : ""}.` : "No other sessions.");
      setVersion((v) => v + 1);
    } catch {
      setMessage("Couldn't sign out other sessions. Please try again.");
    }
  }

  const others = (sessions ?? []).filter((s) => !s.current).length;
  return (
    <div className="space-y-3 text-sm">
      {sessions ? (
        <ul className="space-y-1 text-fg-muted">
          {sessions.map((s) => (
            <li key={s.created_at}>
              Signed in {when(s.created_at)} · last used {when(s.last_seen_at)}
              {s.current ? <span className="ml-1 text-positive">(this device)</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <Button variant="secondary" size="sm" onClick={signOutOthers} disabled={sessions !== null && others === 0}>
        Sign out other devices
      </Button>
      <p className="text-xs text-fg-subtle" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
