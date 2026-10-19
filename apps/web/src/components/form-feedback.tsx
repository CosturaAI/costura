"use client";

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
import { cn } from "@/lib/utils";

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
