import fs from "node:fs";
import { ExplorerView } from "@/components/explore/explorer-view";
import { seedExploreFilters } from "@/lib/core/portals";
import { readInbox, readApplications, careerOpsRoot, type Application } from "@/lib/career-ops";
import { DEFAULT_FILTERS } from "@/lib/explore";

// Read live data at request time so a bare checkout (or `next build` with no
// CAREER_OPS_ROOT) never fails — discovery seeds are best-effort.
export const dynamic = "force-dynamic";

export default function ExplorePage() {
  let seed: { filters: typeof DEFAULT_FILTERS; seededFrom: string[] } = { filters: DEFAULT_FILTERS, seededFrom: [] };
  try {
    seed = seedExploreFilters();
  } catch {
    /* bare checkout → defaults */
  }
  let rootExists = false;
  try {
    rootExists = fs.existsSync(careerOpsRoot());
  } catch {
    /* ignore */
  }
  return (
    // Local change (2026-10-14): ExplorerView only matches on url (inbox) and n/company/role (tracker), so only those
    // go to the browser; sending whole rows for ~6,500 pipeline jobs made this page 3.3 MB.
    <ExplorerView
      seed={seed}
      inboxSnapshot={readInbox().map(({ url, done }) => ({ url, done, company: "", role: "" }))}
      appsSnapshot={readApplications().map(({ n, company, role }) => ({ n, company, role }) as Application)}
      rootExists={rootExists}
    />
  );
}
