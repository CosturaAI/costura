import { describe, expect, it } from "vitest";

import { entityQueryHint, resourceDetail, resourceHref, resourceValue } from "./resource-search";

const person = {
  kind: "person" as const,
  id: "ada@example.com",
  label: "Ada@example.com",
  providers: ["anthropic", "openai"],
  provider_account_id: 7,
  provider_account_label: "Research",
  hint: null,
};

describe("resource search addresses", () => {
  it("keeps a person on the e-mail page without pinning a provider", () => {
    expect(resourceHref(person)).toBe("/people/ada%40example.com");
    expect(resourceHref({ ...person, providers: ["anthropic"] })).toBe("/people/ada%40example.com");
  });

  it("names the provider and account for one console, and only the provider when the account is unknown", () => {
    expect(
      resourceHref({
        kind: "api_key",
        id: "key/1",
        label: "Key",
        providers: ["anthropic"],
        provider_account_id: 4,
        provider_account_label: "Research",
        hint: "sk-ant-...%_",
      }),
    ).toBe("/keys/key%2F1?provider=anthropic&provider_account=4");
    expect(
      resourceHref({
        kind: "service",
        id: "svc_bot",
        label: "bot",
        providers: ["openai"],
        provider_account_id: null,
        hint: null,
      }),
    ).toBe("/accounts/svc_bot?provider=openai");
    expect(
      resourceHref({
        kind: "workspace",
        id: "ws_1",
        label: "Lab",
        providers: ["openrouter"],
        provider_account_id: 2,
        provider_account_label: "OpenRouter",
      }),
    ).toBe("/workspaces/ws_1?provider=openrouter&provider_account=2");
  });

  it("does not pin a provider when a person-like row lists more than one", () => {
    expect(
      resourceHref({
        kind: "workspace",
        id: "ws_1",
        label: "Lab",
        providers: ["anthropic", "openai"],
        provider_account_id: 2,
      }),
    ).toBe("/workspaces/ws_1");
  });

  it("builds a stable value and a safe detail line", () => {
    expect(resourceValue(person)).toBe("person:anthropic,openai:7:ada@example.com");
    expect(resourceDetail(person)).toBe("Anthropic, OpenAI");
    expect(
      resourceDetail({
        kind: "api_key",
        id: "key-1",
        label: "Key",
        providers: ["anthropic"],
        provider_account_id: 4,
        provider_account_label: "Research",
        hint: "sk-ant-...redacted",
      }),
    ).toBe("Anthropic · Research · sk-ant-...redacted");
    expect(
      resourceDetail({
        kind: "service",
        id: "svc",
        label: "bot",
        providers: ["openai"],
        provider_account_label: "OpenAI",
        hint: "service",
      }),
    ).toBe("OpenAI · service");
  });

  it("reads only a known provider and a positive account from the result address", () => {
    expect(entityQueryHint({ provider: "anthropic", provider_account: "4", q: "ignored" })).toEqual(
      { provider: "anthropic", account: 4 },
    );
    expect(entityQueryHint({ provider: ["openai", "anthropic"], provider_account: "0" })).toEqual({
      account: undefined,
      provider: "openai",
    });
    expect(entityQueryHint({ provider: "all", provider_account: "nope" })).toEqual({
      provider: undefined,
      account: undefined,
    });
  });
});
