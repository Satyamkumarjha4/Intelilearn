import type { ConsoleGraph, RunQuery, RunStatus } from "@/lib/types";

export type StatusTab = "all" | "running" | "failed" | "succeeded";
export type RunFilterState = { status: StatusTab; job: ConsoleGraph | ""; q: string; run: string | null };

/** What `?run=` may hold. It is put into an API path, so only a run's own id gets through. */
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The run list's filters and the selected run, as they live in the address (`?status=&job=&q=&run=`). */
export class RunFilters {
  static readonly TABS: { id: StatusTab; label: string; statuses: RunStatus[] }[] = [
    { id: "all", label: "All", statuses: [] },
    { id: "running", label: "Running", statuses: ["queued", "running"] },
    { id: "failed", label: "Failed", statuses: ["failed"] },
    { id: "succeeded", label: "Finished", statuses: ["succeeded"] },
  ];

  static readonly JOBS: { id: ConsoleGraph; label: string }[] = [
    { id: "flow", label: "Lesson flow" },
    { id: "study_material", label: "Study sheet" },
    { id: "runtime_repair", label: "Repair" },
    { id: "grade_test", label: "Grading" },
  ];

  static readonly DEFAULT: RunFilterState = { status: "all", job: "", q: "", run: null };

  static parse(params: Pick<URLSearchParams, "get">): RunFilterState {
    const status = RunFilters.TABS.find((tab) => tab.id === params.get("status"))?.id ?? "all";
    const job = RunFilters.JOBS.find((j) => j.id === params.get("job"))?.id ?? "";
    const run = params.get("run");
    return { status, job, q: params.get("q") ?? "", run: run && RUN_ID.test(run) ? run : null };
  }

  /** The address for these filters, leaving out what is at its default. */
  static href(path: string, filters: RunFilterState): string {
    const params = new URLSearchParams();
    if (filters.status !== "all") params.set("status", filters.status);
    if (filters.job) params.set("job", filters.job);
    if (filters.q.trim()) params.set("q", filters.q.trim());
    if (filters.run) params.set("run", filters.run);
    const text = params.toString();
    return text ? `${path}?${text}` : path;
  }

  /** What the list endpoint is asked for. The selected run is not a filter. */
  static query(filters: RunFilterState): RunQuery {
    const statuses = RunFilters.TABS.find((tab) => tab.id === filters.status)?.statuses ?? [];
    return { status: statuses, graph: filters.job, q: filters.q.trim() };
  }

  /** The run id when the whole search text is one: the API searches topics and learners, so an id opens the run. */
  static runIdIn(text: string): string | null {
    const id = text.trim();
    return RUN_ID.test(id) ? id : null;
  }

  /** The tab's label; the Failed tab carries how many failed runs there are, once known ("100+" past one page). */
  static tabLabel(id: StatusTab, failedCount: number | null, more: boolean): string {
    const label = RunFilters.TABS.find((tab) => tab.id === id)?.label ?? id;
    if (id !== "failed" || !failedCount) return label;
    return `${label} · ${failedCount}${more ? "+" : ""}`;
  }

  static change(filters: RunFilterState, patch: Partial<RunFilterState>): RunFilterState {
    return { ...filters, ...patch };
  }
}
