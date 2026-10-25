"use client";

import { CodeIcon, DownloadIcon, FlagIcon, HistoryIcon, MoreHorizontalIcon, RefreshCwIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { LessonBook } from "@/components/lessons/lesson-book";
import { LessonSandbox } from "@/components/lessons/lesson-sandbox";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Button, buttonVariants } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { CONTACT, CONTACT_TOPICS } from "@/content/legal/contact";
import { ApiError } from "@/lib/api";
import { BookKeys, LessonBook as Book, ReadPages } from "@/lib/lesson-book";
import { lessonsApi } from "@/lib/lessons-api";
import { Mailto } from "@/lib/mailto";
import { PlainError, PlainVersion } from "@/lib/plain-notes";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import { RepairGate, RepairReport, type SandboxError, type SandboxMessage } from "@/lib/sandbox-bridge";
import type { LessonDocument, LessonVersion, TestStatus } from "@/lib/types";

type Repair = { state: "idle" } | { state: "running" } | { state: "failed"; message: string } | { state: "limit" };
type Panel = "code" | "versions" | null;

type Props = {
  lessonId: string;
  testStatus: TestStatus;
  /** Opens the Test tab (the last page of the book leads there). */
  onGoToTest: () => void;
};

/**
 * Loads the lesson document and shows it as a notebook: one page of the sandboxed document at a time, index flaps and
 * previous/next around it, and a toolbar (PDF, and a menu with version history, view code and reload).
 * A crash the runtime reports is sent to `POST /repair` once per version of the code; when that fails or the server's
 * repair limit is reached, the learner is told plainly and can reload the view or go back to an earlier version.
 */
export function LessonViewer({ lessonId, testStatus, onGoToTest }: Props) {
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
  const [readPages] = useState(() => new ReadPages(lessonId));
  // The ticks of an earlier visit live in this browser (and only there); on the server there is no storage and none show.
  const [book, setBook] = useState(() => new Book(0).withRead(readPages.load()));
  const [reloading, setReloading] = useState(false);
  const toolbar = useRef<HTMLDivElement>(null);
  const turned = useRef(false);

  useEffect(() => readPages.save(book.read), [readPages, book.read]);

  // ← and → turn the page whenever focus is not in the lesson itself (keys typed inside the iframe never reach us).
  useEffect(() => {
    const turn = (event: KeyboardEvent) => {
      const direction = BookKeys.direction({
        key: event.key,
        altKey: event.altKey,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        shiftKey: event.shiftKey,
        target: event.target as Element | null,
      });
      if (direction) setBook((current) => (direction > 0 ? current.next() : current.prev()));
    };
    window.addEventListener("keydown", turn);
    return () => window.removeEventListener("keydown", turn);
  }, []);

  // A new page starts at its top: bring the toolbar back into view if the learner had scrolled down.
  useEffect(() => {
    if (!turned.current) {
      turned.current = true;
      return;
    }
    const top = toolbar.current?.getBoundingClientRect().top ?? 0;
    if (top < 0) toolbar.current?.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [book.index]);

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
    } else if (message.type === "pages") {
      setBook((current) => current.withPages(message.count, message.titles));
    }
    // `page_changed` only confirms what the book asked for, and `test_submit` (an old lesson's test) is no longer shown.
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

  /** Opens the mail app with the lesson problem subject, and the lesson's address and page in the message. */
  const reportProblem = () => {
    const subject = CONTACT_TOPICS.find((topic) => topic.id === "lesson")!.subject;
    const body = `Lesson: ${window.location.href}\nPage: ${book.eyebrow}\n\nWhat looked wrong:\n`;
    window.location.href = Mailto.link(CONTACT.email, subject, body);
  };

  const reload = async () => {
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
  if (!doc) return <Skeleton className="h-[32rem] rounded-[22px]" />;

  const next = book.nextAction(testStatus);
  const onNext = () => {
    if (next.kind === "test") {
      setBook((current) => current.finish());
      onGoToTest();
    } else {
      setBook((current) => current.next());
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div ref={toolbar} className="flex scroll-mt-20 flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">{book.eyebrow}</p>
          <h2 className="font-heading text-2xl font-semibold tracking-tight">{book.title}</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={download}>
            <DownloadIcon /> PDF
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger className={buttonVariants({ variant: "ghost", size: "icon" })} aria-label="More">
              <MoreHorizontalIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem onClick={showVersions}>
                <HistoryIcon /> Version history
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setPanel(panel === "code" ? null : "code")}>
                <CodeIcon /> View code
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setReloading(true)}>
                <RefreshCwIcon /> Reload this lesson
              </DropdownMenuItem>
              <DropdownMenuItem onClick={reportProblem}>
                <FlagIcon /> Report a problem
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {crash && repair.state !== "running" && (
        <Alert variant="destructive">
          <AlertTitle>Something on this page did not work</AlertTitle>
          <AlertDescription>
            {repair.state === "limit"
              ? "It has already been fixed as often as we allow. Reload this lesson, or go back to an earlier version."
              : repair.state === "failed"
                ? `${PlainError.of(repair.message)} You can reload this lesson or go back to an earlier version.`
                : "You can reload this lesson or go back to an earlier version."}
          </AlertDescription>
        </Alert>
      )}

      <LessonBook
        book={book}
        next={next}
        onGoTo={(index) => setBook((current) => current.goTo(index))}
        onPrev={() => setBook((current) => current.prev())}
        onNext={onNext}
        overlay={
          repair.state === "running" && (
            <>
              <p className="font-heading text-lg font-semibold">Fixing a glitch on this page…</p>
              <p className="text-sm text-muted-foreground">It will reload by itself in a moment.</p>
            </>
          )
        }
      >
        <LessonSandbox key={instance} document={doc} theme={resolvedTheme === "dark" ? "dark" : "light"} page={book.index} onMessage={onMessage} />
      </LessonBook>

      <ConfirmDialog
        open={reloading}
        onOpenChange={setReloading}
        title="Reload this lesson?"
        description="We'll load the lesson again from scratch. Your place in the book is kept."
        confirmLabel="Reload"
        cancelLabel="Not now"
        confirmVariant="default"
        onConfirm={reload}
      />

      {panel === "code" && (
        <pre className="max-h-96 overflow-auto rounded-lg border bg-muted/30 p-3 text-xs" aria-label="Lesson code">
          {doc.code}
        </pre>
      )}
      {panel === "versions" && (
        <div className="rounded-lg border p-3 text-sm">
          <p className="mb-2 font-extrabold">Version history <span className="font-normal text-muted-foreground">· you are on version {doc.code_version}</span></p>
          {versions === null ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : versions.length === 0 ? (
            <p className="text-muted-foreground">No earlier versions: the lesson has not been repaired.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {versions.map((v) => (
                <li key={v.code_version} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">Version {v.code_version}</span>
                  <span className="text-muted-foreground">{PlainVersion.of(v.reason)}</span>
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
