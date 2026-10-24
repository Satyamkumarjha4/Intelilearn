const PLACEHOLDER_ORIGIN = "http://lesson-crafter.invalid";

/**
 * Turn an untrusted `?next=` value into a same-site path, or "/" if it could leave the site.
 *
 * Prefix checks like `startsWith("/") && !startsWith("//")` are not enough: browsers treat `/\evil.com`
 * as `//evil.com`, and tabs/newlines inside the scheme are ignored. Resolving against a placeholder
 * origin and requiring the origin to be unchanged uses the same parser the browser will.
 */
export function safeNext(value: unknown, fallback = "/"): string {
  if (typeof value !== "string" || !value.startsWith("/")) return fallback;
  try {
    const url = new URL(value, PLACEHOLDER_ORIGIN);
    if (url.origin !== PLACEHOLDER_ORIGIN) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
