import Link from "next/link";

function connectLabel(connectHref: string): string {
  if (connectHref === "/sign-in") return "Sign in to connect yours";
  if (connectHref === "/new") return "Create your organization";
  return "Connect a provider in your organization";
}

/**
 * Band under the header of every page of the public sample organization: what the sample is
 * and the way out to the reader's own data. Signed in, the way out leads to the welcome page
 * of the user's own organization, or to the organization form when the user has none yet;
 * without a session it leads to sign-in.
 */
export function DemoBanner({ connectHref, orgName }: { connectHref: string; orgName: string }) {
  return (
    <div
      role="region"
      aria-label="Sample organization"
      className="border-b border-primary bg-accent px-4 py-2 text-sm text-accent-foreground sm:px-6"
    >
      <p className="mx-auto w-full max-w-screen-2xl">
        <span className="font-medium">{orgName}</span> is a fictional company: every figure is
        synthetic, refreshed daily, and read-only.{" "}
        <Link
          prefetch={false}
          href={connectHref}
          className="font-medium text-primary hover:underline"
        >
          {connectLabel(connectHref)}
        </Link>
      </p>
    </div>
  );
}
