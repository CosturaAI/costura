"use client";

import { useActionState, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { CardHeading } from "@/components/card-heading";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";

import { signInAction } from "./actions";

/**
 * E-mail plus an optional name, or the operator secret. The server action sets the cookie
 * and sends the browser to `next` when the page was reached from an invitation link,
 * otherwise to `/`. Controlled inputs, because React resets a form's fields once its
 * action settles.
 */
export function SignInForm({ next, operator = false }: { next?: string; operator?: boolean }) {
  const [state, action, pending] = useActionState(signInAction, idleAction);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  return (
    <Card>
      <CardHeader>
        <CardHeading>{operator ? "Deployment administrator" : "Development sign-in"}</CardHeading>
        <CardDescription>
          {operator
            ? "Enter the administrator e-mail and secret configured for this deployment. This is not a public sign-up."
            : "Enter any e-mail address to open a development session on this local loopback stack."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={action} className="space-y-4">
          {next ? <input type="hidden" name="next" value={next} /> : null}
          <div className="space-y-1">
            <label htmlFor="sign-in-email" className="text-sm font-medium text-foreground">
              E-mail
            </label>
            <Input
              id="sign-in-email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={invalid(state, "email") || undefined}
              aria-describedby={invalid(state, "email") ? "sign-in-email-error" : undefined}
            />
            <FieldError state={state} field="email" id="sign-in-email-error" />
          </div>
          {operator ? (
            <div className="space-y-1">
              <label htmlFor="sign-in-secret" className="text-sm font-medium text-foreground">
                Secret
              </label>
              <Input
                id="sign-in-secret"
                name="secret"
                type="password"
                autoComplete="current-password"
                required
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
              />
            </div>
          ) : (
            <div className="space-y-1">
              <label htmlFor="sign-in-name" className="text-sm font-medium text-foreground">
                Name <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="sign-in-name"
                name="name"
                type="text"
                autoComplete="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <SubmitButton size="lg" pending={pending}>
              {pending ? "Signing in..." : "Continue"}
            </SubmitButton>
            <Feedback state={state} />
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
