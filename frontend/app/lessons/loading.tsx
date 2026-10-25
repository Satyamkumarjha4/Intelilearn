import { Skeleton } from "@/components/ui/skeleton";

/** The shape of "My lessons" while it loads: the heading, the filter chips and a grid of cards. */
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8" aria-busy="true" aria-label="Loading your lessons">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3.5 w-36" />
        <Skeleton className="h-9 w-56" />
      </div>
      <div className="flex gap-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-9 w-24 rounded-full" />
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-40 rounded-[22px]" />
        ))}
      </div>
    </main>
  );
}
