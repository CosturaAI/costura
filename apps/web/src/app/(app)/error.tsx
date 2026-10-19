"use client";

import { ApiDown } from "@/components/api-down";

export default function ScopeError({ error, reset }: { error: Error; reset: () => void }) {
  return <ApiDown error={error} reset={reset} />;
}
