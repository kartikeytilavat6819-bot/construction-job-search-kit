"use client";

// Local change (2026-10-09): the "EVERY JOB" tab — every posting in data/pipeline.md (pending, evaluated and
// screened out), with outcome chips, search and the Massachusetts switch. Read-only; links open the posting.
import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, ExternalLink } from "lucide-react";
import type { PipelineJob } from "@/lib/career-ops";
import { Badge } from "@/components/ui/badge";
import { CompanyLogo } from "@/components/company-logo";
import { cn } from "@/lib/cn";

const OUTCOMES = ["Pending", "Evaluated", "Parked", "Rule fail", "AI triage fail", "No sponsorship", "Outside US", "Other"] as const;
const TONE: Record<string, "good" | "warn" | "bad" | "info" | "muted"> = {
  Pending: "info",
  Evaluated: "good",
  Parked: "warn",
  "Rule fail": "bad",
  "AI triage fail": "bad",
  "No sponsorship": "bad",
  "Outside US": "muted",
  Other: "muted",
};
const PAGE = 200;
// job sieve tiers (local/sieve.py). "Not sieved" = jobs Claude already evaluated, or a sieve that hasn't run yet.
const SIEVE = ["GOLD", "SILVER", "PENDING", "NO_JD", "REJECT", "Not sieved"] as const;
const SIEVE_LABEL: Record<string, string> = { GOLD: "Gold", SILVER: "Silver", PENDING: "Sieve waiting", NO_JD: "No JD", REJECT: "Sieve reject", "Not sieved": "Not sieved" };
const SIEVE_TONE: Record<string, "good" | "warn" | "bad" | "info" | "muted"> = { GOLD: "good", SILVER: "warn", PENDING: "info", NO_JD: "muted", REJECT: "bad", "Not sieved": "muted" };
const SIEVE_RANK: Record<string, number> = { GOLD: 0, SILVER: 1, PENDING: 2, NO_JD: 3, "Not sieved": 4, REJECT: 5 };
const tierOf = (j: PipelineJob) => j.sieve ?? "Not sieved";

export function AllJobsTable({ jobs, inMa }: { jobs: PipelineJob[]; inMa: ((j: PipelineJob) => boolean) | null }) {
  const [q, setQ] = useState("");
  // Outside-US rows are noise for a US search, so they start switched off; one click brings them back.
  const [off, setOff] = useState<Set<string>>(() => new Set(["Outside US"]));
  const [limit, setLimit] = useState(PAGE);
  const sieved = useMemo(() => jobs.some((j) => j.sieve), [jobs]);
  const [sieveOff, setSieveOff] = useState<Set<string>>(() => new Set());
  const [bySieve, setBySieve] = useState(true);

  const scoped = useMemo(() => (inMa ? jobs.filter(inMa) : jobs), [jobs, inMa]);
  const counts = useMemo(() => {
    const c = new Map<string, number>();
    for (const j of scoped) c.set(j.outcome, (c.get(j.outcome) ?? 0) + 1);
    return c;
  }, [scoped]);
  const sieveCounts = useMemo(() => {
    const c = new Map<string, number>();
    for (const j of scoped) c.set(tierOf(j), (c.get(tierOf(j)) ?? 0) + 1);
    return c;
  }, [scoped]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const newest = (a: PipelineJob, b: PipelineJob) => (b.postedAt ?? "").localeCompare(a.postedAt ?? "");
    return scoped
      .filter((j) => !off.has(j.outcome) && !sieveOff.has(tierOf(j)))
      .filter((j) => !needle || `${j.company} ${j.role} ${j.location ?? ""} ${j.reason} ${j.sieveReason ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) =>
        sieved && bySieve
          ? SIEVE_RANK[tierOf(a)] - SIEVE_RANK[tierOf(b)] || (b.sieveScore ?? 0) - (a.sieveScore ?? 0) || newest(a, b)
          : newest(a, b),
      );
  }, [scoped, off, sieveOff, q, sieved, bySieve]);

  const toggleSieve = (t: string) => {
    setLimit(PAGE);
    setSieveOff((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  const toggle = (o: string) => {
    setLimit(PAGE);
    setOff((prev) => {
      const next = new Set(prev);
      if (next.has(o)) next.delete(o);
      else next.add(o);
      return next;
    });
  };

  return (
    <div className="mt-4">
      {sieved && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-faint">Sieve</span>
          {SIEVE.filter((t) => sieveCounts.get(t)).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={!sieveOff.has(t)}
              onClick={() => toggleSieve(t)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors max-sm:min-h-[44px]",
                sieveOff.has(t) ? "border-border text-faint line-through" : "border-brand/50 bg-brand-soft text-brand",
              )}
            >
              {SIEVE_LABEL[t]} <span className="tabular-nums">{sieveCounts.get(t)}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setSieveOff(new Set(SIEVE.filter((t) => t !== "GOLD" && t !== "SILVER")));
              setLimit(PAGE);
            }}
            className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted hover:text-foreground max-sm:min-h-[44px]"
          >
            Only Gold + Silver
          </button>
          <button
            type="button"
            onClick={() => setBySieve((v) => !v)}
            className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted hover:text-foreground max-sm:min-h-[44px]"
          >
            Sort: {bySieve ? "best sieve score" : "newest"}
          </button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {OUTCOMES.filter((o) => counts.get(o)).map((o) => (
          <button
            key={o}
            type="button"
            aria-pressed={!off.has(o)}
            onClick={() => toggle(o)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors max-sm:min-h-[44px]",
              off.has(o) ? "border-border text-faint line-through" : "border-brand/50 bg-brand-soft text-brand",
            )}
          >
            {o} <span className="tabular-nums">{counts.get(o)}</span>
          </button>
        ))}
        <div className="relative ml-auto w-64 max-w-full">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setLimit(PAGE);
            }}
            placeholder="Search company, role, place, reason…"
            className="w-full rounded-md border border-border bg-surface/60 py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-faint focus:border-brand/50 focus-visible:ring-2 focus-visible:ring-brand/40"
          />
        </div>
      </div>
      <p className="mt-2 text-xs text-faint tabular-nums">
        Showing {Math.min(limit, rows.length)} of {rows.length} · {scoped.length} jobs in the pipeline · newest first
      </p>

      {rows.length > 0 ? (
        <div className="mt-3 overflow-x-auto rounded-2xl border border-border">
          <table className="w-full min-w-[52rem] text-sm">
            <thead className="bg-surface/60 text-left text-xs uppercase tracking-wide text-faint">
              <tr>
                <th className="px-4 py-2.5 font-medium">Company</th>
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-4 py-2.5 font-medium">Location</th>
                <th className="px-4 py-2.5 font-medium">Outcome</th>
                <th className="hidden px-4 py-2.5 font-medium lg:table-cell">Seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.slice(0, limit).map((j) => (
                <tr key={j.url} className="group align-top transition-colors hover:bg-surface/40">
                  <td className="px-4 py-3 font-medium">
                    <span className="flex items-center gap-2.5">
                      <CompanyLogo name={j.company} size={20} />
                      {j.company}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <a href={j.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 hover:text-brand">
                      {j.role}
                      <ExternalLink aria-hidden="true" className="mt-1 size-3 shrink-0 text-faint" />
                    </a>
                    {j.sieveReason ? (
                      <p className="mt-1 text-xs text-faint">
                        <span className="font-medium text-muted">{j.sieveStage ? `${j.sieveStage} · ` : ""}</span>
                        {j.sieveReason}
                      </p>
                    ) : (
                      j.reason && j.outcome !== "Evaluated" && <p className="mt-1 text-xs text-faint">{j.reason}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted">{j.location ?? "—"}</td>
                  <td className="whitespace-nowrap px-4 py-3">
                    {j.sieve && (
                      <div className="mb-1">
                        <Badge tone={SIEVE_TONE[j.sieve] ?? "muted"}>
                          {SIEVE_LABEL[j.sieve] ?? j.sieve}
                          {j.sieveScore ? ` ${j.sieveScore.toFixed(2)}` : ""}
                        </Badge>
                      </div>
                    )}
                    {j.report ? (
                      <Link href={`/pipeline/${j.report}`}>
                        <Badge tone={TONE[j.outcome]}>{j.outcome} #{j.report}</Badge>
                      </Link>
                    ) : (
                      <Badge tone={TONE[j.outcome]}>{j.outcome}</Badge>
                    )}
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-faint tabular-nums lg:table-cell">{j.postedAt ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-3 rounded-2xl border border-dashed border-border bg-surface/30 px-6 py-12 text-center">
          <p className="font-display text-lg">No matches</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Switch an outcome back on or clear the search.</p>
        </div>
      )}

      {rows.length > limit && (
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => setLimit((l) => l + PAGE * 5)}
            className="rounded-full border border-border px-4 py-2 text-sm font-medium text-muted transition-colors hover:text-foreground"
          >
            Show {Math.min(PAGE * 5, rows.length - limit)} more
          </button>
        </div>
      )}
    </div>
  );
}
