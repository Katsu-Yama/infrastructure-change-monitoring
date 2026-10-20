// Provision only this free, static Pages project. Never change other projects.
import { pathToFileURL } from 'node:url';

export async function ensurePages(env = process.env, request = fetch) {
  const account = env.CLOUDFLARE_ACCOUNT_ID;
  const token = env.CLOUDFLARE_API_TOKEN;
  if (!/^[a-f0-9]{32}$/i.test(account || '') || !token) {
    throw new Error('Cloudflare account ID (32 hex characters) and API token are required');
  }
  const base = `https://api.cloudflare.com/client/v4/accounts/${account}/pages/projects`;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const call = (url, method = 'GET', body) => request(url, {
    method, headers, ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(30000), redirect: 'error',
  });
  const check = async response => {
    if (!response.ok) throw new Error(`Cloudflare Pages request failed (HTTP ${response.status}); check account ID and Pages Write permission`);
    const data = await response.json();
    if (!data.success || data.result?.name !== 'mikawa-insar' || data.result?.production_branch !== 'main') {
      throw new Error('Cloudflare project identity or production branch did not match');
    }
    return data.result;
  };
  const existing = await call(`${base}/mikawa-insar`);
  if (existing.status !== 404) return check(existing);
  const created = await call(base, 'POST', { name: 'mikawa-insar', production_branch: 'main' });
  // Another deployment can win the initial creation race; verify its identity.
  if (created.status === 409) return check(await call(`${base}/mikawa-insar`));
  return check(created);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await ensurePages();
    console.log('Cloudflare Pages project mikawa-insar is ready');
  } catch (error) {
    // Do not print response bodies, headers, or credentials.
    console.error(error.message);
    process.exitCode = 1;
  }
}
