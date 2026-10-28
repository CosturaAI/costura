import { StatePanel } from "@/components/empty-state";

/**
 * A Settings section this caller cannot open: Audit and Advanced need the owner role (Advanced
 * also needs browser writes), and Organization, Members, Teams and Account do not exist on the
 * sample organization. Switching organization from such a section lands here too.
 */
export default function SettingsSectionNotFound() {
  return (
    <StatePanel
      title="This section is not available here"
      message="Audit and Advanced need the owner role in this organization; ask an owner for it. The sample organization has no organization, members, teams or account sections."
      action={{ href: "/settings", label: "Back to Settings" }}
    />
  );
}
