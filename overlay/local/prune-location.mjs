// Move Pending rows in data/pipeline.md whose location the CURRENT portals.yml location_filter rejects
// to Processed (reason logged to data/discard.log), and mark their scan-history rows skipped_location so the
// web Today/Explore pages stop showing them.  node local/prune-location.mjs [--dry-run]
import { readFileSync, writeFileSync, appendFileSync, copyFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import * as yaml from 'js-yaml';
import { buildLocationFilter } from '../scan.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const dry = process.argv.includes('--dry-run');
const portals = yaml.load(readFileSync(join(ROOT, 'portals.yml'), 'utf8'));
const pass = buildLocationFilter(portals.location_filter || {});
const pipePath = join(ROOT, 'data', 'pipeline.md');
const histPath = join(ROOT, 'data', 'scan-history.tsv');

const lines = readFileSync(pipePath, 'utf8').split('\n');
const keep = [], moved = [];
for (const l of lines) {
  if (l.startsWith('- [ ] ')) {
    const parts = l.slice(6).split(' | ').map((s) => s.trim());
    const [url, company = '', title = ''] = parts;
    const loc = parts.slice(3).find((p) => !p.startsWith('posted:')) || '';
    // Junk from the linkedin-alerts plugin: alert-email links ("manage alerts", "see all jobs", search pages)
    // parsed as jobs, often with a blank company. Not postings; never fetch LinkedIn pages.
    // "(LinkedIn)" rows: the plugin stamps one alert's title on every link in the email, so the real job is
    // unknown and LinkedIn pages may not be fetched. Check those alerts in LinkedIn/Gmail directly.
    if (!company || company === '(LinkedIn)' || (/linkedin\.com\//i.test(url) && !/linkedin\.com\/(comm\/)?jobs\/view\/\d+/i.test(url))) {
      moved.push({ url, company: company || '(none)', title, loc: 'not a job posting (LinkedIn alert/search link)' });
      continue;
    }
    if (loc && !pass(loc, url)) { moved.push({ url, company, title, loc }); continue; }
  }
  keep.push(l);
}
const by = {};
for (const m of moved) by[m.company] = (by[m.company] || 0) + 1;
console.log(`${moved.length} pending rows outside the US`, Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 12));
for (const m of moved.slice(0, 8)) console.log('  ', m.company, '|', m.title, '|', m.loc);
if (dry || !moved.length) process.exit(0);

copyFileSync(pipePath, pipePath.replace('.md', '.backup-before-prune.md'));
copyFileSync(histPath, histPath.replace('.tsv', '.backup-before-prune.tsv'));
const p = keep.findIndex((l) => l.trim().toLowerCase().startsWith('## processed'));
const rows = moved.map((m) => `- [x] ~~${m.url} | ${m.company} | ${m.title}~~ - outside the US (${m.loc.replace(/\|/g, '/').slice(0, 60)})`);
if (p >= 0) keep.splice(p + 1, 0, ...rows); else keep.push('', '## Processed', ...rows);
writeFileSync(pipePath, keep.join('\n'));
const now = new Date().toISOString();
appendFileSync(join(ROOT, 'data', 'discard.log'), moved.map((m) => `${now}\t${m.url}\toutside the US (${m.loc})\n`).join(''));
const urls = new Set(moved.map((m) => m.url));
const hist = readFileSync(histPath, 'utf8').split('\n');
let n = 0;
for (let i = 1; i < hist.length; i++) {
  const c = hist[i].split('\t');
  if (urls.has(c[0]) && c[5] !== 'skipped_location') { c[5] = 'skipped_location'; hist[i] = c.join('\t'); n++; }
}
writeFileSync(histPath, hist.join('\n'));
console.log(`moved ${moved.length} rows to Processed; ${n} history rows -> skipped_location (backups *.backup-before-prune.*)`);
