import { Ban, TrendingDown, TrendingUp } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { GameCover } from "@/components/games/game-cover";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { PreviewBanner } from "@/components/layout/preview-banner";
import { OnboardingNotice } from "@/components/onboarding/onboarding-notice";
import { PreferenceBar } from "@/components/profile/preference-bar";
import { FeedbackList } from "@/components/feedback/feedback-list";
import { PreferenceEditor } from "@/components/profile/preference-editor";
import { PendingRefresher } from "@/components/recommendations/pending-refresher";
import { RefreshRecommendationsButton } from "@/components/recommendations/refresh-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import type { ApiFeaturePreference, ApiProfile } from "@/lib/api/types";
import { getFeedbackList, getProfileApi, getProfileSummary, getTaxonomy } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";
import { formatPlaytime } from "@/lib/utils";

export const metadata: Metadata = { title: "My Gamer Profile" };

const CATEGORY_NAMES: Record<string, string> = {
  genre: "Genres",
  theme: "Themes",
  mechanic: "Gameplay mechanics",
  mode: "Game modes",
  structure: "Game structure",
  pace: "Pace and complexity",
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-card border border-line bg-surface/80 p-4">
      <p className="text-xs text-fg-subtle">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold text-fg">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p> : null}
    </div>
  );
}

function signed(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}

/** Features whose recent behaviour differs most from the lifetime pattern. */
function shifts(features: ApiFeaturePreference[]) {
  const withBoth = features.filter(
    (f) =>
      f.inferred?.recent !== null &&
      f.inferred?.historical !== null &&
      f.inferred !== null &&
      f.inferred.recent_confidence >= 0.3,
  );
  const delta = (f: ApiFeaturePreference) => (f.inferred!.recent ?? 0) - (f.inferred!.historical ?? 0);
  const sorted = [...withBoth].sort((a, b) => delta(b) - delta(a));
  return {
    rising: sorted.filter((f) => delta(f) >= 0.2).slice(0, 5),
    falling: sorted.reverse().filter((f) => delta(f) <= -0.2).slice(0, 5),
    delta,
  };
}

function ShiftList({
  title,
  icon,
  items,
  delta,
}: {
  title: string;
  icon: React.ReactNode;
  items: ApiFeaturePreference[];
  delta: (f: ApiFeaturePreference) => number;
}) {
  return (
    <div>
      <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-fg">
        {icon}
        {title}
      </p>
      {items.length ? (
        <ul className="space-y-1.5 text-sm">
          {items.map((f) => (
            <li key={f.slug} className="flex justify-between gap-3">
              <span className="text-fg-muted">{f.name}</span>
              <span className="text-xs text-fg-subtle">
                lifetime {signed(f.inferred!.historical ?? 0)} → recent {signed(f.inferred!.recent ?? 0)}
                <span className="sr-only"> (change {signed(delta(f))})</span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fg-subtle">No clear change.</p>
      )}
    </div>
  );
}

async function RealProfile({ profile }: { profile: ApiProfile }) {
  const me = (await getCurrentUser())!;
  const [{ data: p }, taxonomy, feedback] = await Promise.all([
    getProfileSummary(me, profile),
    getTaxonomy(),
    getFeedbackList(me),
  ]);
  const run = profile.run!;
  const sp = profile.mode_balance.singleplayer_share;
  const { rising, falling, delta } = shifts(profile.features);
  return (
    <>
      <div className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Games owned" value={p.gamesOwned.toLocaleString("en")} />
        <Stat
          label="Games analysed"
          value={run.games_with_metadata.toLocaleString("en")}
          hint={`${run.games_played.toLocaleString("en")} played · ${run.games_rated} rated`}
        />
        <Stat label="Lifetime playtime" value={formatPlaytime(p.totalPlaytimeMinutes)} />
        <Stat
          label="Profile confidence"
          value={`${Math.round(run.confidence * 100)}%`}
          hint={`${run.features_inferred} preferences inferred`}
        />
      </div>

      <div className="mb-8 flex flex-wrap items-center justify-between gap-3 text-sm text-fg-subtle">
        <p>
          Profile computed{" "}
          {new Date(run.created_at).toLocaleString("en-GB", {
            dateStyle: "medium",
            timeStyle: "short",
            timeZone: "UTC",
          })}{" "}
          UTC from your Steam library (model {run.params_version}). Playtime is treated as a
          signal of interest, never as proof that you enjoyed a game.
        </p>
        <RefreshRecommendationsButton />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>What you enjoy</CardTitle>
            <CardDescription>
              From −1 (strong dislike) to +1 (strong preference). The percentage is how sure we
              are, kept separate from the strength.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {p.topPreferences.length ? (
              p.topPreferences.map((pref) => <PreferenceBar key={pref.slug ?? pref.feature} preference={pref} />)
            ) : (
              <p className="text-sm text-fg-muted">Not enough data yet.</p>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Singleplayer vs multiplayer</CardTitle>
              <CardDescription>Share of the playtime we can attribute to each.</CardDescription>
            </CardHeader>
            <CardContent>
              {sp === null ? (
                <p className="text-sm text-fg-muted">Not known yet.</p>
              ) : (
                <>
                  <div className="flex h-3 overflow-hidden rounded-full" aria-hidden="true">
                    <span className="bg-brand-500" style={{ width: `${Math.round(sp * 100)}%` }} />
                    <span className="flex-1 bg-signal-500" />
                  </div>
                  <div className="mt-2 flex justify-between text-sm">
                    <span className="text-brand-300">
                      Singleplayer {Math.round(sp * 100)}% ·{" "}
                      {formatPlaytime(profile.mode_balance.singleplayer_minutes)}
                    </span>
                    <span className="text-signal-300">
                      Multiplayer {100 - Math.round(sp * 100)}% ·{" "}
                      {formatPlaytime(profile.mode_balance.multiplayer_minutes)}
                    </span>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Dislikes</CardTitle>
              <CardDescription>
                Inferred dislikes are capped at −0.5: playing little of something is weak
                evidence. Set a stronger value yourself below.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {p.dislikes.length ? (
                p.dislikes.map((pref) => <PreferenceBar key={pref.slug ?? pref.feature} preference={pref} />)
              ) : (
                <p className="text-sm text-fg-muted">None found.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Excluded tags</CardTitle>
              <CardDescription>Games with these are never recommended.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {p.excludedTags.length ? (
                p.excludedTags.map((t) => (
                  <Badge key={t} tone="negative">
                    <Ban aria-hidden="true" /> {t}
                  </Badge>
                ))
              ) : (
                <p className="text-sm text-fg-muted">None. Use Exclude below to add one.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent vs lifetime</CardTitle>
            <CardDescription>
              Recent interests come from your last two weeks of play and recently played games.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-6 sm:grid-cols-2">
            <ShiftList
              title="Playing more lately"
              icon={<TrendingUp className="size-4 text-positive" aria-hidden="true" />}
              items={rising}
              delta={delta}
            />
            <ShiftList
              title="Less than before"
              icon={<TrendingDown className="size-4 text-caution" aria-hidden="true" />}
              items={falling}
              delta={delta}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Most influential games</CardTitle>
            <CardDescription>The games that shape your profile the most.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-3 sm:grid-cols-2">
              {profile.influential_games.map((g) => (
                <li key={g.game_id} className="flex items-center gap-3">
                  <GameCover
                    title={g.name}
                    artworkUrl={g.capsule_image_url}
                    className="h-11 w-20 shrink-0 rounded-lg [&_span]:text-base"
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-fg">{g.name}</p>
                    <p className="text-xs text-fg-subtle">{formatPlaytime(g.playtime_minutes)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Your preferences</CardTitle>
          <CardDescription>
            Adjust anything we got wrong. Your settings override what we infer, and excluded
            tags are hard filters across every recommendation list.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PreferenceEditor features={profile.features} taxonomy={taxonomy} categoryNames={CATEGORY_NAMES} />
        </CardContent>
      </Card>

      <Card className="mt-6" id="feedback">
        <CardHeader>
          <CardTitle>Your game feedback</CardTitle>
          <CardDescription>
            Likes, favourites and &ldquo;not my type&rdquo; shape your profile a little (less
            than a rating). &ldquo;Not interested&rdquo; only hides a game. Change or undo anything
            here; your profile updates within a few seconds.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FeedbackList games={feedback} />
        </CardContent>
      </Card>
    </>
  );
}

async function Profile() {
  const me = await getCurrentUser();
  if (!me) {
    const { source, data: p } = await getProfileSummary(null);
    return (
      <>
        <PreviewBanner source={source} />
        <PageHeader eyebrow="My Gamer Profile" title="How you play" />
        <Card>
          <CardHeader>
            <CardTitle>What you enjoy</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {p.topPreferences.map((pref) => (
              <PreferenceBar key={pref.feature} preference={pref} />
            ))}
          </CardContent>
        </Card>
      </>
    );
  }
  const profile = await getProfileApi(me);
  return (
    <>
      <OnboardingNotice me={me} />
      <PageHeader
        eyebrow="My Gamer Profile"
        title="How you play"
        description="Built from your play history and anything you set yourself. Settings you choose always override what we work out on our own."
      />
      {profile && profile.status === "ready" && profile.run ? (
        <RealProfile profile={profile} />
      ) : (
        <PendingRefresher what="gamer profile" />
      )}
    </>
  );
}

export default function ProfilePage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Profile />
    </Suspense>
  );
}
