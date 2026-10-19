import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { welcomeHref } from "@/lib/setup";

/**
 * A page under the shell asked for something the API has no row for (a key, workspace or
 * account id, an anomaly), or the address was typed by hand. The address names no
 * organization or provider, so there is nothing to read from it here.
 */
export default function EntityNotFound() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Not found"
        description="No key, workspace, account, model or anomaly with this id is in this organization. It may have been deleted at the provider before the first inventory sync, or the address was typed by hand."
      />
      <EmptyState
        message="Search the inventory for the name instead. An empty inventory means nothing has been imported yet."
        action={{ href: welcomeHref(), label: "Connect a provider" }}
      />
    </div>
  );
}
