import { cn, hashString } from "@/lib/utils";

/**
 * Placeholder artwork derived from the title. Real store artwork replaces this
 * once catalogue ingestion exists; mock data never hot-links copyrighted art.
 */
export function GameCover({
  title,
  artworkUrl,
  className,
}: {
  title: string;
  artworkUrl: string | null;
  className?: string;
}) {
  if (artworkUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- remote store art, sized by container
      <img src={artworkUrl} alt="" className={cn("object-cover", className)} loading="lazy" />
    );
  }
  const h = hashString(title);
  const hueA = h % 360;
  const hueB = (hueA + 40 + ((h >> 9) % 80)) % 360;
  const angle = (h >> 3) % 180;
  const initials = title
    .split(/\s+/)
    .filter((w) => /^[A-Za-z0-9]/.test(w))
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
  return (
    <div
      aria-hidden="true"
      className={cn("relative grid place-items-center overflow-hidden", className)}
      style={{
        backgroundImage: `linear-gradient(${angle}deg, hsl(${hueA} 70% 28%), hsl(${hueB} 75% 16%))`,
      }}
    >
      <div
        className="absolute inset-0 opacity-30"
        style={{
          backgroundImage:
            "radial-gradient(circle at 20% 20%, rgb(255 255 255 / .35), transparent 40%), repeating-linear-gradient(135deg, rgb(255 255 255 / .05) 0 2px, transparent 2px 10px)",
        }}
      />
      <span className="relative font-display text-4xl font-bold text-white/85 drop-shadow">
        {initials}
      </span>
    </div>
  );
}
