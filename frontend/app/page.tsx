import { SystemStatus } from "@/components/system-status";

// Swagger and the admin are served by Django directly (they need Django's static files).
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-10 px-6 py-20">
      <header className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">Lesson Crafter</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          An AI tutor that finds out what you already know, then teaches you the rest.
        </p>
      </header>

      <SystemStatus />

      <nav className="flex gap-4 text-sm">
        <a className="underline underline-offset-4" href={`${backendUrl}/api/docs`} target="_blank">
          API docs (Swagger)
        </a>
        <a className="underline underline-offset-4" href={`${backendUrl}/admin/`} target="_blank">
          Django admin
        </a>
      </nav>
    </main>
  );
}
