import { LogIn } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Full-page navigation to the backend, which redirects to Steam's own sign-in page.
 * Must be a plain <a>, not a client-side <Link>: the flow leaves our site.
 */
export function SignInButton({
  next,
  size = "md",
  className,
  label = "Sign in through Steam",
}: {
  next?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
  label?: string;
}) {
  const href = next
    ? `/api/auth/steam/login?next=${encodeURIComponent(next)}`
    : "/api/auth/steam/login";
  return (
    <a href={href} className={cn(buttonVariants({ size }), className)}>
      <LogIn aria-hidden="true" />
      {label}
    </a>
  );
}
