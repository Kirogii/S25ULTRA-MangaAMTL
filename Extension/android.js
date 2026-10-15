// Android transport: page-origin fetches cannot reach localhost reliably.
var mtAndroidReady = chrome.runtime.sendMessage({type: 'androidSettings'});

async function mtBackendFetch(url, options = {}) {
  const reply = await chrome.runtime.sendMessage({type: 'backendFetch', url: String(url),
    method: options.method || 'GET', headers: options.headers || {}, body: options.body});
  if (!reply?.success) throw new Error(reply?.error || 'Android server is unavailable');
  const bytes = Uint8Array.from(atob(reply.body), character => character.charCodeAt(0));
  return new Response([204, 205, 304].includes(reply.status) ? null : bytes, {status: reply.status, headers: reply.headers});
}

function mtAndroidControls() {
  for (const id of ['colorize', 'cloudMode', 'freeOpenRouter', 'optFreeOpenRouter']) {
    const control = document.getElementById(id);
    if (control) { control.checked = false; control.disabled = true; if (control.closest('.checkbox-group')) control.closest('.checkbox-group').style.display = 'none'; }
  }
  for (const id of ['modelType', 'optModelType']) {
    const select = document.getElementById(id);
    if (select) { for (const option of [...select.options]) if (option.value !== 'local') option.remove(); select.value = 'local'; select.disabled = true; }
  }
  for (const id of ['ocrMode', 'optOcrMode']) {
    const select = document.getElementById(id);
    if (!select) continue;
    for (const option of [...select.options]) {
      if (!['lens', 'hayai', 'glm'].includes(option.value)) option.remove();
      else option.textContent = {lens: 'Google Lens — cloud OCR', hayai: 'Local NPU OCR', glm: 'Local NPU OCR — Korean'}[option.value];
    }
  }
  for (const id of ['inpaintMode', 'optInpaintMode']) {
    const select = document.getElementById(id);
    if (!select) continue;
    for (const option of [...select.options]) {
      if (option.value === 'low') option.remove();
      else if (option.value === 'high') option.textContent = 'LaMa — NPU inpainting';
    }
  }
  for (const id of ['contextLevel', 'optContextLevel']) document.querySelector(`#${id} option[value="high"]`)?.remove();
  for (const id of ['contextHighNote', 'optContextHighNote']) { const note = document.getElementById(id); if (note) note.hidden = true; }
  for (const id of ['customRepo', 'customFile', 'installModelBtn']) {
    const control = document.getElementById(id);
    if (control) control.disabled = true;
  }
  const install = document.getElementById('installModelBtn');
  if (install) {
    const link = document.createElement('a');
    link.textContent = 'Find and download S25 Ultra NPU models';
    link.style.cssText = 'display:block;color:#8ecbff;margin:12px 0';
    link.onclick = async event => {
      event.preventDefault();
      const {serverUrl} = await chrome.storage.local.get('serverUrl');
      await chrome.tabs.create({url: serverUrl.replace(/\/$/, '') + '/models'});
    };
    link.href = 'http://localhost:7860/models';
    document.getElementById('modelsTable').before(link);
  }
  return mtSamsungControls();
}

async function mtSamsungControls() {
  const anchor = document.getElementById('ocrMode') || document.getElementById('optOcrMode');
  if (!anchor || document.getElementById('samsungTranslation')) return;
  const box = document.createElement('div');
  const label = document.createElement('label');
  label.htmlFor = 'samsungTranslation'; label.textContent = 'Translation engine';
  const select = document.createElement('select'); select.id = 'samsungTranslation'; select.disabled = true;
  for (const [value, text] of [['samsung', 'Samsung language packs — background translation'], ['qwen', 'Qwen — selected local NPU model']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
  }
  const note = document.createElement('p'); note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite');
  const hint = document.createElement('p');
  hint.textContent = 'Samsung: English output only. Start Shizuku on the phone and authorize MangaAMTL. Translation runs on a hidden display so you can keep scrolling. Samsung NPU usage is unverified. Qwen uses the NPU model selected in the model finder. Google Lens remains a separate OCR choice.';
  box.append(label, select, note, hint);
  (document.querySelector(`label[for="${anchor.id}"]`) || anchor).before(box);
  let enabled = false;
  async function api(body) {
    const {serverUrl} = await chrome.storage.local.get('serverUrl');
    const response = await mtBackendFetch(serverUrl.replace(/\/$/, '') + '/v1/samsung/' + (body ? 'settings' : 'status'),
      body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Update the Android APK to use Samsung settings');
    return result;
  }
  async function applyState(state) {
    enabled = state.enabled === true; select.value = enabled ? 'samsung' : 'qwen';
    const target = document.getElementById('targetLang'); if (target) target.disabled = enabled;
    if (enabled) {
      await chrome.storage.local.set({targetLang: 'en', modelType: 'local', cloudMode: false});
      if (target) target.value = 'en';
    }
    note.textContent = enabled ? 'Samsung language packs active · English output' : 'Selected Qwen NPU model active';
  }
  document.getElementById('targetLang')?.addEventListener('change', async event => {
    if (enabled) { event.target.value = 'en'; await chrome.storage.local.set({targetLang: 'en'}); }
  }, true);
  select.addEventListener('change', async () => {
    select.disabled = true; note.textContent = 'Updating translation engine…';
    try { await applyState(await api({enabled: select.value === 'samsung'})); }
    catch (error) { select.value = enabled ? 'samsung' : 'qwen'; note.textContent = error.message; }
    finally { select.disabled = false; }
  });
  try { await mtAndroidReady; await applyState(await api()); select.disabled = false; }
  catch (error) { note.textContent = 'Cannot load translation settings: ' + error.message; }
}
