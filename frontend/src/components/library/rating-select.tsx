"use client";

import { useState } from "react";

import { RATINGS, type Rating } from "@/lib/api/types";

/** Compact rating control for library rows. */
export function RatingSelect({
  appid,
  name,
  owned,
  initial,
}: {
  appid: number;
  name: string;
  owned: boolean;
  initial: Rating | null;
}) {
  const [value, setValue] = useState<Rating | null>(initial);
  const [error, setError] = useState(false);
  return (
    <span className="inline-flex items-center gap-2">
      <select
        aria-label={`Your rating for ${name}`}
        value={value === null ? "" : String(value)}
        onChange={async (e) => {
          const previous = value;
          const next = e.target.value === "" ? null : (Number(e.target.value) as Rating);
          setValue(next);
          setError(false);
          const res = await fetch(`/api/me/library/games/${appid}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ owned, rating: next }),
          });
          if (!res.ok) {
            setValue(previous);
            setError(true);
          }
        }}
        className="rounded-lg border border-line bg-surface-raised px-2 py-1 text-xs text-fg focus:border-brand-500 focus:outline-none"
      >
        <option value="">Not rated</option>
        {RATINGS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>
      {error ? <span className="text-xs text-negative">Not saved</span> : null}
    </span>
  );
}
