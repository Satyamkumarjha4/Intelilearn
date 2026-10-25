"use client";

import { useEffect, useRef } from "react";

import { RevealPolicy } from "@/lib/reveal-policy";

/**
 * Makes an element pop in when it scrolls into view. The page is whole when the server sends it: only here, in the
 * browser, does something below the fold become hidden (`data-reveal="pre"`) and then pop (`"pop"`), set straight on the
 * element so nothing re-renders and nothing moves. `onShow` runs once the element is on screen, at once if it never waited
 * (it started in view, or the visitor asked for less motion).
 */
export function useReveal<T extends HTMLElement>(onShow?: () => void) {
  const ref = useRef<T>(null);
  const shown = useRef(onShow);
  useEffect(() => {
    shown.current = onShow;
  });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const lessMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (lessMotion || !("IntersectionObserver" in window) || !RevealPolicy.startsHidden(element.getBoundingClientRect().top, window.innerHeight)) {
      shown.current?.();
      return;
    }
    element.dataset.reveal = "pre";
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        element.dataset.reveal = "pop";
        shown.current?.();
        observer.disconnect();
      },
      { threshold: 0.15 },
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      delete element.dataset.reveal;
    };
  }, []);

  return ref;
}
