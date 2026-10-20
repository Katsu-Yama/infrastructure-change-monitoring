// Local visual/integration check using Playwright from the Codex runtime.
const { chromium } = require('playwright');
const { createServer } = require('node:http');
const { readFile, mkdir } = require('node:fs/promises');
const { resolve, extname } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
  const server = createServer(async (req, res) => {
    let path = new URL(req.url, 'http://localhost').pathname;
    const empty = path.startsWith('/empty/');
    if (empty) path = path.slice(6);
    if (path === '/') path = '/index.html';
    const file = resolve('dist', '.' + path);
    if (!file.startsWith(resolve('dist') + require('node:path').sep) || (empty && path === '/baseline.json')) { res.writeHead(404); return res.end(); }
    try { const data = await readFile(file); res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream' }); res.end(data); }
    catch { res.writeHead(404); res.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  try {
    await mkdir('output', { recursive: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(address);
    await page.locator('#connection').filter({ hasText: '保存済み履歴' }).waitFor();
    assert.equal(await page.locator('#count').textContent(), '5');
    assert((await page.locator('#notice').textContent()).includes('現在の状態は判定できません'));
    assert((await page.locator('#overlay circle').count()) > 500);
    await page.locator('#candidates button').first().click();
    assert.equal(await page.locator('#detail .chart').count(), 1);
    await page.locator('textarea').fill('現地確認メモ テスト');
    await page.reload();
    await page.locator('textarea').waitFor();
    assert.equal(await page.locator('textarea').inputValue(), '現地確認メモ テスト');
    const download = page.waitForEvent('download'); await page.locator('#export').click();
    assert((await download).suggestedFilename().endsWith('.csv'));
    await page.screenshot({ path: 'output/dashboard-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: 'output/dashboard-mobile.png', fullPage: true });
    await page.goto(address + '/empty/');
    await page.locator('#notice.error').waitFor();
    assert.equal(await page.locator('#connection').textContent(), '未接続');
    assert.deepEqual(errors, []);
    console.log('PASS: real report, stale label, map, chart, local note, CSV, mobile, missing data');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exit(1); });
