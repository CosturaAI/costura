"use client";

import { ApiDown } from "@/components/api-down";

/** Root boundary: `/` asks the API for the setup state before it can redirect anywhere. */
export default function RootError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <main id="main" tabIndex={-1} className="min-h-dvh">
      <ApiDown error={error} reset={reset} />
    </main>
  );
}
