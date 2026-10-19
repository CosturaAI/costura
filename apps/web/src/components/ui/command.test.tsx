import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CommandDialog, CommandGroup, CommandInput, CommandItem, CommandList } from "./command";

describe("command dialog", () => {
  it("keeps server-ranked items when the typed text does not match them", async () => {
    const user = userEvent.setup();
    render(
      <CommandDialog open>
        <CommandInput placeholder="Find" />
        <CommandList>
          <CommandGroup heading="People">
            <CommandItem value="person:ada">Ada Lovelace</CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>,
    );

    expect(screen.getByRole("dialog", { name: "Search resources" })).toBeInTheDocument();
    const input = screen.getByRole("combobox", { name: "Search resources" });
    await user.type(input, "zzz");
    expect(screen.getByRole("option", { name: "Ada Lovelace" })).toBeInTheDocument();
  });
});
