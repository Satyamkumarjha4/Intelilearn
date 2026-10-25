import { Skeleton } from "@/components/ui/skeleton";

/** While any page without a loading state of its own is on its way: a title and one card. */
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-8" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-9 w-64 max-w-full" />
      <Skeleton className="h-72 rounded-[22px]" />
    </main>
  );
}
