let ruleCounter = Date.now() % 1_000_000_000 + 1;
const IMAGE_FETCH_TIMEOUT_MS = 25000;
const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
const JOB_HEALTH_ALARM = "mangaTranslatorJobHealth";
const JOB_HEALTH_INTERVAL_MINUTES = 0.5;
const JOB_HEALTH_STORAGE_KEY = "mangaTranslatorActiveJobs";
let jobHealthQueue = Promise.resolve();
function updateJobHealth(action) {
  const result = jobHealthQueue.then(action);
  jobHealthQueue = result.catch(() => {});
  return result;
}

const androidReady = (async () => {
  const saved = await chrome.storage.local.get(null);
  if (saved.androidProfileVersion === 1) return;
  const oldLoopback = /^http:\/\/(localhost|127\.0\.0\.1):8000\/?$/.test(saved.serverUrl || '');
  await chrome.storage.local.set({
    serverUrl: !saved.serverUrl || oldLoopback ? 'http://localhost:7860' : saved.serverUrl,
    modelType: 'local', cloudMode: false, colorize: false, freeOpenRouter: false,
    ocrMode: ['hayai', 'glm', 'lens'].includes(saved.ocrMode) ? saved.ocrMode : 'lens',
    inpaintMode: saved.inpaintMode === 'none' ? 'none' : 'high', contextLevel: 'low',
    ocrLang: saved.ocrLang || 'ja', targetLang: saved.targetLang || 'en',
    combineAmount: saved.combineAmount || '1', androidProfileVersion: 1,
  });
  await chrome.storage.local.remove(['fontFamily', 'styleFontBold', 'styleFontItalic', 'styleFontRegular']);
})();

async function readBytes(response) {
  if (Number(response.headers.get('content-length')) > MAX_IMAGE_BYTES) throw new Error('Image or response exceeds 32 MB');
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader(), chunks = [];
  let length = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > MAX_IMAGE_BYTES) { await reader.cancel(); throw new Error('Image or response exceeds 32 MB'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

function base64Bytes(bytes) {
  let text = '';
  for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(text);
}

async function backendRequest(request) {
  await androidReady;
  const {serverUrl} = await chrome.storage.local.get('serverUrl');
  const base = new URL(serverUrl), target = new URL(request.url);
  const prefix = base.pathname.replace(/\/$/, '');
  if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password
      || target.origin !== base.origin || !target.pathname.startsWith(prefix + '/')
      || !['GET', 'POST'].includes(request.method || 'GET')
      || (request.body != null && (typeof request.body !== 'string' || request.body.length > 1_000_000))) {
    throw new Error('Only the configured Android backend can be requested');
  }
  const response = await fetch(target.href, {method: request.method || 'GET', headers: request.headers,
    body: request.body, redirect: 'error', signal: AbortSignal.timeout(25000)});
  return {success: true, status: response.status, headers: [...response.headers], body: base64Bytes(await readBytes(response))};
}

async function getActiveJobs() {
  const stored = await chrome.storage.session.get(JOB_HEALTH_STORAGE_KEY);
  return stored[JOB_HEALTH_STORAGE_KEY] || {};
}

async function saveActiveJobs(jobs) {
  await chrome.storage.session.set({ [JOB_HEALTH_STORAGE_KEY]: jobs });
}

async function reportJobHealth(job, active) {
  try {
    const response = await fetch(`${job.serverUrl}/v1/health`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: job.jobId, active }),
    });
    if (!response.ok) {
      console.warn(`[BG] Health report for ${job.jobId} failed: HTTP ${response.status}`);
    }
  } catch (error) {
    console.warn(`[BG] Health report for ${job.jobId} failed:`, error);
  }
}

async function registerJobHealth(jobId, serverUrl, tabId) {
  return updateJobHealth(async () => {
  const jobs = await getActiveJobs();
  jobs[jobId] = { jobId, serverUrl: String(serverUrl).replace(/\/$/, ""), tabId };
  await saveActiveJobs(jobs);
  await chrome.alarms.create(JOB_HEALTH_ALARM, { periodInMinutes: JOB_HEALTH_INTERVAL_MINUTES });
  await reportJobHealth(jobs[jobId], true);
  });
}

async function stopJobHealth(jobId, active = false) {
  return updateJobHealth(async () => {
  const jobs = await getActiveJobs();
  const job = jobs[jobId];
  if (!job) return;
  delete jobs[jobId];
  await saveActiveJobs(jobs);
  if (!active) await reportJobHealth(job, false);
  if (!Object.keys(jobs).length) await chrome.alarms.clear(JOB_HEALTH_ALARM);
  });
}

async function stopJobsForTab(tabId) {
  return updateJobHealth(async () => {
  const jobs = await getActiveJobs();
  const stopped = Object.values(jobs).filter(job => job.tabId === tabId);
  if (!stopped.length) return;
  for (const job of stopped) delete jobs[job.jobId];
  await saveActiveJobs(jobs);
  await Promise.all(stopped.map(job => reportJobHealth(job, false)));
  if (!Object.keys(jobs).length) await chrome.alarms.clear(JOB_HEALTH_ALARM);
  });
}

chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name !== JOB_HEALTH_ALARM) return;
  for (const job of Object.values(await getActiveJobs())) {
    await reportJobHealth(job, true);
  }
});

chrome.tabs.onRemoved.addListener(tabId => {
  stopJobsForTab(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) stopJobsForTab(tabId);
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'androidSettings') {
    androidReady.then(() => sendResponse({success: true})).catch(error => sendResponse({success: false, error: String(error)}));
    return true;
  }
  if (request.type === 'backendFetch') {
    backendRequest(request).then(sendResponse).catch(error => sendResponse({success: false, error: String(error)}));
    return true;
  }
  if (request.type === "fetchImage") {
    const url = request.url;
    const pageUrl = sender.tab?.url;
    const tabId = sender.tab?.id;
    if (!url || !pageUrl || tabId === undefined) {
      sendResponse({ success: false, error: "Missing image URL or sender tab" });
      return;
    }

    console.log("[BG] Fetching image for translation:", url);
    fetchImagePowerful(url, pageUrl, tabId)
      .then(base64 => {
        console.log("[BG] Image ready for backend submission:", url);
        sendResponse({ success: true, base64: base64 });
      })
      .catch(err => {
        console.error("[BG] Image fetch failed:", url, err);
        sendResponse({ success: false, error: err.toString() });
      });

    return true; // Keep channel open for async
  }
  if (request.type === "submitImage") {
    submitTranslation(request, sendResponse, sender.tab?.id);
    return true;
  }

  if (request.type === "stopTranslationHealth") {
    stopJobHealth(request.jobId, request.active === true)
      .then(() => sendResponse({ success: true }));
    return true;
  }

  if (request.type === "translateImageUrl") {
    const imageUrl = request.imageUrl;
    const pageUrl = sender.tab?.url || request.pageUrl;
    const tabId = sender.tab?.id;
    if (!imageUrl || !pageUrl || tabId === undefined) {
      sendResponse({ success: false, error: "Missing image URL or source tab for translation" });
      return;
    }
    console.log("[BG] Fetching and submitting image in one request path:", imageUrl);
    fetchImagePowerful(imageUrl, pageUrl, tabId)
      .then(base64Data => submitTranslation({ ...request, base64Data }, sendResponse, tabId))
      .catch(err => {
        console.error("[BG] Image fetch failed before /v1/translate:", imageUrl, err);
        sendResponse({ success: false, error: err.toString() });
      });
    return true;
  }
});

async function submitTranslation(request, sendResponse, senderTabId) {
  const { serverUrl, base64Data, colorize, targetLang, ocrLang, combineAmount,
          contextMode, contextLevel, styleAware, styleFonts } = request;
  const endpoint = `${String(serverUrl || '').replace(/\/$/, '')}/v1/translate`;
    console.log("[BG] submitImage received; preparing request:", endpoint, {
      hasBase64: typeof base64Data === 'string' && base64Data.length > 0,
      base64Length: typeof base64Data === 'string' ? base64Data.length : 0,
    });

    if (!serverUrl || typeof base64Data !== 'string' || !base64Data.includes(',')) {
      sendResponse({ success: false, error: "submitImage missing serverUrl or valid base64 image data" });
      return;
    }

    try {
      await androidReady;
      const saved = await chrome.storage.local.get('serverUrl');
      if (String(serverUrl).replace(/\/$/, '') !== String(saved.serverUrl).replace(/\/$/, '')) throw new Error('Translation must use the configured Android backend');
      if (!/^data:image\/[^;,]+;base64,/i.test(base64Data) || base64Data.length > MAX_IMAGE_BYTES * 4 / 3 + 100) throw new Error('Invalid image or image exceeds 32 MB');
      // Convert Base64 back to Blob for FormData
      const encodedImage = base64Data.split(',')[1];
      const byteString = atob(encodedImage);
      const arrayBuffer = new ArrayBuffer(byteString.length);
      const uint8Array = new Uint8Array(arrayBuffer);
      for (let i = 0; i < byteString.length; i++) {
        uint8Array[i] = byteString.charCodeAt(i);
      }

      const mimeMatch = base64Data.match(/data:(.*?);base64,/);
      const mimeString = mimeMatch ? mimeMatch[1] : "image/png";
      const blob = new Blob([uint8Array], { type: mimeString });

      const formData = new FormData();
      formData.append("image", blob, "manga_page.png");
      formData.append("target_lang", targetLang || "en");
      const requestedOcrLang = ocrLang || "ja";
      formData.append(
        "ocr_lang",
        requestedOcrLang === (targetLang || "en") ? "auto" : requestedOcrLang
      );
      formData.append("colorize", "false");
      if (contextMode === 'on') {
        formData.append("skip_sfx", "true");
        formData.append("context_aware", "true");
        formData.append("context_level", contextLevel === 'high' ? 'high' : 'low');
      }
      if (combineAmount && combineAmount > 1) formData.append("combine_amount", String(combineAmount));
      if (styleAware) formData.append("style_aware", "true");
      formData.append("style_fonts", JSON.stringify(styleFonts || {}));

      console.log("[BG] Sending POST /v1/translate:", endpoint);
      fetch(endpoint, { method: "POST", body: formData, signal: AbortSignal.timeout(25000) })
        .then(async res => {
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(`HTTP ${res.status}: ${data.detail || JSON.stringify(data)}`);
          return data;
        })
        .then(async data => {
          console.log("[BG] /v1/translate response:", data);
          if (data.job_id) {
            if (senderTabId !== undefined) {
              await registerJobHealth(data.job_id, serverUrl, senderTabId);
            }
            // Return immediately. The page content script owns the long poll;
            // an MV3 service worker may be suspended during local GGUF work.
            sendResponse({ success: true, pending: true, job_id: data.job_id });
          } else sendResponse({ success: false, error: "No job ID returned" });
        })
        .catch(err => {
          console.error("[BG] /v1/translate failed:", err);
          sendResponse({ success: false, error: err.toString() });
        });
    } catch (err) {
      console.error("[BG] submitImage preparation failed before /v1/translate:", err);
      sendResponse({ success: false, error: err.toString() });
    }

    return true;
  }

async function extractPageImage(url, tabId) {
  try {
    const canvasResult = await chrome.scripting.executeScript({
      target: { tabId },
      func: (imgUrl) => {
        return new Promise((resolve) => {
          // CSS selectors break on quotes/escapes in CDN URLs. Compare every
          // candidate URL instead, so signed URLs and unusual query strings work.
          const candidates = [...document.images];
          const img = candidates.find(candidate => {
            const values = [candidate.currentSrc, candidate.src,
              candidate.getAttribute('data-original'), candidate.getAttribute('data-src'),
              candidate.getAttribute('o_src')].filter(Boolean);
            return values.some(value => { try { return new URL(value, location.href).href === imgUrl; } catch { return false; } });
          });
          if (!img || !img.complete || img.naturalWidth === 0) return resolve(null);
          
          try {
            const canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            resolve(canvas.toDataURL('image/png'));
          } catch (e) {
            resolve(null); // Canvas is tainted (CORS), fallback to Method 2
          }
        });
      },
      args: [url]
    });

    if (canvasResult && canvasResult[0] && canvasResult[0].result) {
      console.log("[BG] Image grabbed via Canvas (No network request needed)");
      return canvasResult[0].result;
    }
  } catch (e) {
    console.log("[BG] Page pixels are not readable:", String(e));
  }
  return null;
}

async function fetchImagePowerful(url, pageUrl, tabId) {
  if (typeof url !== 'string' || !/^(https?:|blob:|data:image\/)/i.test(url)) throw new Error('Unsupported image URL');
  if (url.startsWith('data:image/')) {
    const response = await fetch(url);
    return `data:${response.headers.get('content-type')};base64,${base64Bytes(await readBytes(response))}`;
  }
  if (url.startsWith('blob:')) {
    const [{result}] = await chrome.scripting.executeScript({target: {tabId}, args: [url], func: async source => {
      const blob = await (await fetch(source)).blob();
      if (!blob.type.startsWith('image/') || !blob.size || blob.size > 32 * 1024 * 1024) throw new Error('Invalid blob image');
      return await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
    }});
    return result;
  }
  const parsed = new URL(url); parsed.hash = ''; url = parsed.href;
  // Fetch original bytes in the extension, so a tainted page canvas is irrelevant.
  const ruleId = ruleCounter++;
  const escapedUrl = url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  
  // Preserve the reading page's Referer for CDNs with hotlink protection.
  const rule = {
    id: ruleId,
    priority: 1,
    action: {
      type: "modifyHeaders",
      requestHeaders: [
        { header: "Referer", operation: "set", value: pageUrl }, // Pretend we are the webpage
        { header: "Origin", operation: "remove" }                // Strip extension origin
      ]
    },
    condition: {
      regexFilter: "^" + escapedUrl + "$",
      resourceTypes: ["xmlhttprequest"],
      initiatorDomains: [chrome.runtime.id]
    }
  };

  try {
    // Apply the header spoofing rule
    await chrome.declarativeNetRequest.updateSessionRules({ addRules: [rule], removeRuleIds: [ruleId] });
  } catch (e) {
    console.error("[BG] Failed to set spoofing rule:", e);
  }

  try {
    const res = await fetch(url, {
      credentials: "include",
      signal: AbortSignal.timeout(IMAGE_FETCH_TIMEOUT_MS),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status}: ${text.substring(0, 100)}`);
    }
    
    const contentType = res.headers.get('content-type') || '';
    if (!contentType.toLowerCase().startsWith('image/') && !contentType.startsWith('application/octet-stream')) {
      const text = await res.text();
      throw new Error(`Expected image but got ${contentType}. Site blocked download. Body: ${text.substring(0, 100)}`);
    }

    const bytes = await readBytes(res);
    if (!bytes.length) throw new Error('Downloaded image is empty');
    return `data:${contentType.split(';')[0]};base64,${base64Bytes(bytes)}`;
  } catch (error) {
    const readable = await extractPageImage(url, tabId);
    if (readable) return readable;
    throw error;
  } finally {
    // Clean up rule to prevent memory leaks
    try { await chrome.declarativeNetRequest.updateSessionRules({ removeRuleIds: [ruleId] }); }
    catch (e) { console.warn("[BG] Failed to remove temporary image rule:", e); }
  }
}

