"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { consoleApi } from "@/lib/console-api";
import { consoleQueries } from "@/lib/console-queries";
import { ModelCatalog } from "@/lib/model-catalog";
import { ProbeQueue } from "@/lib/probe-queue";
import type { ConsoleModel, ProbeResult } from "@/lib/types";

const queue = new ProbeQueue((id) => consoleApi.probeModel(id));

/**
 * Tests models (one, or all with two at a time) and puts each result on its row as it arrives. The server keeps the
 * result too, so the row is updated in the cache and not fetched again.
 */
export function useModelTests() {
  const queryClient = useQueryClient();
  const [testing, setTesting] = useState<ReadonlySet<number>>(new Set());
  const [running, setRunning] = useState(false);
  const signal = useRef({ stopped: false });

  useEffect(() => {
    const current = signal.current;
    current.stopped = false;
    return () => {
      current.stopped = true; // leaving the page starts no more tests
    };
  }, []);

  const keep = useCallback(
    (id: number, result: ProbeResult) => {
      queryClient.setQueryData<ConsoleModel[]>(consoleQueries.models().queryKey, (rows) =>
        rows?.map((row) => (row.id === id ? ModelCatalog.withProbe(row, result, new Date()) : row)),
      );
    },
    [queryClient],
  );

  const test = useCallback(
    async (ids: readonly number[]) => {
      const results: ProbeResult[] = [];
      await queue.run(
        ids,
        {
          onStart: (id) => setTesting((current) => new Set(current).add(id)),
          onResult: (id, result) => {
            results.push(result);
            keep(id, result);
            setTesting((current) => {
              const next = new Set(current);
              next.delete(id);
              return next;
            });
          },
        },
        signal.current,
      );
      return results;
    },
    [keep],
  );

  const testOne = useCallback((id: number) => void test([id]), [test]);

  const testAll = useCallback(
    async (models: readonly ConsoleModel[]) => {
      const ids = models.filter(ModelCatalog.canTest).map((model) => model.id);
      if (ids.length === 0) {
        toast.info("No model can be tested yet: none has its provider's key set.");
        return;
      }
      setRunning(true);
      toast(`Testing ${ids.length} ${ids.length === 1 ? "model" : "models"}…`);
      const results = await test(ids);
      setRunning(false);
      const failed = results.filter((result) => !result.ok).length;
      if (results.length === ids.length) {
        if (failed) toast.error(`Tests finished: ${results.length - failed} work, ${failed} failed.`);
        else toast.success(`Tests finished: all ${results.length} work.`);
      }
    },
    [test],
  );

  return { testing, running, testOne, testAll };
}
