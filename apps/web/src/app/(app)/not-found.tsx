import Link from "next/link";

import { AllProvidersLink } from "@/components/all-providers-link";
import { StatePanel } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { isAll, providerLabel } from "@/lib/providers";
import { welcomeHref } from "@/lib/setup";
import { readViewCookie } from "@/lib/view-cookie";

const LINK = "font-medium text-primary hover:underline";

/**
 * A page under the shell asked for something the API has no row for (a person, a key,
 * workspace or account id, an anomaly), or the address was typed by hand. The address names no
 * organization or provider; the view cookie does, so under one provider the page offers the
 * same address under every provider.
 */
export default async function EntityNotFound() {
  const view = await readViewCookie().catch(() => null);
  const scoped = view?.scope && !isAll(view.scope) ? view.scope : null;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Not found"
        description={`No person, key, workspace, account, model or anomaly with this address is in this organization${scoped ? ` under ${providerLabel(scoped)}` : ""}. It may have been deleted at the provider before the first inventory sync, or the address was typed by hand.`}
      />
      <StatePanel
        message={`Search the inventory for the name instead${scoped ? ", or open this address under every provider" : ""}. An empty inventory means nothing has been imported yet.`}
      >
        <p className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm">
          <Link href="/inventory" className={LINK}>
            Search resources
          </Link>
          {scoped && view ? <AllProvidersLink org={view.org} className={LINK} /> : null}
          <Link href={welcomeHref()} className={LINK}>
            Connect a provider
          </Link>
        </p>
      </StatePanel>
    </div>
  );
}
