import type { Metadata } from "next";
import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";

import { loadSettings } from "../data";
import { AnomalySettingsForm } from "./form";
import { WebhookCard } from "./webhook-card";

export const metadata: Metadata = { title: "Anomaly settings" };

/** How this organization wants spend watched and where its signals are posted. Owners save;
 * everyone else can read. The sample organization has no webhook card. */
export default async function AnomalySettingsPage() {
  const settings = await loadSettings();
  const [current, webhook] = await Promise.all([
    api.anomalySettings(settings.org),
    settings.isDemo ? Promise.resolve(null) : api.webhook(settings.org).catch(() => null),
  ]);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardHeading>Anomaly detection</CardHeading>
          <CardDescription>
            The width of the bounds, whether drops and new principals are flagged, and how long the
            evidence is kept. Where signals are posted is the webhook below.
            {settings.isDemo
              ? " The sample keeps the defaults; in your organization an owner changes them here."
              : null}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AnomalySettingsForm
            org={settings.org}
            settings={current}
            canManage={settings.canManage}
            isOwner={settings.isOwner}
          />
        </CardContent>
      </Card>
      {settings.isDemo ? null : (
        <WebhookCard org={settings.org} webhook={webhook} canManage={settings.canManage} />
      )}
    </div>
  );
}
