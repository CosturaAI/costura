/**
 * Typed fetch against the Costura API (`/api/v1`). Server-only: pages call these functions
 * during rendering, server actions call the write functions, and the browser never talks to
 * the API directly. Types mirror `apps/api/costura/api/schemas/`; money is a string already
 * rounded to cents. Each domain module owns its types and its slice of `api`.
 */

import { anomaliesApi } from "./anomalies";
import { budgetsApi } from "./budgets";
import { connectionsApi } from "./connections";
import { inventoryApi } from "./inventory";
import { organizationsApi } from "./organizations";
import { sessionApi } from "./session";
import { spendApi } from "./spend";
import { teamsApi } from "./teams";
import { webhooksApi } from "./webhooks";

export { ApiError } from "@/lib/api-error";

export * from "./anomalies";
export * from "./budgets";
export * from "./connections";
export * from "./inventory";
export * from "./organizations";
export * from "./session";
export * from "./spend";
export * from "./teams";
export * from "./webhooks";
export type { Period } from "./transport";

export const api = {
  ...sessionApi,
  ...organizationsApi,
  ...connectionsApi,
  ...spendApi,
  ...inventoryApi,
  ...anomaliesApi,
  ...budgetsApi,
  ...webhooksApi,
  ...teamsApi,
};
