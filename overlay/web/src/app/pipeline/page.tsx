import { Suspense } from "react";
import { pipelineSummary } from "@/lib/career-ops";
import { PipelineView } from "@/components/pipeline-view";

export const dynamic = "force-dynamic"; // always read fresh local files

export default function PipelinePage() {
  const { inbox, applications } = pipelineSummary();
  // Local change (2026-10-10): only pending rows reach the client (the view only ever shows those);
  // sending all ~3,800 processed rows too made the page several MB. EVERY JOB loads via /api/all-jobs.
  return (
    <Suspense>
      <PipelineView applications={applications} inbox={inbox.filter((j) => !j.done)} />
    </Suspense>
  );
}
