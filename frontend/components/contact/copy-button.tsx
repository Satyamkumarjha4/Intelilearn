"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Clipboard } from "@/lib/clipboard";

type Props = {
  text: string;
  label: string;
  /** What was copied, for the toast ("Copied" alone says little). */
  what?: string;
  variant?: "outline" | "ghost" | "default";
  size?: "sm" | "default";
  /** The element holding the text on screen: selected when copying did not work, so the learner can copy it themselves. */
  target?: React.RefObject<HTMLElement | null>;
};

/** Copies `text`. If the browser will not, the text on the page is selected and the toast says to copy it by hand. */
export function CopyButton({ text, label, what, variant = "outline", size = "default", target }: Props) {
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copy = async () => {
    if (await new Clipboard().copy(text)) {
      toast.success(`Copied${what ? `: ${what}` : ""}`);
      setDone(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setDone(false), 2000);
      return;
    }
    const node = target?.current;
    if (node) {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    }
    toast.error("We couldn't copy it for you. It's selected now: press Ctrl+C (or Cmd+C) to copy.");
  };
  return (
    <Button variant={variant} size={size} onClick={copy}>
      {done ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
      {done ? "Copied" : label}
    </Button>
  );
}
