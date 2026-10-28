import { beforeEach, describe, expect, it, vi } from "vitest";

const { revalidatePath } = vi.hoisted(() => ({ revalidatePath: vi.fn() }));
vi.mock("next/cache", () => ({ revalidatePath }));

import { ApiError } from "./api-error";
import { runMutation } from "./mutations";

beforeEach(() => vi.clearAllMocks());

describe("runMutation", () => {
  it("returns success and refreshes only the routes the write names", async () => {
    await expect(
      runMutation(async () => "saved", [["/budgets"], ["/workspaces/[id]", "page"]]),
    ).resolves.toEqual({ ok: true, message: "saved" });
    expect(revalidatePath.mock.calls).toEqual([["/budgets"], ["/workspaces/[id]", "page"]]);
  });

  it("refreshes every page by default", async () => {
    await runMutation(async () => "done");
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
  });

  it("turns API and unexpected failures into action state without revalidation", async () => {
    await expect(
      runMutation(async () => {
        throw new ApiError(422, "/key", "key rejected");
      }),
    ).resolves.toEqual({ ok: false, message: "Key rejected." });
    await expect(
      runMutation(async () => {
        throw new Error("boom");
      }),
    ).resolves.toEqual({ ok: false, message: "boom" });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("rethrows Next redirect errors", async () => {
    const redirect = Object.assign(new Error("redirect"), {
      digest: "NEXT_REDIRECT;replace;/;307;",
    });
    await expect(
      runMutation(async () => {
        throw redirect;
      }),
    ).rejects.toBe(redirect);
  });
});
