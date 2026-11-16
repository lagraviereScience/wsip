import type { UnownedFilters } from "@/lib/types";

const INPUT =
  "h-9 rounded-lg border border-line bg-surface px-2.5 text-sm text-fg placeholder:text-fg-subtle focus:border-brand-400 focus:outline-none";
const LABEL = "flex flex-col gap-1 text-xs text-fg-subtle";

/** Plain GET form: filters live in the URL and work without client JavaScript. */
export function UnownedFiltersForm({ filters }: { filters: UnownedFilters }) {
  return (
    <form method="get" className="mt-5 flex flex-wrap items-end gap-3" aria-label="Filters">
      <label className={LABEL}>
        Max price ($)
        <input
          className={`${INPUT} w-24`}
          type="number"
          name="max_price"
          min={0}
          step={1}
          defaultValue={filters.maxPrice ?? ""}
        />
      </label>
      <label className={LABEL}>
        Min. positive reviews (%)
        <input
          className={`${INPUT} w-24`}
          type="number"
          name="min_review"
          min={0}
          max={100}
          defaultValue={filters.minReview ?? ""}
        />
      </label>
      <label className={LABEL}>
        Released from
        <input
          className={`${INPUT} w-24`}
          type="number"
          name="released_after"
          min={1970}
          max={2100}
          placeholder="year"
          defaultValue={filters.releasedAfter ?? ""}
        />
      </label>
      <label className={LABEL}>
        Released until
        <input
          className={`${INPUT} w-24`}
          type="number"
          name="released_before"
          min={1970}
          max={2100}
          placeholder="year"
          defaultValue={filters.releasedBefore ?? ""}
        />
      </label>
      <label className={LABEL}>
        Players
        <select className={INPUT} name="players" defaultValue={filters.players ?? "any"}>
          <option value="any">Any</option>
          <option value="multiplayer">Multiplayer</option>
          <option value="singleplayer">Singleplayer</option>
        </select>
      </label>
      <label className="flex h-9 items-center gap-2 text-sm text-fg-muted">
        <input type="checkbox" name="free" value="1" defaultChecked={filters.freeOnly} />
        Free-to-play only
      </label>
      <button
        type="submit"
        className="h-9 rounded-lg bg-brand-500 px-4 text-sm font-medium text-white hover:bg-brand-400"
      >
        Apply
      </button>
      <a href="?" className="h-9 px-2 text-sm leading-9 text-fg-subtle hover:text-fg">
        Reset
      </a>
    </form>
  );
}

type Params = Record<string, string | string[] | undefined>;

function num(v: string | string[] | undefined, min: number, max: number): number | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  if (s === undefined || s.trim() === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) && n >= min && n <= max ? n : undefined;
}

export function parseUnownedFilters(params: Params): UnownedFilters {
  const players = Array.isArray(params.players) ? params.players[0] : params.players;
  return {
    maxPrice: num(params.max_price, 0, 10_000),
    minReview: num(params.min_review, 0, 100),
    releasedAfter: num(params.released_after, 1970, 2100),
    releasedBefore: num(params.released_before, 1970, 2100),
    freeOnly: params.free === "1",
    players: players === "multiplayer" || players === "singleplayer" ? players : "any",
  };
}
