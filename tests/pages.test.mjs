import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ensurePages } from '../scripts/ensure-pages.mjs';

const env = { CLOUDFLARE_ACCOUNT_ID: 'a'.repeat(32), CLOUDFLARE_API_TOKEN: 'not-a-real-token' };
const project = () => Response.json({ success: true, result: { name: 'mikawa-insar', production_branch: 'main' } });

test('Pages provision preserves an existing project without writes', async () => {
  const calls = [];
  await ensurePages(env, async (url, options) => { calls.push(options.method); return project(); });
  assert.deepEqual(calls, ['GET']);
});
test('Pages provision creates only the missing project', async () => {
  const calls = [];
  await ensurePages(env, async (url, options) => {
    calls.push({ url, ...options });
    return calls.length === 1 ? new Response(null, { status: 404 }) : project();
  });
  assert.deepEqual(calls.map(c => c.method), ['GET', 'POST']);
  assert.deepEqual(JSON.parse(calls[1].body), { name: 'mikawa-insar', production_branch: 'main' });
});
test('Pages auth and server errors never trigger creation', async () => {
  for (const status of [400, 401, 403, 500]) {
    let count = 0;
    await assert.rejects(ensurePages(env, async () => { count++; return new Response(null, { status }); }), /request failed/);
    assert.equal(count, 1);
  }
});
test('Pages provisioning rejects mismatched project and unsafe account ID', async () => {
  await assert.rejects(ensurePages(env, async () => Response.json({ success: true, result: { name: 'other', production_branch: 'main' } })), /identity/);
  await assert.rejects(ensurePages({ ...env, CLOUDFLARE_ACCOUNT_ID: '../other' }, async () => { throw new Error('Must not call'); }), /32 hex/);
});
