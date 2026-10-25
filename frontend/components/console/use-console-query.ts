"use client";

import { type QueryKey, type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { notFound } from "next/navigation";

import { ConsoleErrors } from "@/lib/console-queries";

/**
 * `useQuery` for the console. The console answers anyone who may not use it with a 404, so a 404 from any of its
 * endpoints renders Next's not-found page: a stranger learns nothing about the area. (It is thrown while rendering, which
 * is where Next catches it.)
 */
export function useConsoleQuery<TData, TKey extends QueryKey>(options: UseQueryOptions<TData, Error, TData, TKey>) {
  const query = useQuery(options);
  if (ConsoleErrors.isNotFound(query.error)) notFound();
  return query;
}
