import { cn } from "@/lib/utils";

type Props = { filled: number; total: number; label: string };

/** How hard a question is: segments in the AI's colour and a word, as on the quick check's cards. */
export function Difficulty({ filled, total, label }: Props) {
  return (
    <div className="flex items-center gap-3 text-[13px] font-extrabold text-insight-text">
      <span role="img" aria-label={`Difficulty ${filled} of ${total}`} className="flex gap-1">
        {Array.from({ length: total }, (_, n) => (
          <span key={n} className={cn("h-2 w-[18px] rounded", n < filled ? "bg-insight" : "bg-border")} />
        ))}
      </span>
      {label}
    </div>
  );
}
