import { ExternalLink, Plus, Trophy } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SignInButton } from "@/components/auth/sign-in-button";
import { GameCover } from "@/components/games/game-cover";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { PreviewBanner } from "@/components/layout/preview-banner";
import { OnboardingNotice } from "@/components/onboarding/onboarding-notice";
import { RatingSelect } from "@/components/library/rating-select";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { getLibrary } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";
import { formatDaysAgo, formatPlaytime } from "@/lib/utils";

export const metadata: Metadata = { title: "My Game Library" };

async function Library() {
  const me = await getCurrentUser();
  const { source, data } = await getLibrary(me);
  // Server order: playtime (when known), then rating, then name.
  const sorted = data;
  const hasPlaytime = data.some((e) => e.playtimeMinutes !== null);
  const editable = source === "api";

  return (
    <>
      <PreviewBanner source={source} />
      {me ? <OnboardingNotice me={me} /> : null}
      <PageHeader
        eyebrow="My Game Library"
        title="Your library"
        description={
          me?.library_mode === "manual"
            ? "Games you've added and rated. Your ratings teach us your taste. Playtime isn't available because we don't read your Steam library."
            : "The games in your Steam library with the playtime Steam reports. We keep history from the day you connect and never fill gaps with guesses."
        }
      >
        {me ? (
          me.library_mode === "manual" ? (
            <div className="mt-5">
              <Link href="/library/add" className={buttonVariants()}>
                <Plus aria-hidden="true" /> Add games
              </Link>
            </div>
          ) : null
        ) : (
          <div className="mt-5">
            <SignInButton next="/library" />
          </div>
        )}
      </PageHeader>
      {sorted.length === 0 ? (
        <p className="rounded-card border border-dashed border-line p-8 text-center text-fg-muted">
          {me?.library_mode === "manual" ? "No games yet. Use \u201cAdd games\u201d to start." : "No games to show yet."}
        </p>
      ) : (
        <div className="overflow-hidden rounded-card border border-line bg-surface/80">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs tracking-wider text-fg-subtle uppercase">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Game</th>
                {editable ? <th scope="col" className="px-4 py-3 font-medium">Your rating</th> : null}
                {hasPlaytime ? (
                  <>
                    <th scope="col" className="hidden px-4 py-3 font-medium sm:table-cell">Last 2 weeks</th>
                    <th scope="col" className="px-4 py-3 text-right font-medium">Total</th>
                    <th scope="col" className="hidden px-4 py-3 text-right font-medium lg:table-cell">Achievements</th>
                    <th scope="col" className="hidden px-4 py-3 text-right font-medium md:table-cell">Last played</th>
                  </>
                ) : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {sorted.map((e) => (
                <tr key={e.game.id} className="hover:bg-surface-hover/60">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <GameCover
                        title={e.game.title}
                        artworkUrl={e.game.artworkUrl}
                        className="h-10 w-16 shrink-0 rounded-md [&_span]:text-sm"
                      />
                      <div className="min-w-0">
                        <p className="flex items-center gap-1.5 truncate font-medium text-fg">
                          {e.game.steamAppId ? (
                            <a
                              href={`https://store.steampowered.com/app/${e.game.steamAppId}/`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="truncate hover:text-brand-300"
                            >
                              {e.game.title}
                              <ExternalLink className="ml-1 inline size-3 opacity-50" aria-hidden="true" />
                            </a>
                          ) : (
                            e.game.title
                          )}
                        </p>
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          {e.playtimeMinutes === 0 ? <Badge tone="signal">Unplayed</Badge> : null}
                          {editable && e.owned === false ? <Badge>Played elsewhere</Badge> : null}
                          {e.game.tags.slice(0, 3).map((t) => (
                            <Badge key={t} className="hidden md:inline-flex">{t}</Badge>
                          ))}
                        </div>
                      </div>
                    </div>
                  </td>
                  {editable && e.game.steamAppId ? (
                    <td className="px-4 py-3">
                      <RatingSelect
                        appid={e.game.steamAppId}
                        name={e.game.title}
                        owned={e.owned ?? true}
                        initial={e.rating ?? null}
                      />
                    </td>
                  ) : editable ? (
                    <td className="px-4 py-3" />
                  ) : null}
                  {hasPlaytime ? (
                    <>
                      <td className="hidden px-4 py-3 text-fg-muted sm:table-cell">
                        {e.recentMinutes > 0 ? formatPlaytime(e.recentMinutes) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right text-fg tabular-nums">
                        {formatPlaytime(e.playtimeMinutes)}
                      </td>
                      <td className="hidden px-4 py-3 text-right text-fg-muted lg:table-cell">
                        {e.achievements ? (
                          <span className="inline-flex items-center gap-1">
                            <Trophy className="size-3.5 text-caution" aria-hidden="true" />
                            {e.achievements.achieved}/{e.achievements.total}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="hidden px-4 py-3 text-right text-fg-muted md:table-cell">
                        {e.playtimeMinutes === null ? "—" : formatDaysAgo(e.lastPlayedDaysAgo)}
                      </td>
                    </>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {source === "api" ? (
        <p className="mt-3 text-xs text-fg-subtle">
          Game data provided by Steam.{hasPlaytime ? " Achievements are fetched for recently played games only." : ""}
        </p>
      ) : null}
    </>
  );
}

export default function LibraryPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Library />
    </Suspense>
  );
}
