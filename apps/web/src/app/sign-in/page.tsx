import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { SampleEntry } from "@/components/sample-entry";
import { Button } from "@/components/ui/button";
import { ApiError, DEMO_ORG, api } from "@/lib/api";
import { safeNextPath } from "@/lib/return-path";
import { first, type Search } from "@/lib/search";
import { readSessionToken } from "@/lib/session-cookie";
import { openOrgHref } from "@/lib/setup";
import { brandName } from "@/lib/theme";

import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Sign in" };

/**
 * The development form renders in development/test. The operator form renders when
 * production has an operator secret. Google renders when it is enabled. A valid session
 * skips the page; a stale cookie shows it.
 */
export default async function SignInPage({
  searchParams,
}: {
  searchParams?: Promise<Search>;
} = {}) {
  const next = safeNextPath(first((await searchParams)?.next));
  const error = first((await searchParams)?.error);
  if ((await readSessionToken()) !== null) {
    let signedIn = true;
    try {
      await api.session();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) signedIn = false;
      else throw error;
    }
    if (signedIn) redirect(next);
  }
  const [demo, googleResult] = await Promise.allSettled([api.org(DEMO_ORG), api.googleAuth()]);
  const sample =
    demo.status === "fulfilled" && demo.value.is_demo
      ? { href: openOrgHref(demo.value.slug), name: demo.value.name }
      : null;
  const google =
    googleResult.status === "fulfilled"
      ? googleResult.value
      : { enabled: false, dev_sign_in_enabled: false, operator_sign_in_enabled: false };
  const googleHref =
    next === "/"
      ? "/api/auth/google/start"
      : `/api/auth/google/start?next=${encodeURIComponent(next)}`;
  const errorMessage =
    error === "denied"
      ? "Google sign-in was cancelled."
      : error
        ? "Google sign-in could not be completed. Start again."
        : null;
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-xl space-y-6 px-4 py-10 sm:py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Sign in to {brandName()}
        </h1>
        <p className="text-sm text-muted-foreground">
          Who spent what on AI, by provider, key and person, with numbers that match the invoice.
        </p>
      </header>
      {errorMessage ? (
        <p role="alert" className="text-sm text-critical">
          {errorMessage}
        </p>
      ) : null}
      {google.enabled ? (
        <Button asChild size="lg">
          <Link href={googleHref}>Continue with Google</Link>
        </Button>
      ) : null}
      {google.dev_sign_in_enabled ? (
        <SignInForm next={next === "/" ? undefined : next} />
      ) : google.operator_sign_in_enabled ? (
        <SignInForm operator next={next === "/" ? undefined : next} />
      ) : google.enabled ? null : (
        <p className="text-sm text-muted-foreground">
          No sign-in method is configured. Set the deployment administrator e-mail and a secret of
          at least 24 characters, or configure Google sign-in. The steps are in{" "}
          <span className="font-medium">docs/operations/install.md</span>.
        </p>
      )}
      {sample ? (
        <SampleEntry
          href={sample.href}
          title="No account yet?"
          description={`${sample.name} is a fictional company with thirteen months of synthetic spend across Anthropic, OpenAI, OpenRouter and Cursor. Open it without signing in; nothing there can be changed.`}
        />
      ) : null}
    </main>
  );
}
