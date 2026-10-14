import { readAllPipeline } from "@/lib/career-ops";

export const runtime = "nodejs";
export const dynamic = "force-dynamic"; // always read fresh local files

// Local change (2026-10-10): the EVERY JOB tab loads its ~3,800 rows on demand instead of every
// /pipeline render embedding them (that made the page ~4.5 MB and slow to open).
export async function GET() {
  return Response.json(readAllPipeline());
}
