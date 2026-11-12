import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * Every page the app has, read from the frontend's `app/` folder, so the warm-up (`tests/warm-up.setup.ts`) opens all of
 * them and a new page is warmed without anyone remembering to list it.
 *
 * Why the warm-up exists: the e2e stack runs `next dev`, which compiles a route the first time anyone opens it and then
 * reloads every open page (Fast Refresh). With several workers that reload lands in the middle of another worker's quiz and
 * times the test out after three minutes. Opening each route once, before the specs, moves the compiling out of the way.
 */
export class AppRoutes {
  /** Any id will do: a dynamic route compiles the same whatever it is asked for, and the page then says "not found". */
  static readonly SAMPLE_ID = "00000000-0000-4000-8000-000000000000";
  private static readonly APP_DIR = fileURLToPath(new URL("../../frontend/app", import.meta.url));

  /** The URL path of each `page.tsx` in `files` (paths relative to `app/`): route groups `(x)` vanish, `[id]` gets an id. */
  static fromPageFiles(files: readonly string[]): string[] {
    return files
      .map((file) => file.split("/"))
      .filter((parts) => parts.at(-1) === "page.tsx")
      .map((parts) =>
        "/" +
        parts
          .slice(0, -1)
          .filter((part) => !/^\(.+\)$/.test(part))
          .map((part) => (/^\[.+\]$/.test(part) ? AppRoutes.SAMPLE_ID : part))
          .join("/"),
      )
      .sort();
  }

  static discover(): string[] {
    return AppRoutes.fromPageFiles(readdirSync(AppRoutes.APP_DIR, { recursive: true }) as string[]);
  }

  /** The pages a signed-in person is sent away from (the landing page, sign-in and the code screen under it), so only a signed-out visit compiles them. */
  static isSignedOutOnly(path: string): boolean {
    return path === "/" || path === "/auth" || path.startsWith("/auth/");
  }

  /** The console is for staff: a learner is shown a page that does not exist there, which compiles nothing. */
  static isConsole(path: string): boolean {
    return path === "/console" || path.startsWith("/console/");
  }
}
