import { NextRequest } from "next/server";
import fs from "node:fs";
import { runDiscovery } from "@/lib/core/scan";
import { rootScript, careerOpsRoot } from "@/lib/career-ops";
import path from "node:path";

// Local change (2026-10-08): Explore runs its own discovery and never applied portals.yml's location_filter,
// so non-US postings (Pune, Mumbai, Abu Dhabi, Sydney...) showed up. Apply the same tiers as scan.mjs:
// block_hard -> drop, always_allow -> keep, block -> drop, otherwise keep. Keywords match at word boundaries.
function loadLocationFilter(): (loc: string) => boolean {
  let text = "";
  try {
    text = fs.readFileSync(path.join(careerOpsRoot(), "portals.yml"), "utf8");
  } catch {
    return () => true;
  }
  const section = text.split(/\r?\n/);
  const lists: Record<string, string[]> = { block_hard: [], always_allow: [], block: [] };
  let inFilter = false;
  let cur = "";
  for (const line of section) {
    if (/^location_filter:/.test(line)) { inFilter = true; continue; }
    if (inFilter && /^\S/.test(line)) break;
    const key = line.match(/^  (block_hard|always_allow|block):/);
    if (key) { cur = key[1]; continue; }
    const item = line.match(/^\s+-\s+"([^"]+)"/);
    if (cur && item) lists[cur].push(item[1]);
  }
  const rx = (k: string) => new RegExp(`(^|[^a-z0-9])${k.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^a-z0-9])`, "i");
  const compile = (ks: string[]) => ks.map(rx);
  const hard = compile(lists.block_hard), allow = compile(lists.always_allow), block = compile(lists.block);
  return (loc: string) => {
    const l = (loc || "").trim();
    if (!l) return true;
    if (hard.some((r) => r.test(l))) return false;
    if (allow.some((r) => r.test(l))) return true;
    return !block.some((r) => r.test(l));
  };
}
import { parseExplorePatch, DEFAULT_FILTERS, type DiscoveredOffer, type ScanEvent } from "@/lib/explore";
import { scannerMissingBody, SCANNER_MISSING_STATUS } from "@/lib/explore-error.mjs";

// Discovery is HTTP-bound across many ATS boards; give it room. It is FREE —
// zero LLM tokens (the scanner only does HTTP + JSON, and --dry-run writes nothing).
export const runtime = "nodejs";
export const maxDuration = 300;
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  let body: Record<string, unknown> = {};
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    /* empty body → defaults */
  }

  const filters = parseExplorePatch(body, DEFAULT_FILTERS);

  // Guard: a data-only checkout (or pre-onboarding) has no scanner. Fail soft.
  // The body carries an explicit code because 400 is a shared channel: the
  // client cannot tell this apart from a malformed request by status alone.
  if (!fs.existsSync(rootScript("scan-ats-full"))) {
    return Response.json(scannerMissingBody(), { status: SCANNER_MISSING_STATUS });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const usOnly = loadLocationFilter();
      const send = (obj: unknown) => {
        const ev = obj as { kind?: string; offer?: DiscoveredOffer; offers?: DiscoveredOffer[] };
        if (ev?.kind === "offer" && ev.offer && !usOnly(ev.offer.location)) return;
        if (ev?.kind === "done" && Array.isArray(ev.offers)) {
          ev.offers = ev.offers.filter((o) => usOnly(o.location));
          (ev as { count?: number }).count = ev.offers.length;
        }
        try {
          controller.enqueue(encoder.encode(JSON.stringify(obj) + "\n"));
        } catch {
          /* stream closed */
        }
      };
      send({ kind: "start", ats: filters.ats, sinceDays: filters.sinceDays, limit: filters.limitPerAts, free: true } satisfies ScanEvent);
      let offers: DiscoveredOffer[] = [];
      try {
        offers = await runDiscovery(filters, (e: ScanEvent) => send(e));
      } catch (err) {
        send({ kind: "error", message: err instanceof Error ? err.message : "discovery failed" } satisfies ScanEvent);
      }
      send({ kind: "done", count: offers.length, offers, cost: { tokens: 0, usd: 0 } } satisfies ScanEvent);
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
