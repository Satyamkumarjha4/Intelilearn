"use client";

import { useEffect, useRef, useState } from "react";

import { Autoplay } from "@/lib/autoplay";

/** How much of the element must be on screen for it to play. */
const VISIBLE = 0.3;

type Options = {
  /** Called every few seconds while it plays. */
  onAdvance: () => void;
  /** Off for a visitor who asked for less motion. */
  enabled: boolean;
  /** The element whose visibility, hover, focus and touch decide whether it plays. */
  target: React.RefObject<HTMLElement | null>;
};

/**
 * Wires `Autoplay` (the timer and pause rules, tested in lib/autoplay.test.ts) to a part of the page: hovering the mouse
 * over it, keyboard focus inside it, a touch on it, and it being less than 30% on screen all pause it. Spread `handlers`
 * on the target. `paused` follows the player, for a progress bar that must stop with it.
 */
export function useAutoplay({ onAdvance, enabled, target }: Options) {
  const player = useRef<Autoplay | null>(null);
  const advance = useRef(onAdvance);
  const [paused, setPaused] = useState(true); // nothing is playing before it is seen
  useEffect(() => {
    advance.current = onAdvance;
  });

  useEffect(() => {
    const autoplay = new Autoplay(() => advance.current(), setPaused);
    player.current = autoplay;
    autoplay.hold("hidden");
    const element = target.current;
    let observer: IntersectionObserver | undefined;
    if (element && "IntersectionObserver" in window) {
      observer = new IntersectionObserver(
        ([entry]) => (entry.intersectionRatio >= VISIBLE ? autoplay.release("hidden") : autoplay.hold("hidden")),
        { threshold: VISIBLE },
      );
      observer.observe(element);
    } else {
      autoplay.release("hidden"); // no way to tell, so play
    }
    return () => {
      observer?.disconnect();
      autoplay.dispose();
      player.current = null;
    };
  }, [target]);

  useEffect(() => {
    player.current?.setEnabled(enabled);
  }, [enabled]);

  const handlers = {
    // A touch also sends mouse events once the finger lifts, which would leave "hover" held for good: mouse pointers only.
    onPointerEnter: (event: React.PointerEvent) => event.pointerType === "mouse" && player.current?.hold("hover"),
    onPointerLeave: (event: React.PointerEvent) => event.pointerType === "mouse" && player.current?.release("hover"),
    // Keyboard focus pauses; the focus a mouse click leaves behind does not (the pointer being over it already does).
    onFocus: (event: React.FocusEvent) => event.target.matches(":focus-visible") && player.current?.hold("focus"),
    onBlur: (event: React.FocusEvent) => !event.currentTarget.contains(event.relatedTarget as Node | null) && player.current?.release("focus"),
    onTouchStart: () => player.current?.touchStart(),
    onTouchEnd: () => player.current?.touchEnd(),
    onTouchCancel: () => player.current?.touchEnd(),
  };

  return { paused, handlers, restart: () => player.current?.restart() };
}
