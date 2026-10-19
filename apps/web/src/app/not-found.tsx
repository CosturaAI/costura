import Link from "next/link";

/** Recovery for unmatched routes and scope failures thrown before the scoped shell can render. */
export default function RootNotFound() {
  return (
    <main
      id="main"
      tabIndex={-1}
      className="mx-auto flex min-h-dvh w-full max-w-xl items-center px-4 py-10 sm:px-6"
    >
      <div className="w-full rounded-lg border border-border bg-card p-6">
        <h1 className="text-base font-semibold text-foreground">Nothing here</h1>
        <p className="mt-2 text-sm text-secondary-foreground">
          The address does not match a page, organization, provider, or valid month in Costura.
        </p>
        <p className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <Link href="/" className="font-medium text-primary hover:underline">
            Go to your organizations
          </Link>
          <Link href="/new" className="font-medium text-primary hover:underline">
            Create an organization
          </Link>
        </p>
      </div>
    </main>
  );
}
