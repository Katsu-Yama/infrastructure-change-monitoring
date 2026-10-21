// Local visual/integration check using Playwright from the Codex runtime.
const { chromium } = require('playwright');
const { createServer } = require('node:http');
const { readFile, mkdir } = require('node:fs/promises');
const { resolve, extname } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const settings = JSON.parse(await readFile('dist/config.json', 'utf8'));
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
  const server = createServer(async (req, res) => {
    let path = new URL(req.url, 'http://localhost').pathname;
    const empty = path.startsWith('/empty/');
    if (empty) path = path.slice(6);
    if (path === '/') path = '/index.html';
    if (empty && path === '/config.json') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ supabaseUrl: '', publishableKey: '', snapshotVerified: false }));
    }
    const file = resolve('dist', '.' + path);
    if (!file.startsWith(resolve('dist') + require('node:path').sep) || (empty && path === '/baseline.json')) { res.writeHead(404); return res.end(); }
    try { const data = await readFile(file); res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream' }); res.end(data); }
    catch { res.writeHead(404); res.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = process.env.DASHBOARD_URL || `http://127.0.0.1:${server.address().port}`;
  const snapshot = process.env.DASHBOARD_URL
    ? await (await fetch(new URL('baseline.json', address))).json()
    : JSON.parse(await readFile('dist/baseline.json', 'utf8'));
  const publicSettings = process.env.DASHBOARD_URL
    ? await (await fetch(new URL('config.json', address))).json() : settings;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  try {
    await mkdir('output', { recursive: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(address);
    const origin = publicSettings.snapshotVerified ? 'Supabase保存済みスナップショット' : '保存済み履歴';
    await page.locator('#connection').filter({ hasText: origin }).waitFor();
    assert.equal(await page.locator('#count').textContent(), String(snapshot.summary.candidate_count));
    assert.equal(await page.locator('#observed').textContent(), snapshot.last_observed);
    const notice = await page.locator('#notice').textContent();
    assert(notice.includes(snapshot.operational_monthly_insar ? '月次InSARの暫定評価' : '公開InSARの履歴評価'));
    if (snapshot.stale) assert(notice.includes('現在の状態は判定できません'));
    const initialDirection = await page.locator('#direction').inputValue();
    for (const source of snapshot.sources) {
      await page.locator('#direction').selectOption(source.id);
      const points = snapshot.points.filter(p => p.source_id === source.id);
      assert.equal(await page.locator('#overlay circle').count(), points.length);
      const usable = points.findIndex(p => p.quality === 'usable' && p.series.at(-1) !== null);
      if (usable >= 0) {
        await page.locator('#overlay circle').nth(usable).click({ force: true });
        assert((await page.locator('#detail').textContent()).includes(source.direction === 'ascending' ? '北行' : '南行'));
        assert((await page.locator('#detail .chart').textContent()).includes(source.dates.at(-1)));
      }
    }
    await page.locator('#direction').selectOption(initialDirection);
    const primaryPoints = snapshot.points.filter(p => p.source_id === initialDirection);
    assert.equal(await page.locator('#overlay circle').count(), primaryPoints.length);
    assert.equal(await page.locator('#candidates button').count(), snapshot.summary.candidate_count);
    await page.locator('#overlay circle').nth(primaryPoints.findIndex(p => p.quality === 'usable')).click({ force: true });
    assert.equal(await page.locator('#detail .chart').count(), 1);
    await page.locator('textarea').fill('現地確認メモ テスト');
    await page.reload();
    await page.locator('#connection').filter({ hasText: origin }).waitFor();
    await page.locator('#overlay circle').nth(primaryPoints.findIndex(p => p.quality === 'usable')).click({ force: true });
    await page.locator('textarea').waitFor();
    assert.equal(await page.locator('textarea').inputValue(), '現地確認メモ テスト');
    const download = page.waitForEvent('download'); await page.locator('#export').click();
    assert((await download).suggestedFilename().endsWith('.csv'));
    await page.screenshot({ path: 'output/dashboard-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: 'output/dashboard-mobile.png', fullPage: true });
    if (!process.env.DASHBOARD_URL) {
      await page.goto(address + '/empty/');
      await page.locator('#notice.error').waitFor();
      assert.equal(await page.locator('#connection').textContent(), '未接続');
    }
    assert.deepEqual(errors, []);
    console.log(`PASS: ${process.env.DASHBOARD_URL ? 'public Cloudflare' : 'local'} report through ${snapshot.last_observed}, provenance label, map, chart, local note, CSV, mobile${process.env.DASHBOARD_URL ? '' : ', missing data'}`);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exit(1); });
