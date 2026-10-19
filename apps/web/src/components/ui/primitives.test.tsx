import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", async (importActual) => {
  const actual = await importActual<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => children,
  };
});

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "./sheet";

describe("interactive UI primitives", () => {
  it("gives sheets an accessible name, closes on Escape, and returns focus", async () => {
    const user = userEvent.setup();
    render(
      <Sheet>
        <SheetTrigger>Open settings</SheetTrigger>
        <SheetContent>
          <SheetTitle>Connection settings</SheetTitle>
          <SheetDescription>Change this provider.</SheetDescription>
          <button type="button">Save</button>
        </SheetContent>
      </Sheet>,
    );
    const trigger = screen.getByRole("button", { name: "Open settings" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Connection settings" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("supports alert confirmation and cancellation", async () => {
    const user = userEvent.setup();
    const confirmed = vi.fn();
    render(
      <AlertDialog>
        <AlertDialogTrigger>Delete connection</AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogTitle>Delete connection?</AlertDialogTitle>
          <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={confirmed}>Delete</AlertDialogAction>
        </AlertDialogContent>
      </AlertDialog>,
    );
    await user.click(screen.getByRole("button", { name: "Delete connection" }));
    expect(screen.getByRole("alertdialog", { name: "Delete connection?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete connection" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirmed).toHaveBeenCalledOnce();
  });

  it("opens a keyboard-accessible dropdown and invokes an item", async () => {
    const user = userEvent.setup();
    const selected = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Actions</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={selected}>Refresh</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Refresh" }));
    expect(selected).toHaveBeenCalledOnce();
  });
});
