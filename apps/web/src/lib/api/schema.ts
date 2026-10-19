/**
 * Names the web uses for the API's response shapes, taken from the generated OpenAPI types
 * so a schema change shows up as a type error instead of a silent drift.
 */

import type { components } from "./generated";

type Schemas = components["schemas"];

export type Schema<Name extends keyof Schemas> = Schemas[Name];
