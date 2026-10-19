"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { ConfirmSubmit, Feedback } from "@/components/form-feedback";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";
import type { AnomalyStatus } from "@/lib/api";

import { bulkStatusAction, setStatusAction } from "./actions";

/** The organization and the month come from the view cookie; the row's provider is posted. */
type Scope = { provider: string };

function ScopeInputs({ provider }: Scope) {
  return <input type="hidden" name="provider" value={provider} />;
}

/** Acknowledge submits at once; Ignore asks first because it hides the row from the default view. */
export function StatusForm({
  id,
  status,
  formIdPrefix = "anomaly",
  ...scope
}: Scope & { id: number; status: AnomalyStatus; formIdPrefix?: string }) {
  const [state, action, pending] = useActionState(setStatusAction, idleAction);
  const formId = `${formIdPrefix}-${id}`;
  return (
    <form id={formId} action={action} className="flex flex-wrap items-center gap-2">
      <ScopeInputs {...scope} />
      <input type="hidden" name="id" value={id} />
      {status === "open" ? (
        <>
          <label htmlFor={`${formId}-reason`} className="sr-only">
            Reason (optional)
          </label>
          <Input
            id={`${formId}-reason`}
            name="reason"
            maxLength={280}
            placeholder="Why (optional), e.g. expected: backfill"
            className="h-8 w-56 min-w-0 text-xs"
          />
          <SubmitButton name="status" value="acknowledged" size="sm" pending={pending}>
            Acknowledge
          </SubmitButton>
          <ConfirmSubmit
            formId={formId}
            title="Ignore this anomaly?"
            description="It leaves the open list and the chart markers. Reopen it later from the Ignored filter."
            confirmLabel="Ignore"
            submitName="status"
            submitValue="ignored"
            pending={pending}
          >
            Ignore
          </ConfirmSubmit>
        </>
      ) : (
        <SubmitButton name="status" value="open" size="sm" variant="outline" pending={pending}>
          Reopen
        </SubmitButton>
      )}
      <Feedback state={state} className="text-xs" />
    </form>
  );
}

/** Bar shown while rows are selected; posts every id with one status. */
export function BulkStatusBar({
  ids,
  onClear,
  ...scope
}: Scope & { ids: number[]; onClear: () => void }) {
  const [state, action, pending] = useActionState(bulkStatusAction, idleAction);
  const formId = "anomalies-bulk";
  return (
    <form
      id={formId}
      action={action}
      className="sticky top-14 z-10 flex flex-wrap items-center gap-3 rounded-lg border border-primary bg-accent px-4 py-2 text-sm"
      aria-label="Bulk actions"
    >
      <ScopeInputs {...scope} />
      {ids.map((id) => (
        <input key={id} type="hidden" name="ids" value={id} />
      ))}
      <span className="font-medium text-primary">{ids.length} selected</span>
      <SubmitButton name="status" value="acknowledged" size="sm" pending={pending}>
        Acknowledge
      </SubmitButton>
      <ConfirmSubmit
        formId={formId}
        title={`Ignore ${ids.length} anomal${ids.length === 1 ? "y" : "ies"}?`}
        description="They leave the open list and the chart markers. Reopen them later from the Ignored filter."
        confirmLabel="Ignore"
        submitName="status"
        submitValue="ignored"
        pending={pending}
      >
        Ignore
      </ConfirmSubmit>
      <Button type="button" variant="ghost" size="sm" onClick={onClear}>
        Clear selection
      </Button>
      <Feedback state={state} className="text-xs" />
    </form>
  );
}
