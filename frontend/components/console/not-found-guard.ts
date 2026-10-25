import { notFound } from "next/navigation";

import { ConsoleErrors } from "@/lib/console-queries";

/** The rule of `useConsoleQuery` for any query result (such as a paged list): a 404 renders the not-found page, since the
 *  console answers anyone who may not use it with one. Call it while rendering, where Next catches what it throws. */
export function notFoundIfRefused<T extends { error: unknown }>(query: T): T {
  if (ConsoleErrors.isNotFound(query.error)) notFound();
  return query;
}
