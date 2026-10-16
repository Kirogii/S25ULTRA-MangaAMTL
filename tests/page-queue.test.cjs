const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../Extension/content.js'), 'utf8');
const start = source.indexOf('    let nextGroup = 0;');
const end = source.indexOf('    // Every page keeps', start);
assert.ok(start > 0 && end > start);
(async () => {
  for (const pageWorkers of [1, 2]) {
    let active = 0, peak = 0;
    const completed = [];
    const context = vm.createContext({
      pageWorkers, groups: Array.from({length: 9}, (_, i) => [i]), combineAmount: 1,
      overlay: {}, processedImages: 0, images: [], updateOverlay() {}, console: {log() {}},
      runGroup: async (group, index) => {
        active++; peak = Math.max(peak, active);
        await new Promise(resolve => setTimeout(resolve, index % 2 ? 1 : 5));
        completed.push(index); active--;
      },
    });
    await vm.runInContext('(async () => {' + source.slice(start, end) + '})()', context);
    assert.equal(peak, pageWorkers);
    assert.equal(active, 0);
    assert.deepEqual(completed.sort((a, b) => a-b), Array.from({length: 9}, (_, i) => i));
  }
  console.log('Page queue: bounded overlap and exactly-once completion passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
