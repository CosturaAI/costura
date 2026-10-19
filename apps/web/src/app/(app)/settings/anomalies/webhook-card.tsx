"use client";

import { useActionState } from "react";

import { CardHeading } from "@/components/card-heading";
import { CopyButton } from "@/components/copy-button";
import { StatePanel } from "@/components/empty-state";
import { ConfirmSubmit, Feedback, FieldError, invalid } from "@/components/form-feedback";
import { StatusBadge } from "@/components/status-badge";
import { SubmitButton } from "@/components/submit-button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { idleAction, idleWebhook } from "@/lib/action-errors";
import type { Webhook, WebhookDelivery } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { SIGNAL_KIND_LABELS } from "@/lib/signals";
import type { Tone } from "@/lib/ui-types";

import {
  removeWebhookAction,
  saveWebhookAction,
  setDigestAction,
  testWebhookAction,
} from "../webhook-actions";
import { resendDeliveryAction } from "./resend-action";

const STATUS_TONES: Record<WebhookDelivery["status"], Tone> = {
  sent: "success",
  pending: "info",
  failed: "critical",
  skipped: "neutral",
};

/**
 * Where this organization's signals are posted: a Slack-compatible incoming webhook. The
 * URL is write-only (the page shows its host), the signing secret appears once after a save,
 * and the newest deliveries show what was sent, retried or given up. Owners save, test,
 * remove and resend one delivery; everyone else reads.
 */
export function WebhookCard({
  webhook,
  canManage,
}: {
  webhook: Webhook | null;
  canManage: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardHeading>Slack webhook</CardHeading>
        <CardDescription>
          Each new anomaly, budget alert and key gap is posted once to a Slack-compatible incoming
          webhook, with its sentence, the money at risk, the owner and a link. Signals open when the
          webhook is saved are not sent.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {webhook === null ? (
          <p className="text-sm text-severity-critical">
            Could not load the webhook; reload to retry.
          </p>
        ) : !webhook.egress_enabled ? (
          <p className="text-sm text-secondary-foreground">
            Outbound webhooks are off on this stack. The operator turns them on by listing the
            allowed hosts in <code className="font-mono text-xs">COSTURA_WEBHOOK_HOSTS</code>.
          </p>
        ) : (
          <>
            <Destination webhook={webhook} canManage={canManage} />
            {canManage && webhook.configured ? <DigestForm webhook={webhook} /> : null}
            {canManage ? <SaveForm webhook={webhook} /> : null}
            {webhook.configured ? (
              <Deliveries deliveries={webhook.deliveries} canManage={canManage} />
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Destination({ webhook, canManage }: { webhook: Webhook; canManage: boolean }) {
  const [tested, test, testing] = useActionState(testWebhookAction, idleAction);
  const [removed, remove, removing] = useActionState(removeWebhookAction, idleAction);
  if (!webhook.configured) {
    return (
      <p className="text-sm text-secondary-foreground">
        No webhook saved. Allowed hosts: {webhook.allowed_hosts.join(", ")}.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-foreground">
        Posting to <span className="font-mono">{webhook.host}</span> since{" "}
        {formatDateTime(webhook.created_at)}.
      </p>
      {webhook.host_blocked ? (
        <p className="text-sm text-severity-critical">
          {webhook.host} is no longer in COSTURA_WEBHOOK_HOSTS; nothing is sent until it is listed
          again or another URL is saved.
        </p>
      ) : null}
      {canManage ? (
        <div className="flex flex-wrap items-center gap-2">
          <form action={test}>
            <SubmitButton size="sm" variant="outline" pending={testing}>
              {testing ? "Sending..." : "Send a test message"}
            </SubmitButton>
          </form>
          <form id="remove-webhook" action={remove}>
            <ConfirmSubmit
              formId="remove-webhook"
              title="Remove the webhook?"
              description="Nothing is posted until a URL is saved again, and the delivery history is deleted."
              confirmLabel="Remove"
              variant="ghost"
              pending={removing}
            >
              {removing ? "Removing..." : "Remove"}
            </ConfirmSubmit>
          </form>
        </div>
      ) : null}
      <Feedback state={tested} className="text-xs" />
      <Feedback state={removed} className="text-xs" />
    </div>
  );
}

function DigestForm({ webhook }: { webhook: Webhook }) {
  const [state, action, pending] = useActionState(setDigestAction, idleAction);
  return (
    <form action={action} className="flex flex-wrap items-center gap-2 text-sm">
      <label htmlFor="webhook-digest" className="text-foreground">
        Digest
      </label>
      <NativeSelect
        id="webhook-digest"
        name="digest"
        defaultValue={webhook.digest}
        className="w-44"
      >
        <option value="off">Off</option>
        <option value="weekly">Weekly, on Mondays</option>
        <option value="monthly">Monthly, on the 2nd</option>
      </NativeSelect>
      <SubmitButton size="sm" variant="outline" pending={pending}>
        {pending ? "Saving..." : "Save"}
      </SubmitButton>
      <span className="w-full text-xs text-muted-foreground">
        The month so far, its projection and what needs a person, posted on a schedule.
      </span>
      <Feedback state={state} className="w-full text-xs" />
    </form>
  );
}

function SaveForm({ webhook }: { webhook: Webhook }) {
  const [state, action, pending] = useActionState(saveWebhookAction, idleWebhook);
  return (
    <form action={action} className="space-y-2">
      <label htmlFor="webhook-url" className="block text-sm font-medium text-foreground">
        {webhook.configured ? "Replace the webhook URL" : "Webhook URL"}
      </label>
      <div className="flex flex-wrap gap-2">
        <Input
          id="webhook-url"
          name="url"
          type="url"
          autoComplete="off"
          placeholder="https://hooks.slack.com/services/..."
          className="min-w-0 flex-1"
          aria-invalid={invalid(state, "url")}
          aria-describedby="webhook-url-error"
        />
        <SubmitButton pending={pending}>{pending ? "Saving..." : "Save"}</SubmitButton>
      </div>
      <FieldError state={state} field="url" id="webhook-url-error" />
      {state.ok && state.secret ? (
        <div className="space-y-2 rounded-lg border border-severity-success/30 bg-severity-success-bg p-3">
          <p className="text-sm text-foreground">{state.message}</p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-card px-2 py-1 font-mono text-xs">
              {state.secret}
            </code>
            <CopyButton value={state.secret} label="Copy the signing secret" />
          </div>
          <p className="text-xs text-muted-foreground">
            The signing secret is shown once. A receiver other than Slack checks X-Costura-Signature
            with it; saving again issues a new one.
          </p>
        </div>
      ) : state.field === "url" ? null : (
        <Feedback state={state} />
      )}
    </form>
  );
}

function signalLabel(d: WebhookDelivery): string {
  return SIGNAL_KIND_LABELS[d.kind as keyof typeof SIGNAL_KIND_LABELS] ?? d.kind;
}

/**
 * The 20 newest outcomes, skipped ones left out: the signal, the status with the last error
 * and the attempt count, and when it was sent or recorded. An owner resends one row; the API
 * renders the signal again as it stands now, so a signal that closed since answers 422.
 */
function Deliveries({
  deliveries,
  canManage,
}: {
  deliveries: WebhookDelivery[];
  canManage: boolean;
}) {
  if (deliveries.length === 0) {
    return (
      <StatePanel
        title="Nothing posted yet"
        message="The next anomaly, budget alert or key gap is listed here with its outcome."
      />
    );
  }
  return (
    <div className="space-y-1">
      <p id="webhook-deliveries-heading" className="text-sm font-medium text-foreground">
        Recent deliveries
      </p>
      <Table aria-labelledby="webhook-deliveries-heading" className="text-sm">
        <TableHeader className="text-xs text-muted-foreground">
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-8 px-0 text-muted-foreground">Signal</TableHead>
            <TableHead className="h-8 text-muted-foreground">Status</TableHead>
            <TableHead className="h-8 text-muted-foreground">When</TableHead>
            {canManage ? (
              <TableHead className="h-8 text-right text-muted-foreground">
                <span className="sr-only">Actions</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {deliveries.map((d) => (
            <DeliveryRow key={d.id} delivery={d} canManage={canManage} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function DeliveryRow({
  delivery: d,
  canManage,
}: {
  delivery: WebhookDelivery;
  canManage: boolean;
}) {
  const [state, action, pending] = useActionState(resendDeliveryAction, idleAction);
  return (
    <TableRow>
      <TableCell className="px-0 py-1.5">
        {signalLabel(d)} <span className="text-xs text-muted-foreground">{d.provider}</span>
      </TableCell>
      <TableCell className="py-1.5">
        <StatusBadge tone={STATUS_TONES[d.status]}>{d.status}</StatusBadge>{" "}
        {d.last_error ? (
          <span className="text-xs text-muted-foreground">
            {d.last_error}, {d.attempts} {d.attempts === 1 ? "attempt" : "attempts"}
          </span>
        ) : null}
      </TableCell>
      <TableCell className="py-1.5 text-xs text-muted-foreground">
        {formatDateTime(d.sent_at ?? d.created_at)}
      </TableCell>
      {canManage ? (
        <TableCell className="py-1.5 text-right whitespace-normal">
          <form action={action} className="inline-flex flex-col items-end gap-1">
            <input type="hidden" name="delivery_id" value={d.id} />
            <SubmitButton
              size="xs"
              variant="outline"
              pending={pending}
              aria-label={`Resend ${signalLabel(d)} ${d.provider}`}
            >
              {pending ? "Resending..." : "Resend"}
            </SubmitButton>
            <Feedback state={state} className="text-xs" />
          </form>
        </TableCell>
      ) : null}
    </TableRow>
  );
}
