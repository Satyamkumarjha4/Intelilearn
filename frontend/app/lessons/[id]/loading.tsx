import { Skeleton } from "@/components/ui/skeleton";

/** The shape of the lesson workspace while it loads: breadcrumb, title, stepper, and the main cards. */
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-6" aria-busy="true" aria-label="Loading your lesson">
      <div className="flex flex-col gap-4">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-9 w-72 max-w-full" />
        <Skeleton className="h-7 w-full max-w-md" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Skeleton className="h-96 rounded-[22px]" />
        <Skeleton className="h-96 rounded-[22px]" />
      </div>
    </main>
  );
}
