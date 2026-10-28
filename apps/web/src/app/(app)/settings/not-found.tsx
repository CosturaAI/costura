import { StatePanel } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

/**
 * A Settings section this caller cannot open: Audit and Advanced need the owner role (Advanced
 * also needs browser writes), and Organization, Members, Teams and Account do not exist on the
 * sample organization. Switching organization from such a section lands here too.
 */
export default function SettingsSectionNotFound() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Section not available"
        description="Audit and Advanced need the owner role in this organization; ask an owner for it. The sample organization has no organization, members, teams or account sections."
      />
      <StatePanel
        message="The other sections of Settings stay open to you."
        action={{ href: "/settings", label: "Back to Settings" }}
      />
    </div>
  );
}
