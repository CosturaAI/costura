import { redirect } from "next/navigation";

import { loadSettings } from "./data";

/** Settings has no page of its own: the sample opens on how it is configured, any other
 * organization on Connections. */
export default async function SettingsIndex() {
  const { isDemo } = await loadSettings();
  redirect(isDemo ? "/settings/sample" : "/settings/connections");
}
