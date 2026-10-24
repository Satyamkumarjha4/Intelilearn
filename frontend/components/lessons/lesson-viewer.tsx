"use client";

import { CodeIcon, DownloadIcon, HistoryIcon, RefreshCwIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { LessonSandbox } from "@/components/lessons/lesson-sandbox";
import { TestResultPanel } from "@/components/lessons/test-result-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import { RepairGate, RepairReport, type SandboxError, type SandboxMessage } from "@/lib/sandbox-bridge";
import { TestSubmitFlow } from "@/lib/test-session";
import type { LessonDocument, LessonVersion, TestSubmission } from "@/lib/types";

type Repair = { state: "idle" } | { state: "running" } | { state: "failed"; message: string } | { state: "limit" };
type Panel = "code" | "versions" | null;

/**
 * Loads the lesson document and shows it in the sandbox, with a small toolbar (view code, version history, rebuild).
 * A crash the runtime reports is sent to `POST /repair` once per version of the code; when that fails or the server's
 * repair limit is reached, the learner sees the error and can rebuild the view or go back to an earlier version.
 */
export function LessonViewer({ lessonId }: { lessonId: string }) {
  const { resolvedTheme } = useTheme();
  const [doc, setDoc] = useState<LessonDocument | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [crash, setCrash] = useState<SandboxError | null>(null);
  const [repair, setRepair] = useState<Repair>({ state: "idle" });
  const [panel, setPanel] = useState<Panel>(null);
  const [versions, setVersions] = useState<LessonVersion[] | null>(null);
  const [gate] = useState(() => new RepairGate());
  const [stream, setStream] = useState<RunEventStream | null>(null);
  const [instance, setInstance] = useState(0);
  const [submission, setSubmission] = useState<TestSubmission | null>(null);
  const [grading, setGrading] = useState<TestSubmitFlow | null>(null);

  const load = useCallback(async () => {
    try {
      setDoc(await lessonsApi.document(lessonId));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load the lesson.");
    }
  }, [lessonId]);

  useEffect(() => {
    let active = true;
    lessonsApi
      .document(lessonId)
      .then((data) => active && setDoc(data))
      .catch((err) => active && setLoadError(err instanceof ApiError ? err.message : "Could not load the lesson."));
    return () => {
      active = false;
    };
  }, [lessonId]);

  useEffect(() => () => stream?.close(), [stream]);
  useEffect(() => () => grading?.dispose(), [grading]);

  const submitTest = (answers: Record<string, unknown>) => {
    const flow = new TestSubmitFlow(lessonsApi, (runId, onEnd) => {
      const events = new RunEventStream(runId, (event) => TERMINAL_EVENTS.has(event.name) && onEnd());
      return () => events.close();
    });
    setGrading(flow);
    setSubmission(null);
    flow.run(lessonId, answers, setSubmission).catch((err) => {
      toast.error(err instanceof ApiError ? err.message : "Could not submit the test.");
    });
  };

  const follow = useCallback(
    (runId: string) => {
      setStream(
        new RunEventStream(runId, (event) => {
          if (!TERMINAL_EVENTS.has(event.name)) return;
          if (event.name === "done") {
            setCrash(null);
            setRepair({ state: "idle" });
            void load();
          } else {
            const message = event.name === "error" ? String(event.data.message) : "The repair was cancelled.";
            setRepair({ state: "failed", message });
          }
        }),
      );
    },
    [load],
  );

  const startRepair = useCallback(
    (error: SandboxError, codeVersion: number) => {
      setRepair({ state: "running" });
      lessonsApi
        .requestRepair(lessonId, RepairReport.of(error), codeVersion)
        .then(({ run_id }) => follow(run_id))
        .catch((err) => {
          if (err instanceof ApiError && err.code === "repair_limit_reached") {
            gate.stop();
            setRepair({ state: "limit" });
          } else if (err instanceof ApiError && err.code === "stale_code_version") {
            void load(); // the lesson moved on; show the current one
            setRepair({ state: "idle" });
          } else {
            setRepair({ state: "failed", message: err instanceof ApiError ? err.message : "Could not start the repair." });
          }
        });
    },
    [lessonId, follow, gate, load],
  );

  const onMessage = (message: SandboxMessage) => {
    if (message.type === "error" && doc) {
      setCrash(message.error);
      if (gate.shouldRepair(message.error, doc.code_version)) startRepair(message.error, doc.code_version);
    } else if (message.type === "test_submit") {
      submitTest(message.answers);
    }
  };

  const showVersions = async () => {
    setPanel(panel === "versions" ? null : "versions");
    try {
      setVersions(await lessonsApi.versions(lessonId));
    } catch {
      toast.error("Could not load the version history.");
    }
  };

  const restore = async (number: number) => {
    try {
      await lessonsApi.restoreVersion(lessonId, number);
      setCrash(null);
      setRepair({ state: "idle" });
      setVersions(await lessonsApi.versions(lessonId));
      await load();
      toast.success(`Went back to version ${number}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not restore that version.");
    }
  };

  const download = async () => {
    try {
      const { LessonPdf } = await import("@/lib/pdf/lesson-pdf");
      const pages = LessonPdf.pagesOf(doc!.data as Parameters<typeof LessonPdf.pagesOf>[0]);
      const blob = await LessonPdf.blob(String(doc!.data.title ?? "Lesson"), pages);
      const url = URL.createObjectURL(blob);
      Object.assign(document.createElement("a"), { href: url, download: "lesson.pdf" }).click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Could not make the PDF.");
    }
  };

  const rebuild = async () => {
    setCrash(null);
    setRepair({ state: "idle" });
    await load();
    setInstance((n) => n + 1); // a fresh iframe, so a stuck page starts clean
  };

  if (loadError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{loadError}</AlertDescription>
      </Alert>
    );
  }
  if (!doc) return <div className="h-96 rounded-lg border bg-muted/30" aria-busy="true" />;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => setPanel(panel === "code" ? null : "code")} aria-pressed={panel === "code"}>
          <CodeIcon /> View code
        </Button>
        <Button variant="outline" size="sm" onClick={showVersions} aria-pressed={panel === "versions"}>
          <HistoryIcon /> Versions
        </Button>
        <Button variant="outline" size="sm" onClick={download}>
          <DownloadIcon /> PDF
        </Button>
        <Button variant="outline" size="sm" onClick={rebuild}>
          <RefreshCwIcon /> Rebuild
        </Button>
        <span className="ml-auto text-xs text-muted-foreground">Version {doc.code_version}</span>
      </div>

      {repair.state === "running" && (
        <Alert aria-live="polite">
          <AlertTitle>Repairing this lesson…</AlertTitle>
          <AlertDescription>Something on this page crashed. We are fixing it and will reload it automatically.</AlertDescription>
        </Alert>
      )}
      {crash && repair.state !== "running" && (
        <Alert variant="destructive">
          <AlertTitle>Something on this page did not work</AlertTitle>
          <AlertDescription>
            {repair.state === "limit"
              ? "It has already been repaired as often as allowed. Rebuild the view, or go back to an earlier version."
              : repair.state === "failed"
                ? `${repair.message} You can rebuild the view or go back to an earlier version.`
                : "You can rebuild the view or go back to an earlier version."}
            <span className="mt-1 block font-mono text-xs">{crash.component ? `${crash.component}: ` : ""}{crash.message}</span>
          </AlertDescription>
        </Alert>
      )}

      <LessonSandbox key={instance} document={doc} theme={resolvedTheme === "dark" ? "dark" : "light"} onMessage={onMessage} />

      {submission && <TestResultPanel submission={submission} />}

      {panel === "code" && (
        <pre className="max-h-96 overflow-auto rounded-lg border bg-muted/30 p-3 text-xs" aria-label="Lesson code">
          {doc.code}
        </pre>
      )}
      {panel === "versions" && (
        <div className="rounded-lg border p-3 text-sm">
          {versions === null ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : versions.length === 0 ? (
            <p className="text-muted-foreground">No earlier versions: the lesson has not been repaired.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {versions.map((v) => (
                <li key={v.code_version} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">Version {v.code_version}</span>
                  <span className="text-muted-foreground">{v.reason || "Earlier code"}</span>
                  <Button className="ml-auto" size="xs" variant="outline" onClick={() => restore(v.code_version)}>
                    Restore
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
