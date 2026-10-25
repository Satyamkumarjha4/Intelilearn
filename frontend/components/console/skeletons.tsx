import { Skeleton } from "@/components/ui/skeleton";

/** Placeholders shaped like what is loading, so the page does not jump when the numbers arrive. */
export function KpiRowSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div aria-hidden="true" className="grid grid-cols-4 gap-4 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="grid gap-2 rounded-2xl border bg-card p-4">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="h-[34px] w-full" />
        </div>
      ))}
    </div>
  );
}

export function CardSkeleton({ height = 260 }: { height?: number }) {
  return (
    <div aria-hidden="true" className="grid gap-3 rounded-2xl border bg-card p-4">
      <Skeleton className="h-5 w-40" />
      <Skeleton className="w-full" style={{ height }} />
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="grid gap-4">
      <Skeleton className="h-8 w-48" />
      <KpiRowSkeleton />
      <div className="grid grid-cols-[1.7fr_1fr] gap-4 max-[900px]:grid-cols-1">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    </div>
  );
}
