// Browser regression for opening the HTML directly and failed app downloads.
const { chromium } = require('playwright');
const { createServer } = require('node:http');
const { readFile } = require('node:fs/promises');
const { resolve, extname } = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');

(async () => {
  const publishedUrl = 'https://mikawa-insar.pages.dev/';
  const allowed = new Set(['/index.html', '/bootstrap.js', '/style.css', '/controls.css']);
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };
  const server = createServer(async (req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (!allowed.has(path)) { res.writeHead(404); return res.end('Unavailable'); }
    try {
      const data = await readFile(resolve('web', '.' + path));
      res.writeHead(200, { 'Content-Type': types[extname(path)] }); res.end(data);
    } catch { res.writeHead(404); res.end(); }
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
  try {
    const filePage = await browser.newPage();
    const fileErrors = []; filePage.on('pageerror', e => fileErrors.push(e.message));
    // Keep this regression independent of the public service's availability.
    await filePage.route(publishedUrl + '**', route => route.fulfill({
      contentType: 'text/html', body: '<p id="published">Published dashboard</p>' }));
    await filePage.goto(pathToFileURL(resolve('web/index.html')).href);
    await filePage.waitForURL(publishedUrl);
    await filePage.locator('#published').waitFor();
    assert.deepEqual(fileErrors, []);

    const failedPage = await browser.newPage();
    await failedPage.goto(`http://127.0.0.1:${server.address().port}/index.html`);
    await failedPage.locator('#notice.error').waitFor();
    assert.equal(await failedPage.locator('#connection').textContent(), '読み込みエラー');
    assert.equal(await failedPage.locator('#notice a').getAttribute('href'), publishedUrl);
    console.log('PASS: direct-file entry opens published dashboard; failed app download shows recovery link');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exit(1); });
