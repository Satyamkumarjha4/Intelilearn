import { MessageCircleQuestionIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type Props = {
  /** `full` is the mark and the name; `mark` is the mark alone (a narrow space, a favicon-sized spot). */
  variant?: "full" | "mark";
  size?: "sm" | "md" | "lg";
  /** `marigold` for the mark on a primary-coloured background, where a teal mark would disappear. */
  tone?: "primary" | "marigold";
  className?: string;
};

const SIZES = { sm: { mark: 28, text: "text-lg" }, md: { mark: 34, text: "text-xl" }, lg: { mark: 48, text: "text-3xl" } } as const;

/** Socra's logo: a teal, pressable-looking square with a question bubble (the tutor asks before it teaches), and the
 *  name in the heading font. */
export function Logo({ variant = "full", size = "md", tone = "primary", className }: Props) {
  const { mark, text } = SIZES[size];
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span
        role={variant === "mark" ? "img" : undefined}
        aria-label={variant === "mark" ? "Socra" : undefined}
        aria-hidden={variant === "full" ? true : undefined}
        className={cn(
          "inline-grid shrink-0 place-items-center",
          tone === "primary"
            ? "bg-primary text-primary-foreground shadow-[0_3px_0_var(--primary-deep)]"
            : "bg-marigold text-marigold-foreground shadow-[0_3px_0_var(--marigold-deep)]",
        )}
        style={{ width: mark, height: mark, borderRadius: mark * 0.32 }}
      >
        <MessageCircleQuestionIcon strokeWidth={2.4} style={{ width: mark * 0.58, height: mark * 0.58 }} aria-hidden="true" />
      </span>
      {variant === "full" && <span className={cn("font-heading font-semibold tracking-tight", text)}>Socra</span>}
    </span>
  );
}
