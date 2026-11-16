import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { Logo } from "@/components/brand/logo";
import { ManualOnboarding } from "@/components/onboarding/manual-onboarding";
import { OnboardingStatus } from "@/components/onboarding/onboarding-status";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Setting up" };

async function Status() {
  const me = await getCurrentUser();
  if (!me) redirect("/");
  return me.library_mode === "manual" ? (
    <ManualOnboarding initial={me} />
  ) : (
    <OnboardingStatus initial={me} />
  );
}

export default function OnboardingPage() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-3xl flex-col justify-center gap-8 px-4 py-12">
      <Logo />
      <div>
        <h1 className="text-3xl font-bold text-fg">Setting up your profile</h1>
        <p className="mt-2 text-fg-muted">
          You signed in through Steam. Your Steam password never reaches us.
        </p>
      </div>
      <Suspense fallback={<div className="h-40 animate-pulse rounded-card bg-surface" />}>
        <Status />
      </Suspense>
    </main>
  );
}
