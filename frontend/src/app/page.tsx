import { ArrowRight, Flame, Gamepad2, ShieldCheck, ShoppingBag } from "lucide-react";
import Link from "next/link";

import { SignInButton } from "@/components/auth/sign-in-button";
import { Logo } from "@/components/brand/logo";
import { buttonVariants } from "@/components/ui/button";

const LISTS = [
  {
    icon: Gamepad2,
    title: "Games you own that you should play",
    body: "Your backlog, ranked by how much you're likely to enjoy each game — not by how long it's been sitting there.",
  },
  {
    icon: ShoppingBag,
    title: "Games you don't own that you should play",
    body: "New finds that match how you actually play. Price and reviews are shown separately so they never skew the match.",
  },
  {
    icon: Flame,
    title: "Trending games that fit you",
    body: "Games that are genuinely growing right now, filtered down to the ones that suit your taste.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-6 sm:px-6">
        <Logo />
        <Link href="/dashboard" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          Explore the preview
        </Link>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 sm:px-6">
        <section className="py-16 sm:py-24">
          <p className="mb-4 text-xs font-semibold tracking-[0.2em] text-brand-400 uppercase">
            Personal game recommendations from your Steam library
          </p>
          <h1 className="max-w-3xl text-4xl leading-[1.05] font-bold text-fg sm:text-6xl">
            Stop scrolling your library.{" "}
            <span className="bg-gradient-to-r from-brand-400 to-signal-400 bg-clip-text text-transparent">
              Start playing.
            </span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-fg-muted">
            We read the play history in your Steam library, learn what you really enjoy,
            and tell you what to play next — from games you already own, games worth
            buying, and what&apos;s rising right now.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <SignInButton size="lg" />
            <Link href="/dashboard" className={buttonVariants({ variant: "secondary", size: "lg" })}>
              See a sample dashboard <ArrowRight aria-hidden="true" />
            </Link>
          </div>
          <p className="mt-4 flex items-center gap-2 text-sm text-fg-subtle">
            <ShieldCheck className="size-4" aria-hidden="true" />
            You sign in on Steam&apos;s own site. Your password never reaches us.
          </p>
        </section>

        <section aria-labelledby="lists" className="pb-24">
          <h2 id="lists" className="sr-only">
            Your three lists
          </h2>
          <div className="grid gap-5 md:grid-cols-3">
            {LISTS.map(({ icon: Icon, title, body }) => (
              <div key={title} className="rounded-card border border-line bg-surface/80 p-6">
                <span className="mb-4 inline-grid size-10 place-items-center rounded-xl bg-brand-500/15 text-brand-300">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <h3 className="text-lg font-semibold text-fg">{title}</h3>
                <p className="mt-2 text-sm text-fg-muted">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-line px-4 py-6 text-center text-xs text-fg-subtle">
        What Do You Want to Play? is not affiliated with Valve Corporation or Steam.
      </footer>
    </div>
  );
}
