/** Webhook fixtures: delivery off on the stack, and a saved destination with history. */

import type { Webhook } from "@/lib/api";

export const webhookOff: Webhook = {
  egress_enabled: false,
  allowed_hosts: [],
  configured: false,
  host: null,
  created_at: null,
  host_blocked: false,
  digest: "off",
  deliveries: [],
};

export const webhookSaved: Webhook = {
  egress_enabled: true,
  allowed_hosts: ["hooks.slack.com"],
  configured: true,
  host: "hooks.slack.com",
  created_at: "2026-08-10T09:00:00Z",
  host_blocked: false,
  digest: "weekly",
  deliveries: [
    {
      id: 11,
      kind: "anomaly",
      provider: "anthropic",
      reference: "8",
      status: "sent",
      attempts: 1,
      last_error: null,
      created_at: "2026-08-12T09:00:00Z",
      sent_at: "2026-08-12T09:01:00Z",
      next_attempt_at: "2026-08-12T09:00:00Z",
    },
    {
      id: 12,
      kind: "no_owner",
      provider: "openrouter",
      reference: "orkey_hash_1",
      status: "pending",
      attempts: 2,
      last_error: "HTTP 503",
      created_at: "2026-08-12T10:00:00Z",
      sent_at: null,
      next_attempt_at: "2026-08-12T10:35:00Z",
    },
  ],
};
