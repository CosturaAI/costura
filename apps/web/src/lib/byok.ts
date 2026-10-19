import type { UsageRow } from "@/lib/api";

/** Copy shared by the BYOK column header and the entity KPI. */
export const BYOK_NOTE =
  "Routed through OpenRouter on your own provider keys; billed by the providers.";

/** True for an amount that is a number other than zero; "0.00" and null are not BYOK. */
export function isByokAmount(amount: string | null | undefined): boolean {
  if (amount === null || amount === undefined || amount === "") return false;
  const parsed = Number.parseFloat(amount);
  return !Number.isNaN(parsed) && parsed !== 0;
}

/** Whether a table needs the BYOK column: at least one row with a non-zero amount. */
export function hasByok(rows: UsageRow[]): boolean {
  return rows.some((row) => isByokAmount(row.byok_amount));
}
