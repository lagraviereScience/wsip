export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-6">
      <div className="h-10 w-2/3 animate-pulse rounded-lg bg-surface-raised" />
      <div className="h-4 w-1/2 animate-pulse rounded bg-surface-raised" />
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-72 animate-pulse rounded-card bg-surface" />
        ))}
      </div>
    </div>
  );
}
