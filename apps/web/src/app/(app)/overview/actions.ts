"use server";

import { type ActionState } from "@/lib/action-errors";
import { api } from "@/lib/api";
import { runMutation } from "@/lib/mutations";
import { requireActiveOrg } from "@/lib/view";

/** Hides the getting-started card for good: `POST .../setup/dismiss` stores the timestamp. */
export async function dismissSetupAction(): Promise<ActionState> {
  const org = await requireActiveOrg();
  return runMutation(async () => {
    await api.dismissSetup(org);
    return "Dismissed.";
  }, [["/overview"]]);
}
