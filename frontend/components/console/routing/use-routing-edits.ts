"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { consoleQueries } from "@/lib/console-queries";
import { RoutingDraft } from "@/lib/routing-draft";
import { RoutingProfile } from "@/lib/routing-profile";
import { RoutingSaver } from "@/lib/routing-save";
import type { ConsoleRouting, NodeRouting, ProfilePreview } from "@/lib/types";

const saver = new RoutingSaver(consoleApi);

/**
 * The routing page's local edits: the steps as edited beside the steps as saved, which steps differ, and Save, which
 * sends one request per changed step. Edits live here until saved or discarded; the cache holds what the server has.
 */
export function useRoutingEdits(routing: ConsoleRouting | undefined) {
  const queryClient = useQueryClient();
  const [edits, setEdits] = useState<Record<string, NodeRouting>>({});
  const [failures, setFailures] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState(false);

  const saved = useMemo(() => (routing ? RoutingDraft.flatten(routing) : []), [routing]);
  const current = useMemo(() => new Map(saved.map((node) => [node.key, edits[node.key] ?? node])), [saved, edits]);
  const changed = useMemo(() => RoutingDraft.changed(saved, [...current.values()]), [saved, current]);

  const edit = useCallback((node: NodeRouting) => {
    setEdits((all) => ({ ...all, [node.key]: node }));
    setFailures((all) => (node.key in all ? Object.fromEntries(Object.entries(all).filter(([key]) => key !== node.key)) : all));
  }, []);

  const discard = useCallback(() => {
    setEdits({});
    setFailures({});
  }, []);

  /** Loads a profile's steps into the edits (the ones it changes and can apply); returns how many it loaded. */
  const load = useCallback(
    (preview: ProfilePreview): { applied: number; skipped: number } => {
      const { drafts, applied, skipped } = RoutingProfile.merge([...current.values()], preview);
      setEdits((all) => ({ ...all, ...Object.fromEntries(drafts.filter((node) => applied.includes(node.key)).map((node) => [node.key, node])) }));
      setFailures((all) => Object.fromEntries(Object.entries(all).filter(([key]) => !applied.includes(key))));
      return { applied: applied.length, skipped: skipped.length };
    },
    [current],
  );

  const save = useCallback(async () => {
    if (!routing) return;
    setSaving(true);
    try {
      const outcome = await saver.save([...current.values()], changed);
      queryClient.setQueryData<ConsoleRouting>(consoleQueries.routing().queryKey, (old) => (old ? RoutingDraft.replace(old, outcome.saved) : old));
      const savedKeys = new Set(outcome.saved.map((node) => node.key));
      setEdits((all) => Object.fromEntries(Object.entries(all).filter(([key]) => !savedKeys.has(key))));
      setFailures(outcome.failed);
      const message = RoutingSaver.message(outcome);
      if (Object.keys(outcome.failed).length) toast.error(message);
      else toast.success(message);
    } catch (error) {
      toast.error(ConsoleFailure.of(error).message);
    } finally {
      setSaving(false);
    }
  }, [routing, current, changed, queryClient]);

  return { saved, current, changed, failures, saving, edit, discard, load, save };
}
