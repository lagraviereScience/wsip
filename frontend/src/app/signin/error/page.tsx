import { AlertTriangle } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SignInButton } from "@/components/auth/sign-in-button";
import { buttonVariants } from "@/components/ui/button";

export const metadata: Metadata = { title: "Sign-in problem" };

const REASONS: Record<string, string> = {
  cancelled: "You cancelled the sign-in on Steam.",
  state_mismatch: "Your sign-in session didn't match. Please start again from this site.",
  state_expired: "Your sign-in took too long or was already used. Please try again.",
  nonce_expired: "The response from Steam was too old. Please try again.",
  nonce_replayed: "That sign-in link was already used. Please try again.",
  provider_unavailable: "Steam didn't respond. Please try again in a minute.",
};
const DEFAULT_REASON = "We couldn't verify your sign-in with Steam. Please try again.";

async function Reason({ searchParams }: { searchParams: Promise<{ reason?: string }> }) {
  const { reason } = await searchParams;
  return <p className="mt-2 text-fg-muted">{REASONS[reason ?? ""] ?? DEFAULT_REASON}</p>;
}

export default function SignInErrorPage(props: PageProps<"/signin/error">) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-6 px-4">
      <AlertTriangle className="size-8 text-caution" aria-hidden="true" />
      <div>
        <h1 className="text-2xl font-bold text-fg">Sign-in didn&apos;t complete</h1>
        <Suspense fallback={<p className="mt-2 text-fg-muted">{DEFAULT_REASON}</p>}>
          <Reason searchParams={props.searchParams as Promise<{ reason?: string }>} />
        </Suspense>
      </div>
      <div className="flex flex-wrap gap-3">
        <SignInButton label="Try again" />
        <Link href="/" className={buttonVariants({ variant: "secondary" })}>
          Back to home
        </Link>
      </div>
    </main>
  );
}
