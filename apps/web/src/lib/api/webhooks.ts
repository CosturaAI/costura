import type { Schema } from "./schema";
import { get, send } from "./transport";

/** `GET /orgs/{org}/webhook`: whether the stack allows outbound posts, the saved host (never
 * the URL) and the newest deliveries. */
export type Webhook = Schema<"WebhookOut">;
export type WebhookDelivery = Schema<"WebhookDeliveryOut">;
/** The save answer: the signing secret appears here and nowhere else. */
type WebhookSaved = Schema<"WebhookSavedOut">;
type WebhookTest = Schema<"WebhookTestOut">;

const path = (org: string) => `/orgs/${encodeURIComponent(org)}/webhook`;

export const webhooksApi = {
  webhook: (org: string) => get<Webhook>(path(org)),
  saveWebhook: (org: string, url: string) => send<WebhookSaved>("PUT", path(org), { url }),
  removeWebhook: (org: string) => send<Webhook>("DELETE", path(org)),
  testWebhook: (org: string) => send<WebhookTest>("POST", `${path(org)}/test`),
  resendWebhookDelivery: (org: string, deliveryId: number) =>
    send<WebhookTest>("POST", `${path(org)}/deliveries/${deliveryId}/resend`),
  setWebhookDigest: (org: string, digest: Webhook["digest"]) =>
    send<Webhook>("PUT", `${path(org)}/digest`, { digest }),
};
