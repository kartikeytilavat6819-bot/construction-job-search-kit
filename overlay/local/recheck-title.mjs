// Re-check scan-history rows marked skipped_title against the CURRENT portals.yml title_filter (+ location filter).
// Used after widening the title filter so already-seen postings aren't ignored for 30 days.
//   node local/recheck-title.mjs [--apply] [--state MA]   (--state XX: only rows located in that US state)
import { readFileSync, writeFileSync, copyFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import * as yaml from 'js-yaml';
import { buildLocationFilter, matchedTitleKeywords } from '../scan.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const apply = process.argv.includes('--apply');
const stateArg = (process.argv.includes('--state') ? process.argv[process.argv.indexOf('--state') + 1] || '' : '').toUpperCase();
const portals = yaml.load(readFileSync(join(ROOT, 'portals.yml'), 'utf8'));
const locOk = buildLocationFilter(portals.location_filter || {});
const histPath = join(ROOT, 'data', 'scan-history.tsv');
const lines = readFileSync(histPath, 'utf8').split('\n');
const hdr = lines[0].split('\t');
const [cU, cT, cC, cS, cL, cP] = ['url', 'title', 'company', 'status', 'location', 'posted_at'].map((n) => hdr.indexOf(n));
const maxAge = Number(portals.max_posting_age_days || 0);
const STATE_NAMES = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut',
  DE: 'Delaware', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa',
  KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan',
  MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire',
  NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio',
  OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota',
  TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia',
  WI: 'Wisconsin', WY: 'Wyoming', DC: 'District of Columbia',
};
// the 2-letter code is matched case-sensitively ("ME" / "IN" / "OR" must not match ordinary words)
const IN_STATE = stateArg ? new RegExp(`\\b${stateArg}\\b|US-${stateArg}-|${STATE_NAMES[stateArg] ? `(${STATE_NAMES[stateArg]})` : '^$'}`) : null;
const restore = [];
for (let i = 1; i < lines.length; i++) {
  const c = lines[i].split('\t');
  if (c[cS] !== 'skipped_title') continue;
  const m = matchedTitleKeywords(c[cT] || '', portals.title_filter);
  const passes = Array.isArray(m) ? m.length > 0 : !!m;
  if (!passes) continue;
  // matchedTitleKeywords reports positives only; re-apply the negative list
  const neg = (portals.title_filter.negative || []).some((k) => {
    const w = k.startsWith('word:') ? new RegExp(`\\b${k.slice(5).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i') : null;
    return w ? w.test(c[cT]) : (c[cT] || '').toLowerCase().includes(k.toLowerCase());
  });
  if (neg || !locOk(c[cL] || '', c[cU])) continue;
  const posted = Date.parse(c[cP] || '');
  if (maxAge && posted && (Date.now() - posted) / 864e5 > maxAge) continue;
  if (IN_STATE && !IN_STATE.test(c[cL] || '')) continue;
  restore.push(i);
}
console.log(`${restore.length} skipped_title rows now pass the title filter${stateArg ? ` (${stateArg})` : ''}`);
for (const i of restore.slice(0, 40)) { const c = lines[i].split('\t'); console.log('  ', c[cC], '|', c[cT], '|', c[cL]); }
if (!apply) process.exit(0);
const pipePath = join(ROOT, 'data', 'pipeline.md');
copyFileSync(histPath, histPath.replace('.tsv', '.backup-before-title-recheck.tsv'));
copyFileSync(pipePath, pipePath.replace('.md', '.backup-before-title-recheck.md'));
let pipe = readFileSync(pipePath, 'utf8');
const have = new Set([...pipe.matchAll(/^- \[[ x]\] ~?~?(\S+)/gm)].map((m) => m[1]));
const add = [];
for (const i of restore) {
  const c = lines[i].split('\t');
  c[cS] = 'added';
  lines[i] = c.join('\t');
  if (!have.has(c[cU])) add.push(`- [ ] ${c[cU]} | ${c[cC]} | ${c[cT]} | ${(c[cL] || '').replace(/\|/g, '/')}`);
}
writeFileSync(histPath, lines.join('\n'));
const m = pipe.match(/^## Processed/m);
pipe = m ? pipe.slice(0, m.index) + add.join('\n') + '\n\n' + pipe.slice(m.index) : pipe + '\n' + add.join('\n') + '\n';
writeFileSync(pipePath, pipe);
console.log(`restored ${restore.length}; appended ${add.length} to pipeline.md Pending`);
