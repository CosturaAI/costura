import { SkeletonCard, SkeletonChart, SkeletonHeader, SkeletonKpis } from "@/components/skeletons";

/** Mirrors the four bands of the page: KPIs, chart, who spends, what to watch. */
export default function Loading() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      <SkeletonHeader />
      <SkeletonKpis />
      <SkeletonChart />
      <div className="grid gap-4 lg:grid-cols-2">
        <SkeletonCard rows={8} />
        <SkeletonCard rows={8} />
        <SkeletonCard rows={6} />
        <SkeletonCard rows={6} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <SkeletonCard rows={3} />
        <SkeletonCard rows={3} />
        <SkeletonCard rows={2} />
        <SkeletonCard rows={3} />
      </div>
    </div>
  );
}
