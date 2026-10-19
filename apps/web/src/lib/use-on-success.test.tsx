import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ActionState } from "@/lib/action-errors";
import { useOnSuccess } from "@/lib/use-on-success";

function Probe({ state, onDone }: { state: ActionState; onDone: () => void }) {
  useOnSuccess(state, onDone);
  return null;
}

describe("useOnSuccess", () => {
  it("runs once per successful result and never for a failure", () => {
    const onDone = vi.fn();
    const failed: ActionState = { ok: false, message: "no" };
    const saved: ActionState = { ok: true, message: "saved" };
    const { rerender } = render(<Probe state={failed} onDone={onDone} />);
    expect(onDone).not.toHaveBeenCalled();
    rerender(<Probe state={saved} onDone={onDone} />);
    rerender(<Probe state={saved} onDone={onDone} />);
    expect(onDone).toHaveBeenCalledTimes(1);
    rerender(<Probe state={{ ok: true, message: "saved again" }} onDone={onDone} />);
    expect(onDone).toHaveBeenCalledTimes(2);
  });
});
