import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import { PROJECT, validateProject, inventoryDigest, assertResetAllowed, encryptBackup, decryptBackup } from '../scripts/reset-monitoring.mjs';

const keys = generateKeyPairSync('rsa', { modulusLength: 2048 });
const snapshot = { project: PROJECT, tables: { reports: [{ bbox: [1, 2, 3, 4] }] }, objects: [] };

test('encrypted backup restores every byte and detects tampering', () => {
  const bytes = Buffer.from('private numerical archive\0\x01\xff');
  const sealed = encryptBackup(bytes, keys.publicKey, inventoryDigest(snapshot));
  assert(!sealed.includes(bytes));
  assert.deepEqual(decryptBackup(sealed, keys.privateKey).plain, bytes);
  const damaged = Buffer.from(sealed); damaged[damaged.length - 1] ^= 1;
  assert.throws(() => decryptBackup(damaged, keys.privateKey));
});

test('reset requires exact dedicated project and verified unchanged inventory', () => {
  validateProject(`https://${PROJECT}.supabase.co`);
  assert.throws(() => validateProject('https://another-project.supabase.co'));
  assertResetAllowed(snapshot, inventoryDigest(snapshot), PROJECT);
  assert.throws(() => assertResetAllowed(snapshot, inventoryDigest(snapshot), 'another-project'));
  assert.throws(() => assertResetAllowed(snapshot, '0'.repeat(64), PROJECT));
  assert.throws(() => assertResetAllowed({ ...snapshot, objects: [{ name: 'new.zip' }] }, inventoryDigest(snapshot), PROJECT));
});

test('inventory digest ignores field ordering but detects changed data', () => {
  assert.equal(inventoryDigest({ a: 1, b: 2 }), inventoryDigest({ b: 2, a: 1 }));
  assert.notEqual(inventoryDigest(snapshot), inventoryDigest({ ...snapshot, tables: {} }));
});
