import {
  FilterBarSkeleton,
  SkeletonChart,
  SkeletonHeader,
  TableSkeleton,
} from "@/components/skeletons";

export default function Loading() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading">
      <SkeletonHeader />
      <FilterBarSkeleton />
      <SkeletonChart height={240} />
      <TableSkeleton rows={8} />
    </div>
  );
}
