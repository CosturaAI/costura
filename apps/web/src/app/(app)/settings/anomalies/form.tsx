"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { NativeSelect } from "@/components/ui/native-select";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";
import type { AnomalySettings } from "@/lib/api";

import { saveAnomalySettingsAction } from "../organization-actions";

export function AnomalySettingsForm({
  settings,
  canManage,
}: {
  settings: AnomalySettings;
  canManage: boolean;
}) {
  const [state, action, pending] = useActionState(saveAnomalySettingsAction, idleAction);
  return (
    <form action={action} className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="anomaly-sensitivity" className="text-sm font-medium text-foreground">
          Sensitivity
        </label>
        <NativeSelect
          id="anomaly-sensitivity"
          name="sensitivity"
          defaultValue={settings.sensitivity}
          disabled={!canManage || pending}
          className="mt-1 w-full"
          aria-invalid={invalid(state, "sensitivity") || undefined}
        >
          <option value="low">Low</option>
          <option value="normal">Normal</option>
          <option value="high">High</option>
        </NativeSelect>
        <FieldError state={state} field="sensitivity" id="anomaly-sensitivity-error" />
      </div>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          name="detect_drops"
          defaultChecked={settings.detect_drops}
          disabled={!canManage || pending}
        />
        Detect spend drops
      </label>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          name="detect_new_principals"
          defaultChecked={settings.detect_new_principals}
          disabled={!canManage || pending}
        />
        Detect new principals
      </label>
      <div className="space-y-1">
        <label htmlFor="anomaly-retention" className="text-sm font-medium text-foreground">
          Keep anomaly evidence (days)
        </label>
        <Input
          id="anomaly-retention"
          name="retention_days"
          type="number"
          min={30}
          max={365}
          defaultValue={settings.retention_days}
          disabled={!canManage || pending}
          aria-invalid={invalid(state, "retention_days") || undefined}
        />
        <FieldError state={state} field="retention_days" id="anomaly-retention-error" />
      </div>
      <div className="space-y-1">
        <label htmlFor="posture-idle" className="text-sm font-medium text-foreground">
          A key is idle after (days without use)
        </label>
        <Input
          id="posture-idle"
          name="idle_days"
          type="number"
          min={7}
          max={365}
          defaultValue={settings.idle_days}
          disabled={!canManage || pending}
          aria-invalid={invalid(state, "idle_days") || undefined}
          aria-describedby={invalid(state, "idle_days") ? "posture-idle-error" : undefined}
        />
        <FieldError state={state} field="idle_days" id="posture-idle-error" />
      </div>
      <div className="space-y-1">
        <label htmlFor="posture-new" className="text-sm font-medium text-foreground">
          A key is new for (days after creation)
        </label>
        <Input
          id="posture-new"
          name="new_key_days"
          type="number"
          min={1}
          max={90}
          defaultValue={settings.new_key_days}
          disabled={!canManage || pending}
          aria-invalid={invalid(state, "new_key_days") || undefined}
          aria-describedby={invalid(state, "new_key_days") ? "posture-new-error" : undefined}
        />
        <FieldError state={state} field="new_key_days" id="posture-new-error" />
      </div>
      {canManage ? (
        <SubmitButton pending={pending}>Save</SubmitButton>
      ) : (
        <p className="text-sm text-muted-foreground">Only an owner can change these.</p>
      )}
      <Feedback state={state} />
    </form>
  );
}
