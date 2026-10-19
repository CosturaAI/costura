import { SkeletonCard, SkeletonChart, SkeletonHeader, SkeletonKpis } from "@/components/skeletons";

export default function Loading() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      <SkeletonHeader />
      <SkeletonCard rows={3} />
      <SkeletonKpis />
      <SkeletonChart height={240} />
      <SkeletonCard rows={4} />
    </div>
  );
}
