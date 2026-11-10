import { useId } from "react";

const STAR = "M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5L2.5 9.4l6.6-.9z";

/** A row of stars: filled, empty, or (for a half-star rating) half filled. Decorative: the caller labels the group. */
export function Stars({ filled, size = 20, className }: { filled: (boolean | "half")[]; size?: number; className?: string }) {
  const id = useId();
  return (
    <span aria-hidden="true" className={className ?? "flex gap-1"}>
      {filled.map((state, index) => (
        <svg key={index} width={size} height={size} viewBox="0 0 24 24">
          {state === "half" ? (
            <defs>
              <linearGradient id={`${id}-${index}`}>
                <stop offset="50%" stopColor="var(--marigold)" />
                <stop offset="50%" stopColor="var(--muted)" />
              </linearGradient>
            </defs>
          ) : null}
          <path
            d={STAR}
            fill={state === "half" ? `url(#${id}-${index})` : state ? "var(--marigold)" : "var(--muted)"}
            stroke={state ? "var(--marigold-deep)" : "var(--border)"}
            strokeWidth="1.2"
            strokeLinejoin="round"
          />
        </svg>
      ))}
    </span>
  );
}
