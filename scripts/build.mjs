import { mkdir, cp, writeFile, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
await mkdir(resolve(root, 'dist'), { recursive: true });
await cp(resolve(root, 'web'), resolve(root, 'dist'), { recursive: true });
const url = process.env.SUPABASE_URL || '';
const key = process.env.SUPABASE_PUBLISHABLE_KEY || '';
if (url && !/^https:\/\/[a-z0-9]+\.supabase\.co$/.test(url)) throw Error('Invalid Supabase URL');
if (key && !key.startsWith('sb_publishable_')) {
  // Legacy anon JWT is supported only after confirming its role.
  let payload;
  try { payload = JSON.parse(Buffer.from(key.split('.')[1], 'base64url')); } catch { throw Error('Publishable/anon key required'); }
  if (payload.role !== 'anon') throw Error('Refusing to expose privileged key');
}
let snapshotVerified = false;
// A real baseline, when available, is bundled as read-only fallback. No synthetic data.
try {
  const report = await readFile(resolve(root, 'output/report.json'));
  await writeFile(resolve(root, 'dist/baseline.json'), report);
  try {
    const published = JSON.parse(await readFile(resolve(root, 'output/published.json'), 'utf8'));
    snapshotVerified = published.payload_digest === createHash('sha256').update(report).digest('hex');
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
} catch (error) { if (error.code !== 'ENOENT') throw error; }
await writeFile(resolve(root, 'dist/config.json'), JSON.stringify({ supabaseUrl: url, publishableKey: key, snapshotVerified }));
console.log(`Built static site. Database configured: ${Boolean(url && key)}`);
