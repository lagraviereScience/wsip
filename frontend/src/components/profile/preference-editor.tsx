"use client";

import { Ban, Hand, RotateCcw, Search, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import type { ApiFeaturePreference, TaxonomyFeature } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const LEVELS: { value: number; label: string }[] = [
  { value: -1, label: "Hate" },
  { value: -0.5, label: "Dislike" },
  { value: 0, label: "Neutral" },
  { value: 0.5, label: "Like" },
  { value: 1, label: "Love" },
];

const MIN_SHOWN_CONFIDENCE = 0.2;

interface Row {
  slug: string;
  name: string;
  category: string;
  categoryName: string;
  inferred: { value: number; confidence: number } | null;
  manualValue: number | null;
  excluded: boolean;
}

type Status = { kind: "idle" } | { kind: "saving"; slug: string } | { kind: "saved" } | { kind: "error"; message: string };

function toRow(f: ApiFeaturePreference): Row {
  return {
    slug: f.slug,
    name: f.name,
    category: f.category,
    categoryName: f.category_name,
    inferred: f.inferred ? { value: f.inferred.value, confidence: f.inferred.confidence } : null,
    manualValue: f.manual?.value ?? null,
    excluded: f.excluded,
  };
}

function nearestLevel(v: number): number {
  return LEVELS.reduce((best, l) => (Math.abs(l.value - v) < Math.abs(best - v) ? l.value : best), 0);
}

/**
 * Manual preferences and exclusions. Manual values always override inferred
 * ones (spec §11); an exclusion is a hard constraint: games with that feature
 * are never recommended.
 */
export function PreferenceEditor({
  features,
  taxonomy,
  categoryNames,
}: {
  features: ApiFeaturePreference[];
  taxonomy: TaxonomyFeature[];
  categoryNames: Record<string, string>;
}) {
  const router = useRouter();
  const [rows, setRows] = useState<Record<string, Row>>(() =>
    Object.fromEntries(features.map((f) => [f.slug, toRow(f)])),
  );
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const synonyms = useMemo(
    () => Object.fromEntries(taxonomy.map((t) => [t.slug, t.synonyms.map((x) => x.toLowerCase())])),
    [taxonomy],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = (slug: string, name: string) =>
      name.toLowerCase().includes(q) || (synonyms[slug] ?? []).some((x) => x.includes(q));
    const known = Object.values(rows).filter(
      (r) =>
        r.manualValue !== null ||
        r.excluded ||
        (r.inferred !== null && r.inferred.confidence >= MIN_SHOWN_CONFIDENCE),
    );
    let list: Row[] = known;
    if (q) {
      // Searching also offers taxonomy features with no preference yet.
      const extra = taxonomy
        .filter((t) => !rows[t.slug] && matches(t.slug, t.name))
        .map<Row>((t) => ({
          slug: t.slug,
          name: t.name,
          category: t.category,
          categoryName: categoryNames[t.category] ?? t.category,
          inferred: null,
          manualValue: null,
          excluded: false,
        }));
      list = [...Object.values(rows).filter((r) => matches(r.slug, r.name)), ...extra];
    }
    if (category !== "all") list = list.filter((r) => r.category === category);
    const strength = (r: Row) =>
      r.manualValue !== null ? 2 + Math.abs(r.manualValue) : r.inferred ? Math.abs(r.inferred.value) * r.inferred.confidence : 0;
    return list.sort((a, b) => strength(b) - strength(a) || a.name.localeCompare(b.name)).slice(0, 60);
  }, [rows, query, category, taxonomy, categoryNames, synonyms]);

  async function save(row: Row, value: number | null, excluded: boolean) {
    const previous = rows[row.slug];
    setRows((r) => ({ ...r, [row.slug]: { ...row, manualValue: value, excluded } }));
    setStatus({ kind: "saving", slug: row.slug });
    try {
      const cleared = value === null && !excluded;
      const res = await fetch(`/api/me/preferences/${row.slug}`, {
        method: cleared ? "DELETE" : "PUT",
        headers: cleared ? undefined : { "Content-Type": "application/json" },
        body: cleared ? undefined : JSON.stringify({ value, excluded }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as ApiFeaturePreference;
      setRows((r) => ({ ...r, [row.slug]: toRow(updated) }));
      setStatus({ kind: "saved" });
      router.refresh();
    } catch {
      setRows((r) => (previous ? { ...r, [row.slug]: previous } : r));
      setStatus({ kind: "error", message: `Couldn't save ${row.name}. Please try again.` });
    }
  }

  const categories = Object.entries(categoryNames);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-56 flex-1">
          <span className="sr-only">Find a genre, mechanic or tag</span>
          <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-fg-subtle" aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a genre, mechanic or tag to set…"
            className="h-9 w-full rounded-lg border border-line bg-surface pr-3 pl-8 text-sm text-fg placeholder:text-fg-subtle focus:border-brand-400 focus:outline-none"
          />
        </label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Category"
          className="h-9 rounded-lg border border-line bg-surface px-2.5 text-sm text-fg"
        >
          <option value="all">All categories</option>
          {categories.map(([slug, name]) => (
            <option key={slug} value={slug}>
              {name}
            </option>
          ))}
        </select>
      </div>

      <p className="min-h-5 text-sm" aria-live="polite">
        {status.kind === "saving" ? <span className="text-fg-subtle">Saving…</span> : null}
        {status.kind === "saved" ? (
          <span className="text-positive">Saved. Your recommendations update within a few seconds.</span>
        ) : null}
        {status.kind === "error" ? <span className="text-negative">{status.message}</span> : null}
      </p>

      {visible.length === 0 ? (
        <p className="text-sm text-fg-muted">No matching features.</p>
      ) : (
        <ul className="divide-y divide-line">
          {visible.map((row) => {
            const effective = row.manualValue ?? (row.inferred ? nearestLevel(row.inferred.value) : null);
            const busy = status.kind === "saving" && status.slug === row.slug;
            return (
              <li key={row.slug} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                <div className="min-w-44 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium text-fg">
                    {row.name}
                    {row.excluded ? (
                      <Badge tone="negative">
                        <Ban aria-hidden="true" /> Excluded
                      </Badge>
                    ) : row.manualValue !== null ? (
                      <Badge tone="brand">
                        <Hand aria-hidden="true" /> Manual
                      </Badge>
                    ) : row.inferred ? (
                      <Badge>
                        <Sparkles aria-hidden="true" /> Inferred
                      </Badge>
                    ) : null}
                  </p>
                  <p className="text-xs text-fg-subtle">
                    {row.categoryName}
                    {row.inferred
                      ? ` · inferred ${row.inferred.value > 0 ? "+" : ""}${row.inferred.value.toFixed(2)}, ${Math.round(row.inferred.confidence * 100)}% sure`
                      : " · no inferred value"}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div role="group" aria-label={`Your preference for ${row.name}`} className="flex overflow-hidden rounded-lg border border-line">
                    {LEVELS.map((l) => {
                      const active = row.manualValue === l.value;
                      const suggested = row.manualValue === null && effective === l.value;
                      return (
                        <button
                          key={l.value}
                          type="button"
                          disabled={busy}
                          aria-pressed={active}
                          onClick={() => save(row, active ? null : l.value, row.excluded)}
                          className={cn(
                            "px-2.5 py-1 text-xs transition-colors",
                            active
                              ? l.value < 0
                                ? "bg-negative/80 text-white"
                                : l.value > 0
                                  ? "bg-brand-500 text-white"
                                  : "bg-surface-raised text-fg"
                              : suggested
                                ? "bg-surface-raised/60 text-fg-muted"
                                : "text-fg-subtle hover:bg-surface-raised hover:text-fg",
                          )}
                        >
                          {l.label}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    aria-pressed={row.excluded}
                    onClick={() => save(row, row.manualValue, !row.excluded)}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs",
                      row.excluded
                        ? "border-negative/40 bg-negative/15 text-negative"
                        : "border-line text-fg-subtle hover:text-fg",
                    )}
                  >
                    <Ban className="size-3.5" aria-hidden="true" />
                    {row.excluded ? "Excluded" : "Exclude"}
                  </button>
                  {row.manualValue !== null || row.excluded ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => save(row, null, false)}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-fg-subtle hover:text-fg"
                      title="Remove your setting and use the inferred value"
                    >
                      <RotateCcw className="size-3.5" aria-hidden="true" /> Reset
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-xs text-fg-subtle">
        Lightly shaded buttons show the nearest level to what we inferred. Click one to set it
        yourself; click it again to go back to the inferred value.
      </p>
    </div>
  );
}
