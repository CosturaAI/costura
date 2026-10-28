"use client";

import { createContext, useCallback, useContext, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { ActionState } from "@/lib/action-errors";
import { useOnSuccess } from "@/lib/use-on-success";
import { cn } from "@/lib/utils";

/** The organization the page rendered, posted so the action can refuse when another tab has
 * switched the view to a different one (`requireActiveOrg(form)`). */
export function OrgField({ org }: { org: string }) {
  return <input type="hidden" name="org" value={org} />;
}

/** Outcome line of a server action; field-level messages render next to their input instead. */
export function Feedback({ state, className }: { state: ActionState; className?: string }) {
  if (!state.message || (state.field && !state.ok)) return null;
  return (
    <p
      role="status"
      className={cn(
        "text-sm",
        state.ok ? "text-severity-success" : "text-severity-critical",
        className,
      )}
    >
      {state.message}
    </p>
  );
}

const RemovalContext = createContext<((message: string) => void) | null>(null);

/**
 * The success line of a removal, kept outside the row it removed: the row and its form leave
 * the page once the action refreshes it, so the line renders here, after `children`, and focus
 * moves to the heading `headingId` (which needs `tabIndex={-1}`) instead of falling to the body.
 */
export function RemovalFeedback({
  headingId,
  children,
  className,
  statusFirst = false,
}: {
  headingId: string;
  children: React.ReactNode;
  className?: string;
  /** The line goes before `children`, next to the heading, when what is removed is a whole
   * section below it. */
  statusFirst?: boolean;
}) {
  const [message, setMessage] = useState<string | null>(null);
  const report = useCallback(
    (next: string) => {
      setMessage(next);
      document.getElementById(headingId)?.focus();
    },
    [headingId],
  );
  const status = (
    <p role="status" className={cn("text-sm text-severity-success empty:hidden", className)}>
      {message}
    </p>
  );
  return (
    <RemovalContext.Provider value={report}>
      {statusFirst ? status : null}
      {children}
      {statusFirst ? null : status}
    </RemovalContext.Provider>
  );
}

/**
 * For a form that removes its own row: a success goes to the enclosing `RemovalFeedback`, and
 * the state returned keeps only a refusal for the form's own `Feedback`. Outside a
 * `RemovalFeedback` the state is returned as it is.
 */
export function useRemovalFeedback(state: ActionState): ActionState {
  const report = useContext(RemovalContext);
  const onSuccess = useCallback(() => report?.(state.message ?? ""), [report, state]);
  useOnSuccess(state, report ? onSuccess : undefined);
  return report && state.ok ? { ok: false, message: null } : state;
}

/** Message under the input named by `state.field`; the input gets `aria-invalid` from `invalid()`. */
export function FieldError({
  state,
  field,
  id,
}: {
  state: ActionState;
  field: string;
  id: string;
}) {
  if (state.ok || state.field !== field || !state.message) return null;
  return (
    <p id={id} role="alert" className="mt-1 text-xs text-severity-critical">
      {state.message}
    </p>
  );
}

export function invalid(state: ActionState, field: string): boolean {
  return !state.ok && state.field === field && Boolean(state.message);
}

/**
 * Submit button that asks first. Used for the destructive actions (disconnect, remove a
 * budget, ignore anomalies). The dialog renders in a portal outside the form, so the confirm
 * button names the form by id.
 */
export function ConfirmSubmit({
  formId,
  title,
  description,
  confirmLabel,
  submitName,
  submitValue,
  children,
  disabled,
  pending = false,
  variant = "outline",
  size = "sm",
  onClick,
  className,
  ...props
}: {
  formId: string;
  title: string;
  description: string;
  confirmLabel: string;
  /** Name and value the confirm button submits with, for forms whose action reads the submitter. */
  submitName?: string;
  submitValue?: string;
  children: React.ReactNode;
  disabled?: boolean;
  /** While the form posts: the trigger stays focusable (`aria-disabled`) and opens nothing. */
  pending?: boolean;
  variant?: React.ComponentProps<typeof Button>["variant"];
  size?: React.ComponentProps<typeof Button>["size"];
} & Omit<React.ComponentProps<"button">, "type">) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          type="button"
          variant={variant}
          size={size}
          disabled={disabled}
          aria-disabled={pending || undefined}
          className={cn("aria-disabled:cursor-not-allowed aria-disabled:opacity-60", className)}
          onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
            if (pending) {
              event.preventDefault();
              return;
            }
            onClick?.(event);
          }}
          {...props}
        >
          {children}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction type="submit" form={formId} name={submitName} value={submitValue}>
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
