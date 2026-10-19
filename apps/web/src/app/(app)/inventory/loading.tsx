import { FilterBarSkeleton, SkeletonHeader, TableSkeleton } from "@/components/skeletons";

export default function Loading() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      <SkeletonHeader />
      <FilterBarSkeleton />
      <TableSkeleton />
    </div>
  );
}
