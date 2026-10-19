import { Skeleton, SkeletonCard } from "@/components/skeletons";

export default function Loading() {
  return (
    <main
      id="main"
      tabIndex={-1}
      className="mx-auto w-full max-w-xl space-y-6 px-4 py-10 sm:py-16"
      role="status"
      aria-label="Loading"
    >
      <div className="space-y-3">
        <Skeleton className="h-7 w-80 max-w-full" />
        <Skeleton className="h-4 w-full" />
      </div>
      <SkeletonCard rows={3} />
      <SkeletonCard rows={3} />
    </main>
  );
}
