"use client";

import { useReveal } from "@/components/landing/use-reveal";
import { RevealPolicy } from "@/lib/reveal-policy";

type Props = {
  as?: "div" | "section" | "p";
  /** Place in its group: later items pop a beat after earlier ones. */
  index?: number;
  /** The call to action's slight tilt. */
  tilt?: boolean;
  className?: string;
  role?: "presentation";
  onShow?: () => void;
  children: React.ReactNode;
};

/** Wraps a part of the landing page so it pops in as it scrolls into view (see `useReveal`). */
export function Reveal({ as: Tag = "div", index = 0, tilt, className, role, onShow, children }: Props) {
  const ref = useReveal<HTMLDivElement>(onShow);
  return (
    <Tag ref={ref as React.RefObject<never>} role={role} data-tilt={tilt ? "" : undefined} className={className} style={{ "--d": RevealPolicy.delay(index) } as React.CSSProperties}>
      {children}
    </Tag>
  );
}
