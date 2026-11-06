import { Alert, AlertDescription } from "@/components/ui/alert";

/** The frame the credits pages share: an eyebrow, a heading, and a column that fits a phone. */
export function PageFrame({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-1">
        <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">{eyebrow}</p>
        <h1 className="font-heading text-3xl font-semibold tracking-tight">{title}</h1>
      </header>
      {children}
    </main>
  );
}

export function LoadFailure({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
