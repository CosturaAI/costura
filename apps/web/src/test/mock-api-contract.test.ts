/**
 * The Playwright suites read a hand-written stand-in for the API (`e2e/mock-api.mjs`). This
 * test starts it and checks every answer the pages read against the response schemas of the
 * OpenAPI snapshot, so a field the API adds as required, renames or retypes fails here instead
 * of drifting silently between the mock and the real contract.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

type Schema = {
  $ref?: string;
  type?: string | string[];
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  anyOf?: Schema[];
  oneOf?: Schema[];
  allOf?: Schema[];
  additionalProperties?: Schema | boolean;
  enum?: unknown[];
  const?: unknown;
};
type OpenApi = {
  paths: Record<
    string,
    Record<
      string,
      { responses?: Record<string, { content?: Record<string, { schema?: Schema }> }> }
    >
  >;
  components: { schemas: Record<string, Schema> };
};

const ROOT = resolve(__dirname, "../..");
const openapi = JSON.parse(
  readFileSync(resolve(ROOT, "../api/tests/snapshots/openapi.json"), "utf8"),
) as OpenApi;
const PORT = 3291;
const BASE = `http://127.0.0.1:${PORT}`;

/** The reads the Playwright pages issue, with the org and provider the specs use. */
const READS = [
  "/api/v1/me",
  "/api/v1/orgs",
  "/api/v1/orgs/default",
  "/api/v1/orgs/default/providers",
  "/api/v1/orgs/default/members",
  "/api/v1/orgs/default/setup",
  "/api/v1/orgs/default/alerts",
  "/api/v1/orgs/default/anomaly-settings",
  "/api/v1/orgs/default/webhook",
  "/api/v1/orgs/default/providers/anthropic/months",
  "/api/v1/orgs/default/providers/anthropic/connection",
  "/api/v1/orgs/default/providers/anthropic/runs",
  "/api/v1/orgs/default/providers/all/budgets",
  "/api/v1/orgs/default/providers/all/signals",
  "/api/v1/orgs/default/providers/all/anomalies/7",
  "/api/v1/orgs/default/providers/anthropic/months/2026-08/summary",
  "/api/v1/orgs/default/providers/anthropic/months/2026-08/usage?by=api_key",
  "/api/v1/orgs/default/providers/all/months/2026-08/anomalies",
  "/api/v1/orgs/default/providers/all/months/2026-08/budgets",
  "/api/v1/orgs/default/providers/anthropic/inventory/api-keys",
];

const templates = Object.keys(openapi.paths).map((template) => ({
  template,
  pattern: new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`),
}));

function resolveRef(schema: Schema): Schema {
  if (!schema.$ref) return schema;
  const name = schema.$ref.split("/").pop() as string;
  return resolveRef(openapi.components.schemas[name]!);
}

/** Every mismatch between `value` and `schema`, as JSON paths; empty when it conforms. */
function mismatches(value: unknown, raw: Schema, at = "$"): string[] {
  const schema = resolveRef(raw);
  const options = schema.anyOf ?? schema.oneOf;
  if (options) {
    const results = options.map((option) => mismatches(value, option, at));
    return results.some((r) => r.length === 0) ? [] : (results[0] ?? [`${at}: no variant`]);
  }
  if (schema.allOf) return schema.allOf.flatMap((part) => mismatches(value, part, at));
  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  if (value === null) return types.length === 0 || types.includes("null") ? [] : [`${at}: null`];
  if (schema.enum && !schema.enum.includes(value)) return [`${at}: ${String(value)} not in enum`];
  if (types.includes("array") || schema.items) {
    if (!Array.isArray(value)) return [`${at}: expected array`];
    return schema.items
      ? value.flatMap((item, i) => mismatches(item, schema.items!, `${at}[${i}]`))
      : [];
  }
  if (types.includes("object") || schema.properties) {
    if (typeof value !== "object" || Array.isArray(value)) return [`${at}: expected object`];
    const record = value as Record<string, unknown>;
    const missing = (schema.required ?? [])
      .filter((key) => !(key in record))
      .map((key) => `${at}.${key}: missing`);
    const nested = Object.entries(schema.properties ?? {}).flatMap(([key, child]) =>
      key in record ? mismatches(record[key], child, `${at}.${key}`) : [],
    );
    const extra =
      typeof schema.additionalProperties === "object"
        ? Object.entries(record)
            .filter(([key]) => !(key in (schema.properties ?? {})))
            .flatMap(([key, item]) =>
              mismatches(item, schema.additionalProperties as Schema, `${at}.${key}`),
            )
        : [];
    return [...missing, ...nested, ...extra];
  }
  const expected: Record<string, (v: unknown) => boolean> = {
    string: (v) => typeof v === "string",
    integer: (v) => Number.isInteger(v),
    number: (v) => typeof v === "number",
    boolean: (v) => typeof v === "boolean",
  };
  const checks = types.filter((type) => type in expected);
  if (checks.length > 0 && !checks.some((type) => expected[type]!(value))) {
    return [`${at}: expected ${checks.join("|")}, got ${typeof value}`];
  }
  return [];
}

let server: ChildProcess;

beforeAll(async () => {
  server = spawn(process.execPath, [resolve(ROOT, "e2e/mock-api.mjs")], {
    env: { ...process.env, MOCK_API_PORT: String(PORT) },
    stdio: "ignore",
  });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      if ((await fetch(`${BASE}/health`)).ok) return;
    } catch {
      // Not listening yet.
    }
    await new Promise((done) => setTimeout(done, 50));
  }
  throw new Error("the mock API did not start");
}, 15_000);

afterAll(() => {
  server?.kill();
});

describe("e2e mock API", () => {
  it.each(READS)("answers %s in the shape of the OpenAPI snapshot", async (read) => {
    const url = new URL(read, BASE);
    const match = templates.find(({ pattern }) => pattern.test(url.pathname));
    expect(match, `no OpenAPI route for ${url.pathname}`).toBeDefined();
    const schema =
      openapi.paths[match!.template]!.get?.responses?.["200"]?.content?.["application/json"]
        ?.schema;
    expect(schema, `no 200 JSON schema for ${match!.template}`).toBeDefined();
    const response = await fetch(url, { headers: { authorization: "Bearer e2e-session" } });
    expect(response.status).toBe(200);
    expect(mismatches(await response.json(), schema!)).toEqual([]);
  });
});

/** Path and required query values the mock's fixed data answers; every documented read is
 * instantiated with them, so a route the mock grows is checked without editing this file. */
const SAMPLE: Record<string, string> = {
  org: "default",
  provider: "anthropic",
  month: "2026-08",
  account_id: "1",
  anomaly_id: "7",
  kind: "api_key",
  entity_id: "key-platform-billing-very-long-identifier",
  external_id: "key-platform-billing-very-long-identifier",
  email: "ana@example.com",
  q: "platform",
  since: "2026-08-01",
  until: "2026-08-31",
  start: "2026-08-01",
  end: "2026-08-31",
};
const PROVIDER_OVERRIDES: Record<string, string> = {
  "/api/v1/orgs/{org}/providers/{provider}/anomalies/{anomaly_id}": "all",
};
/** Documented reads the mock answered when this floor was set; a route it stops answering fails. */
const MOCK_READ_FLOOR = 30;
const NOT_FOR_THE_MOCK = new Set(["/health", "/live", "/ready"]);

type Operation = { parameters?: { name: string; in: string; required?: boolean }[] };

function sampleUrl(template: string): string {
  const operation = (openapi.paths[template]!.get ?? {}) as Operation;
  const path = template.replace(/\{([^}]+)\}/g, (_, name: string) =>
    name === "provider" && PROVIDER_OVERRIDES[template]
      ? PROVIDER_OVERRIDES[template]
      : encodeURIComponent(SAMPLE[name] ?? name),
  );
  const query = new URLSearchParams();
  for (const parameter of operation.parameters ?? []) {
    if (parameter.in === "query" && parameter.required) {
      query.set(parameter.name, SAMPLE[parameter.name] ?? "x");
    }
  }
  const search = query.toString();
  return search ? `${path}?${search}` : path;
}

const DOCUMENTED_READS = Object.keys(openapi.paths)
  .filter((template) => openapi.paths[template]!.get && !NOT_FOR_THE_MOCK.has(template))
  .sort();

describe("every documented read the mock answers", () => {
  const answered: string[] = [];

  it.each(DOCUMENTED_READS)("%s conforms when the mock answers it", async (template) => {
    const response = await fetch(new URL(sampleUrl(template), BASE), {
      headers: { authorization: "Bearer e2e-session" },
    });
    if (response.status !== 200 || !response.headers.get("content-type")?.includes("json")) {
      return;
    }
    answered.push(template);
    const schema =
      openapi.paths[template]!.get?.responses?.["200"]?.content?.["application/json"]?.schema;
    expect(schema, `no 200 JSON schema for ${template}`).toBeDefined();
    expect(mismatches(await response.json(), schema!)).toEqual([]);
  });

  it("answers at least the reads the pages issue", () => {
    const pages = READS.map((read) => {
      const pathname = new URL(read, BASE).pathname;
      return templates.find(({ pattern }) => pattern.test(pathname))!.template;
    });
    expect(answered.length).toBeGreaterThanOrEqual(Math.max(new Set(pages).size, MOCK_READ_FLOOR));
  });
});
