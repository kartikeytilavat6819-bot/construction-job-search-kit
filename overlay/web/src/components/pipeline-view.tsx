"use client";

import { startTransition, useCallback, useEffect, useMemo, useOptimistic, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Search, ChevronsUpDown, X, Compass, ArrowRight } from "lucide-react";
import type { Application, InboxJob, PipelineJob } from "@/lib/career-ops";
import { AllJobsTable } from "@/components/all-jobs-table";
import { Badge } from "@/components/ui/badge";
import { CompanyLogo } from "@/components/company-logo";
import { canonStatus, scoreNum, scoreTone } from "@/lib/format";
import { StatusSelect } from "@/components/status-select";
import { applicationKey, applySavedStatus } from "@/lib/pipeline-status.mjs";
import { InboxTriage } from "@/components/inbox/inbox-triage";
import { cn } from "@/lib/cn";
import { companyPresentation, companySearchText } from "@/lib/company-presentation.mjs";
import { sortRows } from "@/lib/core/pipeline-sort.mjs";

// INBOX (the triage queue) is the default tab; the rest filter the tracker.
const TABS = [
  "INBOX",
  "EVERY JOB", // local change (2026-10-09): every posting in pipeline.md, screened out ones included
  "ALL",
  "EVALUATED",
  "APPLIED",
  "RESPONDED",
  "INTERVIEW",
  "OFFER",
  "HIRED",
  "REJECTED",
  "DISCARDED",
  "SKIP",
] as const;
type Tab = (typeof TABS)[number];

const SORT_KEYS = ["tracker", "company", "role", "score", "status", "date"] as const;

// Local change (2026-10-08): "Massachusetts only" switch. A row is in MA when its location (data/locations.tsv via
// readApplications), role or company names Massachusetts / MA ("Boston, MA", "US-MA-Watertown", "MA/NH").
const MA_RE = /massachusetts|\bMA\b|US-MA-/;
// Some boards write only the city ("Boston, US"); count a Massachusetts town when no other state is named.
const MA_TOWN = /\b(boston|cambridge|somerville|watertown|newton|waltham|woburn|westwood|norwood|marlborough|worcester|wakefield|taunton|springfield|andover|chelmsford|lowell|quincy|braintree|dedham|needham|framingham|natick|tewksbury|lexington|burlington|winthrop|westfield|sandwich|hyannis|foxborough|chelsea|northampton)\b/i;
const OTHER_STATE = /\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b|kentucky|ohio|illinois|virginia|texas|florida|carolina|california|new york|new jersey|connecticut|rhode island|new hampshire|maryland|tennessee|missouri|oregon/i;
// Local change (2026-10-08): the user only wants to see jobs worth applying to. Skipped/discarded rows and evaluated
// rows under 3.5 are hidden from ALL/EVALUATED (still reachable on their own SKIP / DISCARDED tabs).
function isNoise(r: Application): boolean {
  const s = canonStatus(r.status);
  if (s.includes("SKIP") || s.includes("DISCARDED")) return true;
  const n = scoreNum(r.score);
  return s.includes("EVALUATED") && !Number.isNaN(n) && n < 3.5;
}
function isMassachusetts(r: { location?: string; role: string; company: string }): boolean {
  const t = `${r.location ?? ""} | ${r.role} | ${r.company}`;
  return MA_RE.test(t) || (MA_TOWN.test(t) && !OTHER_STATE.test(t));
}
type SortKey = (typeof SORT_KEYS)[number];

export function PipelineView({
  applications,
  inbox,
}: {
  applications: Application[];
  inbox: InboxJob[];
}) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  // Starts AFTER the POST succeeds. React replays the confirmed save over
  // intervening snapshots and discards it when the refresh transition settles.
  const [visibleApplications, showSavedStatus] = useOptimistic(applications, applySavedStatus<Application>);
  const [announcement, setAnnouncement] = useState("");
  const activeTab = useRef<HTMLButtonElement>(null);

  // The URL is the SINGLE source of truth for tab/min/sort/dir, so the home stat
  // tiles' deep links AND the assistant's filterPipeline/navigate actions drive
  // the table identically (no useState mirror → no desync).
  const pTab = (params.get("tab") ?? "").toUpperCase();
  const tab: Tab = (TABS as readonly string[]).includes(pTab) ? (pTab as Tab) : "INBOX";
  const pMin = parseFloat(params.get("min") ?? "");
  const minFilter: number | null = Number.isFinite(pMin) ? pMin : null;
  const pSort = params.get("sort") ?? "";
  const sortKey: SortKey = (SORT_KEYS as readonly string[]).includes(pSort) ? (pSort as SortKey) : "score";
  const sort = { key: sortKey, dir: (params.get("dir") === "1" ? 1 : -1) as 1 | -1 };
  const maOnly = params.get("ma") === "1";
  // Local change (2026-10-10): EVERY JOB rows (~3,800) are fetched only when that tab is opened.
  const [allJobs, setAllJobs] = useState<PipelineJob[] | null>(null);
  useEffect(() => {
    if (tab !== "EVERY JOB" || allJobs) return;
    let live = true;
    fetch("/api/all-jobs")
      .then((r) => r.json())
      .then((rows: PipelineJob[]) => live && setAllJobs(rows))
      .catch(() => live && setAllJobs([]));
    return () => {
      live = false;
    };
  }, [tab, allJobs]);
  const scoped = useMemo(
    () => (maOnly ? visibleApplications.filter(isMassachusetts) : visibleApplications),
    [visibleApplications, maOnly],
  );

  // Search stays LOCAL for snappy typing; seeded from the URL and re-synced only
  // when the URL's q changes (i.e. the assistant set it) — never per keystroke.
  const [q, setQ] = useState(params.get("q") ?? "");
  const lastUrlQ = useRef(params.get("q") ?? "");
  useEffect(() => {
    const urlQ = params.get("q") ?? "";
    if (urlQ !== lastUrlQ.current) {
      lastUrlQ.current = urlQ;
      setQ(urlQ);
    }
  }, [params]);

  const setParams = useCallback(
    (updates: Record<string, string | number | null>) => {
      const sp = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(updates)) {
        if (v == null || v === "") sp.delete(k);
        else sp.set(k, String(v));
      }
      const qs = sp.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [params, router, pathname],
  );

  // Pending + deduped by URL (pipeline.md can list the same posting twice) so the
  // header count, the tab count and the triage list all agree on one number.
  const pendingInbox = useMemo(() => {
    const seen = new Set<string>();
    const out: InboxJob[] = [];
    for (const j of inbox) {
      if (j.done || seen.has(j.url)) continue;
      seen.add(j.url);
      out.push(j);
    }
    return out;
  }, [inbox]);

  const filtered = useMemo(() => {
    if (tab === "INBOX" || tab === "EVERY JOB") return [];
    let rows = scoped;
    if (tab === "ALL" || tab === "EVALUATED") rows = rows.filter((r) => !isNoise(r));
    if (tab !== "ALL") rows = rows.filter((r) => canonStatus(r.status).includes(tab));
    if (minFilter != null) {
      rows = rows.filter((r) => {
        const n = scoreNum(r.score);
        return !Number.isNaN(n) && n >= minFilter;
      });
    }
    if (q.trim()) {
      const needle = q.toLowerCase();
      rows = rows.filter((r) => companySearchText(r).toLowerCase().includes(needle));
    }
    // scoreNum is the real score parser (it handles the tracker's "4.2/5"
    // cells); sortRows takes it rather than keeping a second copy (#4333).
    return sortRows(
      rows,
      sort,
      scoreNum,
      (row) => companyPresentation(row).label,
    ) as Application[];
  }, [scoped, tab, q, sort, minFilter]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8 max-sm:pb-24">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl tracking-tight text-landing">Pipeline</h1>
          <p className="mt-1 text-sm text-muted">
            <span className="tabular-nums">
              {scoped.filter((r) => canonStatus(r.status).includes("EVALUATED") && scoreNum(r.score) >= 4.0).length}
            </span>{" "}
            worth applying (4.0+){maOnly ? " in Massachusetts" : ""} ·{" "}
            <span className="tabular-nums">{pendingInbox.length}</span> new to check
          </p>
        </div>
        {/* the tracker has its own search; the inbox brings its own facet filters */}
        {tab !== "INBOX" && tab !== "EVERY JOB" && (
          <div className="relative w-64 max-w-[40vw]">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search company or role…"
              className="w-full rounded-md border border-border bg-surface/60 py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-faint focus:border-brand/50 focus-visible:ring-2 focus-visible:ring-brand/40"
            />
          </div>
        )}
      </div>

      {/* tabs */}
      <div className="mt-6 flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => {
          const count =
            t === "INBOX"
              ? pendingInbox.length
              : t === "EVERY JOB"
                ? allJobs
                  ? (maOnly ? allJobs.filter(isMassachusetts) : allJobs).length
                  : ""
                : t === "ALL"
                ? scoped.filter((r) => !isNoise(r)).length
                : t === "EVALUATED"
                  ? scoped.filter((r) => !isNoise(r) && canonStatus(r.status).includes(t)).length
                  : scoped.filter((r) => canonStatus(r.status).includes(t)).length;
          return (
            <button
              key={t}
              ref={tab === t ? activeTab : undefined}
              onClick={() => setParams({ tab: t === "INBOX" ? null : t })}
              className={cn(
                // gap-1, not a whitespace text node: flex containers drop
                // whitespace-only anonymous items, which rendered "INBOX0".
                "-mb-px inline-flex items-center justify-center gap-1 border-b-2 px-3 py-2 text-xs font-medium transition-colors max-sm:min-h-[44px]",
                tab === t
                  ? "border-brand text-foreground"
                  : "border-transparent text-muted hover:text-foreground",
              )}
            >
              {t} <span className="text-faint tabular-nums">{count}</span>
            </button>
          );
        })}
      </div>

      {tab !== "INBOX" && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            role="switch"
            aria-checked={maOnly}
            onClick={() => setParams({ ma: maOnly ? null : 1 })}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-colors max-sm:min-h-[44px]",
              maOnly ? "border-brand/50 bg-brand-soft text-brand" : "border-border text-muted hover:text-foreground",
            )}
            title="Show only jobs located in Massachusetts"
          >
            <span
              aria-hidden="true"
              className={cn("relative inline-block h-4 w-7 rounded-full transition-colors", maOnly ? "bg-brand" : "bg-foreground/20")}
            >
              <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-all", maOnly ? "left-3.5" : "left-0.5")} />
            </span>
            Massachusetts only
          </button>
          {maOnly && <span className="text-xs text-faint tabular-nums">{scoped.length} of {visibleApplications.length} tracked</span>}
        </div>
      )}

      <p role="status" className="sr-only">{announcement}</p>

      {tab !== "INBOX" && minFilter != null && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-faint">Filtered:</span>
          <button
            type="button"
            onClick={() => setParams({ min: null })}
            className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand transition-colors hover:bg-brand/15"
            title="Clear score filter"
          >
            score ≥ {minFilter.toFixed(1)}
            <X className="size-3" />
          </button>
        </div>
      )}

      {tab === "EVERY JOB" ? (
        allJobs ? (
          <AllJobsTable jobs={allJobs} inMa={maOnly ? isMassachusetts : null} />
        ) : (
          <p className="mt-6 text-sm text-muted">Loading every job…</p>
        )
      ) : tab === "INBOX" ? (
        /* ── Inbox: the triage surface (Abundance → Triage → Shortlist → Score) ── */
        pendingInbox.length > 0 ? (
          <InboxTriage inbox={pendingInbox} />
        ) : (
          <InboxEmpty count={0} filtered={false} />
        )
      ) : filtered.length > 0 ? (
        /* ── Tracker table ──
           overflow-x-auto, not overflow-hidden: the rounded corners still clip,
           but a table too wide for the viewport can now be scrolled to instead
           of being silently cut off. min-w keeps the columns readable rather
           than letting w-full crush them on a phone. */
        <div className="mt-4 overflow-x-auto rounded-2xl border border-border">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="bg-surface/60 text-left text-xs uppercase tracking-wide text-faint">
              <tr>
                {SORT_KEYS.map((k) => (
                  <th
                    key={k}
                    aria-sort={sort.key === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                    className={cn(
                      "whitespace-nowrap px-4 py-2.5 font-medium",
                      k === "date" && "hidden lg:table-cell",
                    )}
                  >
                    <button
                      type="button"
                      className="inline-flex cursor-pointer select-none items-center gap-1 uppercase tracking-wide hover:text-foreground"
                      onClick={() => setParams({ sort: k, dir: sort.key === k ? sort.dir * -1 : -1 })}
                    >
                      {k}
                      <ChevronsUpDown aria-hidden="true" className="size-3" />
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((r) => {
                const company = companyPresentation(r);
                const key = applicationKey(r);
                return (
                  <tr key={key} data-application-key={key} className="group transition-colors hover:bg-surface/40">
                    <td className="whitespace-nowrap px-4 py-3 font-medium tabular-nums">
                      <Link href={`/pipeline/${r.n}`} className="transition-colors group-hover:text-brand">
                        #{r.n}
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-medium">
                      <Link href={`/pipeline/${r.n}`} className="flex items-center gap-2.5 transition-colors group-hover:text-brand">
                        <CompanyLogo name={company.logoName} size={20} />
                        {company.label}
                      </Link>
                    </td>
                  <td className="px-4 py-3 text-muted">
                    <Link href={`/pipeline/${r.n}`}>{r.role}</Link>
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={scoreTone(r.score)}>{r.score || "—"}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-muted">
                    <StatusSelect
                      n={r.n}
                      current={r.status}
                      inline
                      applicationLabel={`${company.label} — ${r.role} (#${r.n})`}
                      onSaved={(status, restoreFocus) => {
                        // If this focused row leaves its tab, preserve a useful
                        // focus target. Do not interrupt someone using search.
                        const focusedRow = document.activeElement?.closest("tr");
                        if (tab !== "ALL" && !canonStatus(status).includes(tab) && (restoreFocus || focusedRow?.dataset.applicationKey === key)) {
                          activeTab.current?.focus();
                        }
                        setAnnouncement(`Application #${r.n} status saved as ${status}.`);
                        startTransition(() => {
                          showSavedStatus({ key, status });
                          router.refresh();
                        });
                      }}
                    />
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-faint tabular-nums lg:table-cell">{r.date}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4 rounded-2xl border border-dashed border-border bg-surface/30 px-6 py-12 text-center">
          <p className="font-display text-lg">No matches</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Try a different tab or clear the search.</p>
        </div>
      )}
    </div>
  );
}

// Empty inbox. Self-sufficient for the mainstream user (a primary in-web action),
// honest for devs (the CLI/file path stays, demoted to progressive transparency).
function InboxEmpty({ count, filtered }: { count: number; filtered: boolean }) {
  if (filtered) {
    return (
      <div className="mt-4 rounded-2xl border border-dashed border-border bg-surface/30 px-6 py-12 text-center">
        <p className="font-display text-lg">No matches</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Clear the search to see the full inbox.</p>
      </div>
    );
  }
  return (
    <div className="dot-bg mt-4 overflow-hidden rounded-2xl border border-border bg-surface/50 bg-origin-border bg-gradient-to-tr from-brand/10 via-transparent to-transparent shadow-lg">
      <div className="flex items-center gap-2 border-b border-foreground/10 px-5 py-3">
        <span className="size-2.5 rounded-full bg-foreground/15" aria-hidden="true" />
        <span className="size-2.5 rounded-full bg-foreground/15" aria-hidden="true" />
        <span className="size-2.5 rounded-full bg-foreground/15" aria-hidden="true" />
        <span className="ml-3 font-mono text-xs tracking-wide text-muted">career-ops · inbox</span>
      </div>
      <div className="px-6 py-10 text-center">
        <p className="font-display text-lg">
          Your <span className="text-brand">inbox</span> is empty.
        </p>
        {count > 0 ? (
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted">Nothing pending right now.</p>
        ) : (
          <>
            <p className="mx-auto mt-2 max-w-sm text-sm text-muted">Find roles that match your CV — free, no tokens spent.</p>
            <Link
              href="/explore?run=1"
              className="mt-5 inline-flex items-center gap-2 rounded-full bg-brand px-5 py-2.5 text-sm font-medium text-brand-foreground shadow-sm transition-all duration-200 hover:bg-brand-200 hover:-translate-y-0.5 hover:shadow-md"
            >
              <Compass className="size-4" /> Run your first free scan <ArrowRight className="size-4" />
            </Link>
            <p className="mx-auto mt-4 max-w-sm text-xs text-muted">
              Prefer the terminal? Run <code className="rounded bg-surface-hover px-1 py-0.5 font-mono">career-ops scan</code>, or add job URLs to{" "}
              <code className="rounded bg-surface-hover px-1 py-0.5 font-mono">data/pipeline.md</code>.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
