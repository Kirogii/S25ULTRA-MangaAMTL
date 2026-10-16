const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map(), created = [], requests = [];
class Element {
  constructor(tag) { this.tag = tag; this.listeners = {}; this.children = []; created.push(this); }
  set id(value) { this._id = value; elements.set(value, this); }
  get id() { return this._id; }
  append(...children) { this.children.push(...children); }
  before() {}
  setAttribute() {}
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
for (const id of ['ocrMode', 'targetLang']) new Element('select').id = id;
const saved = {serverUrl: 'http://localhost:7860', targetLang: 'fr'};
let enabled = true, fail = false;
const context = {
  Response, Uint8Array, atob,
  document: {getElementById: id => elements.get(id), querySelector: () => null, createElement: tag => new Element(tag)},
  chrome: {storage: {local: {get: async () => saved, set: async value => Object.assign(saved, value)}},
    runtime: {sendMessage: async request => {
      if (request.type === 'androidSettings') return {};
      requests.push(request);
      if (request.method === 'POST' && !fail) enabled = JSON.parse(request.body).enabled;
      const body = fail ? {detail: 'Start Shizuku first'} : {enabled};
      return {success: true, status: fail ? 503 : 200, headers: [], body: Buffer.from(JSON.stringify(body)).toString('base64')};
    }}},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('Extension/android.js', 'utf8'), context);
(async () => {
  await context.mtSamsungControls();
  const select = elements.get('samsungTranslation'), target = elements.get('targetLang');
  assert.equal(select.value, 'samsung'); assert.equal(saved.targetLang, 'en'); assert.equal(target.disabled, true);
  select.value = 'qwen'; await select.listeners.change();
  assert.equal(enabled, false); assert.equal(target.disabled, false);
  assert.equal(requests.at(-1).url, 'http://localhost:7860/v1/samsung/settings');
  fail = true; select.value = 'samsung'; await select.listeners.change();
  assert.equal(select.value, 'qwen'); assert.equal(select.disabled, false);
  assert(created.some(element => element.textContent === 'Start Shizuku first'));
  console.log('Samsung extension settings checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
