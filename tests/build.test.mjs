import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

test('public build rejects privileged Supabase credentials', () => {
  const r = spawnSync(process.execPath, ['scripts/build.mjs'], { env: { ...process.env, SUPABASE_PUBLISHABLE_KEY: 'sb_secret_never_public' }, encoding: 'utf8' });
  assert.notEqual(r.status, 0);
});
test('public build accepts publishable key and contains no write credential', () => {
  const r = spawnSync(process.execPath, ['scripts/build.mjs'], { env: { ...process.env, SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test', SUPABASE_SECRET_KEY: 'sb_secret_never_public' }, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  const config = readFileSync('dist/config.json', 'utf8');
  assert(!config.includes('sb_secret'));
  assert.equal(JSON.parse(config).publishableKey, 'sb_publishable_test');
});
