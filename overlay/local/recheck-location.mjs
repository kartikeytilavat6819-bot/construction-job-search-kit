// Re-check data/scan-history.tsv rows marked skipped_location against the CURRENT portals.yml
// location_filter (scan.mjs's own buildLocationFilter). Rows skipped while the filter was narrower (e.g. one
// region only) are real US jobs the scanner will otherwise ignore for 30 days. Run it after widening the filter.
//
//   node local/recheck-location.mjs            # dry run: counts + samples
//   node local/recheck-location.mjs --apply    # restore: status -> added, append to data/pipeline.md Pending
//
// Keeps out: rows the US filter still rejects, rows local/apply_screen.py moved out as foreign
// (data/discard.log "outside the US" / AtkinsRealis non-US), and postings older than max_posting_age_days.
import { readFileSync, writeFileSync, existsSync, copyFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import * as yaml from 'js-yaml';
import { buildLocationFilter } from '../scan.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const apply = process.argv.includes('--apply');
const portals = yaml.load(readFileSync(join(ROOT, 'portals.yml'), 'utf8'));
const pass = buildLocationFilter(portals.location_filter || {});
const maxAge = Number(portals.max_posting_age_days || 0);

const histPath = join(ROOT, 'data', 'scan-history.tsv');
const lines = readFileSync(histPath, 'utf8').split('\n');
const hdr = lines[0].split('\t');
const col = (n) => hdr.indexOf(n);
const [cU, cT, cC, cS, cL, cP] = ['url', 'title', 'company', 'status', 'location', 'posted_at'].map(col);

const foreign = new Set();
const discard = join(ROOT, 'data', 'discard.log');
if (existsSync(discard)) {
  for (const l of readFileSync(discard, 'utf8').split('\n')) {
    const [, url, why] = l.split('\t');
    if (url && /outside the US|non-US/i.test(why || '')) foreign.add(url);
  }
}
// same UK / French-title guard as local/apply_screen.py
const UK = /\b(UK|U\.K\.|United Kingdom)\b/;
const FR = /ing[ée]nieur|charg[ée]\(e\)|g[ée]nie civil|\(e\)/i;

const restore = [];
const stats = { checked: 0, still_blocked: 0, foreign_screen: 0, too_old: 0, restore: 0 };
const byCo = {};
for (let i = 1; i < lines.length; i++) {
  const c = lines[i].split('\t');
  if (c[cS] !== 'skipped_location') continue;
  stats.checked++;
  const url = c[cU], title = c[cT] || '', loc = c[cL] || '';
  if (foreign.has(url) || UK.test(title) || FR.test(title)) { stats.foreign_screen++; continue; }
  if (!pass(loc, url)) { stats.still_blocked++; continue; }
  const posted = Date.parse(c[cP] || '');
  if (maxAge && posted && (Date.now() - posted) / 864e5 > maxAge) { stats.too_old++; continue; }
  stats.restore++;
  byCo[c[cC]] = (byCo[c[cC]] || 0) + 1;
  restore.push(i);
}
console.log(stats);
console.log('restorable by company:', Object.entries(byCo).sort((a, b) => b[1] - a[1]).slice(0, 25));
for (const i of restore.slice(0, 12)) {
  const c = lines[i].split('\t');
  console.log('  ', c[cC], '|', c[cT], '|', c[cL]);
}
if (!apply) { console.log('\n(dry run - pass --apply to restore)'); process.exit(0); }

const pipePath = join(ROOT, 'data', 'pipeline.md');
copyFileSync(histPath, histPath.replace('.tsv', `.backup-before-recheck.tsv`));
copyFileSync(pipePath, pipePath.replace('.md', `.backup-before-recheck.md`));
let pipe = readFileSync(pipePath, 'utf8');
const have = new Set([...pipe.matchAll(/^- \[[ x]\] ~?~?(\S+)/gm)].map((m) => m[1]));
const add = [];
for (const i of restore) {
  const c = lines[i].split('\t');
  c[cS] = 'added';
  lines[i] = c.join('\t');
  if (have.has(c[cU])) continue;
  const posted = c[cP] ? ` | posted: ${c[cP].slice(0, 10)}` : '';
  add.push(`- [ ] ${c[cU]} | ${c[cC]} | ${c[cT]} | ${(c[cL] || '').replace(/\|/g, '/')}${posted}`);
}
writeFileSync(histPath, lines.join('\n'));
const m = pipe.match(/^## Processed/m);
pipe = m ? pipe.slice(0, m.index) + add.join('\n') + '\n\n' + pipe.slice(m.index) : pipe + '\n' + add.join('\n') + '\n';
writeFileSync(pipePath, pipe);
console.log(`restored ${restore.length} history rows; appended ${add.length} to pipeline.md Pending (backups *.backup-before-recheck.*)`);
