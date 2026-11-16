import { ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { SignInButton } from "@/components/auth/sign-in-button";
import { SignOutButton } from "@/components/auth/sign-out-button";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { SyncButton } from "@/components/onboarding/sync-button";
import { PrivacyControls } from "@/components/settings/privacy-controls";
import { SessionsControl } from "@/components/settings/sessions-control";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import type { GameDetailsStatus } from "@/lib/api/types";
import { getPrivacy } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Settings" };

function Row({ title, body, control }: { title: ReactNode; body: ReactNode; control: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="max-w-xl">
        <div className="font-medium text-fg">{title}</div>
        <div className="text-sm text-fg-muted">{body}</div>
      </div>
      {control}
    </div>
  );
}

const DETAILS: Record<GameDetailsStatus, { label: string; tone: "positive" | "caution" | "negative" | "neutral" }> = {
  accessible: { label: "Game details public", tone: "positive" },
  empty: { label: "Library empty", tone: "caution" },
  private: { label: "Game details private", tone: "negative" },
  error: { label: "Couldn't check", tone: "caution" },
  unknown: { label: "Not checked yet", tone: "neutral" },
};

function formatUtc(iso: string | null): string {
  if (!iso) return "never";
  return `${new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" })} UTC`;
}

async function Settings() {
  const me = await getCurrentUser();
  const privacy = await getPrivacy(me);
  const steam = me?.steam;
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Steam connection</CardTitle>
          <CardDescription>
            You sign in with your Steam account. We never see your Steam password.
          </CardDescription>
        </CardHeader>
        <CardContent className="divide-y divide-line">
          {me && steam ? (
            <>
              <Row
                title={
                  <span className="flex flex-wrap items-center gap-2">
                    {steam.profile_name ?? me.display_name}
                    {me.library_mode === "steam_import" ? (
                      <Badge tone={DETAILS[steam.game_details_status].tone}>
                        {DETAILS[steam.game_details_status].label}
                      </Badge>
                    ) : (
                      <Badge tone="positive">Signed in with Steam</Badge>
                    )}
                  </span>
                }
                body={
                  <>
                    SteamID {steam.steam_id}
                    {me.library_mode === "steam_import"
                      ? ` · last synced ${formatUtc(steam.last_synced_at)}`
                      : " · your library is the games you add and rate here"}
                    {steam.profile_url ? (
                      <>
                        {" · "}
                        <a href={steam.profile_url} target="_blank" rel="noopener noreferrer"
                           className="inline-flex items-center gap-1 text-brand-300 hover:text-brand-400">
                          Steam profile <ExternalLink className="size-3" aria-hidden="true" />
                        </a>
                      </>
                    ) : null}
                  </>
                }
                control={
                  me.library_mode === "steam_import" ? (
                    <SyncButton />
                  ) : (
                    <Link href="/library/add" className={buttonVariants({ variant: "secondary" })}>
                      Add games
                    </Link>
                  )
                }
              />
              <Row
                title="Sign out"
                body="Ends this session on this device. Your data stays until you delete your account."
                control={<SignOutButton />}
              />
            </>
          ) : (
            <Row
              title="Not connected"
              body="You sign in on Steam's own site. Your password never reaches us."
              control={<SignInButton next="/settings" />}
            />
          )}
          {me ? (
            // Any signed-in session can be reviewed and others revoked, whatever the
            // state of the Steam link.
            <Row title="Your sessions" body={<SessionsControl />} control={null} />
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Privacy</CardTitle>
          <CardDescription>
            Your data is yours: control how it is used, take a copy, or delete it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {me && privacy ? (
            <PrivacyControls initial={privacy} steamImport={me.library_mode === "steam_import"} />
          ) : (
            <p className="text-sm text-fg-muted">Sign in to manage your privacy settings.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <>
      <PageHeader eyebrow="Settings" title="Settings" description="Account, privacy and recommendation controls." />
      <Suspense fallback={<PageSkeleton />}>
        <Settings />
      </Suspense>
    </>
  );
}
