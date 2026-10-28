"use client";

import { useActionState, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { CardHeading } from "@/components/card-heading";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { slugify } from "@/lib/org-name";

import { createOrgAction, type NewOrgState } from "./actions";

const idleNewOrg: NewOrgState = { ok: false, message: null, suggestion: null };

/**
 * Name with the organization ID derived live (`slugify`) until Edit turns the ID into its own
 * field. Controlled inputs, because React resets a form's fields once its action settles, and
 * a refused creation must keep what was typed.
 */
export function NewOrgForm({ suggestedName }: { suggestedName: string }) {
  const [state, action, pending] = useActionState(createOrgAction, idleNewOrg);
  const [name, setName] = useState(suggestedName);
  const [customSlug, setCustomSlug] = useState<string | null>(null);
  const slug = customSlug ?? slugify(name);
  const editing = customSlug !== null;

  return (
    <Card>
      <CardHeader>
        <CardHeading>New organization</CardHeading>
        <CardDescription>
          The organization ID is part of every link to it (/o/ID) and cannot change later.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={action} className="space-y-4">
          <div className="space-y-1">
            <label htmlFor="org-name" className="text-sm font-medium text-foreground">
              Name
            </label>
            <Input
              id="org-name"
              name="name"
              type="text"
              autoComplete="organization"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-invalid={invalid(state, "name") || undefined}
              aria-describedby={invalid(state, "name") ? "org-name-error" : undefined}
            />
            <FieldError state={state} field="name" id="org-name-error" />
          </div>

          <div className="space-y-1">
            {editing ? (
              <>
                <label htmlFor="org-slug" className="text-sm font-medium text-foreground">
                  Organization ID
                </label>
                <div className="flex items-center gap-1">
                  <span className="font-mono text-sm text-muted-foreground">/o/</span>
                  <Input
                    id="org-slug"
                    name="slug"
                    type="text"
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                    value={slug}
                    onChange={(event) => setCustomSlug(event.target.value)}
                    aria-invalid={invalid(state, "slug") || undefined}
                    aria-describedby={invalid(state, "slug") ? "org-slug-error" : undefined}
                  />
                </div>
              </>
            ) : (
              <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span>
                  Organization ID:{" "}
                  <span className="font-mono text-foreground">{slug || "..."}</span>, opened at{" "}
                  <span className="font-mono text-foreground">/o/{slug || "..."}</span>
                </span>
                <button
                  type="button"
                  onClick={() => setCustomSlug(slug)}
                  className="font-medium text-primary hover:underline"
                >
                  Edit
                </button>
                <input type="hidden" name="slug" value={slug} />
              </p>
            )}
            <FieldError state={state} field="slug" id="org-slug-error" />
            {state.suggestion ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setCustomSlug(state.suggestion)}
              >
                Use {state.suggestion}
              </Button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <SubmitButton size="lg" pending={pending}>
              {pending ? "Creating..." : "Create organization"}
            </SubmitButton>
            <Feedback state={state} />
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
