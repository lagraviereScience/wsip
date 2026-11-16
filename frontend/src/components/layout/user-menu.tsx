import Link from "next/link";

import { SignInButton } from "@/components/auth/sign-in-button";
import { SignOutButton } from "@/components/auth/sign-out-button";
import { getCurrentUser } from "@/lib/session";

function Avatar({ name, url }: { name: string; url: string | null }) {
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element -- Steam avatar CDN
    return <img src={url} alt="" className="size-9 rounded-lg" referrerPolicy="no-referrer" />;
  }
  return (
    <span className="grid size-9 place-items-center rounded-lg bg-brand-500/20 text-sm font-semibold text-brand-300">
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}

/** Reads the session: render inside <Suspense>. */
export async function UserMenu({ compact = false }: { compact?: boolean }) {
  const me = await getCurrentUser();
  if (!me) {
    return <SignInButton size="sm" className="w-full" label={compact ? "Sign in" : undefined} />;
  }
  return (
    <div className="flex items-center gap-3">
      <Link href="/settings" className="flex min-w-0 flex-1 items-center gap-3">
        <Avatar name={me.display_name} url={me.avatar_url} />
        {compact ? null : (
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-fg">{me.display_name}</span>
            <span className="block text-xs text-fg-subtle">Steam connected</span>
          </span>
        )}
      </Link>
      {compact ? null : <SignOutButton className="px-2" />}
    </div>
  );
}
