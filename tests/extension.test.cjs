// Worker regression checks; --phone sends the real extension workflow to ADB localhost.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const phone = process.argv.includes('--phone');
const server = phone ? 'http://127.0.0.1:17860' : 'http://localhost:7860';
const png = fs.readFileSync(path.join(__dirname, '../Images/Raw.png'));
const saved = {serverUrl: phone ? server : 'http://localhost:8000', colorize: true, modelType: 'openrouter'};
const session = {}, rules = [];
let listener, canvasCalls = 0;
const storage = data => ({
  get: async keys => keys == null ? {...data} : Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, data[k]])),
  set: async values => Object.assign(data, values),
  remove: async keys => { for (const key of keys) delete data[key]; },
});
const chrome = {
  runtime: {id: 'testextension', onMessage: {addListener: fn => listener = fn}},
  storage: {local: storage(saved), session: storage(session)},
  alarms: {create: async () => {}, clear: async () => {}, onAlarm: {addListener: () => {}}},
  tabs: {onRemoved: {addListener: () => {}}, onUpdated: {addListener: () => {}}},
  declarativeNetRequest: {updateSessionRules: async change => rules.push(change)},
  scripting: {executeScript: async () => { canvasCalls++; throw new Error('Canvas is CORS-tainted'); }},
};
const calls = [];
async function workerFetch(url, options = {}) {
  calls.push([String(url), options]);
  if (String(url).startsWith('https://cdn.example/')) return new Response(png, {headers: {'Content-Type': 'image/png',
    ...(String(url).includes('oversize') ? {'Content-Length': String(33 * 1024 * 1024)} : {})}});
  if (phone) return fetch(url, options);
  if (String(url).endsWith('/v1/translate')) {
    assert.equal(options.body.get('colorize'), 'false');
    assert.equal(options.body.get('image').size, png.length);
    return Response.json({job_id: 'test-job'});
  }
  return Response.json({status: 'ok'});
}
const context = vm.createContext({chrome, fetch: workerFetch, console, URL, Blob, FormData, Response,
  AbortController, AbortSignal, Uint8Array, ArrayBuffer, atob, btoa, setTimeout, clearTimeout});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../Extension/background.js'), 'utf8'), context);
const message = request => new Promise(resolve => listener(request, {tab: {id: 7, url: 'https://reader.example/chapter'}}, resolve));
async function main() {
  if (phone) {
    for (let attempt = 0; attempt < 30; attempt++) {
      try { if ((await fetch(server + '/health', {signal: AbortSignal.timeout(1000)})).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
  assert.equal((await message({type: 'androidSettings'})).success, true);
  assert.equal(saved.serverUrl, server);
  assert.equal(saved.colorize, false);
  assert.equal(saved.modelType, 'local');
  assert.equal(saved.ocrMode, 'lens');
  assert.equal(saved.inpaintMode, 'blur');
  if (phone) {
    const settings = await message({type: 'backendFetch', url: server + '/SetAllSettings', method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({model_type: 'local', cloud_mode: false, ocr_mode: 'lens', inpaint_mode: 'high'})});
    assert.equal(settings.success, true, settings.error);
    assert.equal(settings.status, 200, Buffer.from(settings.body || '', 'base64').toString());
  }
  const downloaded = await message({type: 'fetchImage', url: 'https://cdn.example/page.png?token="signed"'});
  assert.equal(downloaded.success, true, downloaded.error);
  assert.deepEqual(Buffer.from(downloaded.base64.split(',')[1], 'base64'), png);
  assert.equal(canvasCalls, 0, 'HTTP image bytes must not depend on a readable page canvas');
  assert.equal(rules.length, 2, 'Temporary rule must be added and cleaned up');
  assert.equal(rules[0].addRules[0].condition.initiatorDomains[0], chrome.runtime.id);
  assert.ok(new RegExp(rules[0].addRules[0].condition.regexFilter).test(new URL('https://cdn.example/page.png?token="signed"').href));
  assert.equal((await message({type: 'fetchImage', url: 'https://cdn.example/oversize.png'})).success, false);
  assert.equal((await message({type: 'fetchImage', url: 'javascript:alert(1)'})).success, false);
  const rejected = await message({type: 'backendFetch', url: 'https://wrong-server.example/meta'});
  assert.equal(rejected.success, false);
  const response = await message({type: 'backendFetch', url: server + '/health'});
  assert.equal(response.success, true, response.error);
  assert.equal(JSON.parse(Buffer.from(response.body, 'base64')).status, 'ok');
  const result = await message({type: 'submitImage', serverUrl: server, base64Data: downloaded.base64, colorize: true, targetLang: 'en', ocrLang: 'ja'});
  assert.equal(result.success, true, result.error);
  assert.equal(result.pending, true);
  if (phone) {
    const relay = async (route, options = {}) => {
      const response = await message({type: 'backendFetch', url: server + route, ...options});
      assert.equal(response.success, true, response.error);
      return {status: response.status, body: Buffer.from(response.body, 'base64')};
    };
    const deadline = Date.now() + 900000;
    while (Date.now() < deadline) {
      await relay('/v1/health', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({job_id: result.job_id, active: true})});
      const state = JSON.parse((await relay('/v1/translate/' + result.job_id)).body);
      assert.ok(!['failed', 'cancelled'].includes(state.status), JSON.stringify(state));
      if (state.status === 'completed') {
        const rendered = await relay('/v1/translate/' + result.job_id + '/image', {method: 'POST', headers: {Prefer: 'respond-async'}});
        if (rendered.status === 200) {
          assert.deepEqual(rendered.body.subarray(0, 8), Buffer.from([137,80,78,71,13,10,26,10]));
          assert.ok(!rendered.body.equals(png));
          fs.mkdirSync(path.join(__dirname, '../android/evidence'), {recursive: true});
          fs.writeFileSync(path.join(__dirname, '../android/evidence/extension-android-translated.png'), rendered.body);
          console.log('Extension upload, polling, heartbeat and async PNG handoff passed on the phone');
          await message({type: 'stopTranslationHealth', jobId: result.job_id, active: true});
          return;
        }
        assert.equal(rendered.status, 202, rendered.body.toString());
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error('Phone translation timed out');
  }
  await Promise.all(['parallel-a', 'parallel-b'].map(id => context.registerJobHealth(id, server, 7)));
  assert.ok(session.mangaTranslatorActiveJobs['parallel-a']);
  assert.ok(session.mangaTranslatorActiveJobs['parallel-b']);
  await Promise.all([context.stopJobHealth('parallel-a', true), context.registerJobHealth('parallel-c', server, 7)]);
  assert.equal(session.mangaTranslatorActiveJobs['parallel-a'], undefined);
  assert.ok(session.mangaTranslatorActiveJobs['parallel-b']);
  assert.ok(session.mangaTranslatorActiveJobs['parallel-c']);
  console.log('Extension worker and concurrent heartbeat checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
