import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { InventorySearchItem } from "@/lib/api";

import { ResourceSearch, type ResourceSearchFn } from "./resource-search";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const person: InventorySearchItem = {
  kind: "person",
  id: "ada@example.com",
  label: "Ada",
  providers: ["anthropic", "openai"],
  hint: null,
};
const service: InventorySearchItem = {
  kind: "service",
  id: "svc_bot",
  label: "billing-bot",
  providers: ["openai"],
  provider_account_id: 3,
  provider_account_label: "OpenAI",
  hint: "service",
};
const key: InventorySearchItem = {
  kind: "api_key",
  id: "key-1",
  label: "Platform key",
  providers: ["anthropic"],
  provider_account_id: 4,
  provider_account_label: "Research",
  hint: "sk-ant-...redacted",
};
const workspace: InventorySearchItem = {
  kind: "workspace",
  id: "ws_1",
  label: "Lab",
  providers: ["openrouter"],
  provider_account_id: 2,
  provider_account_label: "OpenRouter",
  hint: null,
};

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("ResourceSearch", () => {
  beforeEach(() => {
    push.mockReset();
  });

  it("stays closed until Ctrl+K or Cmd+K, and ignores an IME composition", async () => {
    const search = vi.fn<ResourceSearchFn>();
    render(<ResourceSearch search={search} delay={0} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();

    const button = screen.getByRole("button", { name: "Search resources" });
    button.focus();
    fireEvent.keyDown(document, { key: "Process", ctrlKey: true });
    fireEvent.keyDown(document, { key: "k", ctrlKey: true, isComposing: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const dialog = screen.getByRole("dialog", { name: "Search resources" });
    expect(dialog).toBeInTheDocument();
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(button));
  });

  it("returns focus to the button on Escape", async () => {
    const user = userEvent.setup();
    render(<ResourceSearch search={vi.fn()} delay={0} />);
    const button = screen.getByRole("button", { name: "Search resources" });
    await user.click(button);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(button));
  });

  it("shows the instruction, then loading, empty, error and grouped results", async () => {
    const user = userEvent.setup();
    const pending = deferred<InventorySearchItem[]>();
    const search = vi
      .fn<ResourceSearchFn>()
      .mockImplementationOnce(() => pending.promise)
      .mockRejectedValueOnce(new Error("provider unavailable"))
      .mockResolvedValueOnce([person, service, key, workspace]);
    render(<ResourceSearch search={search} delay={0} />);
    await user.click(screen.getByRole("button", { name: "Search resources" }));
    const input = screen.getByRole("combobox", { name: "Search resources" });

    await user.type(input, "a");
    expect(screen.getByText("Type at least two characters.")).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();

    await user.type(input, "d");
    expect(await screen.findByText("Searching…")).toBeInTheDocument();
    pending.resolve([]);
    expect(await screen.findByText("No current resources match.")).toBeInTheDocument();

    await user.type(input, "x");
    expect(await screen.findByText("provider unavailable")).toBeInTheDocument();

    await user.type(input, "y");
    expect(await screen.findByRole("option", { name: /Ada/ })).toBeInTheDocument();
    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.getByText("Services")).toBeInTheDocument();
    expect(screen.getByText("API keys")).toBeInTheDocument();
    expect(screen.getByText("Workspaces / Projects")).toBeInTheDocument();
    expect(screen.getByText("Anthropic, OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Anthropic · Research · sk-ant-...redacted")).toBeInTheDocument();
  });

  it("cancels a stale request and opens the selected resource", async () => {
    const user = userEvent.setup();
    let first: AbortSignal | undefined;
    const search = vi.fn<ResourceSearchFn>((query, signal) => {
      if (query === "ze") {
        first = signal;
        return new Promise(() => {});
      }
      return Promise.resolve([key]);
    });
    render(<ResourceSearch search={search} delay={0} />);
    await user.click(screen.getByRole("button", { name: "Search resources" }));
    const input = screen.getByRole("combobox", { name: "Search resources" });
    await user.type(input, "ze");
    await waitFor(() => expect(search).toHaveBeenCalledWith("ze", expect.any(AbortSignal)));
    await user.type(input, "p");
    const option = await screen.findByRole("option", { name: /Platform key/ });
    expect(first?.aborted).toBe(true);

    await user.click(option);
    expect(push).toHaveBeenCalledWith("/keys/key-1?provider=anthropic&provider_account=4");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("always offers the full resources list", async () => {
    const user = userEvent.setup();
    render(<ResourceSearch search={vi.fn<ResourceSearchFn>()} delay={0} />);
    await user.click(screen.getByRole("button", { name: "Search resources" }));
    expect(screen.getByText("Type at least two characters.")).toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "All resources, including missing rows" }));
    expect(push).toHaveBeenCalledWith("/inventory");
  });

  it("opens the first result on Enter once results arrive", async () => {
    const user = userEvent.setup();
    const search = vi.fn<ResourceSearchFn>().mockResolvedValue([person, service]);
    render(<ResourceSearch search={search} delay={0} />);
    await user.click(screen.getByRole("button", { name: "Search resources" }));
    await user.type(screen.getByRole("combobox", { name: "Search resources" }), "ad");
    expect(await screen.findByRole("option", { name: /Ada/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /All resources/ })).toBeNull();
    await user.keyboard("{Enter}");
    expect(push).toHaveBeenCalledWith(expect.not.stringMatching(/^\/inventory/));
  });

  it("waits for the debounce before searching", async () => {
    const search = vi.fn<ResourceSearchFn>(() => new Promise(() => {}));
    const user = userEvent.setup();
    render(<ResourceSearch search={search} delay={250} />);
    await user.click(screen.getByRole("button", { name: "Search resources" }));
    await user.type(screen.getByRole("combobox", { name: "Search resources" }), "ze");
    expect(search).not.toHaveBeenCalled();
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1), { timeout: 1000 });
  });
});
