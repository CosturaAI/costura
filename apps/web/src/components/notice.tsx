import { AlertTriangle } from "lucide-react";

import { WRITES_DISABLED_MESSAGE } from "@/lib/action-errors";

/** Warning band above a page's forms (writes refused, secret key missing). */
export function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="note"
      className="flex gap-3 rounded-lg border border-severity-warning/30 bg-severity-warning-bg px-4 py-3 text-sm text-secondary-foreground"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-severity-warning" aria-hidden />
      <p>{children}</p>
    </div>
  );
}

/** The sentence every write form shows when the API answers `writes_enabled: false`. */
export function WritesDisabledNotice() {
  return <Notice>{WRITES_DISABLED_MESSAGE}</Notice>;
}

/** The sentence for an instance without key storage (`secret_ready: false`): no key can be
 * saved, so the connect forms are not shown. */
export function KeyStorageNotice() {
  return (
    <Notice>
      Key storage is not configured on this instance, so a key cannot be saved yet. Ask whoever runs
      Costura to finish the server setup.
    </Notice>
  );
}
