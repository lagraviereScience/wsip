import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 text-center">
      <div>
        <p className="font-display text-6xl font-bold text-brand-400">404</p>
        <h1 className="mt-4 text-2xl font-semibold text-fg">Nothing to play here</h1>
        <p className="mt-2 text-fg-muted">That page doesn&apos;t exist.</p>
        <Link href="/dashboard" className={buttonVariants({ className: "mt-8" })}>
          Back to the dashboard
        </Link>
      </div>
    </main>
  );
}
