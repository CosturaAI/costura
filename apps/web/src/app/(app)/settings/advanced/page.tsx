import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { anyRunning } from "@/lib/setup";

import { ResetSetupForm } from "../connection-forms";
import { loadSettings } from "../data";
import { DeleteOrganizationForm } from "./delete-form";

export const metadata: Metadata = { title: "Advanced settings" };

/**
 * Advanced section: the one action that deletes data, alone at the end of the rail so it is
 * never a neighbour of a routine setting. Only an owner of a writable organization
 * can reset, and the API answers 403 to anybody else, so the section itself is 404 for them.
 */
export default async function AdvancedSettingsPage() {
  const settings = await loadSettings();
  if (!settings.canManage) notFound();
  const syncActive = anyRunning(settings.setup.runs);

  return (
    <div className="space-y-5">
      <Card className="border-severity-critical/30">
        <CardHeader>
          <CardHeading>Reset onboarding</CardHeading>
          <CardDescription>
            Start over as if this organization were newly created. Keys provided by the instance
            configuration stay, so on such an instance the welcome page opens in the importing state
            instead of asking for a key.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ResetSetupForm syncActive={syncActive} />
        </CardContent>
      </Card>
      <Card className="border-severity-critical/30">
        <CardHeader>
          <CardHeading>Delete organization</CardHeading>
          <CardDescription>
            Deletes this organization, its members, its keys and its spend. A sync that is queued or
            running blocks the delete until it finishes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DeleteOrganizationForm slug={settings.org} />
        </CardContent>
      </Card>
    </div>
  );
}
