"use client";

import { Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { GameCover } from "@/components/games/game-cover";
import { GameStateEditor, type GameState } from "@/components/library/game-state-editor";
import type { SearchResult } from "@/lib/api/types";

const DEBOUNCE_MS = 350;

/** Search Steam's store and add or rate games straight from the results. */
export function GameSearch({ onChange }: { onChange?: (next: GameState, prev: GameState) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "empty">("idle");
  const latest = useRef(0);

  const term = query.trim();
  const tooShort = term.length < 2;

  useEffect(() => {
    if (tooShort) {
      latest.current++; // drop any in-flight search for an old term
      return;
    }
    const ticket = ++latest.current;
    const timer = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const res = await fetch(`/api/me/library/search?q=${encodeURIComponent(term)}`);
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as { results: SearchResult[] };
        if (ticket !== latest.current) return; // a newer search superseded this one
        setResults(body.results);
        setStatus(body.results.length ? "idle" : "empty");
      } catch {
        if (ticket === latest.current) setStatus("error");
      }
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [term, tooShort]);

  const shown = tooShort ? [] : results;
  const shownStatus = tooShort ? "idle" : status;

  return (
    <div className="space-y-4">
      <label className="relative block">
        <span className="sr-only">Search Steam games</span>
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Steam games, e.g. Factorio"
          maxLength={100}
          autoComplete="off"
          className="h-11 w-full rounded-xl border border-line bg-surface-raised pr-10 pl-10 text-sm text-fg placeholder:text-fg-subtle focus:border-brand-500 focus:outline-none"
        />
        {shownStatus === "loading" ? (
          <Loader2 className="absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin text-fg-subtle" aria-hidden="true" />
        ) : null}
      </label>

      <div aria-live="polite">
        {shownStatus === "error" ? (
          <p className="text-sm text-negative">Steam&apos;s store didn&apos;t respond. Try again in a moment.</p>
        ) : null}
        {shownStatus === "empty" ? <p className="text-sm text-fg-muted">No games found.</p> : null}
      </div>

      <ul className="divide-y divide-line">
        {shown.map((r) => (
          <li key={r.steam_appid} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start">
            <GameCover
              title={r.name}
              artworkUrl={r.capsule_image_url}
              className="h-14 w-32 shrink-0 rounded-md [&_span]:text-base"
            />
            <div className="min-w-0 flex-1 space-y-2">
              <p className="font-medium text-fg">
                {r.name}
                {r.release_year ? <span className="ml-2 text-xs text-fg-subtle">{r.release_year}</span> : null}
              </p>
              <GameStateEditor
                appid={r.steam_appid}
                name={r.name}
                initial={{ owned: r.owned, rating: r.rating }}
                onSaved={onChange}
              />
            </div>
          </li>
        ))}
      </ul>
      {shown.length ? <p className="text-xs text-fg-subtle">Search results provided by Steam.</p> : null}
    </div>
  );
}
