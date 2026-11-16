import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "border-line bg-surface-raised text-fg-muted",
        brand: "border-brand-500/30 bg-brand-500/10 text-brand-300",
        signal: "border-signal-500/30 bg-signal-500/10 text-signal-300",
        positive: "border-positive/30 bg-positive/10 text-positive",
        caution: "border-caution/30 bg-caution/10 text-caution",
        negative: "border-negative/30 bg-negative/10 text-negative",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeProps = ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
