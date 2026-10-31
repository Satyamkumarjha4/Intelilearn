import { Skeleton } from "@/components/ui/skeleton";

/** The shape of "Quick quizzes" while it loads: the heading and a grid of cards. */
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8" aria-busy="true" aria-label="Loading your quizzes">
      <Skeleton className="h-9 w-56" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-36 rounded-[22px]" />
        ))}
      </div>
    </main>
  );
}
