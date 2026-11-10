import { queryOptions } from "@tanstack/react-query";

import { ConsoleApi, consoleApi } from "@/lib/console-api";

import type { TestimonialList } from "./types";

/** The cache entry of the Testimonials screen. Its key starts with "console" like every other. */
export class TestimonialQueries {
  constructor(private readonly api: ConsoleApi = consoleApi) {}

  /** Not refetched when the tab regains focus, so a form being filled in is not disturbed. */
  list() {
    return queryOptions({
      queryKey: ["console", "testimonials"] as const,
      queryFn: (): Promise<TestimonialList> => this.api.testimonials(),
      refetchOnWindowFocus: false,
    });
  }
}

export const testimonialQueries = new TestimonialQueries();
