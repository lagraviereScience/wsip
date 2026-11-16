import { useId } from "react";

import { cn } from "@/lib/utils";

/** Brand mark: a play triangle inside a question-mark arc. */
export function LogoMark({ className }: { className?: string }) {
  // Unique per instance: a gradient whose first definition sits inside a hidden
  // (display:none) copy of the logo would otherwise not render at all.
  const gradientId = useId();
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8", className)}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset="1" stopColor="#2dd4bf" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${gradientId})`} />
      <path
        d="M10.5 11.5a5.5 5.5 0 1 1 7.6 5.1c-1.3.6-2.1 1.5-2.1 2.9"
        fill="none"
        stroke="#07080d"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path d="M14.2 22.6l4.6 2.7-4.6 2.7z" fill="#07080d" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark />
      {compact ? null : (
        <span className="font-display text-[15px] leading-tight font-semibold text-fg">
          What Do You
          <br />
          Want to Play?
        </span>
      )}
    </span>
  );
}
