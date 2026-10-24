import { HomeContent } from "@/components/home-content";
import { SystemStatus } from "@/components/system-status";

// Swagger and the admin are served by Django directly (they need Django's static files).
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-10 px-4 py-12">
      <HomeContent />

      <SystemStatus />

      <nav className="flex gap-4 text-sm text-muted-foreground">
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
