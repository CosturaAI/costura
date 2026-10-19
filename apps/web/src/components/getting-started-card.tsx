"use client";

import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { CardHeading } from "@/components/card-heading";
import { Feedback } from "@/components/form-feedback";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { idleAction, type ActionState } from "@/lib/action-errors";
import { GettingStartedItem } from "@/lib/setup";
import { cn } from "@/lib/utils";

/**
 * Checklist at the top of the overview until the organization dismisses it. The items and
 * their done state are computed by the page (`gettingStartedItems`); the dismiss action is
 * passed in because it lives next to the page.
 */
export function GettingStartedCard({
  items,
  canDismiss,
  dismiss,
}: {
  items: GettingStartedItem[];
  canDismiss: boolean;
  dismiss: (prev: ActionState, form: FormData) => Promise<ActionState>;
}) {
  const [state, action, pending] = useActionState(dismiss, idleAction);
  const remaining = items.filter((item) => !item.done).length;
  if (state.ok) return null;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>Getting started</CardHeading>
          <CardDescription>
            {remaining === 0
              ? "Everything on this list is done."
              : `${remaining} of ${items.length} left; each takes a minute.`}
          </CardDescription>
        </div>
        {canDismiss ? (
          <form action={action} className="flex items-center gap-2">
            <SubmitButton variant="ghost" size="sm" pending={pending}>
              {pending ? "Dismissing..." : "Dismiss"}
            </SubmitButton>
            <Feedback state={state} />
          </form>
        ) : null}
      </CardHeader>
      <CardContent>
        <ul className="space-y-2" aria-label="Getting started">
          {items.map((item) => (
            <li key={item.id} className="flex items-center gap-2 text-sm">
              {item.done ? (
                <Check className="h-4 w-4 text-severity-success" aria-label="done" role="img" />
              ) : (
                <Circle className="h-4 w-4 text-faint-foreground" aria-label="to do" role="img" />
              )}
              <Link
                href={item.href}
                className={cn(
                  "hover:underline",
                  item.done ? "text-muted-foreground line-through" : "text-primary",
                )}
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
