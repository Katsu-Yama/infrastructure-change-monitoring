// Explicit, two-phase maintenance for this dedicated project only.
import { generateKeyPairSync, randomBytes, publicEncrypt, privateDecrypt, createCipheriv, createDecipheriv, createHash, constants } from 'node:crypto';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { gzipSync, gunzipSync } from 'node:zlib';

export const PROJECT = 'sxbvyjgzrzynkvounfxy';
const URL = `https://${PROJECT}.supabase.co`;
const BUCKET = 'mikawa-insar-pairs';
const TABLES = { mikawa_reports: 'report_month', mikawa_catalog: 'aoi_id', mikawa_interferograms: 'id' };
const hash = data => createHash('sha256').update(data).digest('hex');
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])])) : value;
export const inventoryDigest = value => hash(JSON.stringify(canonical(value)));

export function validateProject(url) {
  if (url !== URL) throw Error('Maintenance is restricted to the dedicated mikawa-insar project');
}

export function assertResetAllowed(inventory, expected, confirmation) {
  if (confirmation !== PROJECT || !/^[a-f0-9]{64}$/.test(expected || '') || inventoryDigest(inventory) !== expected)
    throw Error('Reset confirmation or backed-up inventory digest does not match');
}

export function encryptBackup(plain, publicKey, digest) {
  const key = randomBytes(32), iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(plain), cipher.final()]);
  const header = { digest, sha256: hash(plain), iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'),
    key: publicEncrypt({ key: publicKey, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, key).toString('base64') };
  key.fill(0);
  return Buffer.concat([Buffer.from('MIKAWA1\n' + JSON.stringify(header) + '\n'), encrypted]);
}

export function decryptBackup(archive, privateKey) {
  const first = archive.indexOf(10), second = archive.indexOf(10, first + 1);
  if (archive.subarray(0, first).toString() !== 'MIKAWA1' || second < 0) throw Error('Invalid encrypted backup');
  const header = JSON.parse(archive.subarray(first + 1, second));
  const key = privateDecrypt({ key: privateKey, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, Buffer.from(header.key, 'base64'));
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(header.iv, 'base64'));
  decipher.setAuthTag(Buffer.from(header.tag, 'base64'));
  const plain = Buffer.concat([decipher.update(archive.subarray(second + 1)), decipher.final()]);
  key.fill(0);
  if (hash(plain) !== header.sha256) throw Error('Backup digest mismatch');
  return { plain, digest: header.digest };
}

function cacheDirectory(path) {
  const target = resolve(path), root = resolve('.cache');
  if (!target.startsWith(root + sep)) throw Error('Local backup keys and plaintext must stay under .cache');
  mkdirSync(target, { recursive: true });
  return target;
}

function client() {
  validateProject(process.env.SUPABASE_URL);
  const key = process.env.SUPABASE_SECRET_KEY;
  if (!key) throw Error('Missing private Supabase key');
  const headers = { apikey: key, 'Content-Type': 'application/json' };
  if (!key.startsWith('sb_secret_')) headers.Authorization = 'Bearer ' + key;
  return async (path, method = 'GET', data, binary = false) => {
    for (let attempt = 0; ; attempt++) {
      let response;
      try {
        response = await fetch(URL + path, { method, headers,
          body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(90000) });
      } catch {
        if (attempt >= 3) throw Error('Supabase maintenance connection failed');
      }
      if (response?.ok) {
        const buffer = Buffer.from(await response.arrayBuffer());
        if (binary) {
          if (buffer.length >= 5 * 1024 ** 2) throw Error('Unexpectedly large stored object');
          return buffer;
        }
        if (!buffer.length) return null;
        try { return JSON.parse(buffer); } catch { throw Error('Invalid maintenance API response'); }
      }
      if (response && (attempt >= 3 || (response.status !== 429 && response.status < 500)))
        throw Error(`Supabase maintenance HTTP ${response.status} ${method} ${path.split('?')[0]}`);
      await new Promise(done => setTimeout(done, [2000, 5000, 10000][attempt]));
    }
  };
}

async function inventory(api) {
  const buckets = await api('/storage/v1/bucket');
  if (buckets.length !== 1 || buckets[0].id !== BUCKET || buckets[0].public)
    throw Error('Unexpected storage scope; refusing maintenance');
  const root = await api('/storage/v1/object/list/' + BUCKET, 'POST', { prefix: '', limit: 1000 });
  if (root.some(o => o.name !== 'v1')) throw Error('Unexpected object outside monitoring prefix');
  const entries = await api('/storage/v1/object/list/' + BUCKET, 'POST', {
    prefix: 'v1', limit: 1000, offset: 0, sortBy: { column: 'name', order: 'asc' } });
  if (entries.length >= 1000 || entries.some(o => !/^[a-f0-9]{32}\.zip$/.test(o.name)))
    throw Error('Incomplete or unexpected storage inventory');
  const objects = entries.map(o => ({ name: 'v1/' + o.name, size: Number(o.metadata?.size) }));
  if (objects.some(o => !Number.isSafeInteger(o.size) || o.size <= 0)) throw Error('Invalid object size');
  const tables = {};
  for (const [name, primary] of Object.entries(TABLES)) {
    tables[name] = await api(`/rest/v1/${name}?select=*&order=${primary}.asc&limit=1000`);
    if (tables[name].length >= 1000) throw Error('Incomplete table inventory');
  }
  return { project: PROJECT, tables, objects };
}

function summary(value) {
  return { project: PROJECT, inventory_digest: inventoryDigest(value),
    tables: Object.fromEntries(Object.entries(value.tables).map(([name, rows]) => [name, rows.length])),
    objects: value.objects.length, bytes: value.objects.reduce((sum, o) => sum + o.size, 0) };
}

async function main() {
  const [action, arg1, arg2, arg3] = process.argv.slice(2);
  if (action === 'keygen') {
    const dir = cacheDirectory(arg1);
    const pair = generateKeyPairSync('rsa', { modulusLength: 3072,
      publicKeyEncoding: { type: 'spki', format: 'pem' }, privateKeyEncoding: { type: 'pkcs8', format: 'pem' } });
    writeFileSync(resolve(dir, 'private-key.pem'), pair.privateKey, { mode: 0o600, flag: 'wx' });
    writeFileSync(resolve(dir, 'public-key.pem'), pair.publicKey, { mode: 0o600, flag: 'wx' });
    console.log('PUBLIC_KEY_BASE64=' + Buffer.from(pair.publicKey).toString('base64'));
    return;
  }
  if (action === 'decrypt') {
    const { plain, digest } = decryptBackup(readFileSync(arg1), readFileSync(arg2));
    const data = JSON.parse(gunzipSync(plain));
    if (inventoryDigest(data.inventory) !== digest || data.files.length !== data.inventory.objects.length)
      throw Error('Decrypted inventory does not match backup');
    for (const file of data.files) {
      const bytes = Buffer.from(file.data, 'base64');
      const object = data.inventory.objects.find(o => o.name === file.name);
      if (!object || object.size !== bytes.length || file.sha256 !== hash(bytes)) throw Error('Backed-up object verification failed');
    }
    const dir = cacheDirectory(arg3);
    writeFileSync(resolve(dir, 'backup.json.gz'), plain, { mode: 0o600, flag: 'wx' });
    writeFileSync(resolve(dir, 'manifest.json'), JSON.stringify(summary(data.inventory), null, 2), { mode: 0o600, flag: 'wx' });
    console.log(JSON.stringify({ verified_local_backup: true, ...summary(data.inventory) }));
    return;
  }
  if (!['backup', 'reset'].includes(action) || process.env.RESET_CONFIRMATION !== PROJECT)
    throw Error('Explicit maintenance action and project confirmation are required');
  const api = client(), current = await inventory(api);
  if (action === 'backup') {
    const publicKey = Buffer.from(process.env.BACKUP_PUBLIC_KEY || '', 'base64').toString();
    if (!publicKey.startsWith('-----BEGIN PUBLIC KEY-----')) throw Error('A public encryption key is required');
    const files = [];
    for (const object of current.objects) {
      const bytes = await api('/storage/v1/object/authenticated/' + BUCKET + '/' + object.name, 'GET', undefined, true);
      if (bytes.length !== object.size) throw Error('Object size changed during backup');
      files.push({ name: object.name, data: bytes.toString('base64'), sha256: hash(bytes) });
      if (files.length % 20 === 0) console.log(`BACKUP ${files.length}/${current.objects.length}`);
    }
    const plain = gzipSync(JSON.stringify({ inventory: current, files }));
    mkdirSync('output', { recursive: true });
    writeFileSync('output/monitoring-backup.enc', encryptBackup(plain, publicKey, inventoryDigest(current)));
    console.log(JSON.stringify({ encrypted_backup: true, ...summary(current) }));
    return;
  }
  assertResetAllowed(current, process.env.EXPECTED_DIGEST, process.env.RESET_CONFIRMATION);
  if (current.objects.length) await api('/storage/v1/object/' + BUCKET, 'DELETE', { prefixes: current.objects.map(o => o.name) });
  for (const name of ['mikawa_interferograms', 'mikawa_catalog', 'mikawa_reports'])
    await api(`/rest/v1/${name}?${TABLES[name]}=not.is.null`, 'DELETE');
  const empty = await inventory(api);
  if (empty.objects.length || Object.values(empty.tables).some(rows => rows.length)) throw Error('Reset verification failed');
  console.log(JSON.stringify({ reset_verified: true, ...summary(empty) }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
  main().catch(error => { console.error(error.message); process.exit(1); });
