import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { canManage } from "@/lib/roles";
import { overviewHref } from "@/lib/setup";
import { requireActiveOrg } from "@/lib/view";

import { WelcomeFlow } from "./welcome-flow";

export const metadata: Metadata = { title: "Welcome" };

/**
 * First visit of an organization: connect a provider key, then land on the overview where
 * the sync banner follows the first import. One centered column without the shell. The
 * sample-data link depends on `GET /me`; when that call fails the page renders without it.
 * The sample organization has nothing to connect, so its welcome is the overview.
 */
export default async function WelcomePage() {
  const org = await requireActiveOrg();
  let setup;
  try {
    setup = await api.setup(org);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) redirect("/");
    throw error;
  }
  const [me, organization] = await Promise.allSettled([api.me(), api.org(org)]);
  if (organization.status === "fulfilled" && organization.value.is_demo) {
    redirect(overviewHref());
  }
  const demoOrg = me.status === "fulfilled" ? me.value.demo_org : null;
  const role = organization.status === "fulfilled" ? organization.value.role : null;
  return (
    <WelcomeFlow
      org={org}
      setup={setup}
      demoOrg={demoOrg}
      canConnect={organization.status !== "fulfilled" || canManage(role)}
    />
  );
}
