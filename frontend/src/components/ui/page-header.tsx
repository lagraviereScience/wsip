import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-8">
      {eyebrow ? (
        <p className="mb-2 text-xs font-semibold tracking-[0.18em] text-brand-400 uppercase">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="text-3xl font-bold text-fg sm:text-4xl">{title}</h1>
      {description ? <p className="mt-2 max-w-2xl text-fg-muted">{description}</p> : null}
      {children}
    </header>
  );
}
