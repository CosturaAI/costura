import { PUBLIC_DEMO_REPOSITORY } from "@/lib/public-demo";

export function PublicDemoBar() {
  return (
    <div
      role="region"
      aria-label="Live demo"
      className="sticky top-0 z-30 flex h-(--public-demo-bar) items-center justify-center gap-3 bg-primary px-4 text-sm text-primary-foreground print:hidden"
    >
      <p className="truncate">
        <span className="font-medium">Costura live demo</span>
        <span className="hidden sm:inline">: synthetic data, open source under Apache 2.0.</span>
      </p>
      <a
        href={PUBLIC_DEMO_REPOSITORY}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0 rounded-md border border-primary-foreground/40 px-2 py-0.5 font-medium hover:bg-primary-foreground/10"
      >
        View on GitHub
      </a>
    </div>
  );
}
