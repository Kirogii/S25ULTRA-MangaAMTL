const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../Extension/content.js'), 'utf8');
const start = source.indexOf('  async function finishBackendTranslation(');
const end = source.indexOf('  async function sendRuntimeMessage(', start);
assert.ok(start > 0 && end > start);
(async () => {
  for (const supportsWait of [true, false]) {
    let polls = 0;
    const delays = [];
    const context = vm.createContext({
      Date, console: {log() {}},
      setTimeout(resolve, delay) { delays.push(delay); resolve(); },
      blobToDataUrl: async () => 'data:image/png;base64,UE5H',
      chrome: {runtime: {sendMessage: async () => {}}},
      fetch: async (url) => {
        if (url.endsWith('/image')) return {ok: true, status: 200, blob: async () => ({size: 3})};
        assert.ok(url.endsWith('?wait=0.5'));
        return {ok: true, headers: {get: () => supportsWait ? '1' : null},
          json: async () => ({status: ++polls === 1 ? 'processing' : 'completed'})};
      },
    });
    vm.runInContext(source.slice(start, end), context);
    const result = await context.finishBackendTranslation('http://localhost:7860',
      {success: true, pending: true, job_id: 'sample'});
    assert.equal(result.success, true);
    assert.equal(polls, 2);
    assert.deepEqual(delays, supportsWait ? [] : [100]);
  }
  console.log('Status waits: immediate wake and legacy polling fallback passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
