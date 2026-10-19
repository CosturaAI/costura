/**
 * `FormData` to typed values through a zod schema, so every server action validates the same
 * way: a missing field reads as an empty string, values are trimmed, and the first failing
 * field becomes the form's message. Only the fields listed in `fields` are named back to the
 * form (they render a field-level error); hidden inputs fail with a sentence and no field.
 */

import { z } from "zod";

import type { ActionState } from "@/lib/action-errors";

/** Repeated names (checkbox groups) become arrays; a single value stays a string. */
function formObject(form: FormData): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const key of new Set(form.keys())) {
    const values = form.getAll(key).map((value) => (typeof value === "string" ? value : ""));
    out[key] = values.length > 1 ? values : (values[0] ?? "");
  }
  return out;
}

type Parsed<T> = { ok: true; data: T } | { ok: false; error: ActionState };

export function parseForm<S extends z.ZodType>(
  form: FormData,
  schema: S,
  fields: readonly string[] = [],
): Parsed<z.output<S>> {
  const result = schema.safeParse(formObject(form));
  if (result.success) return { ok: true, data: result.data };
  const issue = result.error.issues[0];
  const name = typeof issue!.path[0] === "string" ? issue!.path[0] : undefined;
  return {
    ok: false,
    error: {
      ok: false,
      message: issue!.message,
      ...(name && fields.includes(name) ? { field: name } : {}),
    },
  };
}

/** A trimmed string; absent reads as "". */
export const text = () => z.string().trim().catch("");

/** A positive whole number from a text input or hidden field. */
export const positiveId = (message: string) =>
  z.coerce.number({ error: message }).int(message).positive(message);

/** A calendar month, `YYYY-MM`. */
export const monthText = (message: string) =>
  z.string({ error: message }).regex(/^\d{4}-(0[1-9]|1[0-2])$/, message);

/** An e-mail address in the loose shape the API accepts. */
export const emailText = (message: string) =>
  z
    .string({ error: message })
    .trim()
    .refine((value) => value.includes("@"), message);

/** A checkbox: present and "on" (or "true") is true. */
export const checkbox = () =>
  z
    .string()
    .optional()
    .transform((value) => value === "on" || value === "true");
