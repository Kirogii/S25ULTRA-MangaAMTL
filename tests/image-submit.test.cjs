const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../Extension/content.js'), 'utf8');
const start = source.indexOf('  async function processImage(');
const end = source.indexOf('  // ========================================================================', start);
async function check(mime, oversized = false) {
  const original = `data:image/${mime};base64,YWJj`;
  let submitted, canvases = 0, replaced = false;
  const context = vm.createContext({
    Image: class {
      constructor() { this.naturalWidth = oversized ? 10000 : 800; this.naturalHeight = oversized ? 10000 : 1200; }
      set src(value) { this.onload(); }
    },
    collectImage: async () => original,
    document: {createElement: () => { canvases++; return {getContext: () => ({drawImage() {}}), toDataURL: () => 'data:image/png;base64,cG5n'}; }},
    window: {location: {href: 'https://reader.example/chapter'}},
    sendRuntimeMessage: async request => { submitted = request; return {success: true}; },
    finishBackendTranslation: async () => ({image_data_url: 'data:image/png;base64,b3V0'}),
    applyTranslatedSrc: async () => { replaced = true; },
    console: {log() {}},
  });
  vm.runInContext(source.slice(start, end), context);
  const request = () => context.processImage({dataset: {}}, 'http://localhost:7860', false, 'en', 'ja');
  if (oversized) { await assert.rejects(request, /40 megapixels/); assert.equal(submitted, undefined); return; }
  await request();
  assert.equal(submitted.base64Data, mime === 'webp' ? 'data:image/png;base64,cG5n' : original);
  assert.equal(canvases, mime === 'webp' ? 1 : 0);
  assert.equal(replaced, true);
}
(async () => { await check('png'); await check('jpeg'); await check('webp'); await check('png', true); console.log('Image upload: original PNG/JPEG, unsupported-format conversion, size limit passed'); })().catch(error => { console.error(error); process.exitCode = 1; });
