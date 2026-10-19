"use client";

import { useRouter } from "next/navigation";
import { startTransition } from "react";

import { CopyDetails, type ErrorDetails } from "@/components/copy-details";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-error";

type BoundaryError = Error & { digest?: string };

const UNREACHABLE = /fetch failed|ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND/;

function describe(error: BoundaryError): { title: string; message: string } {
  const limited =
    error instanceof ApiError ? error.status === 429 : error.message.startsWith("429 ");
  if (limited) {
    return {
      title: "Sample data is temporarily busy",
      message: "This browser has reached the sample data request limit. Wait a minute, then retry.",
    };
  }
  const unreachable =
    error instanceof ApiError ? error.status >= 500 : UNREACHABLE.test(error.message);
  if (unreachable) {
    return {
      title: "Costura did not answer",
      message:
        "The data service is not reachable right now. Retry in a moment; if this keeps happening, tell whoever runs this Costura instance.",
    };
  }
  return {
    title: "This page could not load",
    message:
      "The data service may be unreachable, or the page hit an error. Retry in a moment; if this keeps happening, tell whoever runs this Costura instance and include the reference under Technical details.",
  };
}

/** What "Copy details" writes: the API's route, status and code when the API refused, the
 * Next.js digest when the server render failed. */
function details(error: BoundaryError): ErrorDetails {
  const api = error instanceof ApiError ? error : null;
  return {
    route: api?.path ?? null,
    status: api?.status ?? null,
    code: api?.code ?? null,
    message: api?.detail ?? error.message,
    digest: error.digest ?? null,
  };
}

/** Body of the error boundaries: what failed, a Retry that refetches, and the reference folded. */
export function ApiDown({ error, reset }: { error: BoundaryError; reset: () => void }) {
  const router = useRouter();
  const { title, message } = describe(error);
  const reference = error.digest ? `Reference ${error.digest}` : error.message;
  const code = error instanceof ApiError ? error.code : null;

  return (
    <div className="mx-auto max-w-2xl p-8">
      <div className="rounded-lg border border-severity-critical/30 bg-severity-critical-bg p-6">
        <h1 className="text-base font-semibold text-severity-critical">{title}</h1>
        <p className="mt-2 text-sm text-secondary-foreground">{message}</p>
        <details className="mt-3 text-xs text-secondary-foreground">
          <summary className="cursor-pointer">Technical details</summary>
          <pre className="mt-2 overflow-x-auto rounded bg-card p-3 font-mono">{reference}</pre>
          {code ? (
            <p className="mt-2">
              Error code <code className="font-mono">{code}</code>
            </p>
          ) : null}
        </details>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              startTransition(() => {
                router.refresh();
                reset();
              })
            }
          >
            Retry
          </Button>
          <CopyDetails details={details(error)} />
        </div>
      </div>
    </div>
  );
}
